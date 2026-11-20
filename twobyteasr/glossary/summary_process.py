"""Exact existing glossary statistics in an owned process, outside the GUI GIL."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

MAX_BYTES = 64 * 1024 * 1024
_SUMMARY_TIMEOUT_SECONDS = 60.0


def evaluate(payload):
    from .terminology import GlossarySnapshot
    return [GlossarySnapshot.from_dict(item).summary() for item in payload]


def summarize(snapshots, cancel):
    """Called by one daemon coordinator, never the GUI thread. Private pipes only."""
    from ..system.processes import popen_hidden_subprocess
    if cancel.is_set(): raise RuntimeError('Glossary summary cancelled')
    request = json.dumps([item.to_dict() for item in snapshots], ensure_ascii=False).encode('utf8')
    if len(request) > MAX_BYTES: raise ValueError('Glossary summary exceeds bounded request size')
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, '--glossary-summary-worker'] if getattr(sys,'frozen',False) else [
        sys.executable, '-m', 'twobyteasr.glossary.summary_process']
    process = popen_hidden_subprocess(command, purpose='glossary summary', own_process_tree=True,
        cwd=str(root), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.perf_counter()+_SUMMARY_TIMEOUT_SECONDS
    finished = threading.Event()
    aborted = []
    def monitor():
        while not finished.wait(.1):
            reason = 'cancelled' if cancel.is_set() else 'timed out' if time.perf_counter() >= deadline else ''
            if reason:
                aborted.append(reason)
                try: process.kill()
                except OSError: pass
                return
    watcher = threading.Thread(target=monitor, name='glossary-summary-cancel', daemon=True)
    watcher.start()
    try:
        # Keep stdin registered until the complete request and EOF are sent.
        # Retrying communicate(input=None) after a short POSIX timeout can
        # strand an unfinished large write. The watcher retains prompt cancel
        # and the original deadline even while Windows is writing to the pipe.
        try:
            output, _error = process.communicate(input=request, timeout=_SUMMARY_TIMEOUT_SECONDS+1)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Glossary summary timed out') from exc
        if aborted or cancel.is_set():
            raise RuntimeError('Glossary summary '+(aborted[0] if aborted else 'cancelled'))
        if process.returncode or len(output)>MAX_BYTES:
            raise RuntimeError('Glossary summary worker failed')
        response = json.loads(output.decode('utf8'))
        if 'error' in response: raise RuntimeError(response['error'])
        return response['summaries']
    finally:
        finished.set()
        watcher.join(timeout=.3)
        if process.poll() is None:
            process.kill()
            try: process.communicate(timeout=2)
            except subprocess.TimeoutExpired: pass


def _ensure_stdio():
    if os.name!='nt': return
    import ctypes
    import io
    import msvcrt
    kernel=ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes=[ctypes.c_ulong]
    kernel.GetStdHandle.restype=ctypes.c_void_p
    for number,name,flags in ((-10,'stdin',os.O_RDONLY),(-11,'stdout',os.O_WRONLY)):
        if getattr(sys,name) is not None: continue
        handle=kernel.GetStdHandle(number & 0xffffffff)
        if handle in (None,0,ctypes.c_void_p(-1).value): raise RuntimeError('Private worker pipe missing')
        stream=os.fdopen(msvcrt.open_osfhandle(handle,os.O_BINARY|flags),'rb' if name=='stdin' else 'wb',buffering=0)
        setattr(sys,name,io.TextIOWrapper(stream,encoding='utf8',write_through=True))


def main():
    os.environ['TWOBYTEASR_PROCESS_ROLE']='glossary-summary'
    _ensure_stdio()
    try:
        data=sys.stdin.buffer.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES: raise ValueError('Oversized glossary summary request')
        response={'summaries':evaluate(json.loads(data.decode('utf8')))}
    except Exception as exc:
        response={'error':type(exc).__name__}
    sys.stdout.buffer.write(json.dumps(response,ensure_ascii=False).encode('utf8'))
    sys.stdout.buffer.flush()
    return 0


if __name__=='__main__': raise SystemExit(main())
