import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker
from twobyteasr.caption_style.studio_motion_browser import MotionBrowserDialog


def make_page(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.project = SubtitleProject(media=StudioMedia(str(tmp_path/'missing.mp4'), duration_ms=6000),
        speakers=[StudioSpeaker('S01'), StudioSpeaker('S02')],
        cues=[StudioCue('a', 0, 2000, '你好世界', speaker_id='S01'),
              StudioCue('b', 2200, 4000, '第二句', speaker_id='S02'),
              StudioCue('c', 4200, 6000, '第三句', speaker_id='S01')])
    page.project_path = tmp_path/'motion.2byteproj'
    page._cue_lookup = {c.id: c for c in page.project.cues}
    page._manual_text_baselines = {c.id: c.text for c in page.project.cues}
    page.cue_model.set_project(page.project)
    page.timeline.set_project(page.project)
    page._populate_speakers()
    page.select_cue('a')
    page.undo_stack.clear()
    app.processEvents()
    return app, page


def close(page):
    page.close_page()
    page.deleteLater()
    QApplication.instance().processEvents()


def test_immediate_scope_apply_undo_and_hydration(tmp_path):
    app, page = make_page(tmp_path)
    try:
        page.motion_scope.setCurrentIndex(page.motion_scope.findData('speaker'))
        page.effect_preset.setCurrentIndex(page.effect_preset.findData('float_up'))
        page.motion_word_mode.setCurrentIndex(page.motion_word_mode.findData('word_reveal'))
        assert page.project.cues[0].effect_id != 'none'
        assert '2' in page.motion_apply.text()
        assert page.motion_apply.isHidden()
        assert page.project.cues[0].effect_id != 'none'
        assert page.project.cues[1].effect_id == 'none'
        assert page.project.cues[2].effect_id == page.project.cues[0].effect_id
        assert page.project.effects[page.project.cues[0].effect_id]['entry']['type'] == 'float_up'
        page.select_cue('b')
        assert page.motion_word_mode.currentData() == 'none'
        page.select_cue('a')
        assert page.motion_word_mode.currentData() == 'word_reveal'
        page.undo_stack.undo()
        assert page.project.effects[page.project.cues[0].effect_id]['entry']['type'] == 'float_up'
        page.undo_stack.undo()
        assert all(c.effect_id == 'none' for c in page.project.cues)
        page.undo_stack.redo()
        assert page.project.cues[0].effect_id != 'none'
    finally:
        close(page)


def test_library_real_entry_and_explicit_apply(tmp_path):
    app, page = make_page(tmp_path)
    observed = []
    def interact():
        dialog = app.activeModalWidget()
        observed.append(isinstance(dialog, MotionBrowserDialog))
        if isinstance(dialog, MotionBrowserDialog):
            dialog._select('soft_fade')
            observed.append(page.project.cues[0].effect_id == 'none')
            dialog.apply_button.click()
        elif dialog:
            dialog.reject()
    try:
        QTimer.singleShot(100, interact)
        page._open_motion_browser()
        assert observed == [True, True]
        assert page.project.effects[page.project.cues[0].effect_id]['entry']['type'] == 'soft_fade'
        assert page.project.cues[1].effect_id == 'none'
    finally:
        close(page)


def test_selected_scope_preserves_different_looks_and_appearance_edits(tmp_path):
    from PySide6.QtCore import QItemSelectionModel
    app, page = make_page(tmp_path)
    try:
        page.project.cues[2].appearance_override = {'font_size':73, 'color':'#FFFF0000'}
        page.motion_scope.setCurrentIndex(page.motion_scope.findData('selected'))
        model = page.cue_table.selectionModel()
        model.clearSelection()
        for row in (0,2):
            model.select(page.cue_model.index(row,0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        page.motion_word_mode.setCurrentIndex(page.motion_word_mode.findData('word_reveal'))
        page.motion_apply.click()
        ids = [c.effect_id for c in page.project.cues]
        assert ids[0] == ids[2] != ids[1]
        assert page.project.cues[2].appearance_override == {'font_size':73,'color':'#FFFF0000'}
        # Ordinary appearance application must not replace each cue's effect.
        page._apply_style()
        assert [c.effect_id for c in page.project.cues] == ids
    finally:
        close(page)


def test_saved_authored_motion_replaces_native_without_changing_words(tmp_path):
    from twobyteasr.caption_style.motion_library import MotionPreset
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    app, page = make_page(tmp_path)
    try:
        page._queue_advanced_preview = lambda *args, **kwargs: None
        page.effect_preset.setCurrentIndex(page.effect_preset.findData('soft_pop'))
        page.motion_word_mode.setCurrentIndex(page.motion_word_mode.findData('word_reveal'))
        page.motion_apply.click()
        preset = MotionPreset('saved','Saved',{'mode':'explicit','origin':'visual_graph','graph':{
            'durationMs':2000,'tracks':[{'target':'group','property':'y','keyframes':[
                {'timeMs':0,'value':80,'easing':'linear'}, {'timeMs':300,'value':0,'easing':'linear'}]}]}},system=False)
        page._apply_advanced_motion(preset)
        snapshot = build_visual_cue_snapshot(page.project,'a')
        assert snapshot.word_animation['mode'] == 'word_reveal'
        assert snapshot.style_recipe['visualGraph']['motionGraph']['tracks'][0]['property'] == 'y'
        saved, _ = page.style_controller._current_motion_for_library()
        assert saved['graph']['tracks'][0]['keyframes'][0]['value'] == 80
        assert page.project.cues[1].effect_id == 'none'
    finally:
        close(page)
