from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from twobyteasr.diagnostics.support_bundle import _scan_session
from twobyteasr.local_models import alignment_readiness as readiness
from twobyteasr.playback.audio_diagnostics import AudioStderr
from twobyteasr.playback.audio_process import AudioProcessBridge
from twobyteasr.playback import audio_process
from twobyteasr.recognition import alignment_backend, asr
from twobyteasr.recognition.run_diagnosis import diagnose_run


def test_slow_cold_device_is_not_restarted_at_the_old_deadline(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    bridge = AudioProcessBridge(Path('ffmpeg.exe'))
    bridge.process = SimpleNamespace(pid=42, poll=lambda: None)
    bridge._ack_pending = True
    bridge._sent_at = 100.
    failures = []
    monkeypatch.setattr(bridge, '_report_failure', lambda *args: failures.append(args))
    monkeypatch.setattr(audio_process.time, 'monotonic', lambda: 119.)
    bridge._check_health()
    assert bridge._ack_pending and not failures
    monkeypatch.setattr(audio_process.time, 'monotonic', lambda: 125.)
    bridge._check_health()
    bridge._check_health()
    assert failures == [('cold_output_timeout', 42, None, '')]
    assert not bridge._ack_pending
    assert app is not None


def test_audio_stderr_keeps_first_error_and_last_stack_under_a_size_limit():
    output = AudioStderr()
    output.append(b'first cause\n')
    for _ in range(100):
        output.append(b'x' * 512)
    output.append(b'\nRuntimeError: last frame')
    stderr = output.text()
    assert stderr.startswith('first cause')
    assert stderr.endswith('RuntimeError: last frame')
    assert '[stderr truncated]' in stderr
    assert len(stderr.encode()) < 8300


@pytest.fixture
def qwen_routes(monkeypatch, tmp_path):
    from twobyteasr.model_integrity import load_dependency_lock

    routes = {}
    models = load_dependency_lock()['models']
    for key in ('qwen_aligner', 'qwen_ultra_aligner'):
        folder = tmp_path / key
        folder.mkdir()
        for name in models[key]['required_files']:
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('fixture', encoding='utf8')
        routes[key] = str(folder)
    monkeypatch.setattr(alignment_backend, 'model_directory', routes.get)
    monkeypatch.setattr(asr, '_main_worker_python', lambda: 'isolated-python.exe')
    packages = dict.fromkeys(('qwen-asr', 'torch', 'transformers', 'numpy', 'safetensors', 'nagisa'), '0.0.6')
    monkeypatch.setattr(readiness, 'runtime_identity', lambda python: {'packages': packages})
    monkeypatch.setattr(readiness, '_read_receipt', lambda key: {})
    return routes


def test_official_weights_allow_legacy_route_but_ultra_requires_its_own_receipt(qwen_routes, monkeypatch):
    assert readiness.qwen_status('qwen_aligner')['ready']
    assert readiness.qwen_status('qwen_ultra_aligner')['state'] == 'inference_pending'
    monkeypatch.setattr(readiness, '_read_receipt', lambda key: {'status': 'FAIL', 'error': 'sample failed'})
    status = readiness.qwen_status('qwen_ultra_aligner')
    assert not status['ready']
    assert status['state'] == 'load_failed' and status['reason'] == 'sample failed'


def test_wrong_profile_and_partial_weights_stay_actionable(qwen_routes):
    qwen_routes['qwen_aligner'] = ''
    assert readiness.qwen_status('qwen_aligner')['state'] == 'path_mismatch'
    from twobyteasr.model_integrity import load_dependency_lock
    model = load_dependency_lock()['models']['qwen_ultra_aligner']
    (Path(qwen_routes['qwen_ultra_aligner']) / model['required_files'][0]).unlink()
    assert readiness.qwen_status('qwen_ultra_aligner')['state'] == 'partial'


@pytest.mark.parametrize(('message', 'expected'), [
    ('[alignment:path_mismatch] 官方兼容版', 'alignment_path_mismatch'),
    ('[alignment:inference_pending] Ultra', 'alignment_inference_pending'),
    ('[alignment:load_failed] Ultra', 'alignment_load_failed'),
    ('[alignment:runtime_missing] Ultra', 'runtime_broken'),
    ('[alignment:partial] Ultra', 'model_missing'),
    ('缺少新流水线组件：Qwen3 ForcedAligner 模型', 'legacy_alignment_component'),
])
def test_diagnosis_distinguishes_preflight_states(message, expected):
    outcome = diagnose_run({'status': 'failed', 'result': {'error': message, 'cue_count': 0}})
    assert expected in {row.issue.id for row in outcome.findings}
    if expected != 'runtime_broken':
        assert all(row.issue.id != 'runtime_broken' for row in outcome.findings)


def test_support_scan_retains_errors_around_a_damaged_record(tmp_path):
    raw = (b'{"event_name":"first","message":"actual error"}\ninvalid\n'
           b'{"event_name":"last"}\n{"unfinished"')
    events, missing, _ = _scan_session(tmp_path, {'events.jsonl': raw}, {}, {}, lambda: None)
    assert len(events) == 2
    assert [(row['line'], row['detail']) for row in missing] == [
        (2, 'invalid_record'), (4, 'unterminated_final_line')]


def test_media_probe_codes_do_not_conflate_missing_duration_audio_or_bad_input(tmp_path):
    import json
    from twobyteasr.media.media_service import MediaService

    source = tmp_path / '音訊 來源.mp3'
    source.write_bytes(b'fixture')

    def probe(format_info, streams):
        return MediaService(probe_runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps({'format': format_info, 'streams': streams}))).metadata(source, refresh=True)

    unknown = probe({}, [{'codec_type': 'audio'}])
    assert unknown.has_audio and unknown.duration_state == 'unknown'
    zero = probe({'duration': '0.0'}, [{'codec_type': 'audio'}])
    assert zero.has_audio and zero.duration_state == 'zero'
    silent_video = probe({'duration': '1.0'}, [{'codec_type': 'video'}])
    assert not silent_video.has_audio and silent_video.duration_state == 'known'
    failed = MediaService(probe_runner=lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stderr='input not decodable'))
    with pytest.raises(RuntimeError, match='input not decodable'):
        failed.metadata(source, refresh=True)


