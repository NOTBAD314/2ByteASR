"""Native Qwen Audio 3.1 Flash protocol and stable sentence revisions.

Timestamps enter in milliseconds and leave this boundary in seconds exactly
once. channel_id is never a speaker identity. No compatibility model fallback.
"""
from __future__ import annotations

import base64
import json
import math

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..recognition.asr_capabilities import AUDIO_LANGUAGE_CODES as LANGUAGE_HINT_CODES
from ..recognition.asr_capabilities import QWEN3_FILE_LANGUAGE_CODES

FLASH = 'qwen-audio-3.1-asr-flash'
FLASH30 = 'qwen-audio-3.0-asr-flash'
FLASH_MODELS = frozenset({FLASH30, FLASH})
FILETRANS = 'qwen-audio-3.1-asr-flash-filetrans'
FILETRANS30 = 'qwen-audio-3.0-asr-flash-filetrans'
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
    language_parameter: bool  # a source-language request field exists (omit for mixed/auto)
    timestamp_source: str
    max_hours: float = 12.0
    diarization_max_hours: float = 2.0
    language_field: str = 'language'   # 'language' (one code) or 'language_hints' (list, up to 4)


FILETRANS_MODELS = {
    QWEN3_FILETRANS: FiletransModel(
        QWEN3_FILETRANS, 'Qwen3-ASR-Flash 录音文件识别', 'file_url', 'enable_words',
        diarization=False, vocabulary=False, context=False, language_parameter=True,
        timestamp_source='qwen3_filetrans_native'),
    FILETRANS: FiletransModel(
        FILETRANS, 'Qwen-Audio-3.1-ASR-Flash 录音文件识别', 'file_urls', 'always',
        diarization=True, vocabulary=True, context=True, language_parameter=True,
        timestamp_source='qwen31_native', language_field='language_hints'),
    FILETRANS30: FiletransModel(
        FILETRANS30, 'Qwen-Audio-3.0-ASR-Flash Filetrans', 'file_urls', 'always',
        diarization=True, vocabulary=True, context=True, language_parameter=True,
        timestamp_source='qwen30_native', language_field='language_hints'),
}

FILETRANS_LANGUAGE_CODES = {code: code for code in QWEN3_FILE_LANGUAGE_CODES}


def filetrans_language_parameters(model, code) -> dict:
    """The request's language field for one task language code, or {}."""
    spec = filetrans_spec(model)
    code = str(code or '')
    if not spec.language_parameter or code in {'', 'auto'}:
        return {}
    if spec.language_field == 'language_hints':
        if code not in LANGUAGE_HINT_CODES:
            raise ASRProtocolError(f'此 Filetrans 模型不支援語言：{code}', 'configuration_error')
        return {'language_hints': [code]}
    if code not in FILETRANS_LANGUAGE_CODES:
        raise ASRProtocolError(f'此 Filetrans 模型不支援語言：{code}', 'configuration_error')
    return {'language': code}


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
    from ..subtitle_rules.language_rules import normalize_language
    code = FILETRANS_LANGUAGE_CODES.get(normalize_language(language))
    if spec.language_parameter and code:
        hints['filetrans_language'] = code
    return hints


MAX_FILETRANS_TERMS = 2000
MAX_FILETRANS_NON_ASCII_CHARS = 15
MAX_FILETRANS_ASCII_WORDS = 7


def filetrans_term_limit(term):
    """Why one hotword breaks the Filetrans vocabulary rules, or ''."""
    if '\n' in term or '\r' in term:
        return 'contains_line_break'
    if not term.isascii() and len(term) > MAX_FILETRANS_NON_ASCII_CHARS:
        return 'non_ascii_longer_than_15_characters'
    if term.isascii() and len(term.split()) > MAX_FILETRANS_ASCII_WORDS:
        return 'ascii_more_than_7_words'
    return ''


