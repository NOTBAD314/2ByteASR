"""Top-level scope and language apply to real inspector/canvas routes."""
import copy
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,SubtitleStyle
from twobyteasr.timeline.selection_scope import SelectionScope
from twobyteasr.caption_style.caption_layer_transform import resolved_values
from twobyteasr.caption_style.style_presets import StylePresetStore

APP=QApplication.instance() or QApplication([])


@pytest.fixture
def page(tmp_path):
    w=SubtitleStudioPage()
    cues=[StudioCue('stable-'+str(i),i*3000,i*3000+2400,'测试字幕'+str(i),speaker_id='A' if i%2==0 else 'B',
        transform={'language_layers':{'original':{'position_x':500.+i*7,'position_y':700.+i,
            'scale_x':100.+i,'scale_y':80.+i,'rotation':float(i%5)},
            'translation':{'position_x':750.+i*3,'position_y':900.+i,'scale_x':70.,'scale_y':75.}}},
        appearance_override={'translation':{'style':{'font_size':29.,'primary_color':'#FFFF8822'}}}) for i in range(25)]
    p=SubtitleProject(StudioMedia(str(tmp_path/'missing.mp4'),duration_ms=75000,width=1920,height=1080),
        cues=cues,speakers=[StudioSpeaker('A','同名'),StudioSpeaker('B','同名')],
        generation_metadata={'translations':{c.id:'Translation '+str(i) for i,c in enumerate(cues)}},
        studio_state={'bilingual':{'mode':'bilingual'}})
    p.validate();w.project=p;w.project_path=tmp_path/'scope.2byteproj'
    w._cue_lookup={c.id:c for c in p.cues};w._manual_text_baselines={c.id:c.text for c in p.cues}
    w.cue_model.set_project(p);w.timeline.set_project(p);w._populate_speakers();w.select_cue(cues[0].id)
    w.cue_controller.apply_selection_scope(SelectionScope.explicit([c.id for c in cues[:21]],cues[0].id))
    w.style_scope.setCurrentIndex(w.style_scope.findData('selected'));w.style_layer.setCurrentIndex(w.style_layer.findData('original'))
    w.undo_stack.clear();APP.processEvents()
    yield w
    w.close_page();w.deleteLater();APP.processEvents()


def values(page,layer='original'):
    return {c.id:copy.deepcopy(resolved_values(page.project,c,layer)) for c in page.project.cues}


def expected(page,scope):
    if scope=='current':return {'stable-0'}
    if scope=='selected':return {'stable-'+str(i) for i in range(21)}
    if scope=='speaker':return {c.id for c in page.project.cues if c.speaker_id=='A'}
    return {c.id for c in page.project.cues}


@pytest.mark.parametrize('scope',['current','selected','speaker','all'])
def test_numeric_position_follows_top_scope_and_preserves_other_layer(page,scope):
    page.style_scope.setCurrentIndex(page.style_scope.findData(scope))
    panel=page.caption_transform_panel;panel.refresh()
    before=values(page);translation=values(page,'translation')
    panel.edit('position_x',20.);panel.finish_field('position_x')
    after=values(page)
    for cue_id,old in before.items():
        target=dict(old)
        if cue_id in expected(page,scope):target['position_x']=384.
        assert after[cue_id]==target,(scope,cue_id)
    assert values(page,'translation')==translation
    assert page.style_scope.currentData()==scope
    page.undo_stack.undo();assert values(page)==before


def test_canvas_drag_uses_common_delta_across_21_and_one_undo(page):
    before=values(page);translation=values(page,'translation');count=page.undo_stack.count()
    page._position_overlay_interaction_started()
    page._position_overlay_moved(564,652)
    page._position_overlay_committed(564,652)
    after=values(page)
    for cue_id,old in before.items():
        target=dict(old)
        if cue_id in expected(page,'selected'):
            target.update(position_x=old['position_x']+64,position_y=old['position_y']-48)
        assert after[cue_id]==target,cue_id
    assert values(page,'translation')==translation
    assert page.undo_stack.count()==count+1
    assert len(page.selected_cue_ids())==21
    page.undo_stack.undo();assert values(page)==before
    page.undo_stack.redo();assert values(page)==after


