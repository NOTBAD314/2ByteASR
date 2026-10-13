# SPDX-License-Identifier: GPL-3.0-only
"""Apple Silicon MLX smoke: prepare, then time real recognition and alignment (2026-10-13).

1. Prepares the private MLX runtime and the requested locked MLX models with
   the production path (``macos_model_prepare.prepare_mlx``: hash-pinned
   wheels, locked downloads, readiness inference) in an isolated data folder.
2. Synthesizes Chinese speech with macOS ``say`` (utterance times only; the
   voice is a TTS voice, not real speech), then runs MLX Qwen3-ASR on it and
   the MLX aligner on the known script through the production adapters.
3. Records load/inference time, real-time factor, peak child memory, the
   device MLX actually used (Metal GPU or CPU fallback), and the outputs.

This is a smoke and speed/memory record, not an accuracy benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = '今天我们测试兔白字幕在苹果芯片上的本地识别。对齐模型会给每个字配上时间。'


def _say(path: Path) -> str:
    for voice in ('Tingting', ''):
        command = ['say', *(['-v', voice] if voice else []), '--data-format=LEI16@16000', '-o', str(path), SCRIPT]
        if subprocess.run(command, capture_output=True).returncode == 0 and path.is_file():
            return voice or 'default'
    raise RuntimeError('macOS say could not synthesize the test speech')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--keys', default='mlx_qwen_aligner,mlx_qwen3_asr_0_6b')
    parser.add_argument('--source', choices=['AUTO', 'HF_OFFICIAL', 'HF_MIRROR', 'MODELSCOPE'], default='HF_OFFICIAL')
    args = parser.parse_args(argv)
    out = args.output.resolve()
    if 'tmp' not in {part.lower() for part in out.parts}:
        raise SystemExit('--output must be under a tmp directory')
    out.mkdir(parents=True, exist_ok=True)
    data, models = out / 'user-data', out / 'models'
    data.mkdir(exist_ok=True)
    models.mkdir(exist_ok=True)
    os.environ.update({'2BYTEASR_USER_DATA_ROOT': str(data), 'LOCALAPPDATA': str(data),
                       '2BYTEASR_MODEL_ROOT': str(models)})
    sys.path.insert(0, str(ROOT))
    import numpy as np
    from twobyteasr import macos_model_prepare, mlx_backend
    keys = [key for key in args.keys.split(',') if key]
    result = {'keys': keys, 'machine': os.uname().machine, 'macos': __import__('platform').mac_ver()[0],
              'script': SCRIPT, 'kind': 'smoke and speed/memory record on TTS speech; not an accuracy benchmark'}
    try:
        started = time.perf_counter()
        runtime = macos_model_prepare.prepare_mlx(ROOT, models=models, source=args.source, keys=keys)
        result['prepare_s'] = round(time.perf_counter() - started, 1)
        result['runtime_python'] = str(runtime)
        # Receipts go where the app's data root is; under a job-wide
        # TWOBYTEASR_TEST_ROOT that is not ``data`` (2026-10-14).
        from twobyteasr.runtime_paths import user_data_root
        receipts = user_data_root() / 'model-readiness'
        result['readiness'] = {key: json.loads((receipts / (key + '.json')).read_text(encoding='utf-8'))
                               for key in keys}
        os.environ['TWOBYTEASR_MLX_PYTHON'] = str(runtime)
        speech = out / 'say-zh.wav'
        result['voice'] = _say(speech)
        with wave.open(str(speech), 'rb') as stream:
            audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
        duration = len(audio) / 16000
        result['audio_s'] = round(duration, 2)
        asr_keys = [key for key in keys if key != mlx_backend.ALIGNER_KEY]
        if asr_keys:
            backend = next(name for name, model in mlx_backend.PRIMARY_BACKENDS.items() if model == asr_keys[0])
            started = time.perf_counter()
            rows = mlx_backend.transcribe_reference(audio, [{'start': 0.0, 'end': duration}], backend=backend,
                                                    language='Chinese')
            elapsed = time.perf_counter() - started
            result['asr'] = {'backend': backend, 'text': ''.join(row['text'] for row in rows),
                             'wall_s': round(elapsed, 2), 'rtf_including_load': round(elapsed / duration, 3)}
        if mlx_backend.ALIGNER_KEY in keys:
            started = time.perf_counter()
            payload = mlx_backend.run_aligner(audio, [{'id': 'zh', 'text': SCRIPT, 'window_start_ms': 0,
                                                       'window_end_ms': int(duration * 1000), 'language': 'Chinese'}])
            elapsed = time.perf_counter() - started
            row = payload['results'][0]
            units = row.get('char_units') or row.get('word_units') or []
            starts = [unit['start_ms'] for unit in units]
            result['align'] = {'status': row.get('status'), 'units': len(units), 'wall_s': round(elapsed, 2),
                               'load_ms': payload.get('load_ms'), 'inference_ms': payload.get('inference_ms'),
                               'device': payload.get('device'), 'device_info': payload.get('device_info'),
                               'monotonic': starts == sorted(starts),
                               'within_audio': all(0 <= s <= duration * 1000 + 200 for s in starts),
                               'model_basis_share': round(sum(u['start_basis'] == 'model' for u in units)
                                                          / max(1, len(units)), 3),
                               'first_units': [{k: u[k] for k in ('text', 'start_ms', 'end_ms', 'start_basis')}
                                               for u in units[:8]]}
        # macOS reports ru_maxrss in bytes.
        result['peak_child_rss_mb'] = round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 2**20, 1)
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    align = result.get('align') or {}
    result['passed'] = bool(not result.get('error') and result.get('readiness')
                            and (not asr_keys_present(keys) or (result.get('asr') or {}).get('text'))
                            and (mlx_backend_aligner_absent(keys) or (align.get('status') == 'aligned'
                                                                      and align.get('monotonic')
                                                                      and align.get('within_audio'))))
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


def asr_keys_present(keys) -> bool:
    return any(key != 'mlx_qwen_aligner' for key in keys)


def mlx_backend_aligner_absent(keys) -> bool:
    return 'mlx_qwen_aligner' not in keys


if __name__ == '__main__':
    raise SystemExit(main())
