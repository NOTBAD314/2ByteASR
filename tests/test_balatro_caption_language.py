import copy
import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest

from twobyteasr.caption_design.caption_card_ui import examples
from twobyteasr.caption_design.caption_components import compose
from twobyteasr.caption_design.caption_style_reference import (is_balatro, load_reference,
    attach_reference, prompt_reference, validate_draft_diversity)


@pytest.mark.parametrize('prompt', ['Balatro','BALATRO','小丑牌风','赌场纸牌风','传奇卡牌风','传奇封牌'])
def test_style_aliases_share_reference_and_guidance(prompt):
    from twobyteasr.caption_design.design_guidance import load_design_guidance
    from twobyteasr.caption_design.caption_creative_pipeline import main_theme
    guidance, receipt = load_design_guidance(prompt)
    assert is_balatro(prompt) and main_theme(prompt)=='Balatro'
    assert receipt['theme']=='Balatro' and '倍率封签' in guidance and '筹码压印' in guidance
    assert '抽象概念表达 ≠ 抽象画' in guidance
    assert load_reference(prompt)['manifest']['categories']


def test_unrelated_theme_does_not_receive_card_directive():
    from twobyteasr.caption_design.design_guidance import load_design_guidance
    _,receipt=load_design_guidance('冰雪主题')
    assert not is_balatro('冰雪主题') and load_reference('冰雪主题') is None
    assert all('balatro-caption' not in r['path'] for r in receipt['files'])


@pytest.mark.parametrize('index',[0,1,2])
def test_v3_roundtrip_has_semantic_text_and_full_motion(index):
    from twobyteasr.caption_design.web_theme import WebThemeDocument, theme_archive_html
    from twobyteasr.caption_design.source_artifact import frame, to_theme
    parts=dict(HTML='',CSS='',STAGE_CSS='',PARAMETERS=json.dumps({'components':dict(examples()[index],emphasis=['自动战斗'])}))
    theme, receipt=to_theme(frame(parts,'test'),'test',{'name':'纸牌字幕'})
    theme=WebThemeDocument.from_dict(theme).to_dict()
    assert receipt['component_definition']['version']==3
    assert '{{words}}' in theme['cueHtml'] and '.bui-copy .wt-focus' in theme['cueCss']
    tracks=theme['motionSpec']['tracks']
    assert {t['phase'] for t in tracks}=={'build','breathe','resolve'}
    assert all(t['end']<=.97 for t in tracks if t['phase']=='resolve')
    assert sum(t['phase']=='resolve' for t in tracks)>=6
    assert any(t['selector']=='.bui-glint' and t['phase']=='breathe' and t['durationMs']>=700 for t in tracks)
    assert theme_archive_html(theme,sample_text='这种就属于是点了自动战斗',duration_seconds=1.5)


def test_axes_reject_color_only_candidates():
    variants=examples()
    validate_draft_diversity({'candidates':[{'components':v} for v in variants]},'Balatro')
    variants[2]=dict(variants[0],accent='#888888')
    with pytest.raises(ValueError,match='不同的structure'):
        validate_draft_diversity({'candidates':[{'components':v} for v in variants]},'Balatro')


def test_reference_tampering_stops_before_generation(tmp_path):
    import shutil
    root=Path(__file__).resolve().parents[1]
    dest=tmp_path/'assets/design-references/balatro'
    shutil.copytree(root/'assets/design-references/balatro',dest)
    (dest/'reference-atlas.jpg').write_bytes(b'invalid')
    with pytest.raises(ValueError,match='尚未调用模型'):
        load_reference('Balatro',root=tmp_path)


def test_snapshot_and_retry_preserve_image_order_and_identity(tmp_path):
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,saved_reference_images
    from PIL import Image
    media=tmp_path/'media.png';Image.new('RGB',(16,16),'white').save(media)
    ledger=ThemeLedger(tmp_path/'task','小丑牌',references=[(media,'current-media')])
    attach_reference(ledger)
    rows=ledger.value['reference_files'];order=[rows[1]['sha256'],rows[0]['sha256']]
    ledger.value['provider_inputs']=[dict(pixels_attached=True,attached_reference_sha256=order)]
    restored=saved_reference_images(ledger)
    assert restored[0]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert restored[1]['image_url']['url'].startswith('data:image/png;base64,')
    import base64,hashlib
    assert [hashlib.sha256(base64.b64decode(p['image_url']['url'].split(',')[1])).hexdigest() for p in restored]==order
    assert prompt_reference(ledger)['model_pixels_seen_confirmed'] is False
    Path(rows[1]['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='改变'):
        saved_reference_images(ledger)


def test_guidance_budget_keeps_three_directions_and_reference(tmp_path):
    from twobyteasr.caption_design.authored_prompt import assemble
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    ledger=ThemeLedger(tmp_path/'task','Balatro小丑牌风格，没有角色，设计背景框字面关键词和完整进出场')
    ledger.value.update(requested_candidates=3,component_drafts=True,creative_context={'subtitle_text':'这种就属于是点了自动战斗'})
    attach_reference(ledger)
    prompt,receipt=assemble(ledger)
    assert 'candidate_strategy' in receipt['components'] and 'style_reference' in receipt['components']
    assert 'caption-components-3' in prompt
    # Keep the unchanged product input ceiling, leaving room for attached pixels.
    assert len(prompt.encode('utf8'))/3+2304<16384


def test_legacy_component_source_still_supported():
    assert '.cap-type' in compose({'version':1})['cueCss']
    assert '.cap-registration' in compose({'version':2})['cueCss']
    with pytest.raises(ValueError,match='不支持'):
        compose({'version':3,'surface':'pixel-joker'})


def test_saved_three_directions_survive_current_single_default(tmp_path):
    from types import SimpleNamespace
    from twobyteasr.caption_design.authored_generation import generate_staged,normalize_directions
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    directions={'candidates':[]};saved={}
    for ident,definition in zip('ABC',examples()):
        directions['candidates'].append(dict(name=ident,design='完整卡牌字幕与边框字面进出场设计',components=definition))
        theme=WebThemeDocument.from_dict(dict(name=ident,**compose(definition))).to_dict()
        # This valid saved source must survive even if its component definition
        # would expand differently under a later version of the vocabulary.
        theme['cueCss']+='\n.bui-copy{letter-spacing:.025em}'
        saved[ident]=dict(generated_source=theme)
    class Client:
        def complete(self,*a,**kw):raise AssertionError('No provider call on complete saved designs')
    ledger=ThemeLedger(tmp_path,'Balatro')
    directions=normalize_directions(directions)
    result=generate_staged(ledger,Client(),SimpleNamespace(provider='test',model='test'),'saved',
        {'models':{'ai_design_candidate_count':1,'ai_design_mode':'full','ai_design_max_repair_calls':0}},
        request_id='restore',retained={'directions':directions,'candidates':saved})
    assert [c['id'] for c in result.concepts]==list('ABC')
    for c in result.concepts:
        assert c.get('technical_status')!='failed'
        assert c['authored_theme']['cueCss']==saved[c['id']]['generated_source']['cueCss']
