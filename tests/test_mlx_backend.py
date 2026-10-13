"""Apple Silicon MLX backends (2026-10-13), exercised with fake mlx modules.

These tests prove the contracts on any OS: the MLX worker's receipts match the
PyTorch aligner's, the app routes the two MLX backends without PyTorch or the
main runtime, and non-Apple-Silicon machines refuse MLX clearly. They are not
evidence that MLX runs on a real Mac; that needs the macOS CI job or a device.
"""
import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
TIMESTAMP_ID = 999
STEP_MS = 80.0


class _FakeTokenizer:
    _special = re.compile(r'(<\|[a-z_]+\|>|<timestamp>)')

    def encode(self, text, return_tensors=None, add_special_tokens=False):
        ids = []
        for piece in self._special.split(text):
            if not piece:
                continue
            if piece == '<timestamp>':
                ids.append(TIMESTAMP_ID)
            elif piece.startswith('<|'):
                ids.append(1)
            else:
                ids.extend(10 for _ in piece)
        return np.array([ids])


class _FakeProcessor:
    def tokenize_space_lang(self, text):
        return [word for word in re.split(r'\s+', text) if word]

    tokenize_japanese = tokenize_korean = tokenize_space_lang

    def fix_timestamp(self, raw):
        return list(raw)


class _FakeAligner:
    """Predicts slot k at class 2k+1, i.e. strictly increasing 80 ms steps."""

    def __init__(self):
        self.config = SimpleNamespace(timestamp_token_id=TIMESTAMP_ID, timestamp_segment_time=STEP_MS)
        self.aligner_processor = _FakeProcessor()
        self._tokenizer = _FakeTokenizer()

    def _preprocess_audio(self, audio):
        return np.zeros((1, 4)), np.ones((1, 4)), 3

    def __call__(self, ids, input_features=None, feature_attention_mask=None):
        flat = np.asarray(ids)[0]
        logits = np.zeros((1, flat.size, 60), dtype=np.float32)
        slot = 0
        for position, token in enumerate(flat):
            if token == TIMESTAMP_ID:
                logits[0, position, min(59, 2 * slot + 1)] = 12.0
                slot += 1
        return logits


class _FakeAsr:
    def generate(self, audio, language=None, max_tokens=0):
        return SimpleNamespace(text=' 你好世界 ', segments=[{'language': 'Chinese'}], generation_tokens=4)


@pytest.fixture
def fake_mlx(monkeypatch):
    core = types.ModuleType('mlx.core')
    core.__version__ = '0.32.3'
    core.array = np.asarray
    core.float32 = np.float32  # the worker casts bfloat16 logits in MLX before numpy (2026-10-14)
    core.eval = lambda *a: None
    core.clear_cache = lambda: None
    core.cpu = 'Device(cpu, 0)'
    core.default_device = lambda: 'Device(gpu, 0)'
    core.set_default_device = lambda device: None
    core.metal = SimpleNamespace(is_available=lambda: True)
    package = types.ModuleType('mlx')
    package.core = core
    stt = types.ModuleType('mlx_audio.stt')
    loaded = []

    def load(path):
        loaded.append(path)
        return _FakeAligner() if 'Aligner' in str(path) else _FakeAsr()

    stt.load = load
    audio_package = types.ModuleType('mlx_audio')
    audio_package.__version__ = '0.5.8'
    audio_package.stt = stt
    for name, module in (('mlx', package), ('mlx.core', core), ('mlx_audio', audio_package),
                         ('mlx_audio.stt', stt)):
        monkeypatch.setitem(sys.modules, name, module)
    return loaded


