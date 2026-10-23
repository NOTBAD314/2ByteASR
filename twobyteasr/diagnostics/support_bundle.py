"""Consistent, bounded, twice-sanitized support ZIPs and retention."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import time
import uuid
import zipfile

from .event_log import (FORMAT_VERSION, FILE_BYTES, MAX_EVENT_BYTES, TOTAL_BYTES,
                        RETENTION_DAYS, Sanitizer, now, readable)

MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 256 * 1024


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


def collect(root, *, instance=None, scope="recent", start=None, end=None, report=None):
    """Runs on an export/viewer worker, never on the GUI thread."""
    root=Path(root)
    missing=[]; sessions=[]; events=[]; losses=Counter(); consumed=0; cutoff=None
    sanitizer=instance.sanitizer if instance else Sanitizer((root/".alias-key").read_bytes() if (root/".alias-key").is_file() else None)
    snapshot=instance.snapshot() if instance and instance.root.resolve()==root.resolve() else None
    if snapshot:
        cutoff=snapshot["cutoff"]
        if snapshot.get("write_error"): missing.append(dict(reason="writer_error",error=snapshot["write_error"]))
    directories=sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and (p/"session.json").is_file()),key=lambda p:p.stat().st_mtime,reverse=True) if root.exists() else []
    for directory in directories:
        if consumed >= MAX_EXPORT_BYTES:
            missing.append(dict(reason="scan_limit",session=directory.name)); continue
        try:
            files=snapshot["files"] if snapshot and directory==instance.directory else _session_files(directory,missing)
            meta=json.loads(files.get("session.json",b"{}"))
            if not meta:
                missing.append(dict(session=directory.name,reason="missing_session_metadata"));continue
            if meta.get("status")=="running" and not _alive(meta): meta["status"]="previous_not_cleanly_ended"
            meta["directory"]=directory.name
            sessions.append(sanitizer.clean(meta))
            for name,data in files.items():
                if not name.endswith(".jsonl"):continue
                consumed+=len(data)
                lines=data.splitlines(keepends=True)
                for index,line in enumerate(lines):
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
                        events.append(clean)
                    except (ValueError,TypeError,UnicodeError):
                        missing.append(dict(session=directory.name,file=name,line=index+1,reason="invalid_or_partial_line"))
            losses.update(meta.get("losses",{}))
            if meta.get("dropped"):losses["legacy_dropped"]+=meta["dropped"]
        except (OSError,ValueError) as exc:
            missing.append(dict(session=directory.name,reason=type(exc).__name__))
    events.sort(key=lambda r:(r.get("time",""),r.get("pid",0),r.get("sequence",0)))
    newest=sessions[0].get("session_id",sessions[0].get("directory")) if sessions else None
    current_id=instance.session_id if snapshot else newest
    if scope=="session":
        selected=[e for e in events if e.get("session_id")==current_id]
    elif scope=="previous":
        prior=next((s for s in sessions if s.get("status") in {"previous_not_cleanly_ended","not_cleanly_ended"}),None)
        selected=[e for e in events if prior and e.get("session_id")==prior.get("session_id",prior.get("directory"))]
        if prior is None:missing.append(dict(reason="no_retained_unclean_session"))
    else:
        lower=start if scope=="range" else (datetime.now(timezone.utc)-timedelta(minutes=15)).isoformat()
        upper=end or now()
        selected=[e for e in events if (not lower or e.get("time","")>=lower) and e.get("time","")<=upper]
    # Pull the retained upstream provenance for this project/task, even across sessions.
    project_ids={e.get("project_id") for e in selected if e.get("project_id")}
    task_ids={e.get("task_id") for e in selected if e.get("task_id")}
    if report and report.get("project_id"):project_ids.add(sanitizer.alias(report["project_id"],"project"))
    for e in events:
        if e.get("project_id") in project_ids and e.get("task_id"):task_ids.add(e["task_id"])
    included={id(e) for e in selected}
    for e in events:
        if id(e) not in included and ((e.get("project_id") and e.get("project_id") in project_ids) or (e.get("task_id") and e.get("task_id") in task_ids)):
            selected.append(e)
    selected.sort(key=lambda r:(r.get("time",""),r.get("pid",0),r.get("sequence",0)))
    used_ids={e.get("session_id") for e in selected}
    selected_sessions=[s for s in sessions if s.get("session_id",s.get("directory")) in used_ids or s.get("session_id")==current_id]
    return dict(events=selected,sessions=selected_sessions,missing=missing[:128],missing_count=len(missing),
                losses=dict(losses),cutoff_sequence=cutoff,scope=scope,upstream_task_ids=sorted(task_ids),
                scanned_bytes=consumed,sanitizer=sanitizer)


SCOPE_LABELS = {"recent": "最近 15 分钟（含相关操作）", "session": "本次运行",
                "previous": "上次没有正常结束的运行", "range": "指定时间范围"}


def summary(data, report_id, description="", report=None):
    """README.txt and the copied text: conclusion, starting step, then the trail."""
    from ..i18n import tr
    from .support_triage import analyze, render_summary
    analysis = data.get("analysis") or analyze(data, report)
    sessions = data.get("sessions") or []
    session = next((s for s in sessions if isinstance(s.get("build"), dict)), sessions[0] if sessions else {})
    build = session.get("build") if isinstance(session.get("build"), dict) else {}
    version = str(tr("版本：{version} · {channel} · commit {commit} · 来源指纹 {fingerprint} · {mode}",
                     version=build.get("version") or "?", channel=build.get("channel") or "?",
                     commit=str(build.get("commit") or "?")[:12], fingerprint=str(build.get("source_sha256") or "?")[:16],
                     mode=tr("打包程序") if session.get("frozen") else tr("源码运行")))
    extra = []
    if data.get("cutoff_sequence") is not None:
        extra.append(tr("本程序记录截至 #{sequence}，其他进程只读完整的行", sequence=data["cutoff_sequence"]))
    if data.get("missing"):
        extra.append(tr("读不到的部分：{detail}", detail=json.dumps(data["missing"][:8], ensure_ascii=False)))
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    scope = data.get("scope") or "recent"
    return render_summary(analysis, report_id=report_id, description=description, generated=generated, version=version,
                          scope=tr(SCOPE_LABELS[scope]) if scope in SCOPE_LABELS else scope,
                          event_count=len(data.get("events") or []), extra_notes=extra)


def export_report(target, *, root, instance=None, scope="recent", start=None, end=None,
                  description="", report=None, content=None, settings=None):
    data=collect(root,instance=instance,scope=scope,start=start,end=end,report=report)
    if not data["events"]:
        raise ValueError("所選範圍沒有可用事件，請改選本次會話或重試；未產生空診斷包")
    sanitizer=data.pop("sanitizer")
    report_id=(report or {}).get("report_id") or "report-"+uuid.uuid4().hex[:16]
    description=sanitizer.string(description)
    note=summary(data,report_id,description,report)
    files={"README.txt":note.encode("utf8"),
           "events.jsonl":("".join(json.dumps(r,ensure_ascii=False,separators=(",", ":"))+"\n" for r in data["events"])).encode("utf8"),
           "readable.log":"".join(readable(r) for r in data["events"]).encode("utf8"),
           "environment.json":json.dumps(dict(sessions=data["sessions"],settings=sanitizer.clean(settings or {}),
               environment_events=[r for r in data["events"] if r.get("event_name") in {"host","qt","screens","graphics","media","modules","player.modules"}]),ensure_ascii=False,indent=2).encode("utf8")}
    import sys
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
        selected=[{k:sanitizer.string(v) if isinstance(v,str) else sanitizer.clean(v,k) for k,v in row.items() if k in {"subtitle_id","text","translation","start_ms","end_ms"}} for row in content[:50]]
        raw=json.dumps(selected,ensure_ascii=False,indent=2).encode("utf8")
        if len(raw)>MAX_ATTACHMENT_BYTES:raise ValueError("選取的內容超過 256 KiB，請縮小範圍")
        files["selected-content.json"]=raw
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
                    import re
                    for line in raw.splitlines():
                        match=re.search(r'File "([^"]+)", line (\d+)(.*)',line)
                        if match:lines.append(f'File "{Path(match[1]).name}", line {match[2]}{sanitizer.string(match[3])}')
                        elif re.match(r'^(Windows fatal exception|Fatal Python error|Thread |Current thread |Timeout |Stack )',line):lines.append(sanitizer.string(line))
                    files[f"crash/{s['directory']}-{kind}.txt"]='\n'.join(lines).encode('utf8')
                    if size>128*1024:data['missing'].append(dict(reason='attachment_truncated',attachment=kind,omitted_bytes=size-128*1024))
            except OSError as exc:data['missing'].append(dict(reason=type(exc).__name__,attachment=kind))
    # Include attachment failures in both views of the same export result.
    note=summary(data,report_id,description,report)
    files['README.txt']=note.encode('utf8')
    manifest=dict(format_version=FORMAT_VERSION,report_id=report_id,created=now(),scope=scope,
                  cutoff_sequence=data["cutoff_sequence"],event_count=len(data["events"]),
                  status="partial" if data["missing"] or any(v for k,v in data["losses"].items() if any(word in k for word in ('failed','dropped','rotated','truncated','suppressed'))) else "complete",
                  missing=data["missing"],losses=data["losses"],upstream_task_ids=data["upstream_task_ids"],
                  content_included=bool(content),dumps_included=False,
                  files=[dict(name=k,bytes=len(v)) for k,v in files.items()])
    files["manifest.json"]=json.dumps(manifest,ensure_ascii=False,indent=2).encode("utf8")
    if sum(map(len,files.values()))>MAX_EXPORT_BYTES:raise ValueError("診斷內容超過 32 MiB，請縮小時間範圍")
    target=Path(target)
    temp=target.with_name(target.name+"."+uuid.uuid4().hex[:8]+".tmp")
    try:
        with zipfile.ZipFile(temp,"w",zipfile.ZIP_DEFLATED) as z:
            for name,value in files.items():z.writestr(name,value)
        with zipfile.ZipFile(temp) as z:
            if z.testzip() is not None or "events.jsonl" not in z.namelist():raise OSError("ZIP verification failed")
        os.replace(temp,target)
    finally:
        try:temp.unlink(missing_ok=True)
        except OSError:pass
    return dict(report_id=report_id,status=manifest["status"],files=len(files),bytes=target.stat().st_size,summary=note,target=str(target))
