"""Idle storage maintenance outside the window process (2026-11-23).

User report: a minute after start the whole app stuttered for many minutes; the
six-hourly cache pass held Python's lock inside the window process.
"""
import io
import threading
import time
from pathlib import Path
from threading import Event

import pytest

from twobyteasr.recognition.task_journal import dependency_matcher, depends_on
from twobyteasr.runtime_paths import RuntimePaths
from twobyteasr.storage import maintenance_process
from twobyteasr.storage.storage_service import StorageService


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def service(tmp_path):
    data = tmp_path / 'data'; cache = data / 'cache'; cache.mkdir(parents=True)
    models = data / 'models'; models.mkdir()
    paths = RuntimePaths(tmp_path, data, models, cache, data / 'projects', data,
        data / 'logs', tmp_path / 'renderer', data / 'tmp')
    return StorageService(paths, roots=[cache], state_root=data / 'storage')


def _thumbnails(service, tmp_path, count):
    source = tmp_path / 'video.mp4'; source.write_bytes(b'video')
    folder = service.paths.cache_root / 'thumbs'; folder.mkdir()
    paths = []
    for index in range(count):
        path = folder / f't{index}.jpg'; path.write_bytes(b'jpg')
        assert service.register(path, 'thumbnail', source=str(source), producer='filmstrip')
        paths.append(path)
    items = [item for item in service.scan(Event(), include_models=False).items if item.category == 'thumbnail']
    assert len(items) == count and all(item.cleanable for item in items)
    return paths, items


@pytest.mark.parametrize('references', [
    [], [r'C:\cache\task1'], ['C:\\'], ['D:\\a\\b\\', r'c:\CACHE\Task2\chunk.wav'], ['relative'],
])
def test_prepared_matcher_answers_like_depends_on(references):
    candidates = [r'C:\cache\task1', r'C:\cache\task1\f.wav', r'C:\cache\task10\f', r'C:\Cache\task2\chunk.wav',
                  r'C:\cache\task2\chunk.wav2', r'D:\a\b\c', r'D:\a\bc', r'D:\a\b', 'D:\\', r'relative\x', r'E:\z']
    matches = dependency_matcher(references)
    assert [matches(path) for path in candidates] == [depends_on(path, references) for path in candidates]


def test_prepared_matcher_does_not_scale_with_references():
    references = [rf'C:\cache\task{i // 100}\chunk{i:05d}.wav' for i in range(5000)]
    matches = dependency_matcher(references)
    started = time.perf_counter()
    for index in range(2000):
        assert not matches(rf'C:\preview\filmstrip\t{index}.jpg')
    # depends_on took ~10 ms per path with 2000 references; this is microseconds.
    assert time.perf_counter() - started < 1.0


def test_automatic_cleanup_stops_at_the_first_busy_check(service, tmp_path):
    paths, items = _thumbnails(service, tmp_path, 5)
    calls = []
    service.busy = lambda: calls.append(1) or True
    result = service.clean(items, automatic=True)
    assert len(calls) == 1
    assert len(result.skipped) == 5 and not result.deleted
    assert all('稍后重试' in row['reason'] for row in result.skipped)
    assert all(path.exists() for path in paths)


def test_automatic_cleanup_rechecks_busy_at_the_delete_boundary(service, tmp_path):
    paths, items = _thumbnails(service, tmp_path, 2)
    activity = iter([False, True])
    service.busy = lambda: next(activity)
    result = service.clean(items, automatic=True)
    assert len(result.skipped) == 2 and not result.deleted
    assert all(path.exists() for path in paths)

def test_cleanup_uses_one_index_connection(service, tmp_path, monkeypatch):
    paths, items = _thumbnails(service, tmp_path, 4)
    opened = []
    original = service._connect
    monkeypatch.setattr(service, '_connect', lambda: opened.append(1) or original())
    result = service.clean(items)
    assert len(result.deleted) == 4 and not any(path.exists() for path in paths)
    assert opened == [1]
    entries, _leases = service._registered(read_only=True)
    assert not any(Path(path) in paths for path in entries)


