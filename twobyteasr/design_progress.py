"""Public artifact progress only; activity never stands in for completed work."""
import json
import re
import time


class PublicProgress:
    """Shared progress for generation children, repairs and explicit resumes."""
    def __init__(self,request_id,label,seconds,*,event_callback=None,stage_callback=None,path=None):
        self.event_callback,self.stage_callback,self.path=event_callback,stage_callback,path
        self.last_emit=0.;self.parts=[];self.persisted_chars=0;self.sequence=0;self.last_receipt_emit=0.
        self.phase=dict(name='design_child',label=label,request_id=request_id,status='running',
            started_monotonic=time.monotonic(),last_output_monotonic=None,last_response_monotonic=None,
            timeout_seconds=seconds,output_chars=0,completed_candidates=0,warning_seconds=120,provider_state='starting',
            local_state='worker已开始，等待响应',last_local_monotonic=time.monotonic(),
            transport_bytes=None,transport_events=0,last_byte_monotonic=None,
            complete_sections=0,artifact_revision=None,production_state='尚未开始校验/渲染',remote_progress=None,
            public_summary='',summary_capability='not_provided',recent_events=[])
        self.emit()
    def emit(self):
        self.last_emit=time.monotonic()
        if self.path and self.phase['output_chars']!=self.persisted_chars:
            from .theme_persistence import write_text_atomic
            body=''.join(self.parts)
            write_text_atomic(self.path,body)
            self.persisted_chars=self.phase['output_chars']
            self.phase['artifact_revision']=__import__('hashlib').sha256(body.encode('utf8')).hexdigest()
            # A section is complete only once the next boundary has arrived.
            boundaries=re.findall(r'^===(HTML|CSS|STAGE_CSS|PARAMETERS|END[^\r\n]*)===\s*$',body,re.M)
            self.phase['complete_sections']=max(0,len(boundaries)-1)
        if self.event_callback:self.event_callback(dict(self.phase))
        elif self.stage_callback:self.stage_callback(self.phase['label']+' · '+status_text(self.phase,self.last_emit))
    def stream(self,kind,detail):
        now=time.monotonic();update_phase(self.phase,kind,detail,now)
        if kind=='delta':self.parts.append(str(detail))
        # Keep a public receipt, not private thinking or credentials. Body is
        # already saved separately; batching never drops the final partial chunk.
        from .provider_diagnostics import redact_diagnostics
        public = str(redact_diagnostics(detail))[:1000] if kind in {'reasoning_summary','stage','provider_event','request_identity'} else ''
        self.sequence+=1
        event=dict(sequence=self.sequence,kind=kind,elapsed_seconds=now-self.phase['started_monotonic'],
                   detail=public,characters=len(str(detail)) if kind=='delta' else None)
        retain=kind not in {'delta','thinking','transport','heartbeat'} or now-self.last_receipt_emit>=1
        if retain:self.phase['recent_events']=(self.phase['recent_events']+[event])[-12:]
        if self.path and retain:
            self.last_receipt_emit=now
            with self.path.with_name('public-events.jsonl').open('a',encoding='utf8') as handle:
                handle.write(json.dumps(event,ensure_ascii=False)+'\n')
        if now-self.last_emit>=1 or kind=='final':self.emit()
    def finish(self,status):
        self.phase.update(status=status,finished_monotonic=time.monotonic(),local_state='worker步骤已'+status,
                          last_local_monotonic=time.monotonic());self.emit()


def complete_candidate_prefix(body):
    match = re.match(r'\s*(?:```json\s*)?\{\s*"candidates"\s*:\s*\[',body)
    if not match:return []
    decoder=json.JSONDecoder();position=match.end();rows=[]
    while len(rows)<3:
        while position<len(body) and body[position] in ' \r\n\t,':position+=1
        try:row,position=decoder.raw_decode(body,position)
        except json.JSONDecodeError:break
        if not isinstance(row,dict) or not row.get('id') or not isinstance(row.get('generated_source'),dict):break
        if any(peer['id']==row['id'] for peer in rows):break
        rows.append(row)
    return rows


def update_phase(phase,kind,detail,now):
    phase['last_activity_monotonic']=now  # legacy consumers; never a work counter
    remote=kind in {'transport','provider_event','thinking','thinking_end','delta','final','heartbeat','reasoning_summary'}
    if remote:
        phase['last_response_monotonic']=now
        phase['transport_events']=phase.get('transport_events',0)+1
        phase['last_event_type']=kind
    else:
        phase['last_local_monotonic']=now
        phase['local_state']={'request_identity':'请求已派发，等待响应','process_alive':'本地进程仍存在，远端状态未知',
            'stderr':'收到本地诊断','stage':'本地步骤有响应'}.get(kind,'本地步骤有响应')
    if kind=='transport':
        if isinstance(detail,str):
            try:detail=json.loads(detail)
            except ValueError:detail={}
        if isinstance(detail,dict):
            if detail.get('bytes',0)>0:
                phase['transport_bytes']=(phase.get('transport_bytes') or 0)+detail['bytes']
                phase['last_byte_monotonic']=now
            if 'connected' in detail:phase['transport_connected']=detail['connected']
    phase['provider_state']={'thinking':'provider_activity','thinking_end':'awaiting_body',
        'delta':'streaming','final':'complete','heartbeat':'heartbeat'}.get(kind,phase.get('provider_state','starting'))
    if kind=='delta' and detail:
        phase['last_output_monotonic']=now
        phase['output_chars']=phase.get('output_chars',0)+len(str(detail))
    if kind=='reasoning_summary' and detail:
        from .provider_diagnostics import redact_diagnostics
        phase['public_summary']=(phase.get('public_summary','')+str(redact_diagnostics(detail)))[-12000:]
        phase['summary_capability']='provided'
        phase['last_summary_monotonic']=now
    if kind=='request_identity':
        try:identity=json.loads(detail) if isinstance(detail,str) else detail
        except ValueError:identity={}
        if isinstance(identity,dict):phase['request_identity']=identity


