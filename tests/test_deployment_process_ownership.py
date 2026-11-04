"""Windows subprocess ownership: real descendants, pipes, and Qt completion."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

import psutil
import pytest
from PySide6.QtCore import QProcess, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.system import deployment
from twobyteasr.local_models import model_workshop

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object ownership")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(predicate, app, seconds=7):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("owned process condition timed out")
        app.processEvents()
        QTest.qWait(10)


def command_fixture(tmp_path, *, exit_code=0, root_wait=False):
    marker = "2BYTEASR_OWNER_" + uuid.uuid4().hex
    pidfile = tmp_path / "owned-child.json"
    child = (
        "import os,json,time;from pathlib import Path;"
        f"marker={marker!r};Path({str(pidfile)!r}).write_text("
        "json.dumps(dict(pid=os.getpid(),born=time.time(),marker=marker)));"
        "print('child holds stdout',flush=True);time.sleep(60)"
    )
    parent = (
        "import os,subprocess,sys,time;from pathlib import Path;"
        f"marker={marker!r};p=subprocess.Popen([sys.executable,'-I','-c',{child!r}]);"
        f"path=Path({str(pidfile)!r});deadline=time.monotonic()+5\n"
        "while not path.exists() and time.monotonic()<deadline:time.sleep(.01)\n"
        "print('root exits after child ready',flush=True)\n"
        + ("time.sleep(60)\n" if root_wait else "")
        + f"sys.exit({exit_code})"
    )
    return [sys.executable, "-I", "-c", parent], pidfile, marker


def is_live(pid):
    try:
        psutil.Process(pid).wait(timeout=0)
        return False
    except psutil.TimeoutExpired:
        return True
    except psutil.NoSuchProcess:
        return False


def child_is_gone(pidfile):
    return pidfile.exists() and not is_live(json.loads(pidfile.read_text())["pid"])


def cleanup_owned(pidfile, marker):
    if not pidfile.exists():
        return
    row = json.loads(pidfile.read_text())
    try:
        child = psutil.Process(row["pid"])
        if not is_live(child.pid):
            return
        assert abs(child.create_time()-row["born"]) < 5
        assert marker in " ".join(child.cmdline())
        descendants = child.children(recursive=True)
        child.kill()
        child.wait(timeout=5)
        for descendant in descendants:
            try:
                descendant.kill()
                descendant.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass


@pytest.mark.parametrize("exit_code", [0, 7])
def test_runner_parent_exit_closes_inherited_pipe_and_tree(tmp_path, capsys, exit_code):
    args, pidfile, marker = command_fixture(tmp_path, exit_code=exit_code)
    started = time.monotonic()
    try:
        if exit_code:
            with pytest.raises(subprocess.CalledProcessError) as caught:
                deployment.run_command(args, cwd=tmp_path, phase="owner-test", timeout=8, capture=True)
            assert caught.value.returncode == exit_code
        else:
            output = deployment.run_command(args, cwd=tmp_path, phase="owner-test", timeout=8, capture=True)
            assert "root exits after child ready" in output
        assert child_is_gone(pidfile)
        assert time.monotonic()-started < 5
        events = [json.loads(line[len(deployment.MARKER):]) for line in capsys.readouterr().out.splitlines()
                  if line.startswith(deployment.MARKER)]
        assert events[-1]["state"] == ("failed" if exit_code else "done")
    finally:
        cleanup_owned(pidfile, marker)


def test_runner_timeout_reaps_real_descendant_before_raising(tmp_path):
    args, pidfile, marker = command_fixture(tmp_path, root_wait=True)
    try:
        with pytest.raises(TimeoutError, match="超过"):
            deployment.run_command(args, cwd=tmp_path, phase="owner-timeout", timeout=.8, capture=True)
        assert child_is_gone(pidfile)
    finally:
        cleanup_owned(pidfile, marker)


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_runner_diagnostic_failure_or_interrupt_still_reaps(tmp_path, monkeypatch, failure):
    args, pidfile, marker = command_fixture(tmp_path, root_wait=True)
    real_event = deployment.event

    def fail_start(phase, state="start", **details):
        if state == "start":
            deadline = time.monotonic()+5
            while not pidfile.exists() and time.monotonic()<deadline:
                time.sleep(.01)
            assert pidfile.exists()
            raise failure("injected diagnostic interruption")
        return real_event(phase, state, **details)

    monkeypatch.setattr(deployment, "event", fail_start)
    try:
        with pytest.raises(failure):
            deployment.run_command(args, cwd=tmp_path, phase="owner-interrupted", timeout=8, capture=True)
        assert child_is_gone(pidfile)
    finally:
        cleanup_owned(pidfile, marker)


def make_bridge(tmp_path, app):
    bridge = model_workshop._HiddenProcessBridge()
    bridge.setWorkingDirectory(str(tmp_path))
    rows, output = [], []

    def consume():
        output.append(bytes(bridge.readAllStandardOutput()).decode("utf8"))

    bridge.readyReadStandardOutput.connect(consume, Qt.ConnectionType.QueuedConnection)
    bridge.finished.connect(lambda code, status: rows.append((code, status, threading.get_ident())))
    return bridge, rows, output


@pytest.mark.parametrize("exit_code", [0, 9])
def test_bridge_parent_exit_finishes_only_after_pipe_and_tree(tmp_path, app, exit_code):
    args, pidfile, marker = command_fixture(tmp_path, exit_code=exit_code)
    bridge, rows, output = make_bridge(tmp_path, app)
    try:
        bridge.start(args[0], args[1:])
        assert bridge.waitForStarted(2000)
        wait_until(lambda:bool(rows), app)
        assert rows == [(exit_code, QProcess.ExitStatus.NormalExit, threading.get_ident())]
        assert child_is_gone(pidfile)
        assert "root exits after child ready" in "".join(output)
        assert bridge.waitForFinished(20)
        app.processEvents()
        assert len(rows) == 1
    finally:
        bridge.kill()
        bridge.waitForFinished(4000)
        cleanup_owned(pidfile, marker)


@pytest.mark.parametrize("action", ["terminate", "kill"])
def test_bridge_cancellation_waits_for_owned_tree(tmp_path, app, action):
    args, pidfile, marker = command_fixture(tmp_path, root_wait=True)
    bridge, rows, output = make_bridge(tmp_path, app)
    try:
        bridge.start(args[0], args[1:])
        assert bridge.waitForStarted(2000)
        wait_until(pidfile.exists, app)
        before = time.monotonic()
        getattr(bridge, action)()
        assert time.monotonic()-before < .1
        assert bridge.waitForFinished(4000)
        app.processEvents()
        assert len(rows) == 1 and rows[0][0] != 0
        assert child_is_gone(pidfile)
    finally:
        bridge.kill()
        bridge.waitForFinished(4000)
        cleanup_owned(pidfile, marker)


def test_bridge_wait_does_not_finish_while_job_cleanup_is_blocked(tmp_path, app, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real_popen = model_workshop.popen_hidden_subprocess

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        actual = process._request_job

        class SlowJob:
            def close(self, timeout=3):
                entered.set()
                assert release.wait(5)
                actual.close(timeout=timeout)
        process._request_job = SlowJob()
        return process

    monkeypatch.setattr(model_workshop, "popen_hidden_subprocess", launch)
    bridge, rows, _ = make_bridge(tmp_path, app)
    try:
        bridge.start(sys.executable, ["-I", "-c", "print('done',flush=True)"])
        assert bridge.waitForStarted(2000)
        wait_until(entered.is_set, app)
        assert not bridge.waitForFinished(30)
        assert bridge.state() == QProcess.ProcessState.Running and not rows
        release.set()
        assert bridge.waitForFinished(3000)
        app.processEvents()
        assert len(rows) == 1
        assert bridge.waitForStarted(20)  # successfully started, even already ended
        assert bridge.waitForFinished(20)
        app.processEvents()
        assert len(rows) == 1
    finally:
        release.set()
        bridge.kill()
        bridge.waitForFinished(4000)


def test_bridge_cleanup_failure_retains_ownership_until_explicit_retry(tmp_path, app, monkeypatch):
    real_popen = model_workshop.popen_hidden_subprocess
    attempts = []

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        actual = process._request_job

        class FlakyJob:
            def close(self, timeout=3):
                attempts.append(threading.get_ident())
                if len(attempts) == 1:
                    raise OSError("injected job close failure")
                actual.close(timeout=timeout)
        process._request_job = FlakyJob()
        return process

    monkeypatch.setattr(model_workshop, "popen_hidden_subprocess", launch)
    args, pidfile, marker = command_fixture(tmp_path)
    bridge, rows, output = make_bridge(tmp_path, app)
    try:
        bridge.start(args[0], args[1:])
        assert bridge.waitForStarted(2000)
        wait_until(lambda:"清理未完成" in "".join(output), app)
        assert not rows and bridge.state() == QProcess.ProcessState.Running
        assert not bridge.waitForFinished(30)
        assert is_live(json.loads(pidfile.read_text())["pid"])
        bridge.kill()
        assert bridge.waitForFinished(4000)
        app.processEvents()
        assert len(rows) == 1 and rows[0][0] != 0
        assert len(attempts) == 2 and len(set(attempts)) == 1
        assert child_is_gone(pidfile)
    finally:
        bridge.kill()
        bridge.waitForFinished(4000)
        cleanup_owned(pidfile, marker)


def test_bridge_sparse_output_and_reuse_have_one_completion_per_run(tmp_path, app):
    bridge, rows, output = make_bridge(tmp_path, app)
    bridge.start(sys.executable, ["-I", "-c", "import time;print('early',flush=True);time.sleep(.7);print('late',flush=True)"])
    assert bridge.waitForStarted(2000)
    wait_until(lambda:"early" in "".join(output), app)
    assert not rows and "late" not in "".join(output)
    wait_until(lambda:len(rows)==1, app)
    assert "late" in "".join(output)
    bridge.start(sys.executable, ["-I", "-c", "print('second',flush=True)"])
    assert bridge.waitForStarted(2000)
    wait_until(lambda:len(rows)==2, app)
    assert "second" in "".join(output)
    bridge.waitForFinished(30)
    app.processEvents()
    assert len(rows) == 2


def test_bridge_start_failure_is_diagnostic_without_duplicate_finished(tmp_path, app):
    bridge, rows, output = make_bridge(tmp_path, app)
    bridge.start(str(tmp_path/"missing-owned-tool.exe"), [])
    assert not bridge.waitForStarted(500)
    app.processEvents()
    assert bridge.state() == QProcess.ProcessState.NotRunning and not rows
    assert "无法启动" in "".join(output)


def test_bridge_qt_owner_destruction_cancels_the_owned_tree(tmp_path, app):
    import shiboken6
    args, pidfile, marker = command_fixture(tmp_path, root_wait=True)
    bridge, rows, _ = make_bridge(tmp_path, app)
    try:
        bridge.start(args[0], args[1:])
        assert bridge.waitForStarted(2000)
        wait_until(pidfile.exists, app)
        run = bridge._run
        shiboken6.delete(bridge)
        assert run["done"].wait(4)
        assert child_is_gone(pidfile)
    finally:
        cleanup_owned(pidfile, marker)


def test_bridge_worker_allocation_failure_never_starts_a_child(tmp_path, app, monkeypatch):
    original_start = threading.Thread.start
    launches = []
    def fail_owner(thread):
        if thread.name == "model-download-owner":
            raise RuntimeError("injected worker allocation failure")
        return original_start(thread)
    monkeypatch.setattr(threading.Thread, "start", fail_owner)
    monkeypatch.setattr(model_workshop, "popen_hidden_subprocess",
                        lambda *a, **kw: launches.append((a, kw)))
    bridge, rows, output = make_bridge(tmp_path, app)
    bridge.start(sys.executable, ["-I", "-c", "pass"])
    assert not bridge.waitForStarted(50)
    QTest.qWait(50)
    assert not launches and not rows
    assert "worker allocation failure" in "".join(output)
    assert bridge.state() == QProcess.ProcessState.NotRunning


def test_bridge_reader_failure_cleans_tree_before_failure_signal(tmp_path, app, monkeypatch):
    args, pidfile, marker = command_fixture(tmp_path, root_wait=True)
    real_popen = model_workshop.popen_hidden_subprocess
    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        stream = process.stdout
        class BrokenOutput:
            def read(self, size):
                deadline = time.monotonic()+5
                while not pidfile.exists() and time.monotonic()<deadline:
                    time.sleep(.01)
                if not pidfile.exists():
                    raise AssertionError("owned child was not ready")
                raise OSError("injected pipe read error")
            def close(self):
                stream.close()
        process.stdout = BrokenOutput()
        return process
    monkeypatch.setattr(model_workshop, "popen_hidden_subprocess", launch)
    bridge, rows, output = make_bridge(tmp_path, app)
    at_finished = []
    bridge.finished.connect(lambda *_: at_finished.append(child_is_gone(pidfile)))
    try:
        bridge.start(args[0], args[1:])
        assert bridge.waitForStarted(2000)
        wait_until(lambda:bool(rows), app)
        assert len(rows)==1 and rows[0][0]!=0
        assert at_finished==[True]
        assert "injected pipe read error" in "".join(output)
        assert bridge.waitForFinished(20)
    finally:
        bridge.kill()
        bridge.waitForFinished(4000)
        cleanup_owned(pidfile, marker)


def test_bridge_job_and_nested_deployment_job_both_close_before_finished(tmp_path, app):
    args, pidfile, marker = command_fixture(tmp_path)
    source_root = Path(deployment.__file__).resolve().parents[2]
    code = ("import sys;sys.path.insert(0," + repr(str(source_root)) + ");"
            "from twobyteasr.system.deployment import run_command;"
            "result=run_command(" + repr(args) + ",cwd=" + repr(str(tmp_path)) +
            ",phase='nested-owner',timeout=6,capture=True);print(result,flush=True)")
    bridge, rows, output = make_bridge(tmp_path, app)
    stopped_at_signal = []
    bridge.finished.connect(lambda *_:stopped_at_signal.append(child_is_gone(pidfile)))
    try:
        bridge.start(sys.executable, ["-I", "-c", code])
        assert bridge.waitForStarted(2000)
        wait_until(lambda:bool(rows), app)
        assert len(rows)==1 and rows[0][0]==0, "".join(output)
        assert stopped_at_signal==[True]
        assert '"state": "done"' in "".join(output)
    finally:
        bridge.kill()
        bridge.waitForFinished(4000)
        cleanup_owned(pidfile, marker)