class _Pipe:
    """Lines the window would write; blocks until told what to say next."""
    def __init__(self):
        self.lines = []
        self.ready = threading.Condition()
        self.closed = False

    def say(self, word):
        with self.ready:
            self.lines.append(word + '\n'); self.ready.notify_all()

    def close(self):
        with self.ready:
            self.closed = True; self.ready.notify_all()

    def __iter__(self):
        while True:
            with self.ready:
                self.ready.wait_for(lambda: self.lines or self.closed, timeout=10)
                if self.lines:
                    line = self.lines.pop(0)
                elif self.closed:
                    return
                else:
                    raise OSError('test pipe timed out')
            yield line


def test_helper_does_nothing_while_the_window_is_busy():
    ran = []
    result = maintenance_process.run(io.StringIO('busy\n'), maintain=lambda *a: ran.append(a),
                                     service_factory=lambda **kwargs: kwargs)
    assert result is None and not ran


def test_helper_follows_the_window_and_stops_with_the_pipe():
    pipe = _Pipe()
    seen = {}

    def maintain(service, cancel):
        seen['idle'] = service['busy']()
        pipe.say('busy')
        deadline = time.monotonic() + 5
        while not service['busy']() and time.monotonic() < deadline:
            time.sleep(.01)
        seen['busy'] = service['busy']()
        pipe.say('idle')
        while service['busy']() and time.monotonic() < deadline:
            time.sleep(.01)
        pipe.close()
        cancel.wait(5)
        seen['cancelled'] = cancel.is_set()
        seen['busy_after_close'] = service['busy']()
        seen['media'] = service['media_references']()
        return 'done'

    pipe.say('idle')
    assert maintenance_process.run(pipe, maintain=maintain, service_factory=lambda **kwargs: kwargs) == 'done'
    assert seen == dict(idle=False, busy=True, cancelled=True, busy_after_close=True, media=None)


class _FakeProcess:
    def __init__(self):
        self.stdin = io.BytesIO(); self.code = None; self.closed_with = None
        self.stdin.close = lambda: setattr(self, 'closed_with', self.stdin.getvalue())

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.code = 0
        return 0

    def kill(self):
        self.code = -9


def test_window_side_reports_changes_only_and_ends_the_helper(qapp, monkeypatch):
    from twobyteasr.storage import storage_ui
    fake = _FakeProcess()
    monkeypatch.setattr(maintenance_process, 'start_helper', lambda: fake)
    state = {'busy': False}
    worker = storage_ui.StorageMaintenanceProcess(lambda: state['busy'])
    worker.start()
    assert worker.isRunning() and worker.timer.isActive()
    worker._poll(); worker._poll()
    state['busy'] = True; worker._poll(); worker._poll()
    state['busy'] = False; worker._poll()
    assert fake.stdin.getvalue() == b'idle\nbusy\nidle\n'
    worker.stop()
    assert fake.closed_with == b'idle\nbusy\nidle\nstop\n'
    assert not worker.timer.isActive()
    finished = []
    worker.finished.connect(lambda: finished.append(True))
    fake.code = 0; worker.cancel.clear(); worker._poll()
    assert finished == [True] and not worker.isRunning()
    worker.deleteLater(); qapp.processEvents()


def test_an_open_project_keeps_the_helper_waiting(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.storage import storage_ui
    studio = SimpleNamespace(project=SimpleNamespace(media=SimpleNamespace(path='')), _close_requested=False)
    monkeypatch.setattr(storage_ui, 'app_busy', lambda owner: False)
    monkeypatch.setattr(storage_ui, 'existing_page', lambda owner, name: studio if name == 'studio' else None)
    assert storage_ui._maintenance_busy(object())
    studio.project = None
    assert not storage_ui._maintenance_busy(object())


def test_helper_command_uses_the_app_itself_when_frozen(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert maintenance_process.helper_command() == [sys.executable, '--storage-maintenance-worker']
