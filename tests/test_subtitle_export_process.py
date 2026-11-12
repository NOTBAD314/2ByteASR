import ctypes
import os
import sys
import time

import psutil
import pytest

from twobyteasr.exports.subtitle_export_task import SubtitleExportTask
from twobyteasr.exports.subtitle_snapshot import SubtitleSnapshot
from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, export_language_layers
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue


def task_for(tmp_path, directory=None, formats=frozenset({"srt"})):
    project = SubtitleProject(StudioMedia('', duration_ms=4000), cues=[StudioCue('a', 0, 1000, '字幕？！')])
    project.validate()
    return SubtitleExportTask(SubtitleSnapshot.capture(project), directory or tmp_path, 'out', formats, (),
                             'combined', True, export_subtitle_artifacts, export_language_layers)


def finished(task):
    task.start()
    assert task.done.wait(30), task.details
    assert task.snapshot is None and task._arguments is None
    assert not task.cleanup_leftovers
    if hasattr(task, 'worker_pid'):
        assert not psutil.pid_exists(task.worker_pid)


def test_real_owned_process_exports_and_exits_without_holding_snapshot(tmp_path):
    task = task_for(tmp_path, formats=frozenset({"srt", "txt", "ass", "json"}))
    finished(task)
    assert task.error is None and task.worker_exit == 0
    assert len(task.artifacts) == 4
    srt = next(artifact for artifact in task.artifacts if artifact.format == "srt")
    assert srt.path.read_text(encoding='utf-8').endswith('字幕\n')
    assert task.snapshot_bytes > 0 and task.snapshot_sha256
    assert not list(tmp_path.glob('.subtitle-*'))


def test_real_process_reports_invalid_destination_and_preserves_existing_files(tmp_path):
    blocked = tmp_path / 'file-as-directory'
    blocked.write_bytes(b'original')
    task = task_for(tmp_path, blocked)
    finished(task)
    assert task.error is not None and task.exception_type == 'FileExistsError'
    assert blocked.read_bytes() == b'original'


def test_pre_cancel_never_starts_a_worker_or_publishes(tmp_path):
    task = task_for(tmp_path)
    task.cancel.set()
    finished(task)
    assert task.exception_type == 'SubtitleExportCancelled'
    assert not hasattr(task, 'worker_pid') and not list(tmp_path.glob('*.srt'))


def large_cold_task(tmp_path, monkeypatch):
    from twobyteasr.system import processes
    real_start = processes.popen_hidden_subprocess
    def cold_start(_command, **kwargs):
        return real_start([sys.executable, '-B', '-X', 'utf8', '-c',
            'import time; time.sleep(.35); from twobyteasr.exports.subtitle_export_process import main; raise SystemExit(main())'],
            **kwargs)
    monkeypatch.setattr(processes, 'popen_hidden_subprocess', cold_start)
    project = SubtitleProject(StudioMedia('', duration_ms=4000), cues=[StudioCue('a', 0, 1000, '大请求字幕')])
    project.generation_metadata['owned_pipe_regression'] = 'x' * 1_000_000
    return SubtitleExportTask(SubtitleSnapshot.capture(project), tmp_path, 'large', {'srt'}, (),
        'combined', False, export_subtitle_artifacts, export_language_layers)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX pipe backpressure and communicate retry regression')
def test_large_request_survives_worker_start_slower_than_poll_interval(tmp_path, monkeypatch):
    task = large_cold_task(tmp_path, monkeypatch)
    finished(task)
    assert task.snapshot_bytes > 1_000_000
    assert task.error is None and len(task.artifacts) == 1
    assert '大请求字幕' in task.artifacts[0].path.read_text('utf8')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX owned cancellation during full input transfer')
def test_cancel_is_not_lost_while_a_large_request_is_being_transferred(tmp_path, monkeypatch):
    task = large_cold_task(tmp_path, monkeypatch)
    task.start()
    deadline = time.monotonic() + 5
    while not hasattr(task, 'worker_pid') and time.monotonic() < deadline:
        time.sleep(.01)
    assert hasattr(task, 'worker_pid')
    task.cancel.set()
    assert task.done.wait(30), task.details
    assert task.exception_type == 'SubtitleExportCancelled'
    assert task.snapshot is None and not list(tmp_path.glob('*.srt'))
    assert not psutil.pid_exists(task.worker_pid)


@pytest.mark.skipif(os.name != 'nt', reason='Windows exclusive file handle')
def test_real_windows_locked_target_returns_explicit_failure_and_can_retry(tmp_path):
    target = tmp_path / 'out.srt'
    target.write_bytes(b'old export')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.restype = ctypes.c_void_p
    api.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                               ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = api.CreateFileW(str(target), 0x80000000, 0, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    try:
        task = task_for(tmp_path)
        finished(task)
        assert task.error is not None and task.exception_type == 'SubtitlePublicationError'
    finally:
        api.CloseHandle(handle)
    assert target.read_bytes() == b'old export'
    retry = task_for(tmp_path)
    finished(retry)
    assert retry.error is None and not list(tmp_path.glob('.subtitle-*'))
