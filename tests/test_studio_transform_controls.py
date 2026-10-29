import copy
import pytest
from tests.test_motion_workflow_ui import make_page,close
from twobyteasr.caption_style.caption_layer_transform import resolved_values,transform_command
from twobyteasr.timeline.studio_edit_sequence import ensure_edit_sequence,sequence_of
from twobyteasr.timeline.studio_media_pool import update_video_clip_transform


def video_graph(page):
    from twobyteasr.projects.studio_project import MediaAsset,VideoTrack,VideoClip
    page.project.media.width=1920;page.project.media.height=1080
    page.project.media_pool=[MediaAsset('video',page.project.media.path,duration_ms=6000,
        video_metadata={'width':1920,'height':1080})]
    page.project.video_tracks=[VideoTrack('V1','V1',[VideoClip('clip','video',source_out_ms=6000,timeline_out_ms=6000)])]
    return page.project.video_tracks[0],page.project.video_tracks[0].clips[0]


def test_legacy_primary_lock_is_visible_and_rejected_then_unlocks(tmp_path):
    app,page=make_page(tmp_path)
    try:
        ensure_edit_sequence(page.project)
        track,clip=video_graph(page)
        # Old projects can carry the primary lock only in EditSequence.
        track.locked=False;sequence_of(page.project).video_track_locked=True
        page.timeline.selected_video_track_id=track.id;page.timeline.selected_video_clip_id=clip.id
        page._refresh_video_transform_panel()
        assert not page.video_position_x.isEnabled() and not page.video_scale_link.isEnabled()
        assert not page.video_unlock_button.isHidden()
        before=copy.deepcopy(vars(clip.transform))
        with pytest.raises(ValueError):update_video_clip_transform(page.project,track.id,clip.id,{'position_x':.1})
        assert vars(clip.transform)==before
        page._video_transform_committed(track.id,clip.id,{'position_x':.1})
        assert vars(clip.transform)==before
        page._unlock_selected_video_track()
        assert not sequence_of(page.project).video_track_locked and page.video_position_x.isEnabled()
    finally:close(page)


def test_video_link_updates_preview_before_commit_and_scrub_release_saves(tmp_path):
    app,page=make_page(tmp_path)
    try:
        ensure_edit_sequence(page.project)
        track,clip=video_graph(page)
        track.locked=False;sequence_of(page.project).video_track_locked=False
        clip.transform.scale_x=1.2;clip.transform.scale_y=.6
        page.timeline.selected_video_track_id=track.id;page.timeline.selected_video_clip_id=clip.id
        page._refresh_video_transform_panel()
        page.video_scale_x.setValue(180)
        assert page.video_scale_y.value()==90
        assert page._video_transform_preview_overrides[clip.id]['scale_y']==.9
        page.video_scale_x.scrubFinished.emit()
        current=page.project.video_tracks[0].clips[0]
        assert current.transform.scale_x==1.8 and current.transform.scale_y==.9
        page.video_scale_link.setChecked(False);page.video_scale_y.setValue(50);page.video_scale_y.editingFinished.emit()
        assert page.project.video_tracks[0].clips[0].transform.scale_x==1.8
        assert page.project.video_tracks[0].clips[0].transform.scale_y==.5
    finally:close(page)


def test_caption_numeric_hydration_and_language_switch_never_commit(tmp_path):
    app,page=make_page(tmp_path)
    try:
        page.project.generation_metadata['translations']={'a':'翻译甲','b':'翻译乙'}
        page.project.studio_state['bilingual']={'mode':'bilingual'}
        panel=page.caption_transform_panel;panel.refresh()
        before_translation=resolved_values(page.project,page.project.cues[0],'translation')
        panel.controls['position_x'].setValue(35)
        assert resolved_values(page.project,page.project.cues[0],'original')['position_x']==672.
        assert resolved_values(page.project,page.project.cues[0],'translation')==before_translation
        panel.language.setCurrentIndex(1);panel.controls['position_x'].setValue(70)
        count=page.undo_stack.count()
        for _ in range(3):panel.refresh()
        panel.language.setCurrentIndex(0);panel.language.setCurrentIndex(1)
        assert page.undo_stack.count()==count
        assert panel.controls['position_x'].value()==70.
        page.position_overlay._resize_handle='br'  # last completed corner gesture
        page.position_overlay._dragging=False
        panel.language.setCurrentIndex(0);panel.language.setCurrentIndex(1)
        assert page.position_overlay.text=='翻译甲'
        assert page.position_overlay.position_x==1344
        page.select_cue('b')
        assert resolved_values(page.project,page.project.cues[1],'translation')['position_x']!=1344.
    finally:close(page)


