import copy
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, load_project
from twobyteasr.caption_style.caption_layer_transform import transform_command, resolved_values, displayed_layer
from twobyteasr.caption_style.motion_application import motion_command
from twobyteasr.caption_style.bilingual_layout import project_display_cues, companion_id


@pytest.fixture(scope='module',autouse=True)
def app():
    app=QApplication.instance() or QApplication([])
    yield app


def project():
    p=SubtitleProject(media=StudioMedia('missing.mp4',duration_ms=12000,width=1920,height=1080),
        cues=[StudioCue('stable-a',0,5000,'朝起きて 歯を磨いて'),StudioCue('stable-b',6000,12000,'あっという間午後10時')],
        generation_metadata={'translations':{'stable-a':'早上起床 刷牙','stable-b':'一转眼就到晚上十点'}},
        studio_state={'bilingual':{'mode':'bilingual'}})
    p.validate()
    return p


def test_independent_geometry_is_saved_and_undoable_without_content_changes(tmp_path):
    p=project(); stack=QUndoStack()
    original_content=[(c.id,c.text,c.start_ms,c.end_ms,copy.deepcopy(c.evidence_refs)) for c in p.cues]
    original_translation=copy.deepcopy(p.generation_metadata)
    before=resolved_values(p,p.cues[0],'translation')
    stack.push(transform_command(p,['stable-a'],'original',{'position_x':240.,'position_y':450.,'rotation':18.,'scale_x':120.}))
    assert resolved_values(p,p.cues[0],'translation')==before
    stack.push(transform_command(p,['stable-a'],'translation',{'position_x':1500.,'position_y':700.,'anchor_x':.25,'scale_x':75.}))
    a=resolved_values(p,p.cues[0],'original'); b=resolved_values(p,p.cues[0],'translation')
    assert a['position_x']==240 and b['position_x']==1500
    assert a['scale_y']==120 and b['scale_y']==75
    assert resolved_values(p,p.cues[1],'original')['position_x'] != 240
    path=save_project(p,tmp_path/'roundtrip.2byteproj'); restored=load_project(path)
    assert resolved_values(restored,restored.cues[0],'original')==a
    assert resolved_values(restored,restored.cues[0],'translation')==b
    stack.undo();assert resolved_values(p,p.cues[0],'translation')==before
    stack.redo();assert resolved_values(p,p.cues[0],'translation')==b
    assert original_content==[(c.id,c.text,c.start_ms,c.end_ms,c.evidence_refs) for c in p.cues]
    assert p.generation_metadata==original_translation


def test_batch_only_changes_named_field_and_keeps_per_cue_ratio():
    p=project()
    for cue,x,rotation,sx,sy in [(p.cues[0],320.,12.,100.,50.),(p.cues[1],740.,-9.,80.,120.)]:
        transform_command(p,[cue.id],'original',{'position_x':x,'rotation':rotation,'scale_x':sx,'scale_y':sy}).redo()
    transform_command(p,[c.id for c in p.cues],'original',{'position_y':300.}).redo()
    a,b=[resolved_values(p,c,'original') for c in p.cues]
    assert (a['position_x'],b['position_x'],a['rotation'],b['rotation'])==(320.,740.,12.,-9.)
    transform_command(p,[c.id for c in p.cues],'original',{'scale_x':200.}).redo()
    a,b=[resolved_values(p,c,'original') for c in p.cues]
    assert a['scale_y']==100. and b['scale_y']==300.


def test_linked_motion_preserves_geometry_and_single_layer_override_survives_new_text():
    p=project()
    transform_command(p,['stable-a'],'original',{'position_y':820.,'scale_x':125.}).redo()
    transform_command(p,['stable-a'],'translation',{'position_y':650.,'scale_x':90.}).redo()
    positions=[resolved_values(p,p.cues[0],layer) for layer in ('original','translation')]
    motion_command(p,['stable-a'],motion={'entry':{'type':'float_up','duration':350}},language='linked').redo()
    original,translation=project_display_cues(p)[:2]
    assert original.effect_id==translation.effect_id!='none'
    assert [resolved_values(p,p.cues[0],layer) for layer in ('original','translation')]==positions
    original_id=original.effect_id
    motion_command(p,['stable-a'],motion={'entry':{'type':'none'},'exit':{'type':'none'}},words={'type':'none'},language='translation').redo()
    p.generation_metadata['translations']['stable-a']='重新翻译也保持自己的视觉设置'
    original,translation=project_display_cues(p)[:2]
    assert original.effect_id==original_id
    assert p.effects[translation.effect_id]['entry']['type']=='none'
    assert not p.cues[0].transform['language_motion']['linked']


