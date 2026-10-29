"""Bounded background process/window evidence; never used to kill processes."""
from __future__ import annotations
import json
import os
import queue
import threading
import time
from pathlib import Path

_queue = queue.Queue(maxsize=256)
_YOUNG_CHILD_S = 15.0
_SETTLED_POLL_S = 5.0
_lock = threading.Lock()
_thread = None


def process_log_path():
    return Path(os.environ.get('TWOBYTEASR_CHILD_PROCESS_LOG') or
                Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'2ByteASR'/'logs'/f'processes-{os.getpid()}.jsonl')


def record_process(payload):
    global _thread
    try:_queue.put_nowait((process_log_path(),payload))
    except queue.Full:return
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread=threading.Thread(target=_run,daemon=True,name='process-window-diagnostics')
            _thread.start()


def _write(path, payload):
    from .editor_diagnostics import safe as redact_diagnostics, safe_text
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.stat().st_size>8*1024*1024:
            path.replace(path.with_suffix('.previous.jsonl'))
        record=redact_diagnostics(payload)
        # 2026-10-21: the command lists are what the caller chose to log (prompts
        # and keys already left out); keep them, with paths, keys, URLs and
        # e-mails redacted like any other text, instead of dropping the field.
        if isinstance(record,dict) and isinstance(payload,dict):
            for key in ('command','original_command'):
                if isinstance(payload.get(key),(list,tuple)):
                    record[key]=[safe_text(arg) for arg in payload[key]]
        with path.open('a',encoding='utf8') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n')
    except OSError:pass


def _poll_due(owned, now, last):
    """0.5 s cadence while a child is new, then every _SETTLED_POLL_S."""
    young=any(now-entry[-1]<_YOUNG_CHILD_S for entry in owned.values())
    return now-last>=(.5 if young else _SETTLED_POLL_S)


def _run():
    from ..system.processes import _window_snapshot
    try:
        import psutil
        # A frozen application's resource directory can expose an empty
        # namespace to an isolated worker that does not install this optional
        # observer. Keep recording child events and report that limitation.
        if not callable(getattr(psutil, 'Process', None)):
            raise ImportError('psutil has no Process implementation')
    except ImportError as exc:
        psutil=None
        _write(process_log_path(), {'phase':'diagnostics_unavailable',
            'component':'process_window_observer','reason':str(exc)})
    owned={};seen=set();last=0.
    while True:
        try:
            path,payload=_queue.get(timeout=.5)
            _write(path,payload)
            if payload['phase']=='start' and payload.get('child_pid') and psutil:
                try:
                    process=psutil.Process(payload['child_pid'])
                    if process.ppid()==os.getpid():owned[process.pid]=(process,path,payload,time.monotonic())
                except psutil.Error:pass
        except queue.Empty:pass
        if not psutil or not owned:continue
        # Windows (consoles, browsers, firewall prompts) appear when a child
        # starts. Watch new children every 0.5 s; long-lived ones (mpv, the
        # media probe, renderers) only every 5 s. Polling them all at 2 Hz
        # cost ~20% of a core for hours. Keep one filtered EnumWindows per
        # child: sharing a single full snapshot instead measured 3-5 GUI
        # heartbeat gaps >=100 ms per 5 s idle (1 this way), cause not found.
        now=time.monotonic()
        if not _poll_due(owned,now,last):continue
        last=now
        # One shared native census serves every child. On Windows it releases
        # the GIL during the system walk, like the resource sampler.
        tree=_process_tree(psutil)
        for pid,(process,path,payload,_started) in list(owned.items()):
            try:
                if not process.is_running():owned.pop(pid,None);continue
                family=[process,*(_descendants(psutil,tree,pid) if tree is not None else process.children(recursive=True))]
                for child in family:
                    for window in _window_snapshot(child.pid):
                        identity=(child.pid,child.create_time(),window['hwnd'],window['title'])
                        if not window['visible'] or identity in seen:continue
                        seen.add(identity)
                        title=window['title']
                        kind=('console' if child.name().lower() in {'cmd.exe','conhost.exe','openconsole.exe'}
                              else 'browser' if child.name().lower() in {'chrome.exe','msedge.exe'} else 'other')
                        _write(path,{**payload,'phase':'visible_window','observed_monotonic':last,
                            'child_pid':child.pid,'parent_pid':child.ppid(),'executable':child.exe(),
                            'command':payload['command'] if child.pid==pid else ['<redacted>'] if payload.get('redacted_details') else _safe_command(child.cmdline()),'window_kind':kind,'window':window,
                            'classification':'observed process type; authentication intent requires window evidence'})
            except psutil.Error:owned.pop(pid,None)
        # A system firewall/permission dialog may be owned by Windows rather
        # than by the application. Observe it; never claim or terminate it.
        if owned:
            for window in _window_snapshot(None):
                title=window['title'].lower()
                if not window['visible'] or not any(x in title for x in ('安全警报','防火墙','windows security','firewall','用户账户控制')):continue
                identity=(window['hwnd'],window['title'])
                if identity in seen:continue
                seen.add(identity)
                try:
                    system=psutil.Process(window['pid'])
                    _write(process_log_path(),{'phase':'system_permission_window','window_kind':'system_permission_candidate',
                        'window':window,'child_pid':system.pid,'parent_pid':system.ppid(),'executable':system.exe(),
                        'command':_safe_command(system.cmdline()),'owned':False,'trigger':'unknown; correlate with child start timestamps'})
                except psutil.Error:pass
        if len(seen)>512:seen.clear()


def _process_tree(psutil):
    """{parent pid: [child pids]} from one system snapshot, or None."""
    try:
        if os.name == 'nt':
            # Share the existing GIL-releasing census used by resource
            # diagnostics. psutil's system-wide C snapshot held the GUI and
            # the video receiver/compositor Python threads for 30-40 ms.
            from ..system.process_snapshot import process_snapshot
            parents={pid:row[0] for pid,row in process_snapshot().items()}
        else:
            snapshot=getattr(psutil,'_ppid_map',None)
            if not callable(snapshot):return None
            parents=snapshot()
    except Exception:return None
    tree={}
    for child,parent in parents.items():
        if child!=parent:tree.setdefault(parent,[]).append(child)
    return tree


def _descendants(psutil, tree, pid):
    result=[];pending=list(tree.get(pid,()));visited={pid}
    while pending:
        child=pending.pop()
        if child in visited:continue
        visited.add(child)
        try:result.append(psutil.Process(child))
        except psutil.Error:continue
        pending.extend(tree.get(child,()))
    return result


def _safe_command(command):
    result=[];redact=False
    for arg in command:
        value=str(arg)
        result.append('<redacted>' if redact else value)
        redact=value.lower() in {'-p','--prompt','--token','--api-key','--password','--secret','--auth-key'}
    return result