def test_preset_geometry_reaches_existing_language_overrides_without_touching_translation(page,monkeypatch):
    before=values(page);translation=values(page,'translation')
    patch={'id':'scope-preset','name':'范围预设','font_size':63.,'position_x':280.,'position_y':430.,'scale_x':125.,'scale_y':135.}
    monkeypatch.setattr(StylePresetStore,'load_patch',lambda *_:patch)
    page.style_apply_geometry.setChecked(True)
    page._apply_style(replace_preset=True)
    after=values(page)
    for cue_id,old in before.items():
        if cue_id in expected(page,'selected'):
            assert after[cue_id]['position_x']==280 and after[cue_id]['position_y']==430,cue_id
            assert after[cue_id]['scale_x']==125 and after[cue_id]['scale_y']==135,cue_id
        else:assert after[cue_id]==old
    assert values(page,'translation')==translation


def test_empty_selected_scope_never_falls_back_to_primary(page):
    page.selection_model.set_scope(SelectionScope.empty())
    page.cue_table.selectionModel().clearSelection()
    page.style_scope.setCurrentIndex(page.style_scope.findData('selected'))
    page.session.selected_cue_id='stable-0'
    assert page._style_target_ids()==[]
    assert page.caption_transform_panel.targets()==[]


@pytest.mark.parametrize('layer',['original','translation','group'])
def test_numeric_scale_preserves_ratios_and_other_properties(page,layer):
    page.style_layer.setCurrentIndex(page.style_layer.findData(layer))
    old={k:values(page,k) for k in ('original','translation')}
    panel=page.caption_transform_panel;panel.refresh();panel.edit('scale_x',125.);panel.finish_field('scale_x')
    for language in ('original','translation'):
        after=values(page,language)
        for key,before in old[language].items():
            if key not in expected(page,'selected') or layer not in (language,'group'):
                assert after[key]==before;continue
            if layer=='group':
                owner=old['original'][key];factor=125/owner['scale_x']
                assert after[key]['scale_x']==pytest.approx(before['scale_x']*factor)
                assert after[key]['scale_y']==pytest.approx(before['scale_y']*factor)
                assert after[key]['position_y']==pytest.approx(owner['position_y']+(before['position_y']-owner['position_y'])*factor)
            else:
                assert after[key]['scale_x']==125.
                assert after[key]['scale_y']==pytest.approx(before['scale_y']*125/before['scale_x'])
                assert after[key]['position_x']==before['position_x']
            assert after[key]['rotation']==before['rotation']


def test_linked_canvas_drag_keeps_bilingual_gap(page):
    page.style_layer.setCurrentIndex(page.style_layer.findData('group'))
    old={k:values(page,k) for k in ('original','translation')}
    page._position_overlay_interaction_started();page._position_overlay_moved(564,652);page._position_overlay_committed(564,652)
    for layer in ('original','translation'):
        after=values(page,layer)
        for key,before in old[layer].items():
            shift=64 if key in expected(page,'selected') else 0
            assert after[key]['position_x']==before['position_x']+shift
            assert after[key]['position_y']==before['position_y']+(-48 if shift else 0)


def test_canvas_resize_uses_same_ratio_across_different_scales(page):
    old=values(page);other=values(page,'translation')
    page.position_overlay._origin_font_size=old['stable-0']['font_size']
    page._position_overlay_interaction_started()
    page._position_overlay_font_preview(old['stable-0']['font_size']*1.5)
    page._position_overlay_font_committed(old['stable-0']['font_size']*1.5)
    after=values(page)
    for key,before in old.items():
        ratio=1.5 if key in expected(page,'selected') else 1
        assert after[key]['scale_x']==pytest.approx(before['scale_x']*ratio)
        assert after[key]['scale_y']==pytest.approx(before['scale_y']*ratio)
    assert values(page,'translation')==other


def test_scope_change_cancels_pending_canvas_and_late_release(page):
    old=values(page);count=page.undo_stack.count()
    page._position_overlay_interaction_started();page._position_overlay_moved(650,650)
    page.style_scope.setCurrentIndex(page.style_scope.findData('all'))
    page._position_overlay_committed(650,650)
    assert values(page)==old and page.undo_stack.count()==count
    page._position_overlay_interaction_started();page._position_overlay_moved(550,650);page._position_overlay_committed(550,650)
    assert all(v['position_x']==old[k]['position_x']+50 for k,v in values(page).items())


