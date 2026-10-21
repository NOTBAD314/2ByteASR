"""Bounded public execution receipts; model body and private thinking stay out."""
import hashlib
import json
import threading
import time
import uuid

from .provider_diagnostics import redact_diagnostics


class ExecutionObserver:
    def __init__(self, callback, identity, *, attempt=1):
        self.callback = callback
        self.identity = dict(identity)
        self.request_id = uuid.uuid4().hex
        self.attempt = attempt
        self.seq = 0
        self.lock = threading.RLock()
        self.last_delta = 0.
        self.chars = 0
        self.provider_request_id = ''
        self.cli_session_id = ''

    def emit(self, kind, detail='', *, source='application', stage=''):
        if self.callback is None:
            return
        with self.lock:
            now = time.monotonic()
            if kind in {'thinking','thinking_end'}:
                kind,detail = 'provider_activity','收到服务端过程事件；当前服务未提供可展示的思考摘要'
            elif kind in {'delta','final'}:
                self.chars += len(str(detail)) if kind=='delta' else 0
                detail = f'已收到正文 {self.chars} 字符；完成后独立校验结构' if kind=='delta' else '收到最终响应，开始校验'
            if kind in {'provider_activity','delta'}:
                if now-self.last_delta < .25:
                    return
                self.last_delta = now
            self.seq += 1
            payload = redact_diagnostics(detail)
            if isinstance(payload,str):payload=payload[:4000]
            row = dict(request_id=self.request_id, attempt=self.attempt, request_seq=self.seq,
                provider_request_id=self.provider_request_id,cli_session_id=self.cli_session_id,
                timestamp=time.time(), monotonic=now, kind=kind, source=source, stage=stage,
                config_id=hashlib.sha256(json.dumps(self.identity,sort_keys=True).encode()).hexdigest()[:16],
                identity=self.identity, payload=payload)
            self.callback(row)

    def stream(self, kind, detail):
        if kind in {'request_identity','cli_identity'}:
            try:
                identity=json.loads(detail)
                self.provider_request_id=identity.get('provider_request_id',self.provider_request_id)
                self.cli_session_id=identity.get('cli_session_id',self.cli_session_id)
            except (ValueError,TypeError):
                pass
            self.emit(kind,detail,source='application')
            return
        self.emit(kind, detail, source='provider' if kind!='stderr' else 'cli_stderr')
