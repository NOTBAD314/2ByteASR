"""Pinned Windows CrispASR adapter for the Japanese Haas checkpoint."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from ..runtime_paths import get_runtime_paths
from ..subtitle_rules.language_rules import normalize_language

BACKEND = 'haas_ja'
RUNTIME_VERSION = '0.8.55'
RUNTIME_REVISION = '0e591b24'
SAMPLE_RATE = 16000
MAX_WINDOW_SECONDS = 30
BATCH_WINDOWS = 32
VARIANTS = {'q8_0': 'haas_ja_q8_0', 'f16': 'haas_ja_f16', 'q4_k': 'haas_ja_q4_k'}


def runtime_environment():
    keys = {'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'PATH', 'TEMP', 'TMP'}
    allowed = {key.upper(): value for key, value in os.environ.items() if key.upper() in keys}
    bundled_cpu = get_runtime_paths().install_root / 'tools' / 'crispasr' / RUNTIME_VERSION / 'cpu'
    if bundled_cpu.is_dir():
        # The optional managed CUDA runtime shares the product's app-local CRT.
        allowed['PATH'] = os.pathsep.join(filter(None, (str(bundled_cpu), allowed.get('PATH'))))
    return dict(allowed, CRISPASR_HAAS_LONGFORM='1', CRISPASR_GAP_FILL='0')


@dataclass(frozen=True)
class Configuration:
    quantization: str
    device: str

    @property
    def model_key(self):
        return VARIANTS[self.quantization]

    @property
    def model_name(self):
        return f'haas-ja-v1.0-{self.quantization}.gguf'


def configuration(settings):
    options = (settings or {}).get('models') or {}
    quantization = options.get('haas_quantization', 'q8_0')
    device = options.get('haas_device', 'cpu')
    if quantization not in VARIANTS or device not in {'cpu', 'cuda'}:
        raise ValueError('Haas 模型精度或執行裝置設定無效。')
    return Configuration(quantization, device)


def runtime_executable(device):
    if sys.platform != 'win32':
        return None
    paths = get_runtime_paths()
    subdir = Path('crispasr') / RUNTIME_VERSION / device
    for root in (paths.managed_runtime_root, paths.install_root / 'tools'):
        candidate = root / subdir / 'crispasr.exe'
        if candidate.is_file():
            return candidate
    return None


def bundle(config):
    from ..model_integrity import verify_model_files
    paths = get_runtime_paths()
    directory = paths.model_root / f'Haas-ja-v1.0-{config.quantization}'
    executable = runtime_executable(config.device)
    if executable is None:
        raise RuntimeError(f'Haas 需要 CrispASR {RUNTIME_VERSION} {config.device.upper()} 執行元件。')
    verify_model_files(config.model_key, directory)
    model = directory / config.model_name
    if not model.is_file():
        raise RuntimeError(f'Haas {config.quantization.upper()} 權重未安裝，請在模型工坊下載。')
    return executable, model


def _clock(item):
    offsets = item.get('offsets') or {}
    if 'from' in offsets and 'to' in offsets:
        return (int(offsets['from']), int(offsets['to']))
    if 't0' in item and 't1' in item:
        # CrispASR t0/t1 are centiseconds. The offsets object is milliseconds.
        return (int(item['t0']) * 10, int(item['t1']) * 10)
    return None


def parse_transcription(payload, first_sample, last_sample):
    """Project local-clock native boundaries onto source PCM exactly once."""
    if not isinstance(payload.get('transcription'), list):
        raise ValueError('CrispASR 缺少有效的 transcription 陣列。')
    duration_ms = (last_sample - first_sample) * 1000 / SAMPLE_RATE
    offset = first_sample / SAMPLE_RATE
    rows = []
    for segment in payload['transcription']:
        text = str(segment.get('text') or '').strip()
        if not text:
            continue
        clock = _clock(segment)
        if clock is None or not 0 <= clock[0] < clock[1] <= duration_ms + 1:
            raise ValueError('CrispASR 字幕時間超出來源 PCM 或缺少原生時間。')
        start, end = clock
        tokens = []
        for word in segment.get('words') or ():
            bounds = _clock(word)
            token = str(word.get('text') or '')
            if token.strip() and bounds and start <= bounds[0] < bounds[1] <= end:
                tokens.append(dict(text=token, start=offset + bounds[0] / 1000,
                                   end=offset + min(bounds[1], duration_ms) / 1000,
                                   source='haas_native_token', start_basis='model', end_basis='model'))
        rows.append(dict(start=offset + start / 1000, end=offset + min(end, duration_ms) / 1000,
                         text=text, tokens=tokens, source=BACKEND,
                         timestamp_source='haas_native', timing_precision='token' if tokens else 'segment'))
    return rows


def _decode_batch(audio, batch, config, executable, model, cancel):
    from .asr import write_pcm16_wav

    # The pinned CLI opens narrow argv paths with fopen on Windows. Use an
    # ASCII relative path from a wide Win32 cwd for Unicode model folders.
    use_relative_model = not os.fspath(model).isascii()
    temporary_parent = model.parent if use_relative_model else None
    model_argument = f'../{model.name}' if use_relative_model else os.fspath(model)
    with tempfile.TemporaryDirectory(prefix='2byteasr-haas-', dir=temporary_parent) as directory:
        root = Path(directory)
        if not (root / model_argument).is_file():
            raise RuntimeError('Haas 固定權重在開始推論前已移動，請重新選取或修復模型。')
        command = [os.fspath(executable), '--backend', 'haas', '--gpu-backend', config.device,
                   '-l', 'ja', '--lid-backend', 'off', '-t', str(min(8, os.cpu_count() or 4)),
                   '-m', model_argument, '--cache-dir', './crispasr-cache', '-ojf']
        for index, (first, last) in enumerate(batch):
            cancel()
            name = f'{index:02}'
            write_pcm16_wav(root / (name + '.wav'), audio[first:last])
            command.extend(('-f', name + '.wav', '-of', name))
        log_path = root / 'crispasr.log'
        with model.open('rb'), log_path.open('wb') as log:
            process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, env=runtime_environment(),
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                deadline = time.monotonic() + 120 + sum(last - first for first, last in batch) / SAMPLE_RATE * 2
                while True:
                    cancel()
                    if time.monotonic() >= deadline:
                        raise TimeoutError('CrispASR 分片處理逾時，未採用未完成輸出。')
                    try:
                        code = process.wait(timeout=.2)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        diagnostic = log_path.read_text(encoding='utf-8', errors='replace')
        if code or f'crispasr {RUNTIME_VERSION} (git {RUNTIME_REVISION},' not in diagnostic:
            raise RuntimeError(f'CrispASR {config.device} 執行失敗（{code}）。{diagnostic[-1000:]}')
        if config.device == 'cuda' and 'using preferred GPU backend: CUDA' not in diagnostic:
            raise RuntimeError('CrispASR 未確認 CUDA 後端，請檢查 NVIDIA 環境。')
        rows = []
        for index, (first, last) in enumerate(batch):
            result = root / f'{index:02}.json'
            if not result.is_file():
                raise RuntimeError(f'CrispASR 未輸出分片 {index} 的 JSON。')
            rows.extend(parse_transcription(json.loads(result.read_bytes()), first, last))
    return rows


def _decode_or_resume(audio, batch, config, executable, model, cancel, cache_dir, context):
    from .alignment_audio import pcm_digest
    from .cache import atomic_write_json, record_run_event, stable_digest
    from .language_guard import settings_policy

    if not cache_dir:
        return _decode_batch(audio, batch, config, executable, model, cancel)
    policy = settings_policy(context.asr_settings_snapshot, context.requested_language)
    identity = dict(version=1, runtime=RUNTIME_REVISION, device=config.device, variant=config.model_key,
                    language=policy['language'], strict=policy['strict'], speakers=context.speaker_source,
                    repair=context.language_guard_repair,
                    ranges=[(first, last, pcm_digest(audio[first:last])) for first, last in batch])
    key = stable_digest(identity)
    target = Path(cache_dir) / 'haas-batches' / (key + '.json')
    try:
        saved = json.loads(target.read_bytes())
        if saved['key'] == key and isinstance(saved['rows'], list):
            record_run_event('haas_batch', windows=len(batch), cache_hit=True, key=key)
            return saved['rows']
    except (OSError, ValueError, TypeError, KeyError):
        pass
    rows = _decode_batch(audio, batch, config, executable, model, cancel)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, dict(key=key, rows=rows))
    from ..storage.storage_service import register_cache
    register_cache(target, 'asr', producer='haas_batch')
    record_run_event('haas_batch', windows=len(batch), cache_hit=False, key=key)
    return rows


def transcribe(audio, regions, context, *, cache_dir=None):
    from .asr import _raise_if_queue_cancelled, _legacy_runtime_value, build_qwen_asr_chunks
    from .cache import record_run_event

    code = normalize_language(context.requested_language)
    if code != 'ja':
        raise ValueError('Haas-ja-v1.0 只適用於已指定或已確認為日語的音訊。')
    config = configuration(context.asr_settings_snapshot or _legacy_runtime_value('RUNTIME_SETTINGS', {}))
    executable, model = bundle(config)
    # Keep VAD edge padding inside CrispASR's 30-second no-inner-cut limit.
    chunks = build_qwen_asr_chunks(audio, regions, chunk_seconds=29.0, max_merge_gap_seconds=1.)
    ranges = ((max(0, round(c['start'] * SAMPLE_RATE)),
               min(len(audio), round(c['end'] * SAMPLE_RATE))) for c in chunks)
    rows = []
    for batch in iter(lambda: list(islice(ranges, BATCH_WINDOWS)), []):
        _raise_if_queue_cancelled()
        rows.extend(_decode_or_resume(audio, batch, config, executable, model, _raise_if_queue_cancelled,
                                     cache_dir, context))
    record_run_event('haas_transcription', model=BACKEND, engine_version=RUNTIME_VERSION, engine_revision=RUNTIME_REVISION,
                     quantization=config.quantization, device=config.device, requested_language=code,
                     native_language_detection=False, windows=len(chunks), segments=len(rows))
    return rows
