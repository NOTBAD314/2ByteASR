"""Documented request controls, separate from client source-language choice."""
from __future__ import annotations
from ..subtitle_rules.language_rules import normalize_language

VERSION='source-control-v1'


def policy(endpoint,requested):
    code=normalize_language(requested);model=str(endpoint.get('model') or '');protocol=endpoint.get('protocol')
    field=None;fixed=None
    if protocol=='mosi_transcriptions' or model=='moss-transcribe-diarize-pro':
        capability='automatic_only'
    elif protocol=='dashscope_filetrans':
        from .qwen31_asr import filetrans_spec
        spec=filetrans_spec(model)
        field='parameters.language' if spec.language_parameter else None
        capability='request_parameter' if field else 'automatic_only'
    elif protocol=='dashscope_multimodal' and model.startswith('qwen3-asr'):
        capability='request_parameter';field='parameters.asr_options.language'
    elif protocol in {'openai_transcription','azure_transcription'}:
        capability='documented_protocol_parameter';field='language'
    elif protocol=='spark_wss':
        capability='fixed_model_language';fixed='zh'
    else:capability='unconfirmed'
    request_language=code if field and code!='auto' else fixed
    return dict(version=VERSION,user_requested_language=code,processing_language_mode='auto' if code=='auto' else 'manual',
        language_control=capability,request_language=request_language,parameter=field,
        parameter_sent=bool(field and code!='auto'),remote_constraint_accepted=None,
        acoustic_language_verified=False)


def hints(endpoint,requested):
    receipt=policy(endpoint,requested)
    return {'asr_request_language':receipt['request_language']} if receipt['parameter_sent'] else {}
