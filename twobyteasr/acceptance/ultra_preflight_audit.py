"""Explicit isolated preflight checks inside the production GUI; never load weights."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib


def verify(output, check):
    import moss_firered_pipeline as pipeline
    import subtitle_core
    from .. import model_integrity
    from ..app.ui import required_recognition_model_keys
    from ..local_models import alignment_readiness
    from ..recognition import alignment_backend, asr, qwen_family
    from ..system import hardware

    root = output / 'preflight-fixture'
    root.mkdir()
    folders = {key: root / key for key in ('qwen_asr', 'qwen_aligner', 'qwen_ultra_aligner', 'qwen_ultra_head')}
    lock = {'schema_version': 1, 'models': {}}
    for key, folder in folders.items():
        folder.mkdir()
        content = ('synthetic isolated model ' + key).encode()
        (folder / 'model.safetensors').write_bytes(content)
        lock['models'][key] = {'required_files': ['model.safetensors'],
                              'sha256': {'model.safetensors': hashlib.sha256(content).hexdigest()}}
    check('production legacy exports resolved aligner backend',
          subtitle_core.selected_qwen_aligner_backend is asr.selected_qwen_aligner_backend)
    scenarios = [
        ('canonical-ultra', {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'ultra-v5'}, 'qwen_ultra_aligner', True),
        ('canonical-head', {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'ultra-v5', qwen_family.HEAD_OPTION: True}, 'qwen_ultra_head', True),
        ('official', {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'official-v1'}, 'qwen_aligner', True),
        ('official-setting-ultra-only', {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'official-v1'}, 'qwen_ultra_aligner', False),
        ('legacy-ultra', {'firered_asr_backend': 'qwen_ultra_aligner'}, 'qwen_ultra_aligner', True),
        ('legacy-head', {'firered_asr_backend': 'qwen_ultra_head'}, 'qwen_ultra_head', True),
    ]
    real_verify = model_integrity.verify_model_files
    for name, models, expected, official_available in scenarios:
        settings = {'models': models}
        calls = []
        def directory(backend=None):
            if backend == 'qwen_aligner' and not official_available:
                return ''
            return str(folders['qwen_ultra_aligner' if backend == 'qwen_ultra_head' else backend])
        def verify_files(key, folder, **kwargs):
            calls.append(key)
            return real_verify(key, folder, root=root)
        legacy = SimpleNamespace(check_runtime=lambda: None, RUNTIME_SETTINGS=settings,
            PRIMARY_ASR_BACKEND='qwen_local', resolve_qwen_asr_local_source=lambda: str(folders['qwen_asr']),
            FIRERED_ASR_BACKEND=models['firered_asr_backend'], QWEN_ASR_BACKEND='api',
            resolve_qwen_aligner_local_source=asr.resolve_qwen_aligner_local_source,
            selected_qwen_aligner_backend=asr.selected_qwen_aligner_backend,
            record_run_event=lambda *args, **kwargs: None)
        packages = dict.fromkeys(('qwen-asr', 'torch', 'transformers', 'numpy', 'safetensors', 'nagisa'), '0.0.6')
        with patch.object(asr, 'get_runtime_context', return_value=SimpleNamespace(asr_settings_snapshot=settings)), \
             patch.dict('os.environ', {'2BYTEASR_QWEN3_ALIGNER_DIR': ''}), \
             patch.object(alignment_backend, 'model_directory', side_effect=directory), \
             patch.object(alignment_backend, 'head_directory', return_value=str(folders['qwen_ultra_head'])), \
             patch.object(model_integrity, 'load_dependency_lock', return_value=lock), \
             patch.object(model_integrity, 'verify_model_files', side_effect=verify_files), \
             patch.object(asr, 'check_selected_worker_dependencies'), \
             patch.object(asr, '_main_worker_python', return_value='isolated-python.exe'), \
             patch.object(alignment_readiness, 'runtime_identity', return_value={'packages': packages}), \
             patch.object(alignment_readiness, '_read_receipt', return_value={}), \
             patch.object(hardware, 'require_local_torch_runtime'), \
             patch.object(hardware, 'selected_cuda_components', return_value=()), \
             patch.object(pipeline, '_script_paths', return_value={}), \
             patch.object(pipeline, '_preflight_cloud_stages'):
            check(name + ' resolves expected profile', asr.selected_qwen_aligner_backend() == expected)
            expected_model_keys = ['qwen_aligner' if expected == 'qwen_aligner' else 'qwen_ultra_aligner']
            if expected == 'qwen_ultra_head':
                expected_model_keys.append('qwen_ultra_head')
            check(name + ' startup and recognition agree on required models',
                  required_recognition_model_keys(settings) == tuple(expected_model_keys))
            pending = False
            try:
                pipeline.check_runtime(legacy)
            except RuntimeError as exc:
                if '[alignment:inference_pending]' not in str(exc):
                    raise
                pending = True
            check(name + ' requires inference receipt only for Ultra', pending == (expected != 'qwen_aligner'))
            wanted = ['qwen_asr', 'qwen_aligner' if expected == 'qwen_aligner' else 'qwen_ultra_aligner']
            if expected == 'qwen_ultra_head':
                wanted.append('qwen_ultra_head')
            check(name + ' passes real file hashes with matching keys', calls == wanted, calls)
            weight = Path(asr.resolve_qwen_aligner_local_source()) / 'model.safetensors'
            original = weight.read_bytes()
            try:
                weight.write_bytes(b'corrupt fixture')
                rejected = False
                try:
                    pipeline.check_runtime(legacy)
                except RuntimeError as exc:
                    rejected = '[alignment:partial]' in str(exc)
                check(name + ' still rejects changed weights', rejected)
            finally:
                weight.write_bytes(original)
