"""Consistent, bounded, twice-sanitized support ZIPs and retention."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import math
import re
import os
import platform
from pathlib import Path
import sys
import time
import uuid
import zipfile

from .event_log import (FORMAT_VERSION, FILE_BYTES, MAX_EVENT_BYTES, TOTAL_BYTES,
                        RETENTION_DAYS, Sanitizer, now, readable)

MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 256 * 1024
MAX_CONTEXT_BYTES = 4 * 1024 * 1024
MAX_EVENTS_BYTES = 24 * 1024 * 1024


def _stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _event_order(row):
    def number(value):
        try:return int(value)
        except (TypeError, ValueError, OverflowError):return 0
    return (_stamp(row.get('time')) or 0, number(row.get('pid')), number(row.get('sequence')))


def _alive(row):
    from .editor_diagnostics import _session_process_alive
    try: return _session_process_alive(row)
    except Exception: return True  # Cannot prove ownership ended: never prune it.


def maintain_sessions(root, *, current=None, clear=False, days=RETENTION_DAYS, total_bytes=TOTAL_BYTES):
    """Only managed session files; preserve running peers and private dumps."""
    root = Path(root).resolve()
    rows, removed, failures = [], 0, 0
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink() or directory == current:
            continue
        metadata=directory/"session.json"
        try:
            row=json.loads(metadata.read_text("utf8"))
            if row.get("status")=="running" and _alive(row): continue
            files=[p for p in directory.iterdir() if p.is_file() and not p.is_symlink() and
                   (p.name in {"session.json","native-fault.txt","session.tmp"} or
                    p.name.startswith(("events", "readable")) and p.suffix in {".log",".jsonl"})]
            rows.append((metadata.stat().st_mtime,directory,files,sum(p.stat().st_size for p in files)))
        except (OSError,ValueError):
            failures+=1
    used=sum(r[3] for r in rows)
    current_bytes=sum(p.stat().st_size for p in current.iterdir() if p.is_file()) if current and current.exists() else 0
    cutoff=time.time()-days*86400
    for stamp,directory,files,size in sorted(rows):
        if not clear and stamp>=cutoff and used+current_bytes<=total_bytes:
            continue
        try:
            if not directory.resolve().is_relative_to(root): continue
            for p in files: p.unlink(missing_ok=True)
            used-=size; removed+=1
            try: directory.rmdir()
            except OSError: pass
        except OSError: failures+=1
    return dict(result="partial" if failures else "completed", removed_sessions=removed,
                failed_sessions=failures, retained_bytes=used+current_bytes,
                retention_days=days, total_limit_bytes=total_bytes,
                note="存活程序及非管理檔案不刪除；容量超限會在後續維護重試")


def _session_files(directory, missing):
    files={}
    for path in directory.iterdir():
        if path.name == "session.json" or (path.name.startswith("events") and path.suffix == ".jsonl"):
            try:
                with path.open("rb") as stream:
                    size=os.fstat(stream.fileno()).st_size
                    data=stream.read(min(size, FILE_BYTES+MAX_EVENT_BYTES))
                files[path.name]=data
                if size > len(data): missing.append(dict(session=directory.name, file=path.name, reason="size_limit", omitted_bytes=size-len(data)))
            except OSError as exc:
                missing.append(dict(session=directory.name,file=path.name,reason=type(exc).__name__))
    return files


def collect(root, *, instance=None, scope="recent", start=None, end=None, report=None,
            cancelled=None, deadline=None):
    """Runs on an export/viewer worker, never on the GUI thread."""
    root=Path(root)
    def checkpoint():
        if cancelled and cancelled():raise InterruptedError('diagnostic collection cancelled')
        if deadline is not None and time.monotonic()>deadline:
            raise TimeoutError('diagnostic collection deadline exceeded')
    checkpoint()
    missing=[]; sessions=[]; events=[]; losses=Counter(); consumed=0; cutoff=None
    try:
        sanitizer=instance.sanitizer if instance else Sanitizer((root/".alias-key").read_bytes() if (root/".alias-key").is_file() else None)
    except OSError as exc:
        missing.append(dict(stage='alias_key',reason=type(exc).__name__))
        sanitizer=Sanitizer()
    snapshot=None
    try:
        if instance and instance.root.resolve()==root.resolve():snapshot=instance.snapshot()
    except Exception as exc:
        missing.append(dict(stage='session_snapshot',reason=type(exc).__name__))
    if snapshot:
        cutoff=snapshot["cutoff"]
        if snapshot.get("write_error"): missing.append(dict(reason="writer_error",error=snapshot["write_error"]))
    directories=[]
    try:
        for p in root.iterdir():
            checkpoint()
            try:
                if p.is_dir() and not p.is_symlink():
                    if (p/'session.json').is_file():directories.append((p.stat().st_mtime,p))
                    else:missing.append(dict(session=p.name,reason='missing_session_metadata'))
            except OSError as exc:missing.append(dict(session=p.name,reason=type(exc).__name__))
    except OSError as exc:missing.append(dict(stage='session_listing',reason=type(exc).__name__))
    directories=[p for _mtime,p in sorted(directories,key=lambda item:item[0],reverse=True)]
    for directory in directories:
        checkpoint()
        if consumed >= MAX_EXPORT_BYTES:
            missing.append(dict(reason="scan_limit",session=directory.name)); continue
        try:
            files=snapshot["files"] if snapshot and directory==instance.directory else _session_files(directory,missing)
            meta=json.loads(files.get("session.json",b"{}"))
            if not isinstance(meta,dict) or not meta:
                missing.append(dict(session=directory.name,reason="missing_session_metadata"));continue
            if meta.get('session_id') is not None and not isinstance(meta['session_id'],str):
                raise ValueError('invalid_session_id')
            current=instance is not None and directory==instance.directory and meta.get('session_id')==instance.session_id
            if meta.get("status")=="running" and not current and not _alive(meta): meta["status"]="previous_not_cleanly_ended"
            meta["directory"]=directory.name
            sessions.append(sanitizer.clean(meta))
            for name,data in files.items():
                if not name.endswith(".jsonl"):continue
                consumed+=len(data)
                lines=data.splitlines(keepends=True)
                for index,line in enumerate(lines):
                    if index % 128 == 0:checkpoint()
                    try:
                        if not line.endswith(b"\n"):
                            raise ValueError("incomplete_line")
                        row=json.loads(line)
                        if not isinstance(row,dict): raise ValueError("not_object")
                        if "event_name" not in row:
                            row.update(format_version=0,event_name=str(row.get("kind","legacy")).lower().replace("_","."),
                                       level="INFO",message="舊版技術狀態記錄",result="observed",session_id=meta.get("session_id",directory.name))
                        # Keep only schema keys that were explicitly populated; scrub twice.
                        message=sanitizer.string(row.get("message","技術狀態記錄"))
                        clean=sanitizer.clean(row)
                        clean["message"]=message
                        clean["event_name"]=sanitizer.string(row["event_name"])
                        for key,default in (('level','INFO'),('result','observed'),('time',meta.get('started_at') or now())):
                            clean.setdefault(key,default)
                            if not isinstance(clean[key],str):raise ValueError('invalid_event_field')
                        for key in ('session_id','task_id','project_id'):
                            if clean.get(key) is not None and not isinstance(clean[key],str):
                                raise ValueError('invalid_event_identity')
                        json.dumps(clean,allow_nan=False)
                        events.append(clean)
                    except (ValueError,TypeError,UnicodeError):
                        missing.append(dict(session=directory.name,file=name,line=index+1,reason="invalid_or_partial_line"))
            for key,value in (meta.get('losses') or {}).items() if isinstance(meta.get('losses'),dict) else ():
                if isinstance(value,(int,float)) and math.isfinite(value) and value>=0:losses[key]+=value
                else:missing.append(dict(session=directory.name,reason='invalid_loss_counter',field=str(key)[:80]))
            if isinstance(meta.get('dropped'),(int,float)) and math.isfinite(meta['dropped']) and meta['dropped']>0:losses['legacy_dropped']+=meta['dropped']
        except (OSError,ValueError,TypeError,UnicodeError) as exc:
            missing.append(dict(session=directory.name,reason=type(exc).__name__))
    events.sort(key=_event_order)
    newest=sessions[0].get("session_id",sessions[0].get("directory")) if sessions else None
    current_id=instance.session_id if snapshot else newest
    if scope=="session":
        selected=[e for e in events if e.get("session_id")==current_id]
    elif scope=="previous":
        prior=next((s for s in sessions if s.get("status") in {"previous_not_cleanly_ended","not_cleanly_ended"}),None)
        selected=[e for e in events if prior and e.get("session_id")==prior.get("session_id",prior.get("directory"))]
        if prior is None:missing.append(dict(reason="no_retained_unclean_session"))
    else:
        # Hidden date controls belong only to the explicit range. A report can
        # remain open for hours: recent must use one fresh, consistent clock.
        upper=_stamp(end) if scope=='range' and end else _stamp(now())
        lower=_stamp(start) if scope=='range' and start else (upper-900 if scope!='range' else None)
        selected=[e for e in events if (stamp:=_stamp(e.get('time'))) is not None
                  and (lower is None or stamp>=lower) and stamp<=upper]
    # Pull the retained upstream provenance for this project/task, even across sessions.
    project_ids={e.get("project_id") for e in selected if e.get("project_id")}
    task_ids={e.get("task_id") for e in selected if e.get("task_id")}
    if report and report.get("project_id"):project_ids.add(sanitizer.alias(report["project_id"],"project"))
    for e in events:
        if e.get("project_id") in project_ids and e.get("task_id"):task_ids.add(e["task_id"])
    included={id(e) for e in selected}
    context=[]; context_bytes=0
    for e in events:
        if id(e) not in included and ((e.get("project_id") and e.get("project_id") in project_ids) or (e.get("task_id") and e.get("task_id") in task_ids)):
            size=len(json.dumps(e,ensure_ascii=False).encode('utf8','replace'))
            if context_bytes+size>MAX_CONTEXT_BYTES:
                losses['context_omitted_by_budget']+=1
                continue
            context.append(dict(e,context_only=True));context_bytes+=size
    selected.sort(key=_event_order)
    used_ids={e.get("session_id") for e in selected+context}
    selected_sessions=[s for s in sessions if s.get("session_id",s.get("directory")) in used_ids or s.get("session_id")==current_id]
    return dict(events=selected,context_events=context,sessions=selected_sessions,missing=missing[:128],missing_count=len(missing),
                losses=dict(losses),cutoff_sequence=cutoff,scope=scope,upstream_task_ids=sorted(task_ids),
                scanned_bytes=consumed,sanitizer=sanitizer)


SCOPE_LABELS = {"recent": "最近 15 分钟（含相关操作）", "session": "本次运行",
                "previous": "上次没有正常结束的运行", "range": "指定时间范围"}


def _report_build(data):
    """Read process receipts or bundled metadata; never run source Git scans.

    A bare/minimum recorder may not have an initialized build receipt. Export
    and its viewer must still work without invoking development-time probes.
    """
    root=Path(__file__).resolve().parents[2]
    payload={}
    for name in ('2byteasr_version.json','2byteasr_build.json'):
        try:
            value=json.loads((root/name).read_text('utf-8-sig'))
            if isinstance(value,dict):payload.update(value)
        except (OSError,ValueError,UnicodeError):pass
    session=next((s for s in data.get('sessions',[]) if isinstance(s.get('build'),dict) and s['build']),{})
    receipt=session.get('build',{})
    aliases={'app_version':'version','git_sha':'commit','build_channel':'channel',
             'source_sha256':'source_sha256','source_file_count':'source_file_count','build_time':'build_time'}
    result={key:receipt.get(alias) or payload.get(key) or payload.get(alias) or 'unknown'
            for key,alias in aliases.items()}
    return result


def summary(data, report_id, description="", report=None):
    """README.txt and the copied text: conclusion, starting step, then the trail."""
    from ..i18n import tr
    from .support_triage import analyze, render_summary
    analysis = data.get("analysis") or analyze(data, report)
    sessions = data.get("sessions") or []
    session = next((s for s in sessions if isinstance(s.get("build"), dict)), sessions[0] if sessions else {})
    build = session.get("build") if isinstance(session.get("build"), dict) else {}
    if not build:
        identity=_report_build(data)
        build=dict(version=identity['app_version'],channel=identity['build_channel'],
                   commit=identity['git_sha'],source_sha256=identity['source_sha256'])
        session=dict(session,frozen=bool(getattr(sys,'frozen',False)))
    version = str(tr("版本：{version} · {channel} · commit {commit} · 来源指纹 {fingerprint} · {mode}",
                     version=build.get("version") or "?", channel=build.get("channel") or "?",
                     commit=str(build.get("commit") or "?")[:12], fingerprint=str(build.get("source_sha256") or "?")[:16],
                     mode=tr("打包程序") if session.get("frozen") else tr("源码运行")))
    extra = []
    if data.get("cutoff_sequence") is not None:
        extra.append(tr("本程序记录截至 #{sequence}，其他进程只读完整的行", sequence=data["cutoff_sequence"]))
    if data.get("missing"):
        extra.append(tr("读不到的部分：{detail}", detail=json.dumps(data["missing"][:8], ensure_ascii=False)))
    if data.get('context_events'):
        extra.append(tr('另附 {count} 笔范围外的工程/任务背景记录，不计入本页时间轴。',count=len(data['context_events'])))
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    scope = data.get("scope") or "recent"
    return render_summary(analysis, report_id=report_id, description=description, generated=generated, version=version,
                          scope=tr(SCOPE_LABELS[scope]) if scope in SCOPE_LABELS else scope,
                          event_count=len(data.get("events") or []), extra_notes=extra)


def export_report(target, *, root, instance=None, scope="recent", start=None, end=None,
                  description="", report=None, content=None, settings=None):
    data=collect(root,instance=instance,scope=scope,start=start,end=end,report=report)
    sanitizer=data.pop("sanitizer")
    report_id=(report or {}).get("report_id") or "report-"+uuid.uuid4().hex[:16]
    report=dict(report or {},report_id=report_id)
    report.setdefault('marked_at',now())
    settings=dict(settings) if isinstance(settings,dict) else {}
    data['missing'].extend(settings.pop('_missing',[]) or [])
    if not data['events']:
        data['missing'].append(dict(stage='collection',reason='no_events_in_selected_range'))
        data['events']=[dict(time=now(),event_name='diagnostics.range_empty',level='WARN',
                             result='partial',message='所选范围没有可读取事件；保留回报标记与缺失原因。',
                             report_id=report_id)]
    description=sanitizer.string(description)
    note=summary(data,report_id,description,report)
    # Bound the actual serialized output, not just the input JSONL scan. The
    # readable copy used to double large ranges and fail the entire report.
    encoded=[]; event_bytes=0; retained=[]
    def priority(row):
        important=(row.get('level') in {'ERROR','WARN'} or row.get('edit_session_id')
                   or row.get('event_name') in {'problem.marked','project.saved','project.save_failed'}
                   or str(row.get('event_name','')).startswith('video.export'))
        return (bool(row.get('context_only')),not bool(important),-(_stamp(row.get('time')) or 0),-_event_order(row)[2])
    for row in sorted([*data['events'],*data.get('context_events',[])],key=priority):
        try:raw=(json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode('utf8')
        except (ValueError,TypeError,UnicodeError):
            data['missing'].append(dict(stage='serialization',reason='invalid_event',sequence=row.get('sequence')))
            continue
        if event_bytes+len(raw)>MAX_EVENTS_BYTES:
            data['losses']['export_events_omitted_by_budget']=data['losses'].get('export_events_omitted_by_budget',0)+1
            continue
        retained.append(row);event_bytes+=len(raw)
    if not retained:
        data['missing'].append(dict(stage='serialization',reason='no_serializable_events'))
        retained=[dict(time=now(),event_name='diagnostics.records_unavailable',level='WARN',result='partial',
                       message='事件资料不足；保留回报标记、应用环境与缺失说明。',report_id=report_id)]
    retained.sort(key=_event_order)
    encoded=[(json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode('utf8') for row in retained]
    readable_parts=[]; readable_bytes=0
    for row in retained:
        try:raw=readable(row).encode('utf8')
        except (KeyError,ValueError,TypeError,UnicodeError):
            data['missing'].append(dict(stage='readable',reason='invalid_readable_event',sequence=row.get('sequence')))
            continue
        if readable_bytes+len(raw)>4*1024*1024:
            data['losses']['readable_omitted_by_budget']=data['losses'].get('readable_omitted_by_budget',0)+1
            continue
        readable_parts.append(raw);readable_bytes+=len(raw)
    environment_events=[r for r in data['events'] if r.get('event_name') in {'host','qt','screens','graphics','media','modules','player.modules'}]
    if len(environment_events)>64 or len(data['sessions'])>64:
        data['missing'].append(dict(stage='environment',reason='environment_records_limited_to_latest_64'))
    # Always provide application-level identity, even without logs or Studio.
    environment=dict(build=_report_build(data),system=platform.system(),
                     system_release=platform.release(),machine=platform.machine(),
                     python=sys.version.split()[0],frozen=bool(getattr(sys,'frozen',False)))
    try:
        clean_settings=sanitizer.clean(settings)
        json.dumps(clean_settings,allow_nan=False)
    except Exception as exc:
        clean_settings={}
        data['missing'].append(dict(stage='settings_serialization',reason=type(exc).__name__))
    files={"README.txt":note.encode("utf8"),
           "events.jsonl":b''.join(encoded),
           "readable.log":b''.join(readable_parts),
           "environment.json":json.dumps(dict(application=environment,sessions=data["sessions"][:64],settings=clean_settings,
               environment_events=environment_events[-64:]),ensure_ascii=False,indent=2).encode("utf8")}
    if sys.platform == 'darwin':
        from ..system.macos_compatibility import host_diagnostics
        files['macos-compatibility.json'] = json.dumps(sanitizer.clean(host_diagnostics()),ensure_ascii=False,indent=2).encode('utf8')
        from ..runtime_paths import user_data_root
        for name in ('macos-startup.json','macos-startup-failure.json'):
            path=user_data_root()/'logs'/name
            try:
                if path.is_file() and path.stat().st_size <= MAX_ATTACHMENT_BYTES:
                    files[name]=json.dumps(sanitizer.clean(json.loads(path.read_text('utf8'))),ensure_ascii=False,indent=2).encode('utf8')
            except (OSError,ValueError):
                pass
    if content:
        # Only explicitly previewed/selected rows. Never read the project file here.
        selected=[]
        for row in content[:50]:
            try:
                clean={k:sanitizer.string(v) if isinstance(v,str) else sanitizer.clean(v,k) for k,v in row.items() if k in {"subtitle_id","text","translation","start_ms","end_ms"}}
                json.dumps(clean,allow_nan=False)
                selected.append(clean)
            except (TypeError,ValueError,AttributeError,UnicodeError):
                data['missing'].append(dict(stage='selected_content',reason='invalid_selected_record'))
        raw=json.dumps(selected,ensure_ascii=False,indent=2).encode("utf8")
        if len(raw)>MAX_ATTACHMENT_BYTES:data['missing'].append(dict(stage='attachment',reason='selected_content_exceeds_256KiB'))
        else:files["selected-content.json"]=raw
    capture=getattr(instance,'playback_capture',None) if instance is not None else None
    if capture:
        try:
            raw=json.dumps(sanitizer.clean(capture),ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
            if len(raw)<=4*1024*1024:files['playback-diagnostic.json']=raw
            else:data['missing'].append(dict(reason='playback_capture_exceeds_4MiB'))
        except (TypeError,ValueError,UnicodeError) as exc:
            data['missing'].append(dict(stage='playback_capture',reason=type(exc).__name__))
    # Only explicitly referenced jobs from this live recorder. Keep technical
    # manifests; never copy raw renderer props, subtitle text or process output.
    if instance is not None and Path(root).resolve()==instance.root.resolve():
        export_root=Path(root).parent.parent/'SubtitleStudioPreview/logs/exports'
        allowed={'job_id','project_revision','caption_canvas','requested_encoder','requested_settings','settings',
                 'runtime','worker_pid','worker_thread','burn_in','render_backend','last_encoding'}
        jobs=list(dict.fromkeys(row.get('task_id') for row in reversed(data['events']) if row.get('task_id')))
        def modified(path):
            try:return path.stat().st_mtime
            except OSError:return -1
        for job_id in jobs[:8]:
            if not isinstance(job_id,str) or not re.fullmatch(r'[a-fA-F0-9]{16,64}',job_id):continue
            folder=export_root/job_id
            if not folder.is_dir() or folder.is_symlink():continue
            for path in sorted(folder.glob('*/manifest.json'),key=modified,reverse=True)[:3]:
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(export_root.resolve()) or path.stat().st_size>MAX_ATTACHMENT_BYTES:continue
                    manifest=json.loads(path.read_text('utf8'))
                    if not isinstance(manifest,dict):raise ValueError('export manifest must be an object')
                    technical={key:value for key,value in manifest.items() if key in allowed}
                    settings_keys={'container','codec','encoder','quality_mode','quality','bitrate_kbps','max_bitrate_kbps',
                        'width','height','fps','audio_codec','audio_bitrate_kbps','audio_sample_rate','audio_channels',
                        'preset','profile','level','pixel_format','gop','b_frames','font_directory','output_kind','audio_bit_depth'}
                    for field in ('settings','requested_settings'):
                        value=technical.get(field)
                        if isinstance(value,dict):
                            technical[field]={key:val for key,val in value.items() if key in settings_keys}
                            if technical[field].get('font_directory'):
                                technical[field]['font_directory']=sanitizer.alias(technical[field]['font_directory'],'path')
                    runtime=technical.get('runtime')
                    if isinstance(runtime,dict):
                        keys={'executable_path','argv0','packaged','module_path','schema_version','app_version','git_sha',
                            'git_dirty','build_time','build_channel','source_sha256','source_file_count'}
                        technical['runtime']={key:val for key,val in runtime.items() if key in keys}
                    files[f'exports/{job_id}-{path.parent.name}.json']=json.dumps(sanitizer.clean(technical),ensure_ascii=False,indent=2).encode('utf8')
                except (OSError,ValueError,TypeError,UnicodeError) as exc:
                    data['missing'].append(dict(stage='export_manifest',reason=type(exc).__name__,task_id=job_id))
    # Crash stacks have no source lines/locals; raw native files are never copied.
    for s in data["sessions"]:
        directory=Path(root)/s["directory"]
        if directory.parent.resolve()!=Path(root).resolve():continue
        candidates=[(directory/'native-fault.txt','native'),(Path(root).parent/f"gui-hang-{s.get('pid')}.txt",'hang')]
        for path,kind in candidates:
            try:
                if path.is_file() and path.stat().st_size:
                    size=path.stat().st_size
                    with path.open('rb') as stream:raw=stream.read(128*1024).decode('utf8','replace')
                    lines=[]
                    for line in raw.splitlines():
                        match=re.search(r'File "([^"]+)", line (\d+)(.*)',line)
                        if match:lines.append(f'File "{Path(match[1]).name}", line {match[2]}{sanitizer.string(match[3])}')
                        elif re.match(r'^(Windows fatal exception|Fatal Python error|Thread |Current thread |Timeout |Stack )',line):lines.append(sanitizer.string(line))
                    files[f"crash/{s['directory']}-{kind}.txt"]='\n'.join(lines).encode('utf8')
                    if size>128*1024:data['missing'].append(dict(reason='attachment_truncated',attachment=kind,omitted_bytes=size-128*1024))
            except OSError as exc:data['missing'].append(dict(reason=type(exc).__name__,attachment=kind))
    # Optional duplicates/captures must not make every event unrecoverable.
    for name in ['readable.log','playback-diagnostic.json',*[k for k in files if k.startswith('crash/')],
                 *reversed([k for k in files if k.startswith('exports/')])]:
        if sum(map(len,files.values()))<=MAX_EXPORT_BYTES-128*1024:break
        if name in files:
            omitted=len(files.pop(name))
            data['missing'].append(dict(stage='budget',reason='optional_attachment_omitted',attachment=name,bytes=omitted))
    # Include attachment failures in both views of the same export result.
    note=summary(data,report_id,description,report)
    files['README.txt']=note.encode('utf8')
    manifest=dict(format_version=FORMAT_VERSION,report_id=report_id,created=now(),scope=scope,
                  cutoff_sequence=data["cutoff_sequence"],event_count=len(data["events"]),
                  context_event_count=len(data.get('context_events',[])),serialized_event_count=len(retained),
                  status="partial" if data["missing"] or any(v for k,v in data["losses"].items() if any(word in k for word in ('failed','dropped','rotated','truncated','suppressed','omitted'))) else "complete",
                  missing=data["missing"][:128],missing_count=len(data['missing']),losses=data["losses"],upstream_task_ids=data["upstream_task_ids"],
                  content_included=bool(content),dumps_included=False,
                  files=[dict(name=k,bytes=len(v)) for k,v in files.items()])
    files["manifest.json"]=json.dumps(manifest,ensure_ascii=False,indent=2).encode("utf8")
    if sum(map(len,files.values()))>MAX_EXPORT_BYTES:raise ValueError("診斷內容超過 32 MiB，請縮小時間範圍")
    target=Path(target).absolute()
    temp=target.with_name(target.name+"."+uuid.uuid4().hex[:8]+".tmp")
    phase='zip_packaging'
    try:
        with zipfile.ZipFile(temp,"w",zipfile.ZIP_DEFLATED) as z:
            for name,value in files.items():z.writestr(name,value)
        phase='zip_verification'
        with zipfile.ZipFile(temp) as z:
            required={'README.txt','manifest.json','environment.json','events.jsonl'}
            if z.testzip() is not None or not required.issubset(z.namelist()):raise OSError("ZIP verification failed")
            checked=json.loads(z.read('manifest.json'))
            checked_environment=json.loads(z.read('environment.json'))
            checked_events=[json.loads(line) for line in z.read('events.jsonl').splitlines() if line.strip()]
            if (checked.get('report_id')!=report_id or not checked_environment.get('application')
                    or not z.read('README.txt').strip() or not checked_events
                    or len(checked_events)!=len(retained)):
                raise ValueError('Diagnostic ZIP content verification failed')
            for item in checked['files']:
                if z.getinfo(item['name']).file_size!=item['bytes']:
                    raise ValueError('Diagnostic ZIP manifest size mismatch')
        phase='atomic_publication'
        written_bytes=temp.stat().st_size
        os.replace(temp,target)
    except Exception as exc:
        try:exc.diagnostic_stage=phase
        except Exception:pass
        raise
    finally:
        try:temp.unlink(missing_ok=True)
        except OSError:pass
    return dict(report_id=report_id,status=manifest["status"],files=len(files),bytes=written_bytes,summary=note,target=str(target))


def export_failure_details(exc):
    """Copyable technical evidence; never infer disk capacity from a type."""
    from .event_log import exception_info
    chain=exception_info(exc)
    frames=[frame for item in chain.get('chain',[]) for frame in item.get('frames',[])]
    stage='collection' if any(f.get('function') in {'collect','snapshot','_session_files'} for f in frames) else 'export'
    stage=getattr(exc,'diagnostic_stage',stage)
    if not getattr(exc,'diagnostic_stage',None) and any(f.get('function') in {'writestr','_open_to_write','replace'} for f in frames):stage='write_or_package'
    reason='no_events' if isinstance(exc,ValueError) and '沒有可用事件' in str(exc) else type(exc).__name__
    details=dict(stage=stage,reason_code=reason,errno=getattr(exc,'errno',None),winerror=getattr(exc,'winerror',None),exception=chain)
    return dict(error=type(exc).__name__,stage=stage,reason_code=reason,
                details=json.dumps(details,ensure_ascii=False,indent=2))
