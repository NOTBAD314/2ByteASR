"""Real owned Windows children; rescue cleanup checks PID creation time."""
import json
import os
import sys
import threading
import time

import psutil
import pytest

from twobyteasr import advanced_renderer

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows renderer descendant cleanup")


@pytest.fixture
def owned_renderer(tmp_path, monkeypatch):
    processes, jobs, identities = [], [], []
    pidfile = tmp_path / "owned-processes.json"
    original = advanced_renderer.popen_hidden_subprocess

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        identities.append((process.pid, psutil.Process(process.pid).create_time()))
        job = getattr(process, "_request_job", None)
        if job is not None:
            jobs.append(job)
        return process

    def known_identities():
        result = list(identities)
        if pidfile.exists():
            result.extend((item["pid"], item["create_time"])
                          for item in json.loads(pidfile.read_text()))
        return list(dict.fromkeys(result))

    def rescue():
        for pid, created in reversed(known_identities()):
            try:
                current = psutil.Process(pid)
                if current.create_time() == created:
                    current.kill()
                    current.wait(3)
            except psutil.NoSuchProcess:
                pass

    monkeypatch.setattr(advanced_renderer, "popen_hidden_subprocess", launch)
    timer = threading.Timer(5, rescue)
    timer.start()
    yield processes, jobs, pidfile, known_identities
    timer.cancel()
    for job in jobs:
        job.close()
    rescue()
    (tmp_path / "fixture-identities.json").write_text(json.dumps(known_identities(), indent=2))


def _command(pidfile, *, root_wait=True, inherit_pipe=True):
    child = [sys.executable, "-c", "import time;time.sleep(30)"]
    output = "sys.stdout" if inherit_pipe else "subprocess.DEVNULL"
    code = (
        "import subprocess,sys,time,json,os,psutil;from pathlib import Path;"
        f"p=subprocess.Popen({child!r},stdout={output},stderr={output},"
        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));"
        "time.sleep(.1);"
        f"Path({str(pidfile)!r}).write_text(json.dumps(["
        "{'pid':item.pid,'create_time':item.create_time()} "
        "for item in [psutil.Process(),*psutil.Process().children(recursive=True)]]));"
        "print('ready',flush=True);"
        + ("time.sleep(30)" if root_wait else "sys.exit(0)")
    )
    return [sys.executable, "-u", "-c", code]


def _assert_exited(known_identities):
    identities = known_identities()
    assert len(identities) >= 2, "fixture must actually start its descendant"
    for pid, created in identities:
        try:
            current = psutil.Process(pid)
            assert current.create_time() != created, f"owned process is still alive: {pid}"
        except psutil.NoSuchProcess:
            pass


def test_cancel_silent_renderer_stops_its_descendants(owned_renderer):
    processes, jobs, pidfile, identities = owned_renderer
    cancel, sent = threading.Event(), []

    def ready(line):
        if line == "ready":
            sent.append(time.perf_counter())
            cancel.set()

    with pytest.raises(InterruptedError):
        advanced_renderer._run_streaming_process(
            _command(pidfile), on_line=ready, cancelled=cancel.is_set, stall_timeout=30)
    assert time.perf_counter() - sent[0] < 1.5
    assert processes[0].poll() is not None
    _assert_exited(identities)


def test_cancel_after_root_exit_stops_descendant_holding_stdout(owned_renderer):
    processes, jobs, pidfile, identities = owned_renderer
    cancel, root_exited = threading.Event(), []

    def ready(line):
        if line == "ready":
            processes[0].wait(timeout=2)
            root_exited.append(True)
            cancel.set()

    started = time.perf_counter()
    with pytest.raises(InterruptedError):
        advanced_renderer._run_streaming_process(
            _command(pidfile, root_wait=False), on_line=ready, cancelled=cancel.is_set)
    assert root_exited and time.perf_counter() - started < 2
    _assert_exited(identities)


@pytest.mark.parametrize("inherit_pipe", [False, True])
def test_normal_completion_reaps_descendants_after_root_exit(owned_renderer, inherit_pipe):
    processes, jobs, pidfile, identities = owned_renderer
    started, lines = time.perf_counter(), []
    code, tail = advanced_renderer._run_streaming_process(
        _command(pidfile, root_wait=False, inherit_pipe=inherit_pipe), on_line=lines.append)
    assert code == 0 and lines == ["ready"] and tail == "ready"
    assert time.perf_counter() - started < 2
    _assert_exited(identities)


@pytest.mark.parametrize("failure", [OSError, TimeoutError])
def test_cleanup_failure_is_propagated_once_without_readline_hang(owned_renderer, failure):
    processes, jobs, pidfile, identities = owned_renderer
    cancel, calls = threading.Event(), []

    class FailedJob:
        def close(self, timeout=3):
            calls.append(timeout)
            raise failure("fixture cleanup did not finish")

    def ready(line):
        if line == "ready":
            assert jobs, "the renderer must own a Windows Job"
            processes[0]._request_job = FailedJob()
            cancel.set()

    started = time.perf_counter()
    with pytest.raises(failure, match="fixture cleanup did not finish"):
        advanced_renderer._run_streaming_process(
            _command(pidfile), on_line=ready, cancelled=cancel.is_set)
    assert calls == [3] and time.perf_counter() - started < 2
    jobs[0].close()  # Real Job remains owned by this fixture.
    _assert_exited(identities)


def test_cancel_callback_error_still_cleans_owned_job(owned_renderer):
    processes, jobs, pidfile, identities = owned_renderer
    ready = threading.Event()

    def broken_cancel():
        if ready.is_set():
            raise ValueError("fixture cancellation callback failed")
        return False

    with pytest.raises(ValueError, match="fixture cancellation callback failed"):
        advanced_renderer._run_streaming_process(
            _command(pidfile), on_line=lambda line: ready.set(), cancelled=broken_cancel)
    _assert_exited(identities)


def test_stream_preserves_order_tail_and_exit_status():
    lines = []
    code, tail = advanced_renderer._run_streaming_process(
        [sys.executable, "-u", "-c", "import sys;[print(i) for i in range(400)];sys.exit(7)"],
        on_line=lines.append)
    assert code == 7
    assert lines == [str(i) for i in range(400)]
    assert tail.splitlines() == lines[-120:]
