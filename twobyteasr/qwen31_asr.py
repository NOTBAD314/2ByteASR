"""Native Qwen Audio 3.1 Flash protocol and stable sentence revisions.

Timestamps enter in milliseconds and leave this boundary in seconds exactly
once. channel_id is never a speaker identity. No compatibility model fallback.
"""
from __future__ import annotations

import base64
import json
import math

FLASH = 'qwen-audio-3.1-asr-flash'
FILETRANS = 'qwen-audio-3.1-asr-flash-filetrans'


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
            if self.native and row.get('speaker_id') is not None:
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
                if self.native and word.get('speaker_id', row.get('speaker_id')) is not None:
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