def filetrans_hints(canonical_terms, *, vocabulary_id='', vocabulary_model=''):
    """Filetrans HTTP input.context and modest native vocabulary, no aliases.

    Official HTTP reference: each context round is capped at 400 characters;
    instantaneous plus compiled hotwords are capped at 2,000 entries. Do not
    rely on the server's silent tail truncation or random over-limit sampling.
    Terms outside the hotword rules are skipped and listed with a reason
    (2026-10-17), like MOSS keyterms: one long personal glossary row must not
    fail the whole recognition. Input order is the hotword ranking.
    """
    terms, dropped = [], []
    for term in dict.fromkeys(str(x).strip() for x in canonical_terms if str(x).strip()):
        reason = filetrans_term_limit(term)
        if not reason and len(terms) >= MAX_FILETRANS_TERMS:
            reason = 'over_2000_terms'
        if reason:
            dropped.append({'term': term, 'reason': reason})
        else:
            terms.append(term)
    text = '本场规范词（仅实际提到时采用，保持大小写和数字）：'
    packed = []
    for term in terms:
        candidate = text + '、'.join(packed + [term])
        if len(candidate) <= 400: packed.append(term)
    hints = {'vocabulary': {term: 2 for term in terms},
             'filetrans_context': ([{'role': 'user', 'content': [{'type': 'input_text',
                                    'text': text + '、'.join(packed)}]}] if packed else []),
             'filetrans_vocabulary_dropped': dropped[:200],
             'hint_counts': {'native_vocabulary': len(terms), 'context_terms': len(packed),
                             'context_omitted_terms': len(terms) - len(packed), 'weight': 2,
                             'vocabulary_dropped': len(dropped), 'vocabulary_limit': MAX_FILETRANS_TERMS}}
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
    def __init__(self, native=False, *, model=FLASH):
        self.native = native
        self.model = model
        self.sentences = {}
        self.events = 0
        self.received_output = False
        self.full_text = None
        self.text_rank = (-1, -1, -1)
        self.row_events = {}

    def consume(self, payload):
        if payload.get('code') not in (None, '', '200', 200):
            raise ASRProtocolError(str(payload.get('message') or payload['code']), str(payload['code']))
        output = payload.get('output')
        if not isinstance(output, dict):
            raise ASRProtocolError('Flash响应缺少output对象')
        full_text = output.get('text')
        # Official guide and API reference currently document both envelopes.
        if isinstance(output.get('output'), dict):
            output = output['output']
        self.events += 1
        self.received_output = True
        if isinstance(output.get('text'), str):
            full_text = output['text']
        rows = output.get('sentences')
        if rows is None:
            row = output.get('sentence')
            rows = [row] if isinstance(row, dict) else []
        if not isinstance(rows, list):
            raise ASRProtocolError('Flash sentences不是数组')
        accepted = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('sentence_id'), int):
                raise ASRProtocolError('Flash句子缺少稳定sentence_id，不能安全合并修订')
            key = row.get('channel_id', 0), row['sentence_id']
            earlier = self.sentences.get(key)
            if earlier and earlier.get('sentence_end') and not row.get('sentence_end'):
                continue
            self.sentences[key] = dict(row)
            self.row_events[key] = self.events
            accepted.append(row)
        finalized = [row for row in accepted if row.get('sentence_end')]
        rank = (max((row.get('end_time') or 0 for row in finalized), default=0),
                max((row['sentence_id'] for row in finalized), default=0), self.events)
        if isinstance(full_text, str) and (finalized or not rows or not self.sentences) and rank >= self.text_rank:
            self.full_text = full_text
            self.text_rank = rank

    def result(self, duration):
        if not self.received_output:
            raise ASRProtocolError('Flash流未返回业务结果')
        compact = lambda text: ''.join(c for c in str(text or '') if c.isalnum()).casefold()
        ordered = [row for _, row in sorted(self.sentences.items())]
        if self.model == FLASH and not self.native and len(ordered) > 1:
            last = ordered[-1]
            # Real SSE responses can increment sentence_id on each cumulative
            # revision. Earlier prefixes have no finalized words. Treating
            # them as independent sentences duplicates text and loses timing.
            final_text = compact(last.get('text'))
            def compatible_prefix(row):
                earlier = compact(row.get('text'))
                if not earlier or len(earlier) > len(final_text):
                    return False
                if final_text.startswith(earlier):
                    return True
                # An earlier unfinalized hypothesis can contain a corrected
                # word. Only discard it with a fully stabilized later frame.
                words = last.get('words') or []
                return (bool(words) and all(word.get('fixed') is True for word in words)
                        and SequenceMatcher(None, earlier, final_text[:len(earlier)], autojunk=False).ratio() >= .78)
            if (last.get('sentence_end') and final_text and final_text == compact(self.full_text)
                    and all(row.get('begin_time') == last.get('begin_time')
                            and row.get('channel_id', 0) == last.get('channel_id', 0)
                            and (row.get('end_time') or 0) <= last['end_time']
                            and compatible_prefix(row)
                            and not any(word.get('fixed') is True for word in row.get('words', []))
                            for row in ordered[:-1])):
                ordered = [last]
        segments, words = [], []
        for row in ordered:
            if not row.get('sentence_end'):
                raise ASRProtocolError('Flash连接已结束，但仍有未完成句子', 'incomplete_result')
            start, end = seconds(row.get('begin_time')), seconds(row.get('end_time'))
            if not start <= end <= duration + .1:
                raise ASRProtocolError('Flash句时间越出本请求范围')
            segment = dict(start=start, end=min(end, duration), text=str(row.get('text', '')),
                           sentence_id=row['sentence_id'], channel_id=row.get('channel_id',0), timestamp_source='qwen31_native_sentence',
                           response_event=self.row_events[(row.get('channel_id', 0), row['sentence_id'])])
            if row.get('speaker_id') is not None:
                segment['speaker'] = row['speaker_id']
            segments.append(segment)
            for word in row.get('words', []):
                # A completed sentence alone does not freeze 3.1 word timing.
                if self.model == FLASH and not self.native and word.get('fixed') is not True:
                    continue
                try:
                    ws, we = seconds(word.get('begin_time')), seconds(word.get('end_time'))
                except ASRProtocolError:
                    continue
                if not start <= ws < we <= end + .01:
                    continue
                entry = dict(start=ws, end=we, word=str(word.get('text', ''))+str(word.get('punctuation') or ''),
                             timestamp_source='qwen31_native_word', sentence_id=row['sentence_id'],
                             channel_id=row.get('channel_id',0))
                if word.get('speaker_id', row.get('speaker_id')) is not None:
                    entry['speaker'] = word.get('speaker_id', row.get('speaker_id'))
                words.append(entry)
        # Mixed stable/unstable words must never silently delete unstabilized
        # text in the downstream word-first converter. Use sentence granularity.
        text = ''.join(s['text'] for s in segments)
        if self.full_text is not None and compact(text)==compact(self.full_text):
            text = self.full_text
        elif self.full_text is not None:
            # Some short responses expose only the final sentence plus full
            # transcript. Preserve all text; never assign the last sentence's
            # word timing to missing earlier sentences.
            text=self.full_text;words=[]
            segments=[dict(start=0,end=duration,text=text,timestamp_source='request_bounds_coarse',response_event=self.text_rank[-1])]
        if compact(''.join(w['word'] for w in words)) != compact(text):
            words = []
        return dict(text=text, segments=segments, words=words, protocol='qwen31_flash',
                    timestamp_source='qwen31_native' if self.model == FLASH else 'qwen30_native',
                    timing_granularity='word' if words else ('coarse' if segments and segments[0].get('timestamp_source')=='request_bounds_coarse' else 'sentence'), events=self.events,
                    native_diarization=self.native)


