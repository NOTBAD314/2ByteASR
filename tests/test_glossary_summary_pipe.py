"""Real delayed readers and large private pipes, including cancellation."""
import json
import subprocess
import sys
import threading
import time

import pytest

from twobyteasr.glossary import summary_process
from twobyteasr.system import processes

class Snapshot:
    def to_dict(self):return {'blob':'字'*(512*1024)}

def delayed_reader(monkeypatch, seconds):
    code=(f'import time,json,sys;time.sleep({seconds});'
          'data=json.load(sys.stdin);'
          'print(json.dumps({"summaries":[{"received":len(data[0]["blob"])}]}))')
    def launch(_command, *, purpose, own_process_tree, **kwargs):
        return subprocess.Popen([sys.executable,'-X','utf8','-c',code],**kwargs)
    monkeypatch.setattr(processes,'popen_hidden_subprocess',launch)

def test_large_request_continues_until_delayed_reader_gets_eof(monkeypatch):
    delayed_reader(monkeypatch,.4)
    cancel=threading.Event()
    timer=threading.Timer(3,cancel.set);timer.start()
    try:
        assert summary_process.summarize([Snapshot()],cancel)==[{'received':512*1024}]
    finally:
        timer.cancel();timer.join(timeout=.2)

def test_cancel_interrupts_a_blocked_large_stdin_write(monkeypatch):
    delayed_reader(monkeypatch,5)
    cancel=threading.Event();timer=threading.Timer(.2,cancel.set);timer.start()
    start=time.monotonic()
    try:
        with pytest.raises(RuntimeError,match='cancelled'):
            summary_process.summarize([Snapshot()],cancel)
        assert time.monotonic()-start<2
    finally:
        timer.cancel();timer.join(timeout=.2)

def test_deadline_interrupts_a_blocked_large_stdin_write(monkeypatch):
    delayed_reader(monkeypatch,5)
    monkeypatch.setattr(summary_process,'_SUMMARY_TIMEOUT_SECONDS',.25)
    start=time.monotonic()
    with pytest.raises(RuntimeError,match='timed out'):
        summary_process.summarize([Snapshot()],threading.Event())
    assert time.monotonic()-start<2
