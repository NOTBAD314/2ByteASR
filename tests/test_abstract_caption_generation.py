import copy
import json
import re
import threading
import time
from types import SimpleNamespace

import pytest
from twobyteasr.caption_design.authored_generation import generate_staged
from twobyteasr.caption_design.caption_components import compose
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
from twobyteasr.caption_design.source_artifact import frame,token,to_theme
from twobyteasr.caption_design.theme_motion import validate_motion_spec


class FixtureClient:
    def __init__(self,shared=None):self.shared=shared or {'calls':[],'active':0,'peak':0,'lock':threading.Lock()}
    def complete(self,messages,**kw):
        content=messages[0]['content'];content=content if isinstance(content,str) else content[0]['text']
        with self.shared['lock']:
            self.shared['calls'].append(kw);self.shared['active']+=1
            self.shared['peak']=max(self.shared['peak'],self.shared['active'])
        try:
            if kw.get('response_kind')!='source_artifact':
                schema=kw['json_schema']['properties']['candidates'];count=schema['maxItems']
                draft='components' in schema['items']['properties']
                return json.dumps({'candidates':[dict(name='抽象方向'+str(i),design='文字优先、薄底板与错峰收束的不同方向',
                    **({'components':dict(version=1,layout=('compact','editorial','centered')[i],lettering=('press','register','gradient')[i],rhythm=('settle','slide','align')[i])} if draft else {})) for i in range(count)]})
            for _ in range(5):
                if kw['cancel_check']():
                    from twobyteasr.providers.ai_providers import AIProviderError
                    raise AIProviderError('此候选已取消',category='cancelled')
                time.sleep(.01)
            marker=re.findall(r'2BYTE-ARTWORK/1 ([a-f0-9]{24})',content)[-1]
            raw=frame(dict(HTML='',CSS='',STAGE_CSS='',PARAMETERS=json.dumps({'components':{'version':1}})),'fixture').replace(token('fixture'),marker)
            kw['on_stream_event']('delta',raw);kw['on_stream_event']('final','success')
            return raw
        finally:
            with self.shared['lock']:self.shared['active']-=1
    def invocation_trace(self):return {'dispatched':True,'timings':{'queue_ms':0,'retry_count':0}}


def run(tmp_path,models=None,**kw):
    client=FixtureClient();ledger=ThemeLedger(tmp_path,'chess 对弈抽象字幕')
    result=generate_staged(ledger,client,SimpleNamespace(provider='fixture',model='local'),'unused',
        {'models':dict(ai_design_wait_mode='long30',**(models or {}))},request_id='fixture',
        client_factory=lambda:FixtureClient(client.shared),**kw)
    return ledger,result,client.shared


def test_default_only_one_implementation_and_no_implicit_paid_review(tmp_path):
    events=[]
    ledger,result,shared=run(tmp_path,stage_event_callback=events.append)
    assert len(shared['calls'])==2 and len(result.concepts)==1
    assert result.concepts[0].get('technical_status')!='failed'
    assert ledger.value['authorship_budget']['repair_calls_per_candidate']==0
    timing=json.loads((tmp_path/'candidates/A/v1/timing.json').read_text('utf8'))
    assert timing['actual_calls']==1 and timing['provider_queue_ms'] is None
    assert timing['provider_reasoning_ms'] is None
    assert set(timing['milestones'])>={'first_provider_event','first_body','response_complete','parse_complete','terminal'}
    assert any(e.get('pending_directions') and not e.get('partial_concepts') for e in events)
    assert any(e.get('candidate_states',{}).get('A',{}).get('activity') for e in events)


def test_three_drafts_use_one_light_request_and_keep_same_source(tmp_path):
    ledger,result,shared=run(tmp_path,dict(ai_design_candidate_count=3,ai_design_mode='drafts'))
    assert len(shared['calls'])==1 and len(result.concepts)==3
    assert all(c.get('technical_status')!='failed' for c in result.concepts)
    sources=[c['authored_theme'] for c in result.concepts]
    assert len({s['cueCss'] for s in sources})==3
    assert len({json.dumps(s['motionSpec']) for s in sources})==3
    assert all('{{words}}' in s['cueHtml'] for s in sources)


def test_explicit_three_candidates_bound_parallelism_and_cancel_one(tmp_path):
    ledger,result,shared=run(tmp_path,dict(ai_design_candidate_count=3,ai_design_concurrency=2),
        candidate_cancel_check=lambda ident:ident=='B')
    assert shared['peak']<=2
    assert len(result.concepts)==3
    assert [c['id'] for c in result.concepts if c.get('technical_status')!='failed']==['A','C']
    assert ledger.value['candidate_states']['B']['status']=='cancelled'
    assert result.concepts[1]['ledger_path']
    assert ledger.value['scheduling']['actual_peak_candidates']==2
    assert (tmp_path/'jobs/A/candidates/A/v1/provider-original.txt').is_file()
    assert (tmp_path/'jobs/C/candidates/C/v1/provider-original.txt').is_file()


def test_render_failure_does_not_buy_an_automatic_repair(tmp_path):
    from twobyteasr.caption_design.theme_draft import DraftValidationError
    def bad(*args,**kwargs):raise DraftValidationError('正文溢出')
    _,result,shared=run(tmp_path,render_candidate=bad)
    assert len(shared['calls'])==2 and result.concepts[0]['technical_status']=='failed'


