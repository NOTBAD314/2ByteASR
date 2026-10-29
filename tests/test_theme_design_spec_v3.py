"""V3 contract tests. Raster swatches here are technical fixtures, never mascots."""
import copy
import hashlib
import json
from pathlib import Path
import re

import pytest

from twobyteasr.caption_design.theme_design_spec_v3 import (
    DesignSpecError, MotifAssetUnavailable, compile_static_html,
    resolve_motif, validate_design_spec, validate_static_visual_evidence,
)
from twobyteasr.caption_design.web_theme_compiler import prepare_static_v3_options

ROOT=Path(__file__).resolve().parents[1]


def options():
    return json.loads((ROOT/'examples/web-themes/polar-static-v3/design-options.json').read_text('utf8'))


def swatch_asset(spec,tmp_path):
    from PIL import Image
    image=Image.new('RGBA',(256,256),(0,0,0,0))
    # Flat alpha/color swatch solely exercises bitmap embedding. It must not
    # pass the distinct bear/goggles/reference-completeness visual checks.
    image.paste((211,237,249,255),(20,20,236,236))
    path=tmp_path/'technical-alpha-swatch.png'
    image.save(path)
    spec['motif_asset']=dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    spec['asset_source']=dict(kind='existing',description='pytest technical alpha swatch, not a mascot or design candidate')
    return path


def test_three_pending_designs_degrade_without_blocking_hero_documents(tmp_path):
    payload=options()
    for c in payload['concepts']:
        validate_design_spec(c['design'])
    result=prepare_static_v3_options(payload,payload['text'],asset_root=tmp_path)
    assert len(result['options'])==3 and result['selected_concept_id']==''
    assert all('class="v3-motif"' not in option['html'] for option in result['options'])
    assert all(row['status']=='omitted' for row in result['asset_status'].values())
    assert list(tmp_path.iterdir()) == []
    assert payload['selected_concept_id'] == ''


@pytest.mark.parametrize('mutate,message',[
    (lambda d:d.update(canvas_transparent=False),'透明'),
    (lambda d:d['local_backplate'].update(enabled=False),'局部冰雪底板'),
    (lambda d:d['gradient_stops'][1].update(role='ice_white'),'纯色'),
    (lambda d:d.update(outline_layers=d['outline_layers'][:1]),'单层'),
    (lambda d:d['outline_layers'][1].update(role='unknown'),'palette_roles'),
    (lambda d:d.update(outline_layers=list(reversed(d['outline_layers']))),'覆盖'),
    (lambda d:d['text_fill_layers'][0].update(kind='solid'),'gradient_stops'),
    (lambda d:d.update(safe_area=dict(canvas=[1920,1080],bounds=[0,0,1920,1080])),'安全区'),
    (lambda d:d.update(motion_beats={'timeline':'animation'}),'动作隐喻'),
])
def test_explicit_visual_requirements_cannot_be_erased(mutate,message):
    d=options()['concepts'][0]['design']
    mutate(d)
    with pytest.raises(DesignSpecError,match=message):validate_design_spec(d)


def test_asset_content_identity_and_transparency_are_checked(tmp_path):
    d=options()['concepts'][0]['design']
    path=swatch_asset(d,tmp_path)
    assert resolve_motif(d,tmp_path).startswith('data:image/png;base64,')
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(DesignSpecError,match='SHA256'):resolve_motif(d,tmp_path)
    swatch_asset(d,tmp_path)
    d['motif_asset']['path']='../outside.png'
    with pytest.raises(DesignSpecError,match='指定资产目录'):resolve_motif(d,tmp_path)


def test_opaque_image_cannot_claim_transparency(tmp_path):
    from PIL import Image
    d=options()['concepts'][0]['design']
    path=swatch_asset(d,tmp_path)
    Image.new('RGB',(256,256),'white').save(path)
    d['motif_asset']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(DesignSpecError,match='Alpha'):resolve_motif(d,tmp_path)
    assert 'class="v3-motif"' not in compile_static_html(d,'无角色方案仍应成立',asset_root=tmp_path)


def test_compiler_consumes_layers_palette_and_preserves_static_selection_boundary(tmp_path):
    payload=options()
    for c in payload['concepts']:swatch_asset(c['design'],tmp_path)
    result=prepare_static_v3_options(payload,'啊感觉他就是你看<script>',asset_root=tmp_path)
    assert result['selected_concept_id']=='' and not result['motion_authored']
    assert len(result['options'])==3
    for item in result['options']:
        html=item['html']
        assert '<script' not in html and '&lt;script&gt;' in html
        assert not re.search(r'\b(animation|transition)\s*:|@keyframes|setInterval|__timelines',html)
        assert 'data:font/' in html and 'data:image/png;base64,' in html
        assert html.count('class="v3-letter outline"')==len(item['design']['outline_layers'])
        assert 'background-image:linear-gradient(180deg,#F4FCFF 0%,#C7E8F4 100%)' in html
        assert html.count('class="v3-material"')==len(item['design']['material_stack'])
        for role,hexcode in item['design']['palette_roles'].items():
            assert '--palette-'+role+':'+hexcode in html
        assert 'subtitle-placement' in html


def test_same_shape_or_font_is_not_a_three_option_set(tmp_path):
    payload=options()
    payload['concepts'][1]['design']['local_backplate']['structure']='ice-ledge'
    with pytest.raises(DesignSpecError,match='底板结构'):
        prepare_static_v3_options(payload,payload['text'],asset_root=tmp_path)


@pytest.mark.parametrize('evidence,message',[
    ({'checked':0},'checked=0'),
    ({'checked':1,'backgrounds':['game']},'多背景'),
    ({'checked':3,'backgrounds':['game','light','dark'],'scores':{'average':9.9}},'硬门'),
])
def test_render_counts_or_average_scores_never_pass_visual_gate(evidence,message):
    with pytest.raises(DesignSpecError,match=message):validate_static_visual_evidence(evidence)
