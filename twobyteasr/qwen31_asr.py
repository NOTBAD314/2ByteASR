"""Native Qwen Audio 3.1 Flash protocol and stable sentence revisions.

Timestamps enter in milliseconds and leave this boundary in seconds exactly
once. channel_id is never a speaker identity. No compatibility model fallback.
"""
from __future__ import annotations

import base64
import json
import math

from dataclasses import dataclass

FLASH = 'qwen-audio-3.1-asr-flash'
FILETRANS = 'qwen-audio-3.1-asr-flash-filetrans'
QWEN3_FILETRANS = 'qwen3-asr-flash-filetrans'


@dataclass(frozen=True)
class FiletransModel:
    """Request/response schema of one DashScope 录音文件识别 model.

    Sources (checked 2026-10-13): Qwen-ASR API reference
    https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference and the
    非实时语音识别 guide
    https://help.aliyun.com/zh/model-studio/non-realtime-speech-recognition-user-guide .
    The two families differ; never swap only the model string.
    """
    model: str
    label: str
    input_field: str          # 'file_url' (one string) or 'file_urls' (list of one)
    word_timestamps: str      # 'enable_words' (opt-in parameter) or 'always'
    diarization: bool         # parameters.diarization_enabled supported
    vocabulary: bool          # native hotwords (vocabulary / vocabulary_id)
    context: bool             # input.context domain hints
    language_parameter: bool  # parameters.language (one code, omit for mixed)
    timestamp_source: str
    max_hours: float = 12.0
    diarization_max_hours: float = 2.0


FILETRANS_MODELS = {
    QWEN3_FILETRANS: FiletransModel(
        QWEN3_FILETRANS, 'Qwen3-ASR-Flash 录音文件识别', 'file_url', 'enable_words',
        diarization=False, vocabulary=False, context=False, language_parameter=True,
        timestamp_source='qwen3_filetrans_native'),
    FILETRANS: FiletransModel(
        FILETRANS, 'Qwen-Audio-3.1-ASR-Flash 录音文件识别', 'file_urls', 'always',
        diarization=True, vocabulary=True, context=True, language_parameter=False,
        timestamp_source='qwen31_native'),
}

# Task language (首页“字幕语言”) -> parameters.language. ``auto`` sends nothing.
FILETRANS_LANGUAGE_CODES = {'zh': 'zh', 'ja': 'ja', 'en': 'en'}


def is_filetrans_model(model) -> bool:
    return str(model or '') in FILETRANS_MODELS


def filetrans_spec(model) -> FiletransModel:
    try:
        return FILETRANS_MODELS[str(model or '')]
    except KeyError:
        raise ASRProtocolError(f'不是已接入的百炼录音文件识别模型：{model}', 'input_limit') from None


def filetrans_hints_for_model(model, canonical_terms, *, vocabulary_id='', vocabulary_model='', language=None):
    """Per-model hints. Qwen3-ASR Filetrans has no hotword/context parameter.

    The glossary still applies after recognition (词库校对); it is simply not
    sent as a recognition hint for a model whose API does not accept one.
    """
    spec = filetrans_spec(model)
    if spec.vocabulary:
        hints = filetrans_hints(canonical_terms, vocabulary_id=vocabulary_id, vocabulary_model=vocabulary_model)
    else:
        terms = [str(x).strip() for x in canonical_terms if str(x).strip()]
        hints = {'hint_counts': {'native_vocabulary': 0, 'context_terms': 0,
                                 'unsupported_by_model': len(dict.fromkeys(terms))}}
    code = FILETRANS_LANGUAGE_CODES.get(str(language or '').lower())
    if spec.language_parameter and code:
        hints['filetrans_language'] = code
    return hints


