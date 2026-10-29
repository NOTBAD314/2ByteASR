import copy
import json
from types import SimpleNamespace

import pytest
from twobyteasr.caption_design.artwork_recovery import inspect_source, save_recovery, saved_recovery, merge_completion
from twobyteasr.caption_design.source_artifact import frame, to_theme
from twobyteasr.caption_design.caption_type_effects import examples, compose
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger


def test_no_body_is_not_a_recoverable_html_failure():
    value=inspect_source('', 'task/A')
    assert value['body_chars']==0 and not value['recoverable'] and value['mode']=='regenerate'


def test_truncated_parameters_only_requests_missing_section_and_preserves_prefix(tmp_path):
    parts=dict(HTML='<div>{{text}}</div>',CSS='.text{color:red}',STAGE_CSS='',PARAMETERS='{"motionSpec":')
    original=frame(parts,'old').split('===END')[0]
    (tmp_path/'provider-partial.txt').write_text(original,'utf8')
    saved=save_recovery(tmp_path,'old')
    assert saved['complete_sections']==['HTML','CSS','STAGE_CSS'] and saved['missing_sections']==['PARAMETERS']
    recovery=saved_recovery(tmp_path)
    completion=frame({'PARAMETERS':json.dumps({'motionSpec':{'version':2}})},'new',kind='2BYTE-COMPLETION/1')
    theme,_=to_theme(merge_completion(completion,recovery,'new'),'new',{'name':'原方向'})
    assert theme['cueHtml']==parts['HTML'] and theme['cueCss']==parts['CSS']
    with pytest.raises(ValueError):merge_completion(completion,recovery,'other')
    (tmp_path/'provider-partial.txt').write_text(original+'tampered','utf8')
    with pytest.raises(ValueError,match='改变'):saved_recovery(tmp_path)


@pytest.mark.parametrize('raw',['hello','2BYTE-ARTWORK/1 wrong\n===HTML===\nfoo','===CSS===\nx',''])
def test_invalid_prefix_cannot_be_accepted(raw):
    assert inspect_source(raw,'task')['recoverable'] is False


def test_duplicate_section_cannot_be_spliced():
    raw=frame(dict(HTML='foo',CSS='bar',STAGE_CSS='',PARAMETERS='bad'),'task').split('===END')[0]
    assert not inspect_source(raw.replace('===CSS===','===HTML==='),'task')['recoverable']


@pytest.mark.parametrize('definition',examples())
def test_new_effects_use_same_safe_runtime_and_keep_semantic_text(definition):
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    theme=WebThemeDocument.from_dict(dict(name='test',**compose(definition))).to_dict()
    assert 'data-semantic-text="true"' in theme['cueHtml']
    assert '{{words}}' in theme['cueHtml'] and len(theme['motionSpec']['tracks'])<=32
    assert {'build','breathe','resolve'}=={t['phase'] for t in theme['motionSpec']['tracks']}
    assert any('.wt-w' in t['selector'] or '.bui-copy'==t['selector'] for t in theme['motionSpec']['tracks'])


def test_search_is_before_planning_and_reuses_saved_evidence_without_network(tmp_path):
    from twobyteasr.caption_design.caption_reference_search import search_references, prompt_evidence
    calls=[]
    def fetch(url,timeout):
        calls.append(url)
        return (b'<rss><channel><item><title>Balatro CRT typography</title><link>https://example.com/design</link><description>Pixel type</description></item></channel></rss>'
                if 'bing.com' in url else b'Balatro Jokers Hand Levels phosphor scanline')
    ledger=ThemeLedger(tmp_path,'Balatro 私有项目名不发送')
    value=search_references(ledger,fetch=fetch)
    assert value['new_web_search_this_request'] and value['pixels_seen'] is False
    assert len(calls)==4 and not any('私有' in url for url in calls)
    assert prompt_evidence(ledger)['translation']
    search_references(ledger,fetch=lambda *a:pytest.fail('Must reuse saved evidence'))