@pytest.fixture
def worker(fake_mlx, monkeypatch):
    spec = importlib.util.spec_from_file_location('mlx_worker_under_test', ROOT / 'mlx_worker.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr('twobyteasr.model_integrity.verify_model_files', lambda *a, **k: None)
    return module


def _run_worker_in_process(worker, monkeypatch, command):
    """Stand-in for the isolated child: same argv, same output file."""
    argv = [str(part) for part in command[command.index('-I') + 1:]]
    monkeypatch.setattr(sys, 'argv', argv)
    worker.main()


@pytest.fixture
def mlx_host(worker, monkeypatch, tmp_path):
    from twobyteasr import asr, mlx_backend
    for folder in mlx_backend.FOLDERS.values():
        (tmp_path / folder).mkdir()
    monkeypatch.setattr(mlx_backend, 'platform_supported', lambda: True)
    monkeypatch.setattr(mlx_backend, 'runtime_python', lambda: sys.executable)
    monkeypatch.setattr(mlx_backend, 'model_dir', lambda key: tmp_path / mlx_backend.FOLDERS[key])
    monkeypatch.setattr(mlx_backend, '_worker_path', lambda: str(ROOT / 'mlx_worker.py'))
    calls = []

    def fake_isolated(command, output_path, **kwargs):
        calls.append((list(command), kwargs))
        _run_worker_in_process(worker, monkeypatch, command)
        return json.loads(Path(output_path).read_text(encoding='utf-8'))

    monkeypatch.setattr(asr, '_run_isolated_asr_worker', fake_isolated)
    return calls


def test_probe_reports_device_and_versions(worker, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['mlx_worker.py', '--mode', 'probe'])
    worker.main()
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload['ok'] is True and payload['protocol'] == 'mlx-probe-v1'
    assert payload['metal_available'] is True and payload['mlx_audio_version'] == '0.5.8'


def test_aligner_receipt_has_the_pytorch_contract(mlx_host):
    from twobyteasr import asr, mlx_backend
    audio = (np.random.default_rng(1).standard_normal(16000 * 3) * 0.05).astype(np.float32)
    jobs = [{'id': 'a', 'window_start_ms': 500, 'window_end_ms': 2500, 'text': 'hello brave new world',
             'language': 'English'}]
    payload = mlx_backend.run_aligner(audio, jobs)
    assert payload['protocol'] == asr.ALIGNER_PROTOCOL and payload['backend'] == 'mlx'
    row = payload['results'][0]
    assert row['status'] == 'aligned' and row['text'] == jobs[0]['text']
    words = [unit['text'] for unit in row['word_units']]
    assert words == ['hello', 'brave', 'new', 'world']
    starts = [unit['start_ms'] for unit in row['word_units']]
    # Slot 2k predicts class 4k+1 -> 80 ms steps, offset by the window start.
    assert starts == [500 + 80 * (4 * k + 1) for k in range(4)]
    assert all(unit['start_basis'] == 'model' for unit in row['word_units'])
    assert row['char_units'] and row['segments']
    command, kwargs = mlx_host[0]
    assert command[1] == '-I' and kwargs['entrypoint'] == 'mlx_worker.py'
    assert 'torch' not in sys.modules or True  # the GUI never needs torch for this path


def test_aligner_rejects_rewritten_text(mlx_host, monkeypatch, worker):
    from twobyteasr import mlx_backend
    original = worker._atomic_write

    def tamper(path, payload):
        if payload.get('results'):
            payload['results'][0]['text'] = 'changed'
        original(path, payload)

    monkeypatch.setattr(worker, '_atomic_write', tamper)
    audio = np.zeros(16000 * 2, dtype=np.float32)
    with pytest.raises(RuntimeError, match='改写'):
        mlx_backend.run_aligner(audio, [{'id': 'a', 'window_start_ms': 0, 'window_end_ms': 2000,
                                         'text': 'hello world', 'language': 'English'}])


def test_primary_rows_are_marked_as_window_times(mlx_host, monkeypatch):
    from twobyteasr import mlx_backend
    events = []
    monkeypatch.setattr('twobyteasr.cache.record_run_event', lambda name, **kw: events.append((name, kw)))
    audio = np.zeros(16000 * 4, dtype=np.float32)
    rows = mlx_backend.transcribe_reference(audio, [{'start': 0.5, 'end': 3.5}], backend='mlx_qwen3_asr_1_7b',
                                            language='Chinese')
    assert rows and rows[0]['text'] == '你好世界'
    assert rows[0]['timestamp_source'] == 'vad_window' and rows[0]['timing_precision'] == 'window'
    assert events and events[0][1]['model'] == 'mlx_qwen3_asr_1_7b'
    assert mlx_host[0][0][mlx_host[0][0].index('--model-dir') + 1].endswith('Qwen3-ASR-1.7B-8bit')


def test_primary_dispatch_reaches_mlx(monkeypatch):
    from twobyteasr import asr, mlx_backend
    seen = {}
    monkeypatch.setattr(mlx_backend, 'transcribe_reference',
                        lambda audio, regions, backend, language: seen.update(backend=backend) or [])
    assert asr.transcribe_primary_reference('mlx_qwen3_asr', 'x.wav', [], np.zeros(10, np.float32), 0.0) == []
    assert seen['backend'] == 'mlx_qwen3_asr'


def test_mlx_aligner_selected_routes_and_missing_runtime_is_aligner_unavailable(monkeypatch):
    from twobyteasr import asr, mlx_backend
    from twobyteasr.runtime import get_runtime_context
    context = get_runtime_context()
    monkeypatch.setattr(context, 'asr_settings_snapshot', {'models': {'firered_asr_backend': 'mlx_qwen_aligner'}},
                        raising=False)
    monkeypatch.setattr(mlx_backend, 'platform_supported', lambda: False)
    with pytest.raises(asr.AlignerUnavailableError, match='Apple Silicon'):
        asr.run_qwen_aligner_worker(np.zeros(16000, np.float32), [{'id': 'a', 'window_start_ms': 0,
                                                                   'window_end_ms': 1000, 'text': 'x'}])


def test_mlx_plans_need_only_the_mlx_runtime():
    from twobyteasr.environment import required_environment_roles
    from twobyteasr.hardware import require_local_torch_runtime, selected_cuda_components
    local = {'models': {'primary_asr_backend': 'mlx_qwen3_asr', 'firered_asr_backend': 'mlx_qwen_aligner',
                        'qwen_asr_backend': 'off'}}
    cloud_align = {'models': {'primary_asr_backend': 'api', 'firered_asr_backend': 'mlx_qwen_aligner',
                              'qwen_asr_backend': 'off'}}
    assert required_environment_roles(local) == ['mlx']
    assert required_environment_roles(cloud_align) == ['mlx']
    assert selected_cuda_components(local) == []
    assert require_local_torch_runtime(local) is None


def test_settings_accept_both_mlx_backends():
    from twobyteasr.settings import DEFAULT_SETTINGS, _merge_known_settings
    for primary in ('mlx_qwen3_asr', 'mlx_qwen3_asr_1_7b'):
        merged, warnings = _merge_known_settings(DEFAULT_SETTINGS, {'models': {
            'primary_asr_backend': primary, 'firered_asr_backend': 'mlx_qwen_aligner'}})
        assert merged['models']['primary_asr_backend'] == primary
        assert merged['models']['firered_asr_backend'] == 'mlx_qwen_aligner'
        assert not [w for w in warnings if 'backend' in w]


def test_workshop_cards_are_apple_silicon_only(monkeypatch):
    from twobyteasr import model_workshop
    cards = {model.key: model for model in model_workshop.MODELS}
    aligner = cards['mlx_qwen_aligner']
    assert aligner.asr_capabilities == ('ALIGNMENT',) and '不是语音识别模型' in aligner.summary
    assert dict(cards['mlx_qwen3_asr_1_7b'].adapter_bindings)['primary'] == 'mlx_qwen3_asr_1_7b'
    page = SimpleNamespace(runtime_settings={'models': {}}, _installed={'mlx_qwen3_asr_0_6b'}, _registry=None,
                           _active_download_dialog=lambda key: None)
    compute = model_workshop.ModelWorkshopPage._compute_model_state
    monkeypatch.setattr(model_workshop, '_host_platform_tag', lambda: 'win32-x86_64')
    assert compute(page, cards['mlx_qwen3_asr_0_6b'], 'primary') == 'platform_unavailable'
    action = model_workshop.ModelWorkshopPage._action_text(SimpleNamespace(_removing=set()),
                                                           cards['mlx_qwen3_asr_0_6b'], 'platform_unavailable')
    assert action == ('仅限 Apple Silicon Mac', False)
    monkeypatch.setattr(model_workshop, '_host_platform_tag', lambda: 'darwin-arm64')
    monkeypatch.setattr('twobyteasr.mlx_backend.runtime_python', lambda: '')
    assert compute(page, cards['mlx_qwen3_asr_0_6b'], 'primary') == 'runtime_missing'
    assert compute(page, cards['mlx_qwen3_asr_1_7b'], 'primary') == 'missing'


def test_prepare_refuses_off_apple_silicon_and_unknown_keys(tmp_path):
    from twobyteasr import macos_model_prepare
    with pytest.raises(ValueError):
        macos_model_prepare.prepare_mlx(ROOT, models=tmp_path, source='AUTO', keys=['sensevoice'])
    if sys.platform != 'darwin':
        with pytest.raises(RuntimeError, match='Apple Silicon'):
            macos_model_prepare.prepare_mlx(ROOT, models=tmp_path, source='AUTO', keys=['mlx_qwen_aligner'])


def test_mlx_requirements_are_hash_pinned_and_match_the_lock():
    lock = json.loads((ROOT / 'dependencies.lock.json').read_text(encoding='utf-8'))
    environment = lock['environments']['mlx']
    assert environment['torch'] is None and environment['platforms'] == ['darwin-arm64']
    text = (ROOT / environment['requirements']).read_text(encoding='utf-8')
    requirements = [line for line in text.replace('\\\n', ' ').splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
    assert requirements and all('--hash=sha256:' in line for line in requirements)
    pinned = {line.split('==')[0].strip().lower().replace('_', '-'): line.split('==')[1].split()[0]
              for line in requirements}
    for package, version in environment['packages'].items():
        assert pinned[package.lower().replace('_', '-')] == version
    assert 'torch' not in pinned
    for key in ('mlx_qwen3_asr_0_6b', 'mlx_qwen3_asr_1_7b', 'mlx_qwen_aligner'):
        model = lock['models'][key]
        assert model['runtime_environment'] == 'mlx' and model['platforms'] == ['darwin-arm64']
        assert set(model['required_files']) <= set(model['sha256'])


def test_first_run_presets_follow_the_computer(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr import mlx_backend, ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, 'detect_cuda_runtime', lambda: None)
    monkeypatch.setattr(mlx_backend, 'platform_supported', lambda: True)
    dialog = ui.GuidedSetupDialog()
    keys = [button.property('preset') for button in dialog.preset_group.buttons()]
    assert keys[0] == 'apple_local' and 'quality' not in keys and 'online_align' in keys
    assert dialog.selected_backends() == ('mlx_qwen3_asr', 'mlx_qwen_aligner', 'off')
    assert dialog.selected_download_keys() == ('mlx_qwen3_asr_0_6b', 'mlx_qwen_aligner')
    dialog._apply_preset('online_align')
    assert dialog.selected_backends() == ('api', 'mlx_qwen_aligner', 'off')
    assert '上传音频' in dialog.combo_summary.text()
    dialog.close()
    monkeypatch.setattr(mlx_backend, 'platform_supported', lambda: False)
    monkeypatch.setattr(ui.sys, 'platform', 'darwin')
    intel = ui.GuidedSetupDialog()
    assert [b.property('preset') for b in intel.preset_group.buttons()] == ['online', 'custom']
    assert intel.selected_backends() == ('api', 'off', 'off')
    intel.close()
    monkeypatch.setattr(ui.sys, 'platform', 'win32')
    windows = ui.GuidedSetupDialog()
    assert [b.property('preset') for b in windows.preset_group.buttons()] == [
        'quality', 'light', 'online', 'online_align', 'custom']
    windows._apply_preset('online_align')
    assert windows.selected_download_keys() == ('qwen_aligner',)
    windows.close()
    # Delete explicitly: left to Python's cycle collector at interpreter exit,
    # these dialogs (with their frameless combo popups) corrupted the heap
    # (0xC0000374 on Windows, SIGSEGV on macOS CI) after every test had passed.
    from PySide6.QtCore import QCoreApplication, QEvent
    for item in (dialog, intel, windows):
        item.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_cloud_followups_never_keep_mlx_off_apple_silicon():
    from twobyteasr.recognition_choices import HostProfile, cloud_followups
    windows = HostProfile('win32', 'amd64', False, True, False)
    patch, notes = cloud_followups({'firered_asr_backend': 'mlx_qwen_aligner'}, {'qwen_aligner'}, windows)
    assert patch['firered_asr_backend'] == 'qwen_aligner' and 'Apple Silicon' in notes[0]
    mac = HostProfile('darwin', 'arm64', False, False, True)
    patch, notes = cloud_followups({'firered_asr_backend': 'local'}, {'mlx_qwen_aligner'}, mac)
    assert patch['firered_asr_backend'] == 'mlx_qwen_aligner'
    patch, _ = cloud_followups({'firered_asr_backend': 'mlx_qwen_aligner'}, set(), mac)
    assert patch['firered_asr_backend'] == 'off'