def test_saved_advanced_motion_can_target_translation_and_survives_reset_and_reopen(tmp_path):
    from twobyteasr.caption_style.motion_library import MotionPreset
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    from twobyteasr.projects.studio_project import load_project,save_project
    app,page=make_page(tmp_path)
    try:
        page.project.generation_metadata['translations']={'a':'翻译甲'}
        page.project.studio_state['bilingual']={'mode':'bilingual'}
        page.motion_language.setCurrentIndex(page.motion_language.findData('translation'))
        page._queue_advanced_preview=lambda *a,**k:None
        preset=MotionPreset('saved-layer','语言层测试',{'mode':'explicit','origin':'visual_graph','graph':{
            'durationMs':2000,'tracks':[{'target':'group','property':'y','keyframes':[
                {'timeMs':0,'value':80,'easing':'linear'},{'timeMs':300,'value':0,'easing':'linear'}]}]}},system=False)
        original_style=page.project.cues[0].style_id
        page._apply_advanced_motion(preset)
        original,translated=project_display_cues(page.project)[:2]
        assert original.style_id==original_style and translated.style_id!=original_style
        assert page.project.style_recipes[translated.style_id]['visualGraph']['motionGraph']['tracks']
        assert page.effect_preset.currentData()=='visual_graph'
        transform_command(page.project,['a'],'translation',{'position_x':1200.}).redo()
        transform_command(page.project,['a'],'translation',{},reset=True).redo()
        saved=load_project(save_project(page.project,tmp_path/'language-motion.2byteproj'))
        assert project_display_cues(saved)[1].style_id==translated.style_id
        assert translated.style_id in saved.style_recipes
    finally:close(page)


def test_saved_native_motion_respects_language_choice(tmp_path,monkeypatch):
    from twobyteasr.caption_style.motion_library import MotionPreset
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    from twobyteasr.caption_style import studio_style_controller
    from types import SimpleNamespace
    app,page=make_page(tmp_path)
    try:
        page.project.generation_metadata['translations']={'a':'翻译甲'}
        page.project.studio_state['bilingual']={'mode':'bilingual'}
        page.motion_language.setCurrentIndex(page.motion_language.findData('translation'))
        preset=MotionPreset('native-layer','整句动效',{'nativeEffect':{'entry':{'type':'float_up','duration':300}}},system=False)
        monkeypatch.setattr(studio_style_controller,'MotionPresetStore',lambda:SimpleNamespace(all=lambda:{preset.id:preset}))
        page._apply_motion_library_preset(preset.id)
        original,translated=project_display_cues(page.project)[:2]
        assert original.effect_id=='none' and translated.effect_id!='none'
        assert page.project.effects[translated.effect_id]['entry']['type']=='float_up'
    finally:close(page)


def test_multi_selection_shows_mixed_values_and_only_updates_edited_axis(tmp_path):
    from PySide6.QtCore import QItemSelectionModel
    app,page=make_page(tmp_path)
    try:
        transform_command(page.project,['a'],'original',{'position_x':100.,'rotation':12.}).redo()
        transform_command(page.project,['c'],'original',{'position_x':700.,'rotation':-7.}).redo()
        model=page.cue_table.selectionModel();model.clearSelection()
        for row in (0,2):model.select(page.cue_model.index(row,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        panel=page.caption_transform_panel;panel.refresh()
        assert len(panel.targets())==2
        assert 'position_x' in panel.mixed and panel.controls['position_x'].lineEdit().text()=='—'
        panel.controls['position_y'].setValue(45)
        a,c=[resolved_values(page.project,page.project.cues[i],'original') for i in (0,2)]
        assert (a['position_x'],c['position_x'],a['rotation'],c['rotation'])==(100.,700.,12.,-7.)
        assert a['position_y']==c['position_y']
        assert a['position_y']==pytest.approx(486.)
    finally:close(page)


def test_inspector_refresh_does_not_overwrite_held_canvas_resize(tmp_path):
    app,page=make_page(tmp_path)
    try:
        page.position_overlay.font_size=77.
        page.position_overlay._dragging=True
        page.style_controller._load_style_inspector()
        assert page.position_overlay.font_size==77.
        page.position_overlay._dragging=False
    finally:close(page)
