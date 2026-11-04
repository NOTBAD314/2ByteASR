"""Adapters for existing pipeline/provider/worker evidence, without payloads."""
from __future__ import annotations
from functools import wraps
import re
import sys
import time

from .event_log import current_context, emit, exception_info, recorder


def technical(payload, depth=0):
    if depth>6:return "<depth-limit>"
    if isinstance(payload,dict):
        result={}
        for k,v in list(payload.items())[:64]:
            low=str(k).lower()
            if low=='problems' and isinstance(v,dict):
                result['problem_count']=len(v)
                result['problem_samples']=[dict(subtitle_id=key,error_code=(re.match(r'^[a-z_]{2,80}(?=:|$)',str(problem))[0] if re.match(r'^[a-z_]{2,80}(?=:|$)',str(problem)) else 'validation_failed')) for key,problem in list(v.items())[:16]]
                continue
            if low in {'segments','cues','words'} and isinstance(v,(list,tuple)):
                result[low+'_count']=len(v)
                result[low+'_range_samples']=[{key:item.get(key) for key in ('id','start','end','start_ms','end_ms','offset','chunk_start','speaker_id') if key in item} for item in v[:8] if isinstance(item,dict)]
                continue
            if any(part in low for part in ("text","prompt","content","response_preview","messages","sentence","subtitle_body","source_sha","cue_digest","cache_key")):
                # Never export unsalted hashes of short text either.
                if isinstance(v,str):result[low+"_characters"]=len(v)
                else:result[low+"_included"]=False
                continue
            if low.endswith("_error") or low in {"error","errors","detail","details","reason","message","failed","stderr","stdout","output","response","runtime_settings","runtime_profile","segments","cues","words","items"}:
                if isinstance(v,(str,bytes)):result[low+"_characters"]=len(v)
                elif isinstance(v,(dict,list,tuple)):result[low+"_count"]=len(v)
                else:result[low]=v
                continue
            result[str(k)]=technical(v,depth+1)
        return result
    if isinstance(payload,(list,tuple)):
        return [technical(v,depth+1) for v in payload[:32]]
    return payload


def legacy_event(name,payload,*,module,task_id=None,project_id=None):
    try:
        data=technical(payload)
        for key in ("event_name","message","level","module","result","task_id","project_id"):data.pop(key,None)
        status=str(payload.get("status") or "").lower()
        lower=name.lower()
        result=("cancelled" if "cancel" in lower or status=="cancelled" else
                "failed" if any(w in lower for w in ("failed","failure","rejected")) or lower.endswith('.error') or status in {"error","failed"} else
                "skipped" if "skipped" in lower or status=='skipped' else
                "waiting" if status in {'queued','waiting'} else
                "started" if any(w in lower for w in ("started","start")) or status in {'trying','started'} else
                "partial" if 'validated' in lower and payload.get('problems') else
                "completed" if any(w in lower for w in ("completed","finished","validated")) or status in {'completed','complete','ready','reused'} else "observed")
        emit(name,module=module,task_id=task_id or payload.get("job_id") or current_context().get("task_id"),
             project_id=project_id or payload.get("project_id") or current_context().get("project_id"),
             result=result,level="ERROR" if result=="failed" else "WARN" if "fallback" in lower else "INFO",**data)
    except Exception:
        pass


def validation(rule):
    """Wrap actual validators: returned means executed; failures retain categories."""
    def decorate(fn):
        @wraps(fn)
        def run(*args,**kwargs):
            start=time.perf_counter()
            fields=dict(rule=rule,validator=fn.__name__,module=fn.__module__,
                        expected="existing_validator_contract",subsequent_decision="caller_decides; follow same task/batch")
            try:
                value=fn(*args,**kwargs)
            except Exception as exc:
                category=getattr(exc,"category",type(exc).__name__)
                emit("ai.validation",level="ERROR",result="failed",error_code=category,
                     rule_detail=str(exc) if type(exc).__name__=='GroupingContractError' else None,
                     input_count=len(args[0]) if args and isinstance(args[0],(list,tuple)) else None,
                     input_characters=len(args[0]) if args and isinstance(args[0],str) else None,
                     actual_boundaries=args[0][:32] if fn.__name__=='validate_boundary_offsets' and args and isinstance(args[0],list) else None,
                     exception=exception_info(exc),position=getattr(exc,"pos",None),
                     duration_ms=round((time.perf_counter()-start)*1000,3),**fields)
                raise
            emit("ai.validation",result="completed",validation="passed",duration_ms=round((time.perf_counter()-start)*1000,3),**fields)
            return value
        return run
    return decorate


def stderr_evidence(value):
    """Keep stack locations/types/statuses, never arbitrary worker text or locals."""
    if value is None:return {"available":False,"reason":"not_captured_by_existing_runner"}
    raw=value[-8192:].decode("utf8","replace") if isinstance(value,bytes) else str(value)[-8192:]
    rows=[]
    for line in raw.splitlines()[-48:]:
        frame=re.search(r'File "([^"]+)", line (\d+)(?:, in (\w+))?',line)
        if frame:
            from pathlib import Path
            rows.append(dict(module=Path(frame[1]).name,line=int(frame[2]),function=frame[3]))
        else:
            error=re.search(r'\b([A-Za-z_][\w.]*(?:Error|Exception|Warning))\b',line)
            code=re.search(r'(?i)\b(?:HTTP|errno|exit(?: code)?|status)\s*[:=]?\s*(-?\d+)',line)
            if error or code:rows.append(dict(type=error[1] if error else None,code=code[1] if code else None))
    return dict(available=True,bytes=len(value),tail=rows[-24:],unstructured_lines_omitted=True,
                truncated=len(value)>8192,encoding="utf8_replace")


def runtime_context_fields():
    """Read already-loaded recognition context; never import the recognition graph."""
    fields=current_context()
    try:
        module=sys.modules.get("twobyteasr.recognition.run_context")
        getter=getattr(module,"get_runtime_context",None)
        if getter:
            runtime=getter()
            if runtime.identity_task_active:fields.setdefault("task_id",runtime.job_id)
    except Exception:pass
    return fields


def service_boundary(action):
    """Record synchronous export/service completion, including returned validation."""
    def decorate(fn):
        @wraps(fn)
        def run(*args,**kwargs):
            from .event_log import operation
            with operation(action,module=fn.__module__,project_id=getattr(args[0],'project_id',None) if args else None) as outcome:
                value=fn(*args,**kwargs)
                if hasattr(value,'valid'):
                    outcome.update(result='completed' if value.valid else 'failed',validation='passed' if value.valid else 'failed',cue_count=getattr(value,'cue_count',None))
                elif isinstance(value,tuple):outcome['artifact_count']=len(value)
                return value
        return run
    return decorate
