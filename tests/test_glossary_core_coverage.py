from pathlib import Path
from twobyteasr.glossary.glossary_build import _covers_seed_category, harvest_title_names, _clean_extracted_name
from twobyteasr.glossary.glossary_sources import category_members, HealthBoard, WikiSite


def test_equipment_and_structured_entity_names_not_navigation():
    assert _covers_seed_category('equipment') == ('equipment','装备')
    assert _covers_seed_category('装备') == ('equipment','装备')
    html='<nav><a title="留言板">留言板</a></nav><table><tr class="divsort" data-param1="S"><td><a title="长名称也可以是重要技能而不是应该被静默过滤的废话">正文</a></td><td><a title="无关描述">说明</a></td></tr></table>'
    assert harvest_title_names(html,structured_only=True)==['长名称也可以是重要技能而不是应该被静默过滤的废话']


def test_api_error_does_not_consume_continuation(monkeypatch):
    monkeypatch.setattr('twobyteasr.glossary.glossary_sources._api_get',lambda *a,**k:{'error':{'code':'badcontinue'}})
    cursor={'current':{'title':'Category:角色','depth':0},'continue':'token','names':['甲'],'queue':[],'visited':['Category:角色']}
    result=category_members(WikiSite('https://example.com/api.php'),'Category:角色',board=HealthBoard(),cursor=cursor)
    assert result==['甲'] and not result.complete
    assert cursor['continue']=='token' and cursor['current'] and cursor['error']=='badcontinue'


def test_skill_titles_require_semantic_container_and_reject_placeholders():
    from twobyteasr.glossary.glossary_build import harvest_character_skills
    html='<nav class="title-line">导航</nav><div class="skill-box"><div class="title-line"><b>终局清账</b></div><div>这不是技能名</div></div><div class="skill-box"><div class="skill-title">{{{缺失}}}</div></div>'
    assert harvest_character_skills(html)==['终局清账']


def test_default_recommendation_requires_both_evidence_and_value():
    from twobyteasr.glossary.glossary_skill import SearchedTerm,diff_term_updates
    base=dict(category_key='character',category='角色',sources=({'url':'https://example.com/roster'},))
    candidates=[SearchedTerm('可靠',verification='catalog_verified',**base),
        SearchedTerm('网址',verification='sourced',**base),
        SearchedTerm('可选别名',verification='page_verified',priority='optional',aliases=('简称',),**base)]
    results=diff_term_updates(candidates,existing_terms=['可选别名'],confirmed_pairs=[],excluded_terms=[])
    assert [r.checked_by_default for r in results]==[True,False,False]


def test_category_resume_continuation_and_child_preserve_progress(monkeypatch):
    calls=[]
    def api(site,params,*args,**kwargs):
        calls.append(params.copy())
        if params['cmtitle']=='Category:角色' and not params.get('cmcontinue'):
            return {'query':{'categorymembers':[{'title':'甲','ns':0},{'title':'Category:已公开','ns':14}]},'continue':{'cmcontinue':'next-page'}}
        if params['cmtitle']=='Category:角色':return {'query':{'categorymembers':[{'title':'乙','ns':0}]}}
        return {'query':{'categorymembers':[{'title':'丙','ns':0}]}}
    monkeypatch.setattr('twobyteasr.glossary.glossary_sources._api_get',api)
    cursor={};board=HealthBoard();site=WikiSite('https://example.com/api.php')
    first=category_members(site,'Category:角色',board=board,max_pages=1,cursor=cursor)
    assert first==['甲'] and not first.complete
    second=category_members(site,'Category:角色',board=board,max_pages=2,cursor=cursor)
    assert second==['甲','乙','丙'] and second.complete
    assert calls[1]['cmcontinue']=='next-page'
    assert calls[2]['cmtitle']=='Category:已公开'


def test_adoption_preserves_evidence_and_existing_manual_record(tmp_path,monkeypatch):
    import subtitle_core as legacy
    from twobyteasr.glossary import glossary_skill as gs
    monkeypatch.setattr(legacy,'LEARNED_TERMS_PATH',str(tmp_path/'terms.json'))
    monkeypatch.setattr(gs,'update_history_path',lambda:tmp_path/'history.json')
    legacy.add_learned_mapping('测试','旧词','旧词')
    before=legacy.load_learned_term_payload(strict=True)
    term=gs.SearchedTerm('新角色',category='角色',category_key='character',priority='core',
        verification='catalog_verified',sources=({'url':'https://example.com/roster','title':'角色目录'},),evidence='目录成员')
    receipt=gs.apply_term_updates(legacy,'测试',[gs.TermDiff('new',term)],task_id='task-test')
    assert receipt['added']==1 and receipt['failed']==0
    after=legacy.load_learned_term_payload(strict=True)
    records=next(iter(after['games'].values()))['mappings']
    assert records[0]==next(iter(before['games'].values()))['mappings'][0]
    assert records[1]['verification']=='catalog_verified'
    assert records[1]['sources']==list(term.sources) and records[1]['task_id']=='task-test'
