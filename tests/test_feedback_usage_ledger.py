from datetime import datetime, timezone
from decimal import Decimal
import json
import pytest

from twobyteasr.providers import usage_ledger as ledger
from twobyteasr.providers.api_usage import normalize_usage, UsageTotals, call_payload

USAGE = dict(prompt_tokens=1000, prompt_cache_hit_tokens=400, prompt_cache_miss_tokens=600,
             completion_tokens=200, completion_tokens_details={'reasoning_tokens':150}, total_tokens=1200)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path/'ledger.sqlite3'
    monkeypatch.setenv('TWOBYTEASR_USAGE_DB', str(path))
    yield path
    assert ledger.flush()


def test_price_arithmetic_no_double_count_or_rounding():
    price = ledger.price_snapshot('https://api.deepseek.com/chat/completions', 'deepseek-flash', '2026-10-20T12:00:00+00:00')
    amount = ledger.estimate(USAGE, price)
    assert Decimal(amount['low']) == Decimal('0.0002112')
    assert amount['low'] == amount['high']
    usage = normalize_usage(USAGE)
    assert usage['total_tokens'] == 1200 and usage['output_tokens'] == 200
    assert usage['uncached_input_tokens'] == 600
    assert usage['reasoning_tokens'] == 150


def test_unknown_and_peak_holiday_tariffs_are_explicit():
    at = '2026-10-20T02:00:00+00:00'
    peak = ledger.price_snapshot('https://api.deepseek.com', 'deepseek-v4-flash', at)
    cost = ledger.estimate(USAGE, peak)
    assert Decimal(cost['high']) == Decimal(cost['low'])*2
    assert peak['period'] == 'peak_or_holiday'
    for endpoint, model in [('https://relay.example', 'deepseek-flash'), ('https://api.deepseek.com', 'unknown')]:
        assert not ledger.price_snapshot(endpoint, model, at)['known']
    assert not ledger.estimate({}, peak)['known']
    assert not ledger.estimate(dict(USAGE, prompt_cache_hit_tokens=1001), peak)['known']
    assert normalize_usage({'prompt_tokens':float('inf')}) is None


def test_request_upsert_survives_reload_and_price_update(db):
    with ledger.usage_scope(project_id='p1', task_id='translation1'):
        attempt = ledger.Attempt(endpoint='https://api.deepseek.com/?secret=do-not-save', model='deepseek-flash', stage='subtitle_translation')
    attempt.start(); attempt.finish({'http_status':200, 'raw_usage':USAGE}, error='invalid_json_content')
    snapshot = dict(attempt.row['price'])
    attempt.finish({'http_status':200}, error='cancelled')
    assert ledger.flush()
    rows = ledger.read_rows(db)
    assert len(rows) == 1 and rows[0]['usage']['total_tokens'] == 1200
    assert rows[0]['price'] == snapshot
    assert rows[0]['task_id'] == 'translation1' and rows[0]['project_id'] == 'p1'
    assert 'secret' not in json.dumps(rows)


def test_missing_usage_and_each_retry_are_not_zero(db):
    class Response:
        status_code = 200
        def json(self): return {'choices': [], 'usage':USAGE}
    ledger.tracked_post(lambda: Response(), endpoint='https://api.deepseek.com', model='deepseek-flash', provider='deepseek', stage='grouping', mode='chat')
    def broken(): raise TimeoutError('network')
    with pytest.raises(TimeoutError):
        ledger.tracked_post(broken, endpoint='https://api.deepseek.com', model='deepseek-flash', provider='deepseek', stage='grouping', mode='chat')
    ledger.flush()
    rows = ledger.read_rows(db)
    assert len(rows) == 2
    assert len({row['request_id'] for row in rows}) == 2
    unknown = next(row for row in rows if row['status'] == 'TimeoutError')
    assert unknown['usage'] is None and not unknown['cost']['known']


def test_dedup_events_accepts_new_usage_without_recount():
    total = UsageTotals()
    total.add(call_payload(stage='translate', request_id='request1'))
    total.add(call_payload(stage='translate', request_id='request1', usage=USAGE))
    total.add(call_payload(stage='translate', request_id='request1', usage=USAGE))
    total.add(call_payload(stage='translate', request_id='request1'))
    assert total.calls == 1 and total.reported_calls == 1
    assert total.values['total_tokens'] == 1200


def test_bounded_error_json_keeps_usage(db, monkeypatch):
    from twobyteasr.providers import llm_adapter
    class Response:
        status_code = 200
        headers = {}
        def iter_content(self, **_):
            yield json.dumps({'usage':USAGE, 'choices':[]}).encode()
        def close(self): pass
    monkeypatch.setattr('requests.post', lambda *a, **k:Response())
    with pytest.raises(Exception):
        llm_adapter.audited_bounded_request([], stage='subtitle_grouping', request_mode='chat',
            model='deepseek-flash', api_key='test', url='https://api.deepseek.com/chat/completions', max_tokens=10)
    ledger.flush()
    rows = ledger.read_rows(db)
    assert len(rows) == 1 and rows[0]['usage']['total_tokens'] == 1200
    assert rows[0]['stage'] == 'subtitle_grouping'


def test_preflight_rejection_is_not_a_dispatched_request(db):
    from twobyteasr.providers.asr_http_transport import complete
    with pytest.raises(Exception):
        complete([], model='deepseek-flash', api_key='', url='https://api.deepseek.com/chat/completions', max_tokens=10)
    ledger.flush()
    assert ledger.read_rows(db) == []


def test_stream_cancel_retains_received_usage_once(db, monkeypatch):
    from twobyteasr.providers.provider_stream import request_chat, StreamProtocolError
    import threading
    cancel = threading.Event()
    diagnostics = {'stage':'subtitle_translation'}
    class Response:
        status_code = 200
        headers = {'Content-Type':'text/event-stream'}
        def iter_content(self, **_):
            packet = {'choices':[{'index':0,'delta':{'content':'Hello'},'finish_reason':None}], 'usage':USAGE}
            yield ('data: '+json.dumps(packet)+'\n\n').encode()
            cancel.set()
            yield b': end\n\n'
        def close(self):pass
    monkeypatch.setattr('requests.post', lambda *a, **k:Response())
    with pytest.raises(StreamProtocolError):
        request_chat('https://api.deepseek.com/chat/completions', {}, {'model':'deepseek-flash'},
                     2, diagnostics, lambda *_:None, cancel.is_set)
    ledger.flush()
    rows=ledger.read_rows(db)
    assert len(rows)==1 and rows[0]['usage']['total_tokens']==1200
    assert rows[0]['status']=='cancelled'


@pytest.mark.parametrize('status,code,category', [(402,'','quota_exhausted'),
    (429,'insufficient_quota','quota_exhausted'),(404,'model_not_found','model_not_supported')])
def test_bounded_http_error_keeps_usage_and_correct_category(db, monkeypatch,status,code,category):
    from twobyteasr.providers.asr_http_transport import complete
    class Response:
        status_code=status
        headers={}
        def iter_content(self, **_):
            yield json.dumps({'error':{'code':code},'usage':USAGE}).encode()
        def close(self):pass
    monkeypatch.setattr('requests.post',lambda *a,**k:Response())
    with pytest.raises(Exception) as error:
        complete([], model='deepseek-flash',api_key='fixture',url='https://api.deepseek.com',max_tokens=10)
    assert error.value.category==category
    ledger.flush()
    rows=ledger.read_rows(db)
    assert len(rows)==1 and rows[0]['usage']['total_tokens']==1200
