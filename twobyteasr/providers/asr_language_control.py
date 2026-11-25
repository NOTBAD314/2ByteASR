"""Documented request controls, separate from client source-language choice."""
from __future__ import annotations
from ..subtitle_rules.language_rules import normalize_language

VERSION='source-control-v2'


def policy(endpoint,requested):
    from ..recognition.asr_capabilities import cloud_capability
    code = normalize_language(requested)
    adapter = cloud_capability(endpoint)
    field = adapter.manual_field
    fixed = 'zh' if adapter.language_mode == 'fixed' else None
    capability = {'hint': 'documented_protocol_parameter' if field == 'language' else 'request_parameter',
                  'detect': 'automatic_only', 'fixed': 'fixed_model_language'}.get(adapter.language_mode, 'unconfirmed')
    request_language=code if field and code!='auto' else fixed
    return dict(version=VERSION,user_requested_language=code,processing_language_mode='auto' if code=='auto' else 'manual',
        language_control=capability,request_language=request_language,parameter=field,
        parameter_sent=bool(field and code!='auto'),remote_constraint_accepted=None,
        acoustic_language_verified=False)


def hints(endpoint,requested):
    receipt=policy(endpoint,requested)
    return {'asr_request_language':receipt['request_language']} if receipt['parameter_sent'] else {}


def flash_parameters(endpoint):
    from .qwen31_asr import ASRProtocolError, FLASH
    from ..recognition.asr_capabilities import CLOUD
    parameters = {'format': 'wav', 'sample_rate': '16000'}
    code = endpoint.get('asr_request_language')
    if code and code != 'auto':
        if code not in CLOUD[endpoint['model']].manual_codes:
            raise ASRProtocolError(f'此 Flash 模型不支援語言：{code}', 'configuration_error')
        parameters['language_hints'] = [code]
    conflict = None
    if endpoint.get('model') == FLASH:
        requested = endpoint.get('speaker_source') in {'native', 'filetrans'}
        conflict = 'flash_diarization_ignores_language_hints' if requested and 'language_hints' in parameters else None
        native = requested and not (conflict and endpoint.get('strict_language', True))
        parameters['speaker_diarization_enabled'] = native
        if endpoint.get('keep_dialect') and not (code and endpoint.get('strict_language', True)):
            parameters['keep_dialect'] = True
    return parameters, conflict


def record_request(endpoint, parameters, *, conflict=None):
    """Only the explicit recognition controls may enter the public receipt."""
    from ..recognition.cache import record_run_event
    allowed = ('language', 'language_hints', 'speaker_diarization_enabled', 'diarization_enabled', 'keep_dialect')
    fields = {key: parameters[key] for key in allowed if key in parameters}
    record_run_event('asr_language_request', model=endpoint.get('model'), protocol=endpoint.get('protocol'),
                     requested_language=endpoint.get('requested_language') or endpoint.get('asr_request_language')
                     or endpoint.get('filetrans_language') or 'auto',
                     strict_language=bool(endpoint.get('strict_language')), parameters=fields, conflict=conflict,
                     repair=bool(endpoint.get('language_guard_repair')),
                     request_index=endpoint.get('language_request_index'),
                     audio_range=endpoint.get('language_request_range'))