def flash(audio, endpoint, *, check=lambda: None, requests_module=None):
    from . import network_policy
    from ..recognition.asr import _pcm16_wav_bytes
    from .provider_stream import sse_data
    from ..recognition.speaker_evidence import save_speaker_evidence
    client = requests_module or network_policy
    duration = len(audio) / 16000
    if not 0 < duration <= 300:
        raise ASRProtocolError('Qwen 3.1 Flash每请求必须在5分钟以内', 'input_limit')
    model = endpoint.get('model')
    if model not in FLASH_MODELS:
        raise ASRProtocolError('Flash 适配器要求精确模型 ID', 'configuration_error')
    from .asr_language_control import flash_parameters, record_request
    parameters, conflict = flash_parameters(endpoint)
    native = bool(parameters.get('speaker_diarization_enabled'))
    body = dict(model=model, input={'messages':[{'role':'user','content':[{
        'type':'input_audio','input_audio':{'data':'data:audio/wav;base64,'+
            base64.b64encode(_pcm16_wav_bytes(audio)).decode('ascii')}}]}]}, parameters=parameters)
    check()
    record_request(endpoint, parameters, conflict=conflict)
    # No automatic retry after uncertain dispatch. Successful chunks are cached
    # by the owning request process; user retry resumes only unfinished chunks.
    streaming = model == FLASH or duration >= 60
    packets = []
    revisions = SentenceRevisions(native, model=model)
    try:
        with client.post(endpoint['url'], json=body,
                         headers={'Authorization':'Bearer '+endpoint['api_key'],
                                  'X-DashScope-SSE':'enable' if streaming else 'disable'},
                         timeout=(10, 180), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ASRProtocolError(f'Qwen Flash HTTP {response.status_code}',
                                       'authentication' if response.status_code in {401,403} else f'http_{response.status_code}')
            if 'text/event-stream' in response.headers.get('Content-Type', response.headers.get('content-type', '')):
                for data in sse_data(response.iter_content(65536), {}, lambda: (check(), False)[1]):
                    if data == '[DONE]':
                        break
                    packet = json.loads(data)
                    packets.append(packet)
                    revisions.consume(packet)
            else:
                check()
                packet = response.json()
                packets.append(packet)
                revisions.consume(packet)
    finally:
        root = endpoint.get('audit_root', '')
        name = endpoint.get('audit_request', 'request') + '-qwen31-original'
        if root and packets:
            from pathlib import Path
            import time
            if (Path(root) / (name + '.json')).is_file():
                name += f'-{time.time_ns()}'
            save_speaker_evidence(root, name, packets)
    check()
    # Each SSE packet repeats the running usage; the last one is the request's.
    from .api_usage import record_api_call
    usage = next((packet['usage'] for packet in reversed(packets)
                  if isinstance(packet, dict) and isinstance(packet.get('usage'), dict)), None)
    record_api_call(stage='asr', provider=endpoint.get('provider', ''), model=model, usage=usage,
                    request_mode='dashscope_sse')
    return revisions.result(duration)