def test_translation_word_animation_never_reuses_source_word_indices():
    p=project(); p.cues[0].evidence_refs=['original-audio-only']
    motion_command(p,['stable-a'],words={'type':'word_reveal'},language='linked').redo()
    companion=displayed_layer(p,p.cues[0],'translation')
    assert not companion.evidence_refs
    assert p.effects[companion.effect_id]['entry']['type']=='fade'
    assert 'word_highlight' not in p.effects[companion.effect_id]
    assert p.cues[0].evidence_refs==['original-audio-only']


def test_gesture_merges_but_separate_gestures_do_not():
    p=project();stack=QUndoStack(); token=object()
    for value in (100.,200.,300.):stack.push(transform_command(p,['stable-a'],'original',{'position_x':value},merge_token=token))
    assert stack.count()==1
    stack.push(transform_command(p,['stable-a'],'original',{'position_x':400.},merge_token=object()))
    assert stack.count()==2
    stack.undo();assert resolved_values(p,p.cues[0],'original')['position_x']==300.
    stack.undo();assert not p.cues[0].transform.get('language_layers')


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf')])
def test_nonfinite_edit_never_changes_project(value):
    p=project();before=copy.deepcopy(p.cues[0].transform)
    with pytest.raises(ValueError):transform_command(p,['stable-a'],'original',{'position_x':value})
    assert p.cues[0].transform==before


def test_display_ass_and_live_use_same_language_data_in_original_mode():
    from twobyteasr.rendering.ass_compiler import compile_ass,compile_ass_revision
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    p=project();p.studio_state['bilingual']['mode']='original'
    transform_command(p,['stable-a'],'original',{'position_x':400.,'position_y':500.,'rotation':25.,'anchor_x':.3}).redo()
    snapshot=build_visual_cue_snapshot(p,'stable-a')
    assert snapshot.position_x==400. and snapshot.position_y==500.
    assert snapshot.rotation==25. and snapshot.anchor_x==.3
    assert r'\frz-25' in compile_ass(p)
    assert r'\frz-25' in compile_ass_revision(StudioRevisionStore(p).render)


def test_negative_and_subpixel_positions_are_not_clamped_by_legacy_style():
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.rendering.ass_compiler import compile_ass
    p=project();p.studio_state['bilingual']['mode']='original'
    transform_command(p,['stable-a'],'original',{'position_x':-120.25,'position_y':400.5}).redo()
    snapshot=build_visual_cue_snapshot(p,'stable-a')
    assert snapshot.position_x==-120.25 and snapshot.position_y==400.5
    from twobyteasr.rendering.ass_font_units import ass_font_style
    from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
    shown = next(cue for cue in project_display_cues(p) if cue.id == 'stable-a')
    caption = resolve_caption_style(p.styles, p.speakers, shown, p.style_recipes, 1920, 1080)
    native = ass_font_style(caption.style, 1920, 1080, layout=caption.layout)
    assert native.position_x < 0  # native line-box compensation must not clamp the authored ink point
    assert f'\\pos({round(native.position_x,2):g},{round(native.position_y,2):g})' in compile_ass(p)


def test_rich_line_motion_is_compiled_for_translation_in_both_export_paths():
    from twobyteasr.rendering.ass_compiler import compile_ass,compile_ass_revision
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.caption_style.word_animation import build_word_animation
    p=project()
    transform_command(p,['stable-a'],'translation',{'anchor_x':.3,'rotation':-6.}).redo()
    motion_command(p,['stable-a'],motion={'entry':{'type':'whip_in','duration':900}},language='linked').redo()
    companion=displayed_layer(p,p.cues[0],'translation')
    plan=build_word_animation(p,companion)
    assert plan['status']=='translation_no_alignment' and not plan['spans']
    assert plan['units']
    for ass in (compile_ass(p),compile_ass_revision(StudioRevisionStore(p).render)):
        lines=[line for line in ass.splitlines() if line.startswith('Dialogue:') and '早上起床' in line]
        assert len(lines)>4
        assert any(r'\move(' in line and r'\alpha' in line for line in lines)


def test_persisted_instance_id_is_not_collapsed_to_another_cue():
    p=project();duplicate=copy.deepcopy(p.cues[0]);duplicate.id='stable-a#copy'
    duplicate.start_ms=8000;duplicate.end_ms=10000;p.cues.append(duplicate)
    p.generation_metadata['translations'][duplicate.id]='独立副本的译文'
    before=copy.deepcopy(p.cues[0].transform)
    transform_command(p,[duplicate.id],'translation',{'position_x':1500.}).redo()
    assert p.cues[0].transform==before
    assert resolved_values(p,p.cues[-1],'translation')['position_x']==1500.
    motion_command(p,[duplicate.id],motion={'entry':{'type':'float_up'}},language='linked').redo()
    assert p.cues[0].effect_id=='none' and p.cues[-1].effect_id!='none'
