"""iFlytek Spark-ASR-2.0 native WSS. No chat protocol or V1 fallback."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import ssl
import threading
import time
from email.utils import formatdate
from urllib.parse import urlencode, urlsplit

from .qwen31_asr import ASRProtocolError

URL = 'wss://iat.cn-huabei-1.xf-yun.com/v1'
MODEL = 'spark_asr_v2'


def signed_url(endpoint, *, now=None):
    url = endpoint.get('url', URL)
    if url != URL:
        raise ASRProtocolError('Spark V2要求官方WSS端点', 'configuration_error')
    for name in ('app_id', 'api_key', 'api_secret'):
        if not endpoint.get(name):
            raise ASRProtocolError(f'Spark缺少{name}', 'configuration_error')
    parsed = urlsplit(url)
    date = formatdate(time.time() if now is None else now, usegmt=True)
    source = f'host: {parsed.hostname}\ndate: {date}\nGET {parsed.path} HTTP/1.1'
    signature = base64.b64encode(hmac.new(endpoint['api_secret'].encode(), source.encode(), hashlib.sha256).digest()).decode()
    auth = f'api_key="{endpoint["api_key"]}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
    return url+'?'+urlencode(dict(host=parsed.hostname, date=date, authorization=base64.b64encode(auth.encode()).decode()))


class DynamicTranscript:
    def __init__(self):
        self.parts = {}
        self.raw_results = []
        self.complete = False

    def consume(self, packet):
        header = packet.get('header') or {}
        if header.get('code', 0) != 0:
            raise ASRProtocolError(f"Spark业务错误 {header.get('code')}：{header.get('message','')}", 'provider_error')
        result = (packet.get('payload') or {}).get('result') or {}
        if result.get('text'):
            try:
                content = json.loads(base64.b64decode(result['text'], validate=True).decode('utf8'))
            except (ValueError, UnicodeError) as exc:
                raise ASRProtocolError('Spark业务结果不是有效base64 JSON') from exc
            if content.get('ret', 0) not in (0, '0'):
                raise ASRProtocolError(f"Spark解码业务ret={content['ret']}", 'provider_error')
            sn = content.get('sn')
            if not isinstance(sn, int):
                raise ASRProtocolError('Spark动态文本缺少业务sn')
            pgs = content.get('pgs', result.get('pgs', 'apd'))
            if pgs == 'rpl':
                rg = content.get('rg', result.get('rg'))
                if not isinstance(rg, list) or len(rg) != 2 or not all(isinstance(n,int) for n in rg) or rg[0] > rg[1]:
                    raise ASRProtocolError('Spark替换范围rg非法')
                for previous in list(self.parts):
                    if rg[0] <= previous <= rg[1]:
                        del self.parts[previous]
            elif pgs != 'apd':
                raise ASRProtocolError('Spark不支持的动态修订类型')
            text = ''.join(str((ws.get('cw') or [{}])[0].get('w', '')) for ws in content.get('ws', []))
            self.parts[sn] = text
            self.raw_results.append(dict(sn=sn, rst=content.get('rst',result.get('rst')),
                                         decoded=content, envelope={k:v for k,v in result.items() if k!='text'}))
        if header.get('status') == 2:
            self.complete = True

    def result(self):
        if not self.complete:
            raise ASRProtocolError('Spark连接结束但未收到结束帧；已收到片段保留', 'incomplete_result')
        # V2's return table marks bg/ed/wb/we as reserved while fa_nbest's prose
        # describes alignment. Retain those fields as evidence. Without a
        # validated response contract, do not invent word times from ws.bg=0
        # or divide duration by text length. The chosen aligner can refine it.
        return dict(text=''.join(self.parts[n] for n in sorted(self.parts)), segments=[], words=[],
                    protocol='spark_asr_v2', timing_granularity='request',
                    native_diarization=False, timing_evidence=self.raw_results)


def transcribe(audio, endpoint, *, check=lambda:None, connection_factory=None):
    import numpy as np
    from .network_policy import ca_bundle
    from .speaker_evidence import save_speaker_evidence
    from websockets.sync.client import connect
    if not 0 < len(audio) <= 60*16000:
        raise ASRProtocolError('Spark每会话音频必须在60秒以内', 'input_limit')
    if endpoint.get('model') != MODEL:
        raise ASRProtocolError('Spark适配器要求spark_asr_v2', 'configuration_error')
    pcm = (np.clip(np.asarray(audio, dtype=np.float64), -1, 1)*32767).astype('<i2').tobytes()
    check()
    ca, _ = ca_bundle()
    factory = connection_factory or connect
    tls=ssl.create_default_context(cafile=ca)
    socket = factory(signed_url(endpoint),open_timeout=10,ssl=tls,max_size=8*1024*1024,close_timeout=2)
    stop = threading.Event()
    errors = []
    state = DynamicTranscript()
    fully_sent=threading.Event()
    def send_audio():
        try:
            # 1280 PCM16 mono bytes = exactly 40ms at16kHz. Pace by sample time.
            started = time.monotonic()
            for seq, offset in enumerate(range(0,len(pcm),1280)):
                check()
                if stop.is_set():return
                wait = started + offset/32000 - time.monotonic()
                if wait > 0 and stop.wait(wait):return
                status = 0 if offset == 0 else 1
                packet = dict(header={'app_id':endpoint['app_id'], 'status':status}, payload={'audio':dict(
                    encoding='raw', sample_rate=16000, channels=1, bit_depth=16,
                    status=status, seq=seq, audio=base64.b64encode(pcm[offset:offset+1280]).decode())})
                if offset == 0:
                    packet['parameter']={'iat':dict(domain=MODEL, language='zh_cn', accent='mandarin',
                        dwa='wpgs', vinfo=1, fa_nbest=True, bos=60000, eos=60000,
                        result=dict(encoding='utf8',compress='raw',format='json'))}
                socket.send(json.dumps(packet,ensure_ascii=False))
            if not stop.is_set():
                socket.send(json.dumps(dict(header={'app_id':endpoint['app_id'],'status':2},payload={'audio':dict(
                    encoding='raw',sample_rate=16000,channels=1,bit_depth=16,status=2,seq=seq+1,audio='')})))
                fully_sent.set()
        except Exception as exc:
            errors.append(exc);stop.set()
    sender = threading.Thread(target=send_audio,name='spark-audio-send',daemon=True)
    sender.start()
    deadline = time.monotonic()+max(120, len(audio)/16000+90)
    try:
        total = 0
        while not state.complete:
            check()
            if errors:raise errors[0]
            if time.monotonic() >= deadline:
                raise ASRProtocolError('Spark会话达到有界等待时间', 'timeout')
            try:
                raw = socket.recv(timeout=.25)
            except TimeoutError:
                continue
            if not raw:break
            total += len(raw)
            if total > 8*1024*1024:
                raise ASRProtocolError('Spark响应超过8MB上限', 'response_limit')
            state.consume(json.loads(raw))
        if not fully_sent.is_set():
            raise ASRProtocolError('Spark 提前结束，尾部音频未完整发送；本块未缓存为成功','incomplete_upload')
        return state.result()
    finally:
        stop.set();socket.close();sender.join(timeout=2)
        save_speaker_evidence(endpoint.get('audit_root',''),endpoint.get('audit_request','request')+'-spark-original',
                              dict(complete=state.complete,results=state.raw_results))