def filetrans_hints(canonical_terms, *, vocabulary_id='', vocabulary_model=''):
    """Filetrans HTTP input.context and modest native vocabulary, no aliases.

    Official HTTP reference: each context round is capped at 400 characters;
    instantaneous plus compiled hotwords are capped at 2,000 entries. Do not
    rely on the server's silent tail truncation or random over-limit sampling.
    """
    terms = list(dict.fromkeys(str(x).strip() for x in canonical_terms if str(x).strip()))
    if len(terms) > 2000:
        raise ASRProtocolError('本场规范词超过 Filetrans 2000 项限制，请缩小启用词库范围。', 'input_limit')
    if any((not x.isascii() and len(x) > 15) or (x.isascii() and len(x.split()) > 7)
           or '\n' in x or '\r' in x for x in terms):
        raise ASRProtocolError('Filetrans热词规范：含非ASCII最多15字符，纯ASCII最多7个空格分词；请缩小本场词库。', 'input_limit')
    text = '本场规范词（仅实际提到时采用，保持大小写和数字）：'
    packed = []
    for term in terms:
        candidate = text + '、'.join(packed + [term])
        if len(candidate) <= 400: packed.append(term)
    hints = {'vocabulary': {term: 2 for term in terms},
             'filetrans_context': ([{'role': 'user', 'content': [{'type': 'input_text',
                                    'text': text + '、'.join(packed)}]}] if packed else []),
             'hint_counts': {'native_vocabulary': len(terms), 'context_terms': len(packed),
                             'context_omitted_terms': len(terms) - len(packed), 'weight': 2}}
    if vocabulary_id:
        if vocabulary_model != FILETRANS:
            raise ASRProtocolError('预编译热词库绑定未确认或属于旧模型；请为 Qwen Audio 3.1 Filetrans 重新核对绑定。', 'vocabulary_model_mismatch')
        hints['vocabulary_id'] = str(vocabulary_id)
        hints['vocabulary_model'] = vocabulary_model
    return hints


class ASRProtocolError(RuntimeError):
    def __init__(self, message, category='invalid_response'):
        super().__init__(message)
        self.category = category


def seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ASRProtocolError('时间戳缺失或非法')
    return value / 1000.0


class SentenceRevisions:
    def __init__(self, native=False):
        self.native = native
        self.sentences = {}
        self.events = 0
        self.received_output = False
        self.full_text = None

    def consume(self, payload):
        if payload.get('code') not in (None, '', '200', 200):
            raise ASRProtocolError(str(payload.get('message') or payload['code']), str(payload['code']))
        output = payload.get('output')
        if not isinstance(output, dict):
            raise ASRProtocolError('Flash响应缺少output对象')
        if isinstance(output.get('text'),str):self.full_text=output['text']
        # Official guide and API reference currently document both envelopes.
        if isinstance(output.get('output'), dict):
            output = output['output']
        self.events += 1
        self.received_output = True
        if isinstance(output.get('text'),str):self.full_text=output['text']
        rows = output.get('sentences')
        if rows is None:
            row = output.get('sentence')
            rows = [row] if isinstance(row, dict) else []
        if not isinstance(rows, list):
            raise ASRProtocolError('Flash sentences不是数组')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('sentence_id'), int):
                raise ASRProtocolError('Flash句子缺少稳定sentence_id，不能安全合并修订')
            self.sentences[(row.get('channel_id', 0), row['sentence_id'])] = dict(row)

    def result(self, duration):
        if not self.received_output:
            raise ASRProtocolError('Flash流未返回业务结果')
        segments, words = [], []
        for _, row in sorted(self.sentences.items()):
            if not row.get('sentence_end'):
                raise ASRProtocolError('Flash连接已结束，但仍有未完成句子', 'incomplete_result')
            start, end = seconds(row.get('begin_time')), seconds(row.get('end_time'))
            if not start <= end <= duration + .1:
                raise ASRProtocolError('Flash句时间越出本请求范围')
            segment = dict(start=start, end=min(end, duration), text=str(row.get('text', '')),
                           sentence_id=row['sentence_id'], timestamp_source='qwen31_native_sentence')
            if row.get('speaker_id') is not None:
                segment['speaker'] = row['speaker_id']
            segments.append(segment)
            for word in row.get('words', []):
                # A completed sentence alone does not freeze 3.1 word timing.
                if not self.native and word.get('fixed') is not True:
                    continue
                try:
                    ws, we = seconds(word.get('begin_time')), seconds(word.get('end_time'))
                except ASRProtocolError:
                    continue
                if not start <= ws < we <= end + .01:
                    continue
                entry = dict(start=ws, end=we, word=str(word.get('text', ''))+str(word.get('punctuation') or ''),
                             timestamp_source='qwen31_native_word')
                if word.get('speaker_id', row.get('speaker_id')) is not None:
                    entry['speaker'] = word.get('speaker_id', row.get('speaker_id'))
                words.append(entry)
        # Mixed stable/unstable words must never silently delete unstabilized
        # text in the downstream word-first converter. Use sentence granularity.
        compact = lambda text: ''.join(c for c in text if c.isalnum())
        text = ''.join(s['text'] for s in segments)
        if self.full_text is not None and compact(text)!=compact(self.full_text):
            # Some short responses expose only the final sentence plus full
            # transcript. Preserve all text; never assign the last sentence's
            # word timing to missing earlier sentences.
            text=self.full_text;words=[]
            segments=[dict(start=0,end=duration,text=text,timestamp_source='request_bounds_coarse')]
        if compact(''.join(w['word'] for w in words)) != compact(text):
            words = []
        return dict(text=text, segments=segments, words=words, protocol='qwen31_flash',
                    timing_granularity='word' if words else ('coarse' if segments and segments[0].get('timestamp_source')=='request_bounds_coarse' else 'sentence'), events=self.events,
                    native_diarization=self.native)


