import pytest
from twobyteasr.glossary import glossary_sources as sources
from twobyteasr.glossary.glossary_skill import GlossarySearchError
from tests.test_workflow_build_lifecycle import setup_build
from tests.test_glossary_skill import _FakeLegacy, _grok_settings
from twobyteasr.glossary import glossary_build as gb

def test_second_page_budget_keeps_first_page_checkpoint(monkeypatch):
    setup_build(monkeypatch)
    monkeypatch.setattr(gb,'category_members',sources.category_members)
    def api(site,params,*a,**kw):
        if params.get('cmcontinue'):raise GlossarySearchError('budget_exhausted','预算耗尽')
        return {'query':{'categorymembers':[{'title':'娜娜莉','ns':0}]},'continue':{'cmcontinue':'next'}}
    monkeypatch.setattr(sources,'_api_get',api)
    result=gb.run_full_library_update(_FakeLegacy(),'异环',_grok_settings())
    assert result['candidate_count']==1 and result['partial']
    assert result['checkpoint']['done_urls']==[]

def test_retry_success_records_each_http_response(monkeypatch):
    import json
    from types import SimpleNamespace
    responses=iter([SimpleNamespace(text='<html>retry</html>',status_code=200,headers={'content-type':'text/html'}),
        SimpleNamespace(text='{"query":{}}',status_code=200,headers={'content-type':'application/json'},json=lambda:{'query':{}})])
    monkeypatch.setattr(sources.requests,'get',lambda *a,**kw:next(responses))
    monkeypatch.setattr(sources,'cancellable_sleep',lambda *a:False)
    board=sources.HealthBoard()
    assert sources._api_get(sources.WikiSite('https://example.com/api.php'),{},board)=={'query':{}}
    assert len(board.receipts)==2 and all(x.get('body_sha256') for x in board.receipts)