def status_text(phase,now):
    if phase.get('finished_monotonic') is not None:now=phase['finished_monotonic']
    output=phase.get('last_output_monotonic')
    response=phase.get('last_response_monotonic')
    recent=output if output is not None else phase.get('started_monotonic',now)
    body=(f'已收 {phase.get("output_chars",0)} 字，最近正文 {max(0.,now-output):.0f}s前，'
          f'已保存 {phase.get("complete_sections",0)} 个完整分节' if output is not None else '尚未收到作品正文')
    body=phase.get('body_summary') or body
    transport=f'最近服务响应 {max(0.,now-response):.0f}s前' if response is not None else '等待服务响应'
    received=phase.get('transport_bytes')
    transport+=f'，已收 {received} 字节' if received is not None else '，字节数未知'
    if phase.get('last_byte_monotonic') is not None:transport+=f'，最后字节 {max(0,now-phase["last_byte_monotonic"]):.0f}s前'
    if phase.get('last_event_type'):transport+='，事件 '+phase['last_event_type']
    transport=phase.get('transport_summary') or transport
    warning=(f' · 长时间未收到新内容（{now-recent:.0f}s）；可继续等待或停止并保留'
             if phase.get('status','running')=='running' and now-recent>=phase.get('warning_seconds',120) else '')
    elapsed=max(0.,now-phase.get('started_monotonic',now))
    local=phase.get('local_state','本地任务等待响应')
    if phase.get('last_local_monotonic') is not None:local+=f'（最近步骤 {max(0,now-phase["last_local_monotonic"]):.0f}s前）'
    summary=phase.get('public_summary') or '当前接口未提供可展示的推理摘要'
    return (f'本地：{local} · 本步骤 {elapsed:.0f}s\n传输：{transport}\n'
            f'作品：{body}；远端内部进度不可见{warning}\n制作：{phase.get("production_state","尚未开始校验/渲染")}\n公开摘要：{summary}')


ACTIVE_STATES={'queued','running','accepted','repairing','finishing'}


def candidate_status(concept, state=None):
    """Terminal task facts override cached pending flags in every view."""
    state=state or {}
    status=state.get('status')
    if status in {'failed','cancelled','rejected'}:return status
    if status in ACTIVE_STATES:return status
    if concept.get('technical_status')=='failed':return 'failed'
    if concept.get('pending'):return 'running'
    if concept.get('preview_integrity_verified') and concept.get('authored_theme'):return 'ready'
    return 'render_pending'


def compact_status(phase, now, *, state=None):
    state=state or {}
    budget=state.get('task_budget') or phase.get('task_budget') or {}
    started=budget.get('task_started_monotonic',phase.get('task_started_monotonic',phase.get('started_monotonic',now)))
    end=now if state.get('status',phase.get('status','running')) in ACTIVE_STATES else state.get('finished_monotonic',phase.get('finished_monotonic',now))
    elapsed=max(0.,end-started)
    output=phase.get('last_output_monotonic')
    age=max(0.,now-(output if output is not None else started))
    activity=(f'正文 {phase.get("output_chars",0)} 字 · {age:.0f}s无新正文' if output is not None else f'{age:.0f}s尚无作品正文')
    label=state.get('detail') or state.get('stage') or phase.get('label') or '准备任务'
    labels={'implementation':'接收作品','application_queue':'排队','technical_validation':'检查源码',
            'rendering':'渲染预览','render_pending':'等待预览','render_validation':'预览检查失败',
            'ready':'可采用','terminal':'已结束','auto_completing':'补全实现','render_repair':'修复渲染'}
    label=labels.get(label,label)
    repairs=f' · 恢复 {budget.get("repairs_used",0)}/{budget.get("max_repairs",2)}' if budget else ''
    remaining=f' · 剩余 {max(0.,budget["total_seconds"]-elapsed):.0f}s' if 'total_seconds' in budget else ''
    silent=' · 远端内部进度不可见' if age>=90 and state.get('status','running') in ACTIVE_STATES else ''
    recent=next((e.get('detail') for e in reversed(phase.get('recent_events',[])) if e.get('detail') and e.get('kind') in {'stage','provider_event','reasoning_summary'}),'')
    latest='\n最近活动：'+recent[-160:] if recent else ''
    return f'{label} · 累计 {elapsed:.0f}s{remaining}{repairs}\n{activity}{silent}{latest}'


def aggregate_activity(states):
    """State publication is local activity, never a synthetic model token."""
    phases=[s.get('activity',{}) for s in states.values()]
    latest=max(phases,key=lambda p:p.get('last_output_monotonic') or 0,default={})
    return dict(last_output_monotonic=latest.get('last_output_monotonic'),
                output_chars=sum(p.get('output_chars',0) for p in phases),
                last_response_monotonic=max((p.get('last_response_monotonic') or 0 for p in phases),default=0) or None,
                public_summary=latest.get('public_summary',''))
