import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from dataclasses import asdict
import json
from twobyteasr.caption_style.font_metadata import resolve_local_face
from twobyteasr.exports.preset_application import preset_command
from twobyteasr.projects.studio_project import SubtitleProject, SubtitleStyle, StudioMedia, StudioCue, load_project, save_project
from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.rendering.advanced_renderer import normalized_visual_snapshot
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.caption_style.style_presets import StylePresetStore

def project():
    p=SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=2000,width=1920,height=1080),
        styles=[SubtitleStyle('default','custom',font_family='思源黑体 Heavy',font_size=90,position_x=960,position_y=1000)],
        cues=[StudioCue(str(i),i*500,(i+1)*500,'一二三四五六七八九十甲乙丙丁戊') for i in range(4)])
    p.validate();return p

def test_heavy_bytes_are_900_and_all_render_inputs_agree(tmp_path):
    face, warning=resolve_local_face('思源黑体 Heavy')
    assert not warning and face.style=='Heavy' and face.weight==900
    p=project();before=deepcopy(p.to_dict())
    snapshot=build_visual_cue_snapshot(p,'0');caption=snapshot.resolved_caption
    assert snapshot.font_weight==900 and caption.measured_width==1350 and caption.style.font_size==90
    assert normalized_visual_snapshot(snapshot)['typography']['fontWeight']==900
    assert ',900,' in compile_ass(p)
    assert p.to_dict()==before
    save_project(p,tmp_path/'p.2byteproj');reopened=load_project(tmp_path/'p.2byteproj')
    assert asdict(reopened.styles[0])==asdict(p.styles[0])

def test_sparse_patch_preserves_each_cue_and_geometry_idempotently():
    p=project();p.styles[0].font_weight=900;p.styles[0].font_style_name='Heavy'
    patch={'id':'partial','name':'color only','primary_color':'#FF0000'}
    cmd=preset_command(p,['0','2'],patch);cmd.redo()
    for cue in p.cues:
        style=resolve_caption_style(p.styles,p.speakers,cue,p.style_recipes).style
        assert style.font_size==90 and style.position_y==1000 and style.font_weight==900
        assert style.primary_color==('#FF0000' if cue.id in ['0','2'] else '#FFFFFF')
    assert preset_command(p,['0','2'],patch) is None
    cmd.undo();assert all(c.style_id=='default' for c in p.cues)

def test_saved_rich_recipe_is_not_rebuilt_from_old_controls(tmp_path):
    p=project();patch={'id':'heavy','name':'heavy','font_family':'思源黑体 Heavy','font_weight':900,
        'font_style_name':'Heavy','font_size':90,'position_y':123,'recipe':{'outline':{'shadow':{'opacity':.5,'blur_radius':13}},'motion':{'mode':'none'}}}
    preset_command(p,[c.id for c in p.cues],patch).redo()
    for c in p.cues:
        assert p.style_recipes[c.style_id]['outline']['shadow']['blur_radius']==13
        assert resolve_caption_style(p.styles,p.speakers,c,p.style_recipes).style.position_y==1000
    assert preset_command(p,[c.id for c in p.cues],patch) is None

def test_missing_font_keeps_authored_choice_and_reports_fallback():
    p=project();p.styles[0].font_family='Nonexistent regression font';before=asdict(p.styles[0])
    result=resolve_caption_style(p.styles,p.speakers,p.cues[0],p.style_recipes)
    assert not result.font_loaded and 'Nonexistent regression font' in result.font_warning
    assert 'SimSun' not in result.style.font_family
    assert asdict(p.styles[0])==before

def test_partial_store_retains_absence(tmp_path):
    store=StylePresetStore(tmp_path);store.path.parent.mkdir(parents=True,exist_ok=True)
    store.path.write_text(json.dumps({'presets':[{'id':'partial','name':'p','bold':False}]}),encoding='utf-8')
    assert store.load_patch('partial')=={'id':'partial','name':'p','bold':False}
    store.set_favorite('partial', True)
    assert 'font_family' not in store.load_patch('partial')
    store.upsert(SubtitleStyle('another', 'another'))
    assert 'font_size' not in store.load_patch('partial')

def test_layout_never_rewrites_authored_size_or_text():
    p=project()
    for text in ['一二三四五六七','一二三四五六七八九十甲乙丙丁戊','这是怎么做到的居然还能继续上传吗','字幕测试 Aa123，Hello！']:
        p.cues[0].text=text
        result=resolve_caption_style(p.styles,p.speakers,p.cues[0],p.style_recipes)
        assert result.style.font_size==90 and not result.requires_split
    p.cues[0].text='长'*80
    assert resolve_caption_style(p.styles,p.speakers,p.cues[0],p.style_recipes).style.font_size==90
    assert len(p.cues)==4


def test_conservative_legacy_face_migration_never_resets_custom_values():
    heavy=SubtitleStyle('h','h',font_family='思源黑体 Heavy',font_size=91,position_y=983,spacing=1.25)
    heavy.validate()
    assert (heavy.font_style_name,heavy.font_weight)==('Heavy',900)
    assert (heavy.font_size,heavy.position_y,heavy.spacing)==(91,983,1.25)
    custom=SubtitleStyle('c','c',font_family='思源黑体 Heavy',font_weight=500,font_size=91)
    custom.validate();assert custom.font_weight==500
    missing=SubtitleStyle('m','m',font_family='Missing Heavy')
    missing.validate();assert missing.font_weight==0