def test_cancel_during_preview_is_cancelled_without_a_repair(tmp_path):
    cancelled=set()
    def stop(concept,*args,**kwargs):
        cancelled.add(concept['id']);raise InterruptedError('cancelled preview')
    ledger,result,shared=run(tmp_path,render_candidate=stop,candidate_cancel_check=cancelled.__contains__)
    assert len(shared['calls'])==2 and result.concepts[0]['technical_status']=='failed'
    assert ledger.value['candidate_states']['A']['status']=='cancelled'


def test_component_transport_uses_empty_source_sections_and_host_expansion():
    raw=frame(dict(HTML='',CSS='',STAGE_CSS='',PARAMETERS=json.dumps({'components':{'version':1}})),'id')
    theme,receipt=to_theme(raw,'id',{'name':'抽象'})
    assert receipt['component_version']=='caption-components-1'
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    assert WebThemeDocument.from_dict(theme).motion_spec['version']==2
    with pytest.raises(ValueError,match='不可混用'):to_theme(raw.replace('===HTML===\n','===HTML===\n<div>bad</div>'),'id',{'name':'bad'})


def test_motion_v2_limits_and_no_silent_capability_loss():
    value=compose({'version':1})['motionSpec']
    assert validate_motion_spec(value)['tracks'][2]['stagger']['amountMs']==140
    for change in (lambda s:s.update(version=1),lambda s:s.update(keyframes=[1,2]),lambda s:s['tracks'][2].update(keyframes=[1,2]),
                   lambda s:s['tracks'][2]['stagger'].update(amountMs=999),
                   lambda s:s['tracks'][0].update(optional=True)):
        bad=copy.deepcopy(value);change(bad)
        with pytest.raises(ValueError):validate_motion_spec(bad)


def test_empty_direction_response_is_not_a_success():
    from twobyteasr.caption_design.authored_generation import normalize_directions
    with pytest.raises(ValueError,match='完整候选'):normalize_directions({'candidates':[]})


def test_default_prompt_allows_theme_led_art_and_text_capabilities(tmp_path):
    from twobyteasr.caption_design.authored_prompt import assemble
    ledger=ThemeLedger(tmp_path,'chess.com风格')
    message,_=assemble(ledger,direction={'name':'对弈','design':'抽象文字'})
    assert '主题名称允许采用' in message
    assert '不预先禁止人物' in message
    assert '主题名称本身不是授权' not in message
    assert '默认保留主题文字框、可辨识角色' not in message
    assert 'caption-components-2' in message and 'stagger' in message
    assert message.count('chess.com风格')==1


def test_draft_cancel_preserves_completed_candidates(tmp_path):
    _,result,shared=run(tmp_path,dict(ai_design_candidate_count=3,ai_design_mode='drafts'),
        candidate_cancel_check=lambda ident:ident=='B')
    assert len(shared['calls'])==1
    assert [c['id'] for c in result.concepts if c.get('technical_status')!='failed']==['A','C']


def test_candidate_can_be_adopted_while_peer_waits_and_advice_does_not_block():
    from PySide6.QtWidgets import QApplication,QPushButton
    from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog
    app=QApplication.instance() or QApplication([])
    dialog=ThemeConceptDialog([
        dict(id='A',name='可用作品',composition='薄底板',creative_version='fixture',
             authored_theme={'verified_fixture':True},preview_integrity_verified=True,
             motion_preview={'status':'motion_ready'},visual_review={'accepted':False,'blocking':True,'notes':'审美待用户签收'}),
        dict(id='B',name='等待作品',composition='另一方向',pending=True,technical_status='pending')],{})
    cancelled=[];dialog.cancel_requested.connect(cancelled.append)
    buttons=dialog.findChildren(QPushButton)
    choose=[b for b in buttons if b.text()=='采用这个方向']
    assert choose[0].isEnabled() and not choose[1].isEnabled()
    next(b for b in buttons if b.text()=='取消此候选').click()
    assert cancelled==['B'] and choose[0].isEnabled()
    choose[0].click();assert dialog.selected_id=='A'


def test_font_cache_invalidates_after_bundled_file_changes(tmp_path,monkeypatch):
    from twobyteasr.caption_design import web_theme_fonts as fonts
    path=tmp_path/'assets/fonts/Cubic11.ttf';path.parent.mkdir(parents=True)
    monkeypatch.setattr(fonts,'detect_install_root',lambda:tmp_path)
    path.write_bytes(b'first-font');first=fonts.offline_font_css('Cubic 11')
    path.write_bytes(b'second-font-larger');second=fonts.offline_font_css('Cubic 11')
    assert first!=second


def test_missing_font_is_explicit_in_actual_browser_receipt():
    from twobyteasr.caption_design.web_theme_fonts import font_use_receipt
    diag={'rendered_fonts':[{'fonts':[{'familyName':'Source Han Sans SC Heavy','glyphCount':4}]}]}
    assert not font_use_receipt('Source Han Sans SC Heavy',diag)['warning']
    assert '实际替代' in font_use_receipt('Missing, Source Han Sans SC Heavy',diag)['warning']
