import copy,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests.test_caption_creative_pipeline import authored,candidates
from twobyteasr.caption_design.authored_visual_revision import revise_candidate


def test_local_revision_restores_frozen_font_without_changing_geometry():
    from twobyteasr.caption_design.authored_visual_revision import preserve_typography
    before='.a{font-size:52px;font-family:"Cubic";width:800px}'
    proposed='.a{font-size:72px;font-family:"Cubic";width:400px}'
    fixed,changes=preserve_typography(before,proposed)
    assert fixed=='.a{font-size:52px;font-family:"Cubic";width:400px}'
    assert len(changes)==1 and changes[0]['proposed']=='72px'
    with pytest.raises(ValueError):preserve_typography(before,'.a{width:400px}')


def test_redo_keeps_artwork_and_request_owned_candidate_identity(tmp_path):
    from twobyteasr.caption_design.authored_visual_revision import normalize_redo_response
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    fresh=copy.deepcopy(candidates()[0]);source=fresh['generated_source']
    fresh['id']='new-theme';source['id']='new-theme'
    ledger=ThemeLedger(tmp_path,'a new direction')
    normalized=normalize_redo_response({'candidate':fresh},'A',ledger)['candidate']
    assert normalized['id']=='A' and normalized['generated_source']==source
    assert ledger.value['normalized_response']['provider_candidate_id']=='new-theme'
    with pytest.raises(ValueError):normalize_redo_response({'candidate':dict(normalized,id='B')},'A',ledger,peer_ids=('B','C'))


def test_missing_motion_target_repair_receives_existing_targets():
    from twobyteasr.caption_design.authored_repair import local_context,compact_patch_context
    value=local_context({'cueHtml':'<div class="cluster"><svg class="bear-svg"/></div>','cueCss':''},'.bear')
    assert value['available_nodes']==[{'tag':'div','classes':'cluster','parent_classes':''},
        {'tag':'svg','classes':'bear-svg','parent_classes':'cluster'}]
    outgoing=compact_patch_context([{'category':'selector','context':value}])
    assert next(iter(outgoing['contexts'].values()))['available_nodes']==value['available_nodes']


def test_metadata_syntax_repair_never_sends_or_changes_valid_artwork(tmp_path):
    from twobyteasr.caption_design.authored_visual_revision import parse_redo_response
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,AUTHORED_OUTPUT_SCHEMA
    fresh=copy.deepcopy(candidates()[0]);source=fresh['generated_source']
    broken=json.dumps({'candidate':fresh}).replace('"name": "','"name": "bad"quote',1)
    schema=dict(type='object',required=['candidate'],properties={'candidate':copy.deepcopy(AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items'])})
    class Client:
        def complete(self,messages,**kwargs):
            assert source['cueHtml'] not in messages[0]['content']
            assert kwargs['input_scope']['source_omitted'] and kwargs['input_scope']['allowed_paths']
            return json.dumps({'candidate':dict(fresh,generated_source={})})
    ledger=ThemeLedger(tmp_path,'test')
    result=parse_redo_response(broken,ledger,Client(),schema,timeout=60)
    assert result['candidate']['generated_source']==source
    ledger.raw_response(broken,'test','test')
    from twobyteasr.caption_design.authored_visual_revision import saved_payload
    assert saved_payload(ledger)==result


def test_full_redo_changes_art_direction_preserves_peers_and_real_provenance(tmp_path,monkeypatch):
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.caption_design.authored_visual_revision import redesign_candidate,saved_payload
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    prior,result=authored(tmp_path/'prior');prior.raw_response(json.dumps({'candidates':candidates()}),'test','test')
    fresh=copy.deepcopy(candidates()[0]);fresh['name']='全新方向';fresh['generated_source']['name']='全新作品'
    fresh['generated_source']['cueCss']+=' .new-art{color:#FFFFFF}'
    fresh['generated_source']['appearance']['fontSize']=88
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='test'))
    class Client:
        def complete(self,messages,**kwargs):
            assert kwargs['operation_kind']=='generate'
            from twobyteasr.caption_design.source_artifact import from_theme
            assert kwargs['response_kind']=='source_artifact' and kwargs['json_schema'] is None
            return from_theme(fresh['generated_source'],'test/A/redo')
        def invocation_trace(self):return {'request_id':'new-real-request'}
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:Client())
    revised=redesign_candidate(prior.root/'ledger.json','A','整体重做',{},ledger_root=tmp_path/'new',request_id='test')
    assert revised.concepts[0]['name']==prior.value['candidates'][0]['name']
    assert revised.concepts[0]['authored_theme']['appearance']['fontSize']==88
    assert revised.concepts[1:]==[dict(c,ledger_path=str(tmp_path/'new/ledger.json')) for c in result.concepts[1:]]
    ledger=ThemeLedger.open(tmp_path/'new/ledger.json')
    assert '2BYTE-ARTWORK/1' in Path(ledger.value['stage_original']).read_text('utf8')
    assert saved_payload(ledger)['candidates'][0]['generated_source']['cueCss']==fresh['generated_source']['cueCss']
    assert ledger.value['creative_redo']['budget_kind']=='generation'


@pytest.mark.parametrize('font_change',[False,True])
def test_revision_preserves_peers_and_rejects_unrelated_font(tmp_path,monkeypatch,font_change):
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    prior,result=authored(tmp_path/'prior');prior.raw_response(json.dumps({'candidates':candidates()}),'test','test')
    source=copy.deepcopy(prior.value['candidates'][0]['generated_source'])
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='test'))
    class Client:
        def complete(self,messages,**kwargs):
            assert kwargs['operation_kind']=='visual_feedback'
            return json.dumps({'cueCss':source['cueCss']+('.local-fix{font-size:12px}' if font_change else '.local-fix{padding:1px}')})
        def invocation_trace(self):return {}
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:Client())
    invoke=lambda:revise_candidate(prior.root/'ledger.json','A','调整留白',{},ledger_root=tmp_path/'new',request_id='test')
    if font_change:
        with pytest.raises(ValueError,match='字体'):invoke()
    else:
        revised=invoke()
        assert revised.concepts[1:]==[dict(c,ledger_path=str(tmp_path/'new/ledger.json')) for c in result.concepts[1:]]
        assert revised.concepts[0]['authored_theme']['cueHtml']==source['cueHtml']
