"""Production style controls preserve persisted anchors and exact edit scope."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, SubtitleStyle
from twobyteasr.caption_style.subtitle_stacking import initialize_project_layout
from twobyteasr.caption_style.style_resolution import resolve_cue_visual


def _page(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    page=SubtitleStudioPage()
    page.project=SubtitleProject(media=StudioMedia(str(tmp_path/'missing.mp4'),duration_ms=5000),
        speakers=[StudioSpeaker('S01'),StudioSpeaker('S02')],
        styles=[SubtitleStyle('default','Default',font_size=60,shadow=0)],
        cues=[StudioCue('a',0,2000,'第一条',speaker_id='S01'),
              StudioCue('b',2400,3200,'第二条',speaker_id='S02'),
              StudioCue('c',3500,4500,'第三条',speaker_id='S01')])
    page.project_path=tmp_path/'layout-controls.2byteproj'
    page._cue_lookup={c.id:c for c in page.project.cues}
    page._manual_text_baselines={c.id:c.text for c in page.project.cues}
    page.cue_model.set_project(page.project);page.timeline.set_project(page.project)
    page._populate_speakers();page.select_cue('a')
    page.undo_stack.clear()
    app.processEvents()
    return app,page


def _finish(page):
    page.close_page();page.deleteLater()
    QApplication.instance().processEvents()


def positions(page):
    return {c.id:(resolve_cue_visual(page.project,c).style.position_x,
                  resolve_cue_visual(page.project,c).style.position_y) for c in page.project.cues}


def arrange(page):
    page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
    page.project.cues[1].start_ms = 500
    initialize_project_layout(page.project)
    page._changed()
    page.select_cue('a')
    page._load_style_inspector()
    page.undo_stack.clear()


def test_numeric_position_is_final_and_only_current_scope_changes(tmp_path,monkeypatch):
    app,page = _page(tmp_path,monkeypatch)
    try:
        arrange(page)
        old = positions(page)
        old_peer_style = asdict(resolve_cue_visual(page.project, page.project.cues[1]).style)
        page.style_position_y.setValue(740)
        page._commit_style_now()
        assert positions(page)['a'][1] == 740
        assert positions(page)['b'] == old['b']
        assert positions(page)['c'] == old['c']
        assert asdict(resolve_cue_visual(page.project, page.project.cues[1]).style) == old_peer_style
        assert page.project.cues[0].transform['position_y'] == 740
        page.undo_stack.undo()
        assert positions(page) == old
        page.undo_stack.redo()
        assert positions(page)['a'][1] == 740
        page.select_cue('b');page.select_cue('a')
        assert page.style_position_y.value() == 740
    finally:
        _finish(page)


def test_speaker_position_and_later_font_edit_preserve_final_anchors(tmp_path,monkeypatch):
    app,page = _page(tmp_path,monkeypatch)
    try:
        arrange(page)
        page.style_scope.setCurrentIndex(page.style_scope.findData('speaker'))
        old_other = positions(page)['b']
        page.style_position_y.setValue(720)
        page._commit_style_now()
        assert positions(page)['a'][1] == positions(page)['c'][1] == 720
        assert positions(page)['b'] == old_other
        before_font = positions(page)
        page.style_font_size.setValue(77)
        page._commit_style_now()
        assert positions(page) == before_font
        page._load_style_inspector()
        assert page.style_position_y.value() == 720
    finally:
        _finish(page)


def test_nonposition_batch_edits_do_not_collapse_initial_rows(tmp_path,monkeypatch):
    app,page = _page(tmp_path,monkeypatch)
    try:
        arrange(page)
        old = positions(page)
        page.style_scope.setCurrentIndex(page.style_scope.findData('all'))
        before_font = positions(page)
        page.style_font_size.setValue(82)
        page._commit_style_now()
        assert positions(page) == before_font == old
    finally:
        _finish(page)


def _shared_remotion_page(tmp_path, monkeypatch):
    """Real GE user-style records shared across speakers; no renderer work."""
    app, page = _page(tmp_path, monkeypatch)
    for name in ('_queue_advanced_preview', 'ensure_active_subtitle_renderer',
                 '_activate_selected_advanced_if_needed', '_revoke_advanced_preview'):
        monkeypatch.setattr(page, name, lambda *_a, **_k: None)
    payload = json.loads((Path(__file__).parent/'fixtures/ge_shared_remotion_style.json').read_text('utf-8-sig'))
    shared = SubtitleStyle(**payload['style'])
    page.project.styles.append(shared)
    page.project.style_recipes[shared.id] = deepcopy(payload['recipe'])
    for cue in page.project.cues:
        cue.style_id = cue.base_preset_id = shared.id
    page._refresh_style_presets()
    page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
    page._changed();page.select_cue('a');page._load_style_inspector()
    page.undo_stack.clear();app.processEvents()
    return app, page, shared.id


def _enter_y(page, value):
    line = page.style_position_y.lineEdit();line.setFocus()
    QTest.keyClick(line, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(line, str(value));QTest.keyClick(line, Qt.Key_Return)
    QApplication.instance().processEvents()


def test_real_shared_remotion_current_position_keeps_peer_style_recipe_and_undo(tmp_path, monkeypatch):
    app, page, original_id = _shared_remotion_page(tmp_path, monkeypatch)
    try:
        before = deepcopy(page.project.to_dict())
        old_positions = positions(page)
        old_peer = asdict(resolve_cue_visual(page.project, page.project.cues[1]).style)
        _enter_y(page, 944)
        assert positions(page)['a'] == (938, 944)
        assert all(positions(page)[key] == old_positions[key] for key in ('b', 'c'))
        assert asdict(resolve_cue_visual(page.project, page.project.cues[1]).style) == old_peer
        assert page.project.style_recipes[original_id] == before['style_recipes'][original_id]
        assert next(asdict(s) for s in page.project.styles if s.id == original_id) == next(
            s for s in before['styles'] if s['id'] == original_id)
        selected = page.project.cues[0]
        # 2026-10-24 (Codex scoped style): a position-only edit lives on the cue's transform and may
        # keep the shared style id; what matters is that the cue still draws the rich recipe.
        from twobyteasr.caption_style.style_resolution import recipe_for_cue
        assert recipe_for_cue(page.project.style_recipes, selected)['visualGraph']['motionGraph'] == before[
            'style_recipes'][original_id]['visualGraph']['motionGraph']
        assert page.undo_stack.count() == 1
        page.undo_stack.undo()
        assert positions(page) == old_positions
        restored = page.project.to_dict()
        # Appearance generations deliberately advance on undo to reject stale
        # background frames; the authoritative presentation must be restored.
        for value in (restored, before):
            for cue in value['cues']:
                cue.pop('appearance_generation', None)
        assert restored == before
        page.undo_stack.redo()
        page.style_font_size.setValue(98);page._commit_style_now()
        assert positions(page)['a'] == (938, 944)
        assert positions(page)['b'] == old_positions['b']
        assert resolve_cue_visual(page.project, page.project.cues[1]).style.font_size == 90
        assert page.project.style_recipes[original_id] == before['style_recipes'][original_id]
    finally:
        _finish(page)


def test_real_shared_remotion_speaker_position_keeps_other_speaker_and_rich_recipe(tmp_path, monkeypatch):
    app, page, original_id = _shared_remotion_page(tmp_path, monkeypatch)
    try:
        old_recipe = deepcopy(page.project.style_recipes[original_id])
        old_peer = deepcopy(page.project.cues[1])
        old_peer_style = asdict(resolve_cue_visual(page.project, old_peer).style)
        page.style_scope.setCurrentIndex(page.style_scope.findData('speaker'))
        page.undo_stack.clear()
        _enter_y(page, 944)
        assert positions(page)['a'] == positions(page)['c'] == (938, 944)
        assert asdict(resolve_cue_visual(page.project, page.project.cues[1]).style) == old_peer_style
        assert page.project.cues[1] == old_peer
        assert page.project.style_recipes[original_id] == old_recipe
        for cue in (page.project.cues[0], page.project.cues[2]):
            recipe = page.project.style_recipes[cue.style_id]
            assert recipe['visualGraph']['motionGraph'] == old_recipe['visualGraph']['motionGraph']
            assert recipe['outline']['shadow'] == old_recipe['outline']['shadow']
        before_font = positions(page)
        page.style_font_size.setValue(98);page._commit_style_now()
        assert positions(page) == before_font
        assert resolve_cue_visual(page.project, page.project.cues[1]).style.font_size == 90
        assert page.project.style_recipes[original_id] == old_recipe
    finally:
        _finish(page)
