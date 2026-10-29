"""Per-dispatched-request usage ledger. No prompts, response text or credentials.

SQLite writes run on one background thread; an attempt's UUID is its primary
key. Updating a partial stream never creates another charge. Undo and local
subtitle cache hits do not touch this ledger.
"""
from __future__ import annotations

import atexit
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal
from functools import wraps
import inspect
import json
import logging
import math
import os
from pathlib import Path
import queue
import sqlite3
import threading
import uuid
from urllib.parse import urlsplit

from .api_usage import normalize_usage

PRICE_SOURCE = 'https://api-docs.deepseek.com/quick_start/pricing/'
USAGE_SOURCE = 'https://api-docs.deepseek.com/api/create-chat-completion/'
VERIFIED = '2026-10-20'
RATES = {'deepseek-flash': ('0.003', '0.15', '0.6'),
         'deepseek-v4-pro': ('0.022', '0.66', '1.98')}
ALIASES = {'deepseek-v4-flash': 'deepseek-flash', 'deepseek-v4-flash-vision-exp': 'deepseek-flash'}
_scope = ContextVar('api_usage_scope', default={})
_queue = queue.Queue()
_lock = threading.Lock()
_writer = None
_active = {}
_errors = {}


@contextmanager
def usage_scope(*, project_id='', task_id='', media_fingerprint=''):
    token = _scope.set(dict(project_id=str(project_id), task_id=str(task_id), media_fingerprint=str(media_fingerprint)))
    try:
        yield
    finally:
        _scope.reset(token)


def context():
    scoped = _scope.get()
    if scoped:
        return dict(scoped)
    try:
        from ..recognition.run_context import get_runtime_context
        ctx = get_runtime_context()
        if ctx.identity_task_active:
            return dict(project_id='', task_id=ctx.job_id, media_fingerprint=str(ctx.media_identity.get('fingerprint', '')))
    except Exception:
        pass
    return dict(project_id='', task_id='')


def ledger_path():
    override = os.environ.get('TWOBYTEASR_USAGE_DB')
    if override:
        return Path(override)
    from ..runtime_paths import get_runtime_paths
    return get_runtime_paths().user_data_root / 'api-usage.sqlite3'


def numeric_usage(value, depth=0):
    """Retain numeric API fields only; never persist arbitrary provider strings."""
    if not isinstance(value, dict) or depth > 3:
        return {}
    result = {}
    for key, item in list(value.items())[:100]:
        if not isinstance(key, str) or not key.replace('_', '').isalnum() or len(key) > 80:
            continue
        if isinstance(item, dict):
            nested = numeric_usage(item, depth+1)
            if nested:
                result[key] = nested
        elif isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item) and item >= 0:
            result[key] = item
    return result


def price_snapshot(endpoint, model, at):
    url = urlsplit(endpoint)
    model = ALIASES.get(model, model)
    snapshot = dict(source=PRICE_SOURCE, verified_at=VERIFIED, version='deepseek-2026-10-20',
                    applied_at=at, currency='USD', model=model,
                    effective='Published tariff observed on verification date; no historical backfill')
    if url.scheme != 'https' or url.hostname != 'api.deepseek.com' or url.port not in (None, 443):
        return dict(snapshot, known=False, reason='第三方或非官方直连端点，费率未知')
    if model not in RATES:
        return dict(snapshot, known=False, reason='该模型没有已核实费率')
    instant = datetime.fromisoformat(at).astimezone(timezone.utc)
    if instant.date().isoformat() < VERIFIED:
        return dict(snapshot, known=False, reason='该时间早于费率核实日期')
    peak_window = instant.weekday() < 5 and (1 <= instant.hour < 4 or 6 <= instant.hour < 10)
    # The official page excludes Chinese holidays. With no verified holiday
    # calendar installed, use a labelled range during weekday peak windows.
    # This is never silently presented as an exact tariff.
    low = list(RATES[model])
    high = [str(Decimal(x)*2) for x in low] if peak_window else low
    return dict(snapshot, known=True, rates_low=low, rates_high=high,
                period='peak_or_holiday' if peak_window else 'off_peak',
                note='工作日峰值窗口；节假日未核实，显示半价至峰值范围' if peak_window else '官方非峰值时段')


def estimate(usage, price):
    counted = normalize_usage(usage) or {}
    if not price.get('known'):
        return dict(known=False, reason=price.get('reason', '费率未知'))
    required = ('input_tokens', 'output_tokens', 'cached_input_tokens')
    if any(key not in counted for key in required):
        return dict(known=False, reason='缺少输入、输出或缓存命中用量')
    hit, total = counted['cached_input_tokens'], counted['input_tokens']
    miss = counted.get('uncached_input_tokens', total-hit)
    if min(hit, miss) < 0 or hit+miss != total:
        return dict(known=False, reason='API 缓存分项与输入总数不一致')
    values = (hit, miss, counted['output_tokens'])
    def cost(rates):
        return format(sum(Decimal(str(n))*Decimal(p) for n, p in zip(values, rates))/Decimal(1_000_000), 'f')
    return dict(known=True, currency=price['currency'], low=cost(price['rates_low']),
                high=cost(price['rates_high']), basis='API usage × saved tariff; reasoning included in output')


