"""Studio recognition stuck right after the cloud checks (2026-11-27).

User report: Qwen3.1 Audio from Subtitle Studio stopped at 「已用 14 秒」 after
「未注册主播声纹」 and 「deepseek 端点配置有效」. Reproduced in VM2 with a damaged
live-recording FLV: Studio's audio-seek copy (ffmpeg with an unread stderr
pipe) blocked forever while holding the media folder's generation lock, and
the recognition worker waited for that lock forever, printing nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from twobyteasr.media import indexed_media
from twobyteasr.media.indexed_media import GenerationLockTimeout, IndexedMediaCache


def _run_bounded(function, seconds):
    box = {}

    def run():
        try:
            box['value'] = function()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            box['error'] = exc
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f'still running after {seconds} s'
    if 'error' in box:
        raise box['error']
    return box.get('value')


def _fake_probe(monkeypatch):
    times = {'streams': ['audio'], 'start_ms': 0.0, 'audio_start_ms': 0.0, 'duration_ms': 1000.0}

    def probe(_ffprobe, path):
        return dict(times) if Path(path).suffix != '.flv' else {**times, 'streams': ['video', 'audio']}
    monkeypatch.setattr(indexed_media, '_probe_times', probe)


def _python_process(monkeypatch, script):
    """popen_hidden_subprocess runs ``script`` with the real stderr/stdout targets."""
    def popen(command, *, purpose='', **kwargs):
        partial = command[-1]
        # Mock a native FFmpeg child, without a Windows venv launcher process.
        executable = getattr(sys, '_base_executable', sys.executable)
        return subprocess.Popen([executable, '-c', script, partial], **kwargs)
    monkeypatch.setattr(indexed_media, 'popen_hidden_subprocess', popen)


def test_audio_seek_copy_survives_ffmpeg_printing_lots_of_errors(tmp_path, monkeypatch):
    source = tmp_path / 'damaged.flv'
    source.write_bytes(b'FLV' + b'\0' * 4096)
    _fake_probe(monkeypatch)
    # 300 KB of "Packet mismatch" lines, far beyond a Windows pipe buffer,
    # then the copy is written: with an unread pipe this never returned.
    _python_process(monkeypatch, (
        "import sys\n"
        "for i in range(4000): sys.stderr.write('[flv] Packet mismatch %d 51593 402331\\n' % i)\n"
        "sys.stderr.flush()\n"
        "open(sys.argv[1], 'wb').write(b'copy')\n"))
    folder = tmp_path / 'cache'
    folder.mkdir()
    marker = _run_bounded(lambda: indexed_media.build_audio_seek_copy(
        str(source), folder, Path('ffmpeg'), Path('ffprobe')), 60)
    assert (folder / indexed_media.AUDIO_SEEK_COPY_NAME).read_bytes() == b'copy'
    assert marker['generator_version'] == indexed_media.AUDIO_SEEK_COPY_VERSION
    assert not list(folder.glob('.audio-seek.*')), 'partial copy or error log left behind'


def test_audio_seek_copy_that_stops_writing_is_stopped(tmp_path, monkeypatch):
    source = tmp_path / 'stuck.flv'
    source.write_bytes(b'FLV' + b'\0' * 4096)
    _fake_probe(monkeypatch)
    _python_process(monkeypatch, "import time\ntime.sleep(600)\n")
    monkeypatch.setattr(indexed_media, 'AUDIO_SEEK_STALL_SECONDS', 1.0)
    folder = tmp_path / 'cache'
    folder.mkdir()
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        _run_bounded(lambda: indexed_media.build_audio_seek_copy(
            str(source), folder, Path('ffmpeg'), Path('ffprobe')), 60)
    assert time.monotonic() - started < 30
    assert not list(folder.glob('.audio-seek.*'))


def _held_lock(folder: Path):
    """generation.lock owned by a live process (this one), as Studio holds it."""
    import psutil
    me = psutil.Process()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'generation.lock').write_text(
        json.dumps({'pid': me.pid, 'create_time': me.create_time()}), encoding='utf-8')


def _cache_with_folder(tmp_path, monkeypatch, source):
    cache = IndexedMediaCache(root=tmp_path / 'seek')
    folder = tmp_path / 'seek' / 'folder'
    monkeypatch.setattr(cache, '_cache_folder', lambda _source: folder)
    return cache, folder


def test_recognition_reads_a_finished_time_map_while_studio_holds_the_lock(tmp_path, monkeypatch):
    from twobyteasr.playback.avsync import AVSyncMap, save_sync_map
    source = tmp_path / 'recording.flv'
    source.write_bytes(b'FLV')
    cache, folder = _cache_with_folder(tmp_path, monkeypatch, source)
    _held_lock(folder)
    save_sync_map(folder, AVSyncMap(gaps=(), source_duration_ms=1000))
    receipt = _run_bounded(lambda: cache.prepare_timeline_source(str(source), ffmpeg='ffmpeg'), 10)
    assert receipt['kind'] == 'identity' and receipt['path'] == str(source.resolve())
    assert (folder / 'generation.lock').is_file(), 'the reader must not touch the owner lock'


def test_waiting_for_studio_lock_is_reported_and_bounded(tmp_path, monkeypatch):
    source = tmp_path / 'recording.flv'
    source.write_bytes(b'FLV')
    cache, folder = _cache_with_folder(tmp_path, monkeypatch, source)
    _held_lock(folder)  # no time map yet: the worker would have to scan under the lock
    seen = []
    with pytest.raises(GenerationLockTimeout):
        _run_bounded(lambda: cache.prepare_timeline_source(
            str(source), ffmpeg='ffmpeg', waiting=seen.append, wait_limit=2.5), 30)
    assert seen and seen[-1] >= 1


def _empty_snapshot():
    from twobyteasr.exports import timeline_media
    from twobyteasr.recognition import recognition_input
    snapshot = dict(version=2, duration_ms=1000, audio_graph={'segments': []}, sequence={}, sources={},
                    media_time_contract=timeline_media.TIME_CONTRACT, media_timebases={})
    snapshot['fingerprint'] = recognition_input._digest(snapshot)
    return snapshot


def test_studio_lock_timeout_becomes_a_plain_message(tmp_path, monkeypatch):
    from twobyteasr.exports import timeline_media
    from twobyteasr.recognition import recognition_input

    def stuck(*_args, **_kwargs):
        raise GenerationLockTimeout(tmp_path, 900)
    monkeypatch.setattr(timeline_media, 'resolve_audio_layers', stuck)
    with pytest.raises(RuntimeError, match='工作台为这个素材生成辅助文件超过 15 分 00 秒'):
        recognition_input.prepare_recognition_input(_empty_snapshot(), tmp_path, 'ffmpeg')


def test_timeline_audio_render_reports_progress_and_stops_when_stalled(tmp_path, monkeypatch):
    from twobyteasr.exports import timeline_media
    from twobyteasr.recognition import recognition_input
    from twobyteasr.system import processes
    monkeypatch.setattr(timeline_media, 'resolve_audio_layers', lambda *a, **k: ([], {}))
    monkeypatch.setattr(processes, 'popen_hidden_subprocess',
                        lambda command, *, purpose='', **kwargs: subprocess.Popen(
                            [sys.executable, '-c', 'import time; time.sleep(600)'], **kwargs))
    monkeypatch.setattr(recognition_input, 'RENDER_STALL_SECONDS', 1.5)
    lines = []
    with pytest.raises(RuntimeError, match='提取识别音频时 .* 没有任何进展'):
        _run_bounded(lambda: recognition_input.prepare_recognition_input(
            _empty_snapshot(), tmp_path, 'ffmpeg', progress=lines.append), 60)
    assert lines and lines[0].startswith('正在从时间轴提取识别用的音频')


def test_source_fingerprint_reports_progress(tmp_path, monkeypatch):
    from twobyteasr.recognition import recognition_result
    path = tmp_path / 'long.flv'
    path.write_bytes(b'x' * (9 * 1024 * 1024))
    clock = iter(range(0, 1000, 11))
    monkeypatch.setattr(time, 'monotonic', lambda: float(next(clock)))
    lines = []
    recognition_result.media_identity_for_task(path, None, progress=lines.append)
    assert lines and '正在核对素材「long.flv」' in lines[0]


def test_supervisor_shows_silence_and_stops_a_silent_worker(tmp_path, monkeypatch):
    from twobyteasr.recognition import queue_process, task_journal
    from twobyteasr.recognition.service import CancellationToken, RunOptions
    from twobyteasr.recognition.task_journal import read_record
    root = tmp_path / 'recognition-tasks'
    monkeypatch.setattr(task_journal, 'task_root', lambda: root)
    script = ("import json,sys,time;sys.stdin.readline();"
              "print(json.dumps({'kind':'console','value':'   [云端预检] 全文断句模型：deepseek 端点配置有效。'}),flush=True);"
              "time.sleep(600)")
    monkeypatch.setattr(queue_process, '_command', lambda: [sys.executable, '-c', script])
    monkeypatch.setattr(queue_process, 'SILENCE_NOTICE_SECONDS', 0.5)
    monkeypatch.setattr(queue_process, 'SILENCE_NOTICE_EVERY_SECONDS', 0.5)
    monkeypatch.setattr(queue_process, 'SILENCE_LIMIT_SECONDS', 3.0)
    lines = []
    with pytest.raises(RuntimeError, match='没有任何进度，已停止'):
        _run_bounded(lambda: queue_process.supervise(['media.wav'], RunOptions(job_id='silent'), CancellationToken(),
                                                     lambda event: None, lambda text, *level: lines.append(text)), 60)
    notices = [line for line in lines if '[等待识别进程]' in line]
    assert notices and '最后一步：[云端预检] 全文断句模型：deepseek 端点配置有效。' in notices[0]
    assert read_record(root / 'silent' / 'task.json')['status'] == 'failed'


def test_failure_text_with_json_braces_reaches_the_screen():
    from twobyteasr.i18n import join_text, tr
    error = 'PRIMARY_API worker failed: [2BYTEASR_API_ERROR] {"category": "network"}'
    assert str(join_text((tr('在线 ASR API 主力转写'), tr(error)))).endswith('{"category": "network"}')


def test_studio_input_failure_returns_a_failed_result_with_its_reason(tmp_path, capsys):
    """A failure while preparing Studio's timeline input used to return no
    result at all: Studio stayed at 「识别中」 and the window clock stopped with
    the cloud-check lines as the last thing on screen."""
    from tests.test_environment_preflight import _fake_legacy, _fake_pipeline
    from twobyteasr.recognition import service
    source = tmp_path / 'recording.flv'
    source.write_bytes(b'recorded')
    stat = source.stat()
    snapshot = {'version': 2, 'duration_ms': 1000, 'audio_graph': {'segments': []}, 'sequence': {},
                'fingerprint': 'f' * 64, 'project': {}, 'project_id': 'p', 'project_path': '',
                # The source changed after the run started: preparation stops.
                'sources': {str(source.resolve()): {'size': stat.st_size + 1, 'mtime_ns': stat.st_mtime_ns}}}
    options = service.RunOptions(job_id='studio-input-failure', recognition_snapshot_json=json.dumps(snapshot),
                                 studio_project_path=str(tmp_path / 'project' / 'p.2byteproj'))
    result = service.run_media_queue([str(source)], options, _legacy=_fake_legacy('api')(),
                                     _pipeline=_fake_pipeline()(), _skip_environment_preflight=True)
    assert [item.status for item in result.results] == ['failed']
    assert '识别启动后素材已改变' in result.results[0].error
    assert '[文件失败] 识别启动后素材已改变' in capsys.readouterr().out