def flash(audio, endpoint, *, check=lambda: None, requests_module=None):
    from . import network_policy
    from .asr import _pcm16_wav_bytes
    from .provider_stream import sse_data
    from .speaker_evidence import save_speaker_evidence
    client = requests_module or network_policy
    duration = len(audio) / 16000
    if not 0 < duration <= 300:
        raise ASRProtocolError('Qwen 3.1 Flash每请求必须在5分钟以内', 'input_limit')
    if endpoint.get('model') != FLASH:
        raise ASRProtocolError('Flash3.1适配器要求精确模型ID', 'configuration_error')
    native = endpoint.get('speaker_source') in {'native', 'filetrans'}
    parameters = dict(format='wav', sample_rate='16000', speaker_diarization_enabled=native)
    body = dict(model=FLASH, input={'messages':[{'role':'user','content':[{
        'type':'input_audio','input_audio':{'data':'data:audio/wav;base64,'+
            base64.b64encode(_pcm16_wav_bytes(audio)).decode('ascii')}}]}]}, parameters=parameters)
    check()
    # No automatic retry after uncertain dispatch. Successful chunks are cached
    # by the owning request process; user retry resumes only unfinished chunks.
    with client.post(endpoint['url'], json=body,
                     headers={'Authorization':'Bearer '+endpoint['api_key'], 'X-DashScope-SSE':'enable'},
                     timeout=(10, 180), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ASRProtocolError(f'Qwen Flash HTTP {response.status_code}',
                                   'authentication' if response.status_code in {401,403} else f'http_{response.status_code}')
        revisions = SentenceRevisions(native)
        packets = []
        if 'text/event-stream' in response.headers.get('Content-Type', response.headers.get('content-type', '')):
            for data in sse_data(response.iter_content(65536), {}, lambda: (check(), False)[1]):
                if data == '[DONE]':
                    break
                packet = json.loads(data)
                revisions.consume(packet);packets.append(packet)
        else:
            check();packet = response.json();revisions.consume(packet);packets.append(packet)
    check()
    save_speaker_evidence(endpoint.get('audit_root',''), endpoint.get('audit_request','request')+'-qwen31-original', packets)
    return revisions.result(duration)