def _write_loop():
    while True:
        item = _queue.get()
        try:
            if isinstance(item, threading.Event):
                item.set()
                continue
            path, row = item
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path, timeout=5) as db:
                db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, at TEXT NOT NULL, row TEXT NOT NULL)')
                old = db.execute('SELECT row FROM requests WHERE id=?', (row['request_id'],)).fetchone()
                if old:
                    previous = json.loads(old[0])
                    # Late empty callbacks cannot erase received token evidence.
                    if previous.get('usage') and not row.get('usage'):
                        row['usage'], row['raw_usage'] = previous['usage'], previous['raw_usage']
                        row['cost'] = previous['cost']
                db.execute('INSERT INTO requests VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET row=excluded.row',
                           (row['request_id'], row['at'], json.dumps(row, ensure_ascii=False)))
            _errors.pop(str(path), None)
        except Exception as exc:
            if not isinstance(item, threading.Event):
                _errors[str(item[0])] = f'{type(exc).__name__}: {exc}'
            logging.getLogger(__name__).exception('API usage ledger write failed')
        finally:
            _queue.task_done()


def enqueue(row, path=None):
    global _writer
    path = Path(path) if path else ledger_path()
    # Copy before crossing threads, preserving this request's tariff forever.
    item = (path, json.loads(json.dumps(row)))
    with _lock:
        if _writer is None or not _writer.is_alive():
            _writer = threading.Thread(target=_write_loop, name='api-usage-writer', daemon=True)
            _writer.start()
    _queue.put(item)


def flush(timeout=2):
    if _writer is None:
        return True
    done = threading.Event()
    _queue.put(done)
    return done.wait(timeout)


def read_rows(path=None):
    path = Path(path) if path else ledger_path()
    if not path.is_file():
        return []
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.2) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT row FROM requests ORDER BY at DESC')]


def write_error():
    return _errors.get(str(ledger_path()), '')


class Attempt:
    def __init__(self, *, endpoint, model, provider='', stage='', mode=''):
        self.path = ledger_path()
        instant = datetime.now(timezone.utc).isoformat()
        parsed = urlsplit(endpoint)
        # No userinfo, path, query, fragment, API keys or request/response bodies.
        safe_endpoint = f'{parsed.scheme}://{parsed.hostname or "unknown"}'
        self.row = dict(request_id=uuid.uuid4().hex, at=instant, endpoint=safe_endpoint,
                        model=str(model), provider=str(provider), stage=str(stage or 'unknown'),
                        mode=mode, status='pending', usage=None, raw_usage={}, **context())
        self.row['price'] = price_snapshot(endpoint, model, instant)
        self.row['cost'] = dict(known=False, reason='尚未取得用量')
        self.started = False

    def start(self):
        if not self.started:
            self.started = True
            enqueue(self.row, self.path)

    def finish(self, diagnostics=None, *, error=''):
        if not self.started:
            return
        diag = diagnostics or {}
        raw = numeric_usage(diag.get('raw_usage') or diag.get('usage') or {})
        usage = normalize_usage(raw)
        self.row.update(status=error or ('received' if usage else 'usage_unknown'),
                        http_status=diag.get('http_status'), raw_usage=raw, usage=usage)
        self.row['cost'] = estimate(raw, self.row['price'])
        enqueue(self.row, self.path)
        from .api_usage import record_api_call
        record_api_call(stage=self.row['stage'], provider=self.row['provider'], model=self.row['model'],
                        request_mode=self.row['mode'], usage=raw, request_id=self.row['request_id'],
                        status=self.row['status'], estimated_cost=self.row['cost'])


def dispatch(diagnostics):
    attempt = _active.get(diagnostics.get('usage_request_id'))
    if attempt:
        attempt.start()


def tracked_diagnostics(parameter):
    """Wrap bounded transports; only dispatch() immediately before HTTP counts."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            values = bound.arguments
            diag = values.get(parameter)
            if diag is None:
                diag = values[parameter] = {}
            attempt = Attempt(endpoint=values.get('url', ''),
                              model=values.get('model') or values.get('body', {}).get('model', ''),
                              provider=values.get('provider', diag.get('provider', '')),
                              stage=diag.get('stage', ''), mode=(
                                  'responses_stream' if values.get('protocol') == 'responses' else 'chat.completions_stream')
                                  if parameter == 'diagnostics' else 'bounded')
            for key in ('usage', 'raw_usage', 'http_status'):
                diag.pop(key, None)
            diag['usage_request_id'] = attempt.row['request_id']
            _active[attempt.row['request_id']] = attempt
            failure = ''
            try:
                return function(*bound.args, **bound.kwargs)
            except BaseException as exc:
                failure = str(getattr(exc, 'category', type(exc).__name__))
                raise
            finally:
                attempt.finish(diag, error=failure)
                _active.pop(attempt.row['request_id'], None)
        return wrapped
    return decorate


def tracked_post(send, *, endpoint, model, provider, stage, mode):
    attempt = Attempt(endpoint=endpoint, model=model, provider=provider, stage=stage, mode=mode)
    attempt.start()
    diag = {}
    error = ''
    try:
        response = send()
        diag['http_status'] = response.status_code
        try:
            payload = response.json()
            if isinstance(payload, dict):
                diag['raw_usage'] = payload.get('usage')
        except Exception:
            error = 'response_json_error'
        if response.status_code >= 400:
            error = f'http_{response.status_code}'
        return response
    except BaseException as exc:
        error = str(getattr(exc, 'category', type(exc).__name__))
        raise
    finally:
        attempt.finish(diag, error=error)


atexit.register(flush, 1)
