"""Capabilities of the adapters that 2ByteASR actually ships.

Language lists describe the model/adapter, not a guarantee of correct text.
None means deployment-dependent or not established. Time and parallel limits
are app request limits unless otherwise indicated by the provider adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..subtitle_rules.language_rules import QWEN_LANGUAGE_NAMES, normalize_language

ABI = 'asr-capability-v1'
AUDIO_LANGUAGE_CODES = frozenset('zh en ja ko vi th id ms tl hi ar fr de es pt ru it nl sv da fi no el pl cs hu ro bg hr sk'.split())
FLASH31_EXTRA = frozenset('tr fa mr ml ne ky az ka hy sl sq et lv lt ca eu gl or dv as kmr tig fy ba be tt ia mhr tok'.split())
QWEN3_FILE_LANGUAGE_CODES = frozenset('zh yue en ja de ko ru fr pt ar it es hi id th tr uk vi cs da fil fi is ms no pl sv'.split())
QWEN_WORD_LANGUAGE_CODES = frozenset(QWEN_LANGUAGE_NAMES)
QWEN_LOCAL_LANGUAGE_CODES = frozenset('zh yue ar de en es fr id it ja ko pt ru th vi tr hi ms nl sv da fi pl cs fil fa el hu mk ro'.split())
SENSEVOICE_CODES = frozenset({'zh', 'yue', 'en', 'ja', 'ko'})
FUN_NANO_CODES = frozenset({'zh', 'en', 'ja'})


@dataclass(frozen=True)
class Capability:
    language_mode: str
    languages: frozenset[str] | None = None
    auto: bool | None = None
    manual_field: str | None = None
    manual_codes: frozenset[str] | None = None
    mixed: bool | None = None
    timing: str = 'unknown'
    native_speakers: bool | None = None
    speaker_conflict: bool = False
    context: bool | None = None
    hotwords: bool | None = None
    max_request_seconds: float | None = None
    app_parallel: int | None = None
    repair: bool = True


NO_PARAMETER = Capability('detect', auto=True)
WHISPER = Capability('decode', auto=True, manual_field='language', timing='segment', native_speakers=False,
                    mixed=None, context=False, hotwords=False)
QWEN_LOCAL = Capability('decode', QWEN_LOCAL_LANGUAGE_CODES, True, 'language', QWEN_WORD_LANGUAGE_CODES,
                        True, 'segment', False, context=True, hotwords=True)
FIRERED = Capability('detect', frozenset({'zh', 'en'}), True, mixed=True, timing='word', native_speakers=False)
LOCAL = {
    'haas_ja': Capability('fixed', frozenset({'ja'}), False, timing='native_token',
                          native_speakers=False, context=False, hotwords=False,
                          max_request_seconds=30, app_parallel=1),
    'moss': Capability('detect', auto=True, mixed=True, timing='segment', native_speakers=True, context=False),
    'firered': FIRERED,
    'firered_llm': replace(FIRERED, timing='segment', context=True),
    'qwen_local': QWEN_LOCAL,
    'mlx_qwen3_asr': replace(QWEN_LOCAL, context=False, hotwords=False),
    'mlx_qwen3_asr_1_7b': replace(QWEN_LOCAL, context=False, hotwords=False),
    'whisper_turbo': WHISPER,
    'sensevoice': Capability('decode', SENSEVOICE_CODES, True, 'language', SENSEVOICE_CODES,
                             timing='segment', native_speakers=False, context=False, hotwords=False),
    'funasr_nano': Capability('hint', FUN_NANO_CODES, True, 'language', FUN_NANO_CODES,
                              timing='segment', native_speakers=False, context=True, hotwords=True),
    # The pinned zh checkpoint recognizes some English, but has no language switch.
    'paraformer': Capability('detect', frozenset({'zh', 'en'}), True, mixed=True, timing='word', native_speakers=False),
    'glm_asr_nano': replace(NO_PARAMETER, timing='segment', native_speakers=False, context=False, max_request_seconds=30),
    'canary_qwen': Capability('fixed', frozenset({'en'}), False, timing='segment', native_speakers=False, max_request_seconds=30),
}

AUDIO_FLASH = Capability('hint', AUDIO_LANGUAGE_CODES, True, 'parameters.language_hints', AUDIO_LANGUAGE_CODES,
                         True, 'word', False, context=True, hotwords=True, max_request_seconds=300, app_parallel=5)
AUDIO_FILETRANS = replace(AUDIO_FLASH, native_speakers=True, max_request_seconds=43200, app_parallel=1)
GATEWAY = Capability('hint', auto=None, manual_field='language', context=None, app_parallel=6)
FILETRANS3 = Capability('hint', QWEN3_FILE_LANGUAGE_CODES, True, 'parameters.language', QWEN3_FILE_LANGUAGE_CODES,
                        True, 'word_opt_in', False, context=False, hotwords=False,
                        max_request_seconds=43200, app_parallel=1)
CLOUD = {
    'qwen-audio-3.0-asr-flash': AUDIO_FLASH,
    'qwen-audio-3.1-asr-flash': replace(AUDIO_FLASH, languages=AUDIO_LANGUAGE_CODES | FLASH31_EXTRA,
                                       manual_codes=AUDIO_LANGUAGE_CODES | FLASH31_EXTRA,
                                       native_speakers=True, speaker_conflict=True),
    'qwen-audio-3.0-asr-flash-filetrans': AUDIO_FILETRANS,
    'qwen-audio-3.1-asr-flash-filetrans': AUDIO_FILETRANS,
    'qwen3-asr-flash-filetrans': FILETRANS3,
    'qwen3-asr-flash': replace(FILETRANS3, manual_field='parameters.asr_options.language', timing='none',
                               context=True, max_request_seconds=None, app_parallel=6),
    'moss-transcribe-diarize-pro': Capability('detect', auto=True, mixed=True, timing='segment', native_speakers=True,
                                            context=False, hotwords=True, max_request_seconds=3600, repair=False),
    'spark_asr_v2': Capability('fixed', frozenset({'zh', 'en'}), False, mixed=True, timing='word',
                               native_speakers=False, context=False, hotwords=False, max_request_seconds=60,
                               app_parallel=1, repair=False),
    'whisper-large-v3-turbo': replace(GATEWAY, auto=True, timing='word_opt_in', native_speakers=False, context=True),
    'whisper-large-v3': replace(GATEWAY, auto=True, timing='word_opt_in', native_speakers=False, context=True),
    'whisper-1': replace(GATEWAY, auto=True, timing='word_opt_in', native_speakers=False, context=True),
    'gpt-transcribe': replace(GATEWAY, auto=True, timing='none', native_speakers=False, context=True),
    'gpt-4o-transcribe': replace(GATEWAY, auto=True, timing='none', native_speakers=False, context=True),
    'gpt-4o-mini-transcribe': replace(GATEWAY, auto=True, timing='none', native_speakers=False, context=True),
    # The provider model can diarize. This app's generic multipart adapter
    # does not yet negotiate the model-specific diarized_json format.
    'gpt-4o-transcribe-diarize': replace(GATEWAY, auto=True, context=False),
    'microsoft/mai-transcribe-2': replace(GATEWAY, auto=True, timing='word_opt_in', native_speakers=True,
                                         mixed=True, context=False, hotwords=True),
}

UNKNOWN = Capability('unconfirmed', repair=False)


def cloud_capability(endpoint):
    model = str(endpoint.get('model') or '')
    protocol = endpoint.get('protocol')
    if protocol == 'mosi_transcriptions':
        return CLOUD['moss-transcribe-diarize-pro']
    if protocol == 'spark_wss':
        return CLOUD['spark_asr_v2']
    if protocol in {'dashscope_asr_flash', 'dashscope_filetrans', 'dashscope_multimodal'}:
        return CLOUD.get(model, UNKNOWN)
    if protocol in {'openai_transcription', 'azure_transcription', 'openrouter_verbose_json'}:
        return CLOUD.get(model, GATEWAY) if model not in CLOUD or CLOUD[model].manual_field == 'language' else GATEWAY
    return UNKNOWN


def issue(backend, requested, *, endpoint=None, strict=True):
    """A known incompatible choice. Unknown deployments stay unverified."""
    code = normalize_language(requested)
    if code == 'auto':
        if backend == 'haas_ja':
            return 'Haas-ja-v1.0 是日語專用模型。請先指定日語，或選用支援自動辨識的主力模型。'
        return ''
    capability = cloud_capability(endpoint or {}) if backend == 'api' else LOCAL.get(backend, UNKNOWN)
    model = (endpoint or {}).get('model') if backend == 'api' else backend
    if backend == 'api' and capability is CLOUD['spark_asr_v2'] and strict and code != 'zh':
        return 'Spark 目前的端點固定使用普通話模式，無法套用所選語言。'
    if ((capability.languages is not None and code not in capability.languages)
            or (capability.manual_codes is not None and code not in capability.manual_codes)):
        return f'{model} 的目前接入方式不支援所選語言（{code}）。'
    return ''


def selected_issue(settings, requested):
    models = (settings or {}).get('models') or {}
    endpoint = {key: models.get('qwen_asr_api_' + key) for key in ('model', 'protocol')}
    strict = ((settings or {}).get('subtitle_language') or {}).get('strict_language') is not False
    return issue(str(models.get('primary_asr_backend') or ''), requested, endpoint=endpoint, strict=strict)
