"""Explicit isolated preflight checks inside the production GUI; never load weights."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib


def verify(output, check):
    import moss_firered_pipeline as pipeline
    import subtitle_core
    from .. import model_integrity
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
        ('canonical-ultra', {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'ultra-v5'}, 'qwen_ultra_aligner'),
        ('canonical-head', {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'ultra-v5', qwen_family.HEAD_OPTION: True}, 'qwen_ultra_head'),
        ('official', {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'official-v1'}, 'qwen_aligner'),
        ('legacy-ultra', {'firered_asr_backend': 'qwen_ultra_aligner'}, 'qwen_ultra_aligner'),
        ('legacy-head', {'firered_asr_backend': 'qwen_ultra_head'}, 'qwen_ultra_head'),
    ]
    real_verify = model_integrity.verify_model_files
    for name, models, expected in scenarios:
        settings = {'models': models}
        calls = []
        def directory(backend=None):
            return str(folders['qwen_ultra_aligner' if backend == 'qwen_ultra_head' else backend])
        def verify_files(key, folder, **kwargs):
            calls.append(key)
            return real_verify(key, folder, root=root)
        legacy = SimpleNamespace(check_runtime=lambda: None, RUNTIME_SETTINGS=settings,
            PRIMARY_ASR_BACKEND='qwen_local', resolve_qwen_asr_local_source=lambda: str(folders['qwen_asr']),
            FIRERED_ASR_BACKEND=models['firered_asr_backend'], QWEN_ASR_BACKEND='api',
            resolve_qwen_aligner_local_source=asr.resolve_qwen_aligner_local_source,
            selected_qwen_aligner_backend=asr.selected_qwen_aligner_backend)
        with patch.object(asr, 'get_runtime_context', return_value=SimpleNamespace(asr_settings_snapshot=settings)), \
             patch.object(alignment_backend, 'model_directory', side_effect=directory), \
             patch.object(alignment_backend, 'head_directory', return_value=str(folders['qwen_ultra_head'])), \
             patch.object(model_integrity, 'load_dependency_lock', return_value=lock), \
             patch.object(model_integrity, 'verify_model_files', side_effect=verify_files), \
             patch.object(asr, 'check_selected_worker_dependencies'), \
             patch.object(hardware, 'require_local_torch_runtime'), \
             patch.object(hardware, 'selected_cuda_components', return_value=()), \
             patch.object(pipeline, '_script_paths', return_value={}), \
             patch.object(pipeline, '_preflight_cloud_stages'):
            check(name + ' resolves expected profile', asr.selected_qwen_aligner_backend() == expected)
            pipeline.check_runtime(legacy)
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
                except model_integrity.ModelIntegrityError:
                    rejected = True
                check(name + ' still rejects changed weights', rejected)
            finally:
                weight.write_bytes(original)