def test_search_failure_is_honest_cached_fallback(tmp_path):
    from twobyteasr.caption_design.caption_reference_search import search_references
    def fail(*args):raise TimeoutError('offline')
    value=search_references(ThemeLedger(tmp_path,'CRT字幕'),fetch=fail)
    assert value['status']=='cached_reference_only' and not value['new_web_search_this_request']


def test_single_balatro_finishes_in_one_model_call_without_source_regeneration(tmp_path):
    from twobyteasr.caption_design.authored_generation import generate_staged
    calls=[]
    class Client:
        def complete(self,*args,**kwargs):
            calls.append(kwargs)
            return {'candidates':[dict(name='传奇显像',design='厚边说明窗、磷光中文字与封签收束的完整设计',components=examples()[0])]}
    ledger=ThemeLedger(tmp_path,'Balatro')
    result=generate_staged(ledger,Client(),SimpleNamespace(provider='fixture',model='test'),'unused',
        {'models':{'ai_design_mode':'single','ai_design_candidate_count':1}},request_id='test')
    assert len(calls)==1 and len(result.concepts)==1
    assert result.concepts[0].get('technical_status')!='failed'
    assert result.concepts[0]['source_origin']=='model_components_new'


def test_bodyless_real_failure_category_is_explicit(tmp_path):
    from twobyteasr.caption_design.authored_generation import generate_staged,normalize_directions
    from twobyteasr.providers.ai_providers import AIProviderError
    class Client:
        def complete(self,*a,**kw):raise AIProviderError('Provider未完整生成正文（finish_reason=length，正文0字符）',category='structured_output_truncated')
    ledger=ThemeLedger(tmp_path,'岩刻')
    directions=normalize_directions({'candidates':[dict(name='粗粝岩刻',design='岩石厚边与凿刻字面的完整字幕方向')]})
    result=generate_staged(ledger,Client(),SimpleNamespace(provider='fixture',model='test'),'unused',{'models':{}},request_id='test',retained={'directions':directions})
    assert ledger.value['candidate_states']['A']['stage']=='response_without_source'
    assert result.concepts[0]['source_recovery']['body_chars']==0


@pytest.mark.parametrize('complete',[False,True])
def test_saved_source_completion_uses_only_missing_sections_and_preserves_source(tmp_path,complete):
    from twobyteasr.caption_design.authored_generation import generate_staged,normalize_directions
    from twobyteasr.caption_design.source_artifact import from_theme,token
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    theme=WebThemeDocument.from_dict(dict(name='原作品',**compose(examples()[0]))).to_dict()
    raw=from_theme(theme,'old')
    if not complete:raw=raw.split('===PARAMETERS===')[0]+'===PARAMETERS===\n{"motionSpec":'
    folder=tmp_path/'old';folder.mkdir();(folder/'provider-partial.txt').write_text(raw,'utf8')
    save_recovery(folder,'old');recovery=saved_recovery(folder)
    calls=[]
    class Client:
        def complete(self,messages,**kw):
            calls.append(messages)
            return frame({'PARAMETERS':json.dumps({k:theme[k] for k in ('motionSpec','palette','appearance')})},'new/A/v1',kind='2BYTE-COMPLETION/1')
    directions=normalize_directions({'candidates':[dict(name='原作品',design='保存原作品的完整形体与字面，只补缺失分节')]})
    ledger=ThemeLedger(tmp_path/'new','字幕')
    result=generate_staged(ledger,Client(),SimpleNamespace(provider='fixture',model='test'),'unused',{'models':{}},request_id='new',retained={'directions':directions,'recoveries':{'A':recovery}})
    assert len(calls)==(0 if complete else 1)
    candidate=result.concepts[0]
    assert candidate.get('technical_status')!='failed'
    assert candidate['authored_theme']['cueHtml']==theme['cueHtml']
    assert candidate['authored_theme']['cueCss']==recovery['parts']['CSS'].strip()
    assert candidate['source_origin']==('saved_source_revalidated' if complete else 'model_source_completed')