def test_media_service_and_studio_use_the_same_install_root(tmp_path, monkeypatch):
    from twobyteasr import runtime_paths
    from twobyteasr.media.media_service import MediaService
    from twobyteasr.playback import audio_engine
    from twobyteasr.studio.studio_video_track import ffmpeg_executable
    from twobyteasr.system.platform_media import executable_name

    monkeypatch.setattr(runtime_paths, 'get_runtime_paths', lambda: SimpleNamespace(install_root=tmp_path))
    monkeypatch.setattr(audio_engine, 'get_runtime_paths', runtime_paths.get_runtime_paths)
    expected = tmp_path / 'tools' / 'ffmpeg' / 'bin'
    service = MediaService()
    assert expected / executable_name('ffmpeg') == service.ffmpeg_path == audio_engine.studio_ffmpeg_path() == ffmpeg_executable()
    assert expected / executable_name('ffprobe') == service.ffprobe_path


@pytest.mark.parametrize(('profile', 'head', 'keys'), [
    ('official-v1', False, ('qwen_aligner',)),
    ('ultra-v5', False, ('qwen_ultra_aligner',)),
    ('ultra-v5', True, ('qwen_ultra_aligner', 'qwen_ultra_head')),
])
def test_application_startup_preflights_exact_saved_profile(profile, head, keys, monkeypatch):
    from twobyteasr.app.ui import required_recognition_model_keys
    from twobyteasr.recognition import alignment_backend
    monkeypatch.setattr(alignment_backend, '_official_weights_replaced_by_ultra', lambda: False)  # official folder present
    settings = {'models': {'firered_asr_backend': 'qwen_aligner',
                           'qwen_alignment_profile': profile, 'qwen_alignment_head': head}}
    assert required_recognition_model_keys(settings) == keys