def test_locked_items_are_excluded_with_actual_count_feedback(page,monkeypatch):
    messages=[];monkeypatch.setattr(page,'_show_studio_hint',messages.append)
    page.project.studio_state['locked_cue_ids']=['stable-4'];page.timeline.locked_speakers={'B'}
    old=values(page);panel=page.caption_transform_panel;panel.refresh();panel.edit('position_x',20.);panel.finish_field('position_x')
    after=values(page)
    assert sum(after[k]!=old[k] for k in old)==10
    assert any('10' in s and '11' in s and '锁定' in s for s in messages)


@pytest.mark.parametrize('layer',['original','translation'])
def test_preset_without_geometry_preserves_each_layout_and_other_language(page,monkeypatch,layer):
    old={k:values(page,k) for k in ('original','translation')}
    patch={'id':'without-geometry','name':'不带位置','font_size':63.,'position_x':280.,'position_y':430.,'scale_x':125.,'scale_y':135.}
    monkeypatch.setattr(StylePresetStore,'load_patch',lambda *_:patch)
    page.style_layer.setCurrentIndex(page.style_layer.findData(layer));page.style_apply_geometry.setChecked(False)
    page._apply_style(replace_preset=True)
    for language in ('original','translation'):
        after=values(page,language)
        for key,before in old[language].items():
            if language!=layer or key not in expected(page,'selected'):assert after[key]==before;continue
            for field in ('position_x','position_y','scale_x','scale_y','rotation','anchor_x','anchor_y'):
                assert after[key][field]==before[field]
            assert after[key]['font_size']==63.


def test_batch_geometry_roundtrip_and_export_use_actual_data(page,tmp_path):
    from twobyteasr.projects.studio_project import save_project,load_project
    from twobyteasr.rendering.ass_compiler import compile_ass
    page._position_overlay_interaction_started()
    page._position_overlay_moved(564,652);page._position_overlay_committed(564,652)
    final=values(page)
    restored=load_project(save_project(page.project,tmp_path/'batch.2byteproj'))
    for cue in restored.cues:
        assert resolved_values(restored,cue,'original')==final[cue.id]
    original=compile_ass(page.project);reopened=compile_ass(restored)
    assert original==reopened
    # Explicit positions from several time points must reach exported events.
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    for index in (0,20):
        snapshot=build_visual_cue_snapshot(restored,restored.cues[index].id)
        assert snapshot.position_x==final[restored.cues[index].id]['position_x']
        assert snapshot.position_y==final[restored.cues[index].id]['position_y']
    assert '\\pos(' in original  # ASS's line-box/font compensation has its own contract.


def test_sparse_preset_preserves_unedited_explicit_layer_face(page):
    from twobyteasr.caption_style.scoped_preset import preset_command
    from twobyteasr.caption_style.scoped_style import effective_layer_style
    page.project.styles.append(SubtitleStyle('private-layer','Layer',font_family='Arial',primary_color='#FF224466',font_size=42))
    cue=page.project.cues[0];cue.transform['language_layers']['original']['style_id']='private-layer'
    before=effective_layer_style(page.project,cue,'original')
    page.undo_stack.push(preset_command(page.project,[cue.id],{'id':'one-field','name':'一个属性','outline_width':4.},layer='original'))
    after=effective_layer_style(page.project,cue,'original')
    assert after.font_family==before.font_family and after.primary_color==before.primary_color
    assert after.outline_width==4. and cue.transform['language_layers']['original']['style_id']=='private-layer'


def test_mouse_preview_is_published_inside_the_same_paused_clock_sample(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin
    calls=[]
    scene=SimpleNamespace(present=lambda cues,ms:calls.append((cues,ms)) or True)
    p=SimpleNamespace(project=object(),isVisible=lambda:True,_caption_scene=scene,
        _caption_playhead_sample={},_caption_tick_time_ms=1200,_caption_transform_preview_serial=0,
        _revision_store=SimpleNamespace(render=SimpleNamespace(visual_revision=1,mapping_revision=1)),
        _caption_sample_ms=lambda:1200)
    monkeypatch.setattr('twobyteasr.rendering.caption_scene.active_cues',lambda *_:['visible-caption'])
    present=StudioAdvancedFlowMixin._present_caption_scene
    present(p);present(p);assert len(calls)==1
    p._caption_transform_preview_serial+=1;present(p)
    assert len(calls)==2  # A mouse change does not wait for a media-clock tick.
