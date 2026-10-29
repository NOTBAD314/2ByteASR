import time
from types import SimpleNamespace
from twobyteasr.glossary.glossary_build import normalize_catalogs
from twobyteasr.glossary.glossary_skill import normalize_searched_terms
from twobyteasr.glossary.glossary_sources import mediawiki_api_url
from twobyteasr.glossary.glossary_task_manager import GlossaryTaskState, GlossaryUpdateManager

def test_observed_catalog_alias_does_not_require_another_search(monkeypatch):
    monkeypatch.setattr('twobyteasr.glossary.glossary_build.is_safe_web_url',lambda url:(True,''))
    result = normalize_catalogs({'pages':[{'url':'https://wiki.biligame.com/yh/角色','title':'异环角色','covers':'characters'}]})
    assert len(result['catalogs'])==1

def test_observed_evidence_url_and_description_survive():
    terms=normalize_searched_terms({'terms':[{'term':'环合复制','category':'mechanic',
        'evidence_url':'https://example.com/game/mechanic','description':'页面解释该机制', 'formality':'community'}]},verification='community')
    assert terms[0].sources[0]['url']=='https://example.com/game/mechanic'
    assert terms[0].evidence=='页面解释该机制'
    assert terms[0].verification!='page_verified'

def test_wiki_api_keeps_game_namespace():
    assert mediawiki_api_url('https://wiki.biligame.com/yh/角色')=='https://wiki.biligame.com/yh/api.php'

def test_progress_and_snapshot_publish_real_counts():
    task=GlossaryTaskState('one','异环','full','Grok','4.7',time.time(),status='running')
    task.stage='资料抓取';task.stage_note='角色目录 example.com 已读，提取 12'
    assert '角色目录' in task.progress_line()
    manager=SimpleNamespace(_tasks={'one':task},task_progress=SimpleNamespace(emit=lambda *args:None))
    GlossaryUpdateManager._on_snapshot(manager,'one',[{'term':'零'}])
    assert task.candidates==1 and task.partial_candidates
