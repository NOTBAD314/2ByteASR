"""Canonical model identities and real execution-event reduction.

Only known aliases are folded. Role names, derived transcripts and provider
models remain distinct; a completion receipt never invents a process start.
"""
from collections.abc import Mapping


_ALIASES = {
    'moss': 'moss', 'moss-host': 'moss',
    'firered': 'firered', 'fire-red': 'firered', 'fire_red': 'firered',
    'fire red': 'firered', 'fireredasr2-aed': 'firered', 'firered-aed': 'firered',
    'qwen': 'qwen3-asr', 'qwen3': 'qwen3-asr', 'qwen3-asr': 'qwen3-asr',
    'qwen3_asr': 'qwen3-asr', 'qwen_asr': 'qwen3-asr', 'qwen_local': 'qwen3-asr',
    'whisper_turbo': 'whisper-turbo', 'whisper-turbo': 'whisper-turbo',
    'whisper': 'whisper-turbo', 'sensevoice': 'sensevoice',
    'funasr_sensevoice': 'sensevoice', 'funasr_nano': 'funasr-nano',
    'qwen_aligner': 'qwen_aligner', 'qwen3-aligner': 'qwen_aligner', 'qwen3_aligner': 'qwen_aligner',
    'mlx_qwen3_asr': 'mlx_qwen3_asr', 'mlx-qwen3-asr': 'mlx_qwen3_asr', 'mlx-asr': 'mlx_qwen3_asr',
    'mlx_qwen3_asr_1_7b': 'mlx_qwen3_asr_1_7b',
    'mlx_qwen_aligner': 'mlx_qwen_aligner', 'mlx-align': 'mlx_qwen_aligner',
}


def canonical_model_id(value):
    raw = str(value or '').strip()
    return _ALIASES.get(raw.casefold(), raw)


def primary_model_id(value):
    raw = str(value or '').strip()
    if '+' in raw or 'consensus' in raw.casefold():
        return ''
    if raw.casefold().startswith('moss-'):
        return 'moss'
    if raw.casefold().endswith('-primary'):
        raw = raw[:-8]
    result = canonical_model_id(raw)
    return result if result in set(_ALIASES.values()) else ''


def review_model_id(backend):
    raw = str(backend or '').strip()
    return 'qwen3-asr' if raw.casefold() == 'local' else canonical_model_id(raw)


def event_model_id(event):
    model = canonical_model_id(event.get('model_id'))
    backend = str(event.get('backend') or '').strip()
    # Historical stage events used a Qwen role label for other review engines.
    if model == 'qwen3-asr' and backend.casefold() not in {'', 'local', 'qwen3-asr'}:
        replacement = review_model_id(backend)
        if replacement not in {'api', 'off'}:
            model = replacement
    return model


def summarize_model_events(events):
    summary = {}
    transitions = {'MODEL_SELECTED', 'MODEL_PLANNED', 'MODEL_ENVIRONMENT_READY',
        'MODEL_STARTED', 'MODEL_STAGE_ENTERED', 'MODEL_COMPLETED',
        'MODEL_RESULT_AVAILABLE', 'MODEL_FAILED', 'MODEL_SKIPPED',
        'asr_worker_started', 'asr_worker_exited'}
    for event in events:
        if not isinstance(event, Mapping) or event.get('event') not in transitions:
            continue
        model = event_model_id(event)
        if not model:
            continue
        item = summary.setdefault(model, dict(model_id=model, role='', backend='',
            selected=False, environment_ready=None, started=False, completed=False,
            failed=False, skipped=False, segment_count=0, failure_reason='', aliases=[],
            roles=[], worker_pids=[]))
        alias = str(event.get('model_id') or '')
        if alias and alias not in item['aliases']:
            item['aliases'].append(alias)
        role = str(event.get('role') or '')
        if role and role not in item['roles']:
            item['roles'].append(role)
        if role and (not item['role'] or role != 'asr_worker'):
            item['role'] = role
        if event.get('backend'):
            item['backend'] = str(event['backend'])
        kind = event['event']
        if kind in {'MODEL_SELECTED', 'MODEL_PLANNED'}:
            item['selected'] = True
        elif kind == 'MODEL_ENVIRONMENT_READY':
            item['environment_ready'] = bool(event.get('environment_ready'))
        elif kind == 'MODEL_STAGE_ENTERED':
            item['stage_entered'] = True
        elif kind in {'MODEL_STARTED', 'asr_worker_started'}:
            item['started'] = True
            pid = event.get('pid')
            if pid and pid not in item['worker_pids']:
                item['worker_pids'].append(pid)
            # Dual observer events for one actual start must not erase a result.
            if kind == 'MODEL_STARTED' and not event.get('pid'):
                item.update(failed=False, completed=False, failure_reason='')
        elif kind in {'MODEL_COMPLETED', 'MODEL_RESULT_AVAILABLE'}:
            item.update(completed=True, failed=False, skipped=False, failure_reason='')
            item['segment_count'] = int(event.get('segment_count') or 0)
        elif kind == 'MODEL_FAILED':
            item.update(failed=True, completed=False,
                failure_reason=str(event.get('failure_reason') or ''))
        elif kind == 'MODEL_SKIPPED':
            item.update(skipped=True, failure_reason=str(event.get('failure_reason') or ''))
        elif kind == 'asr_worker_exited':
            item['worker_returncode'] = event.get('returncode')
    return summary
