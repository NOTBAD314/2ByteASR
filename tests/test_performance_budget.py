import importlib.util
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest

from twobyteasr.acceptance import translation_benchmark as bench


def test_inflight_reservations_and_unknown_failure_remain_charged(tmp_path):
    ledger=bench.Ledger(tmp_path/'budget.json')
    body=dict(model='deepseek-flash',messages=[dict(role='user',content='你好')],max_tokens=8192)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(lambda _:ledger.reserve(body,'test'),range(4)))
    assert ledger.total()==sum(r['reserved_usd'] for r in rows)
    ledger.settle(rows[0],None,.01,RuntimeError())
    assert rows[0]['state']=='unsettled'
    assert bench.Ledger(ledger.path).total()==ledger.total()
    ledger.data['requests'].append(dict(reserved_usd=10-ledger.total()-.001))
    before=len(ledger.data['requests'])
    with pytest.raises(bench.BudgetExceeded):ledger.reserve(body,'test')
    assert len(ledger.data['requests'])==before


@pytest.mark.parametrize('extra',[dict(model='other'),dict(max_tokens=0),dict(max_tokens=8193),dict(tools=[{}])])
def test_unpriced_or_unbounded_calls_are_refused(tmp_path,extra):
    ledger=bench.Ledger(tmp_path/'budget.json')
    body=dict(model='deepseek-flash',messages=[],max_tokens=10);body.update(extra)
    with pytest.raises(bench.BudgetExceeded):ledger.reserve(body,'test')
    assert ledger.total()==0
