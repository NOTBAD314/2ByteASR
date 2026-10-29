import copy
import json
import math
import threading
from types import SimpleNamespace

import pytest

from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger, accept_authored_set
from twobyteasr.caption_design.motion_spec_repair import apply_patches, changed_paths, collect_range_issues
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from scripts.author_balatro_candidates import candidates


def payload(value=120):
    rows = candidates()
    rows[0]['generated_source']['motionSpec']['tracks'][0]['from']['rotationY'] = value
    rows[0]['generated_source']['motionSpec']['tracks'][0]['to']['rotationY'] = 0
    return {'candidates': rows}


def answer(issues, value=70):
    return {'patches': [dict(candidate_index=i['candidate_index'], path=i['path'], value=value) for i in issues]}


@pytest.mark.parametrize('value', [-80, 80])
def test_boundary_no_request(tmp_path, value):
    accept_authored_set(payload(value), ThemeLedger(tmp_path,'Balatro'),'test','test',
        motion_repair=lambda *a:pytest.fail('valid candidate must not call repair'))


@pytest.mark.parametrize('value', [-81, 81, -180, 180])
def test_one_transaction_full_validation_and_receipt(tmp_path, value):
    data=payload(value);before=copy.deepcopy(data);calls=[]
    def repair(issues, request_id, schema):
        calls.append((issues,request_id,schema));return answer(issues)
    ledger=ThemeLedger(tmp_path,'Balatro')
    result=accept_authored_set(data,ledger,'test','model',motion_repair=repair,request_id='parent')
    assert len(calls)==1 and len(result.concepts)==3 and data==before
    receipt=ledger.value['motion_repairs'][0]
    assert receipt['status']=='applied' and receipt['parent_request_id']=='parent'
    assert receipt['repair_request_id']==calls[0][1] and receipt['elapsed_seconds']>=0
    assert receipt['changed_paths']==['candidates[0].generated_source.motionSpec.tracks[0].from.rotationY']
    assert receipt['patches'][0]['before']==value and receipt['patches'][0]['after']==70
    assert (tmp_path/f'repair-{calls[0][1]}.json').is_file()
    assert [c['authored_theme']['cueCss'] for c in result.concepts]==[c['generated_source']['cueCss'] for c in data['candidates']]


@pytest.mark.parametrize('bad', ['70', None, True, float('nan'), float('inf'), -81, 81])
def test_invalid_value_rejected(tmp_path, bad):
    ledger=ThemeLedger(tmp_path,'Balatro');calls=[]
    def repair(issues,*_):calls.append(issues);return answer(issues,bad)
    with pytest.raises(ValueError,match='父请求 parent；修复请求'):
        accept_authored_set(payload(),ledger,'test','model',motion_repair=repair,request_id='parent')
    assert len(calls)==1 and not ledger.value['candidates']
    assert ledger.value['motion_repairs'][0]['status']=='rejected'


@pytest.mark.parametrize('mode',['extra','wrong-path','wrong-index','duplicate','missing','theme-rewrite'])
def test_patch_whitelist_is_exact(mode):
    data=payload();issues,_=collect_range_issues(data);patch=answer(issues)
    if mode=='extra':patch['patches'][0]['name']='changed'
    if mode=='wrong-path':patch['patches'][0]['path']='candidates[0].generated_source.name'
    if mode=='wrong-index':patch['patches'][0]['candidate_index']=1
    if mode=='duplicate':patch['patches']*=2
    if mode=='missing':patch['patches']=[]
    if mode=='theme-rewrite':patch['candidates']=data['candidates']
    with pytest.raises(ValueError):apply_patches(data,patch,issues)


def test_many_leaves_and_untouched_candidate():
    data=payload();data['candidates'][2]['generated_source']['motionSpec']['tracks'][0]['from']['x']=3000
    data['candidates'][2]['generated_source']['motionSpec']['tracks'][0]['to']['x']=0
    issues,_=collect_range_issues(data);assert len(issues)==2
    result,diff=apply_patches(data,answer(issues),issues)
    assert result['candidates'][1]==data['candidates'][1]
    assert set(diff)=={i['path'] for i in issues}==set(changed_paths(data,result))


def test_other_contract_error_does_not_spend_repair(tmp_path):
    data=payload();data['candidates'][1]['generated_source']['cueHtml']='<script>bad</script>'
    with pytest.raises(ValueError):
        accept_authored_set(data,ThemeLedger(tmp_path,'Balatro'),'test','model',
            motion_repair=lambda *a:pytest.fail('unrelated error'))


def test_late_cancel_never_commits(tmp_path):
    cancel=threading.Event();ledger=ThemeLedger(tmp_path,'Balatro')
    def repair(issues,*_):cancel.set();return answer(issues)
    with pytest.raises(Exception,match='已取消'):
        accept_authored_set(payload(),ledger,'test','model',motion_repair=repair,cancel_check=cancel.is_set)
    assert not ledger.value['candidates'] and ledger.value['motion_repairs'][0]['status']=='cancelled'


@pytest.mark.parametrize('change',['operation','generation','page_generation','finished','cancel','project'])
def test_old_request_identity_rejected(change):
    from twobyteasr.caption_design.studio_theme_draft import StudioThemeDraftController
    cancel=threading.Event();project=object()
    obj=SimpleNamespace(provider_operation='op',generation_running=True,phase='PROVIDER',current=SimpleNamespace(generation=2),project=project,
        page=SimpleNamespace(project=project,_ai_request_generation=2,_close_requested=False))
    assert StudioThemeDraftController.provider_request_current(obj,'op',2,cancel)
    # Rendering one independent candidate must not invalidate its siblings.
    obj.phase='READY'
    assert StudioThemeDraftController.provider_request_current(obj,'op',2,cancel)
    if change=='operation':obj.provider_operation='new'
    if change=='generation':obj.current.generation=3
    if change=='page_generation':obj.page._ai_request_generation=3
    if change=='finished':obj.generation_running=False
    if change=='cancel':cancel.set()
    if change=='project':obj.page.project=object()
    assert not StudioThemeDraftController.provider_request_current(obj,'op',2,cancel)
