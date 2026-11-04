import pytest
from tests.test_glossary_skill import _FakeLegacy, _grok_settings
from twobyteasr.glossary import glossary_build as gb
from twobyteasr.glossary.glossary_skill import GlossarySearchError

def setup_build(monkeypatch):
    monkeypatch.setattr(gb,'is_safe_web_url',lambda url:(True,''))
    monkeypatch.setattr('twobyteasr.glossary.glossary_skill.is_safe_web_url',lambda url:(True,''))
    monkeypatch.setattr(gb,'load_model_cache',lambda:{})
    monkeypatch.setattr(gb,'other_game_canonical_terms',lambda *a:[])
    def request(*args,**kw):
        receipt=dict(tool='web_search',urls=['https://wiki.example/characters'])
        kw['on_stream_event']('search_receipt',__import__('json').dumps(receipt))
        return {'pages':[dict(url=receipt['urls'][0],title='角色',covers='characters')]},{'search_evidence':[receipt]}
    monkeypatch.setattr(gb,'_structured_call',request)
    monkeypatch.setattr(gb,'discover_category_names',lambda *a,**kw:['角色'])
    monkeypatch.setattr(gb,'category_members',lambda *a,**kw:['浔','翳','创建角色图鉴']+[f'角色名{i}' for i in range(100)])
    monkeypatch.setattr(gb,'_try_fetch',lambda *a,**kw:None)

def test_full_build_has_live_receipts_incremental_evidence_and_no_64_cap(monkeypatch):
    setup_build(monkeypatch);snapshots=[];events=[];checkpoints=[]
    result=gb.run_full_library_update(_FakeLegacy(),'异环',_grok_settings(),
        report=lambda *a:events.append(a),on_candidates=lambda p:snapshots.append(list(p)),
        checkpoint_writer=lambda p:checkpoints.append(p))
    assert result['candidate_count']==102
    assert result['partial'] and result['build_stats']['catalog_verified']==102
    assert any(e[0]=='检索回执' for e in events)
    assert snapshots[0]==[] and len(snapshots[-1])==102
    assert all(t.verification=='catalog_verified' and 'api.php?' in t.source_urls[0] for t in snapshots[-1])
    assert '技能' in result['build_stats']['missing_categories']
    assert checkpoints[-1]['search_receipts']

def test_cancel_after_first_candidates_retains_checkpoint(monkeypatch):
    setup_build(monkeypatch);state={'cancel':False};checkpoints=[]
    def candidates(items):
        if items:state['cancel']=True
    with pytest.raises(GlossarySearchError,match='取消'):
        gb.run_full_library_update(_FakeLegacy(),'异环',_grok_settings(),cancel_check=lambda:state['cancel'],
            on_candidates=candidates,checkpoint_writer=lambda p:checkpoints.append(p))
    assert len(checkpoints[-1]['candidates'])==102

def test_later_budget_failure_returns_reviewable_partial(monkeypatch):
    setup_build(monkeypatch)
    def stopped(url,**kw):raise GlossarySearchError('budget_exhausted','预算耗尽')
    # Force a failure after the first published batch, before final diff.
    def publish(items):
        if items:raise GlossarySearchError('budget_exhausted','预算耗尽')
    result=gb.run_full_library_update(_FakeLegacy(),'异环',_grok_settings(),on_candidates=publish)
    assert result['partial'] and result['candidate_count']==102
    assert result['build_stats']['failure']=='budget_exhausted'
