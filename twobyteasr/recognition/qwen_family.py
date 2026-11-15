"""One user-facing Qwen family; frozen legacy backend IDs remain executable."""
from __future__ import annotations

KEY = 'qwen_aligner'
LEGACY = frozenset({KEY, 'qwen_ultra_aligner', 'qwen_ultra_head'})
HEAD_OPTION = 'qwen_alignment_head'


def canonical_backend(value):
    return KEY if value in LEGACY else value


def head_requested(settings):
    models = (settings or {}).get('models') or {}
    return models.get('firered_asr_backend') == 'qwen_ultra_head' or models.get(HEAD_OPTION) is True


def normalize_models(models):
    """Normalize future settings only. Never mutate a task's frozen snapshot."""
    backend = models.get('firered_asr_backend')
    if backend == 'qwen_ultra_head':
        models[HEAD_OPTION] = True
    if backend in {'qwen_ultra_aligner', 'qwen_ultra_head'}:
        models['firered_asr_backend'] = KEY
        # These IDs already requested Ultra; this preserves the weight identity,
        # and is not a readiness claim. Missing components remain unavailable.
        models['qwen_alignment_profile'] = 'ultra-v5'


def route_note(settings):
    models = (settings or {}).get('models') or {}
    backend = canonical_backend(models.get('firered_asr_backend', 'local'))
    if backend == KEY:
        return '实验精修已开启' if head_requested(settings) else ''
    if backend == 'local':
        return '用于日语、英语等语言；中文保留 FireRed'
    if backend == 'mfa_aligner':
        return '用于英语等回退语言；中文、日语保留 MFA'
    if backend == 'off':
        return ''
    return '用于所选后端不支持的语言'