def test_unrelated_search_results_are_never_forwarded(tmp_path):
    from twobyteasr.caption_design.caption_reference_search import search_references
    def fetch(url,timeout):
        if 'bing.com' not in url:raise TimeoutError()
        return b'<rss><channel><item><title>Invoice lottery</title><link>https://example.com/tax</link></item></channel></rss>'
    value=search_references(ThemeLedger(tmp_path,'Balatro'),fetch=fetch)
    assert not value['sources'] and not value['new_web_search_this_request']


def test_short_preview_failure_keeps_valid_primary_preview(tmp_path,monkeypatch):
    from io import BytesIO
    from PIL import Image
    from twobyteasr.caption_design.authored_generation import generate_staged,normalize_directions
    from twobyteasr.caption_design.authored_preview import render_candidate_preview,reusable_preview
    directions=normalize_directions({'candidates':[dict(name='试验',design='完整效果框与字面动效的测试方向',components=examples()[0])]})
    class Client:
        def complete(self,*a,**k):pytest.fail('No model call')
    ledger=ThemeLedger(tmp_path/'task','Balatro')
    result=generate_staged(ledger,Client(),SimpleNamespace(provider='fixture',model='test'),'saved',{'models':{}},request_id='test',retained={'directions':directions})
    concept=result.concepts[0]
    output=BytesIO();Image.new('RGBA',(1920,1080),(0,0,0,255)).save(output,format='PNG')
    class Renderer:
        def __init__(self,*a):pass
        def live_set(self,*a,**k):pass
        def live_pause(self,*a,**k):return output.getvalue()
        def _live_request(self,*a,**k):return {'diagnostics':{}}
        def close(self):pass
    monkeypatch.setattr('twobyteasr.rendering.renderer_service.LiveRendererSession',Renderer)
    monkeypatch.setattr('twobyteasr.caption_design.theme_draft.validate_draft_frames',lambda *a,**k:{'passed':True})
    monkeypatch.setattr('twobyteasr.caption_design.authored_motion_review.capture_motion_review',lambda *a,**k:([],{}))
    def movie(service,html,folder,ident,**kwargs):
        if ident.endswith('-short'):raise OSError('disk failed for supplemental file')
        paths={key:folder/('primary.'+ext) for key,ext in [('video','mp4'),('gif','gif')]}
        for path in paths.values():path.write_bytes(b'primary artifact fixture')
        return dict(status='motion_ready',**{key:str(path) for key,path in paths.items()})
    monkeypatch.setattr('twobyteasr.caption_design.theme_direction_preview.render_motion_preview',movie)
    receipt=render_candidate_preview(concept,tmp_path/'preview','字幕')
    assert receipt['motion']['status']=='motion_ready' and receipt['short_motion'] is None
    assert receipt['advisory_failures'][0]['blocking'] is False
    assert reusable_preview(concept,'字幕') is not None


def test_failed_peer_and_aesthetic_advice_do_not_disable_valid_candidate():
    from PySide6.QtWidgets import QApplication,QPushButton
    from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog
    app=QApplication.instance() or QApplication([])
    good=dict(id='A',name='已完成',creative_version='test',authored_theme=compose(examples()[0]),
        motion_preview={'status':'motion_ready'},preview_integrity_verified=True,visual_review={'accepted':False,'notes':'继续改进字体'})
    bad=dict(id='B',name='未完成',creative_version='test',technical_status='failed',source_recovery=inspect_source('','task'))
    dialog=ThemeConceptDialog([good,bad],{})
    buttons=[b for b in dialog.findChildren(QPushButton) if b.text()=='采用这个方向']
    assert [b.isEnabled() for b in buttons]==[True,False]
    dialog.close()
