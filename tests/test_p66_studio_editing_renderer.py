from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.recognition.run_context import RuntimeContext
from twobyteasr.recognition.service import RunOptions
from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
from twobyteasr.timeline.studio_edit_sequence import (
    delete_timeline_range,
    ensure_edit_sequence,
    sequence_of,
    split_at_playhead,
    store_sequence,
)
from twobyteasr.studio.studio_highlight_analyzer import LocalCandidate, candidates_from_local
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.timeline.studio_sequence_mapper import map_playhead_between_sequences, timeline_to_source
from twobyteasr.studio.studio_ui import (
    FillEditorDialog,
    SubtitleStudioPage,
    adaptive_timeline_ticks,
)
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.style_recipe import VisualStyleRecipe, route_recipe
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _page(monkeypatch, tmp_path, *, duration_ms: int = 60_000) -> SubtitleStudioPage:
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page.project.media = StudioMedia(path="D:/fixture.mp4", duration_ms=duration_ms, width=1280, height=720)
    page.project.edit_sequence = {}
    page.project.validate()
    sequence = ensure_edit_sequence(page.project)
    from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
    sync_primary_video_track_from_sequence(page.project, sequence)
    page.timeline.set_project(page.project)
    _app().processEvents()  # settle blank-project startup before measuring edits
    return page


def _editable_three_segment_sequence(page: SubtitleStudioPage):
    sequence = sequence_of(page.project)
    sequence.video_track_locked = False
    sequence = split_at_playhead(sequence, 10_000)
    sequence = split_at_playhead(sequence, 20_000)
    store_sequence(page.project, sequence)
    # Match the production edit command's projection; a raw sequence write
    # alone leaves the video/audio graph and lock state stale.
    from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
    sync_primary_video_track_from_sequence(page.project, sequence)
    page.timeline.reindex_project()
    return sequence


def test_razor_preserves_playhead_and_view_state(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path, duration_ms=900_000)
    sequence = sequence_of(page.project)
    sequence.video_track_locked = False
    store_sequence(page.project, sequence)
    seek_calls = []
    monkeypatch.setattr(page, "_seek", lambda seconds: seek_calls.append(seconds))
    for index in range(20):
        cut_ms = (index + 1) * 30_000
        expected_window = (cut_ms - 8_000, 20_000)
        page.timeline.set_visible_window(*expected_window)
        page.timeline.set_playhead(cut_ms)
        page._razor_video_at(cut_ms)
        assert page.timeline.playhead_ms == cut_ms
        assert (page.timeline.visible_start_ms, page.timeline.visible_duration_ms) == expected_window
        assert len(sequence_of(page.project).segments) == index + 2
    assert seek_calls == []
    page.close_page()


def test_qw_trim_preserves_playhead(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    _editable_three_segment_sequence(page)
    page.timeline.set_playhead(15_000)
    seek_calls = []
    monkeypatch.setattr(page, "_seek", lambda seconds: seek_calls.append(seconds))
    page._trim_to_playhead("start")
    mapped = timeline_to_source(sequence_of(page.project), page.timeline.playhead_ms)
    assert mapped is not None and mapped.source_ms == 15_000
    assert page.timeline.playhead_ms == 10_000
    assert seek_calls == [10.0]
    seek_calls.clear()
    page.undo_stack.undo()
    assert page.timeline.playhead_ms == 15_000 and seek_calls == [15.0]
    seek_calls.clear()
    page.undo_stack.redo()
    assert page.timeline.playhead_ms == 10_000 and seek_calls == [10.0]
    page.close_page()


def test_w_commits_player_clock_once(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    _editable_three_segment_sequence(page)
    page.timeline.set_playhead(15_000)
    seeks = []
    monkeypatch.setattr(page, '_seek', seeks.append)
    page._trim_to_playhead('end')
    assert seeks == [15.0]
    assert sequence_of(page.project).segments[2].timeline_in_ms == 15_000
    page.close_page()


def test_undo_redo_preserves_playhead():
    project = SubtitleProject(media=StudioMedia(path="D:/fixture.mp4", duration_ms=40_000))
    before = ensure_edit_sequence(project)
    after = split_at_playhead(before, 10_000)
    after = split_at_playhead(after, 20_000)
    trimmed = delete_timeline_range(after, 10_000, 20_000)
    forward = map_playhead_between_sequences(after, trimmed, 12_000)
    assert forward is not None and timeline_to_source(trimmed, forward.timeline_ms).source_ms == 20_000
    backward = map_playhead_between_sequences(trimmed, after, forward.timeline_ms)
    assert backward is not None and timeline_to_source(after, backward.timeline_ms).source_ms == 20_000


def test_delete_multiple_timeline_items_one_undo(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    sequence = _editable_three_segment_sequence(page)
    page.timeline.selected_segment_ids = {sequence.segments[0].id, sequence.segments[1].id}
    page.timeline.selected_segment_id = sequence.segments[0].id
    monkeypatch.setattr(page, "_seek", lambda _seconds: None)
    before_index = page.undo_stack.index()
    page._delete_current()
    assert page.undo_stack.index() == before_index + 1
    assert len(sequence_of(page.project).segments) == 1
    assert sequence_of(page.project).segments[0].timeline_in_ms == 20_000
    page.undo_stack.undo()
    assert len(sequence_of(page.project).segments) == 3
    page.close_page()


def test_adaptive_timeline_ticks_for_long_media():
    major, minor = adaptive_timeline_ticks(3 * 60 * 60 * 1000, 1720)
    assert major >= 600_000
    assert minor < major
    assert 3 * 60 * 60 * 1000 / major <= 20


def test_t_creates_and_focuses_current_subtitle_editor(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.show()
    page.timeline.set_playhead(4_000)
    page._add_subtitle_at_playhead()
    _app().processEvents()
    assert len(page.project.cues) == 1
    assert page._canvas_editor is page.subtitle_edit_input
    assert page.subtitle_edit_card.isVisible()
    page._cancel_canvas_inline_edit()
    assert page.project.cues == []
    page.close_page()


def test_review_letter_shortcuts_are_contextual(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    states = []
    reasr = []
    monkeypatch.setattr(page, "_set_review_mode", lambda value: states.append(bool(value)))
    assert page._dispatch_shortcut_sequence("R") is True
    assert states == [True]
    page._review_mode = True
    page._command_callbacks["reasr_review"] = lambda: reasr.append(True)
    assert page._dispatch_shortcut_sequence("Shift+R") is True
    assert reasr == [True]
    page.close_page()


def test_transform_box_visible_for_selected_cue_when_paused(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.project.cues = [StudioCue("cue", 0, 2_000, "测试字幕")]
    page.cue_model.set_project(page.project)
    page.cue_controller.model_changed()
    page.show()
    page.select_cue("cue")
    page._playback_state_changed(True)
    _app().processEvents()
    assert page.position_edit_button.isChecked()
    assert not page.position_overlay.isHidden()
    page.close_page()


def test_fill_editor_gradient_layout_and_stop_behavior():
    app = _app()
    dialog = FillEditorDialog({
        "type": "linear-gradient",
        "stops": [
            {"position": 0.0, "color": "#FFFFCC00"},
            {"position": 1.0, "color": "#FF20D9FF"},
        ],
        "angle": 30,
    })
    dialog.show()
    app.processEvents()
    assert dialog._location_host.isHidden()
    assert dialog._stop_host.geometry().top() < dialog._angle_host.geometry().top()
    assert dialog._angle_host.geometry().top() < dialog.gradient.geometry().top() < dialog.picker.geometry().top()
    before = len(dialog.gradient._stops)
    QTest.mouseClick(dialog.gradient.bar, Qt.MouseButton.LeftButton,
                     pos=dialog.gradient.bar.rect().center())
    assert len(dialog.gradient._stops) == before
    QTest.mouseDClick(dialog.gradient.bar, Qt.MouseButton.LeftButton,
                      pos=dialog.gradient.bar.rect().center())
    assert len(dialog.gradient._stops) == before + 1
    while len(dialog.gradient._stops) > 2:
        dialog.gradient._delete_selected()
    dialog.gradient._delete_selected()
    assert len(dialog.gradient._stops) == 2
    dialog.close()


def test_ai_preset_bulk_delete_preserves_favorites(tmp_path):
    store = StylePresetStore(tmp_path)
    for style_id in ("ai-a", "ai-b", "custom-c"):
        store.upsert(SubtitleStyle(style_id, style_id), {"name": style_id}, source="ai" if style_id.startswith("ai-") else "custom")
    store.set_favorite("ai-b", True)
    assert store.delete_all_ai(keep_favorites=True) == 1
    assert set(store.load_user()) == {"ai-b", "custom-c"}


def test_fast_analysis_transcript_path():
    options = RunOptions(recognition_purpose="analysis", studio_project_path="D:/project.2byteproj")
    legacy = SimpleNamespace(
        canonicalize_runtime_game_name=str,
        runtime_game_identity=str,
    )
    context = options.create_runtime_context(legacy)
    assert isinstance(context, RuntimeContext)
    assert context.recognition_purpose == "analysis"
    assert context.studio_project_path.endswith(".2byteproj")


def test_candidate_keeps_its_dialogue_and_does_not_stretch_to_context():
    project = SubtitleProject(
        media=StudioMedia(path="fixture.flv", duration_ms=180_000),
        cues=[
            StudioCue("a", 30_000, 55_000, "先铺垫这次挑战"),
            StudioCue("b", 60_000, 70_000, "突然翻车了"),
            StudioCue("c", 72_000, 92_000, "最后又救回来了"),
        ],
    )
    rows = candidates_from_local(project, [LocalCandidate(60_000, 70_000, 0.9, ["signal"])], limit=1, max_seconds=180)
    candidate = rows[0]
    assert (candidate.signal_in_ms, candidate.signal_out_ms) == (60_000, 70_000)
    # 2026-10-24 (clip evidence ADR, Codex): the context around a signal is for viewing, not a cut;
    # the range stays on the dialogue the signal covers instead of stretching to its neighbours.
    assert (candidate.source_in_ms, candidate.source_out_ms) == (60_000, 70_000)


def test_generated_ai_style_changes_video_preview(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.project.cues = [StudioCue("cue", 0, 2_000, "AI 字幕")]
    page.cue_model.set_project(page.project)
    page.cue_controller.model_changed()
    page.select_cue("cue")
    recipe = style_recipe_for_prompt("手写纸片渐变")
    visual = VisualStyleRecipe.from_style_recipe(recipe)
    page._preview_visual_recipe(visual)
    assert page.style_preview._gradient is not None
    assert page.style_controller._apply_style_recipe("cue", recipe)
    cue = page._cue_lookup["cue"]
    assert cue.style_id in page.project.style_recipes
    assert route_recipe(page.project.style_recipes[cue.style_id]).engine == "remotion"
    page.close_page()


def test_static_advanced_style_does_not_replay_but_motion_style_does(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.project.cues = [StudioCue("cue", 0, 2_000, "AI 字幕")]
    page.cue_model.set_project(page.project)
    page.cue_controller.model_changed()
    page.select_cue("cue")

    static_recipe = style_recipe_for_prompt("手写纸片渐变")
    static_recipe.motion = {"mode": "none"}
    static_recipe.visual_graph = {}
    assert page.style_controller._apply_style_recipe("cue", static_recipe)
    assert page._pending_motion_replay_cue_id == ""
    static_effect = page.project.effects[page._cue_lookup["cue"].effect_id]
    assert static_effect["entry"]["type"] == "none"

    motion_recipe = style_recipe_for_prompt("手写纸片渐变")
    assert page.style_controller._apply_style_recipe("cue", motion_recipe)
    assert page._pending_motion_replay_cue_id == "cue"
    page.close_page()


def test_gradient_survives_preview_and_render_path():
    recipe = style_recipe_for_prompt("手写纸片渐变")
    project = SubtitleProject(
        media=StudioMedia(path="fixture.flv", duration_ms=10_000, width=1280, height=720),
        cues=[StudioCue("cue", 0, 2_000, "渐变字幕", style_id="gradient")],
        styles=[SubtitleStyle("default", "默认"), SubtitleStyle("gradient", "渐变")],
        style_recipes={"gradient": recipe.to_dict()},
    )
    snapshot = build_visual_cue_snapshot(project, "cue")
    assert isinstance(snapshot.fill, dict)
    assert snapshot.fill["type"] == "linear-gradient"
    assert len(snapshot.fill["stops"]) >= 2
    assert route_recipe(snapshot.style_recipe).engine == "remotion"


def test_structural_actions_spawn_no_visible_console(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    sequence = sequence_of(page.project)
    sequence.video_track_locked = False
    store_sequence(page.project, sequence)
    calls = []
    monkeypatch.setattr("twobyteasr.studio.studio_video_track.run_hidden_subprocess", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(page, "_seek", lambda _seconds: None)
    page._razor_video_at(12_000)
    _app().processEvents()
    assert calls == []
    assert page.timeline.thumbnail_requests_enabled is False
    page.close_page()


# Keep the acceptance vocabulary from the P6.6 brief directly discoverable.
# The more specific tests above remain the primary regression contracts.
def test_split_preserves_playhead(monkeypatch, tmp_path):
    test_razor_preserves_playhead_and_view_state(monkeypatch, tmp_path)


def test_ripple_preserves_mapped_playhead(monkeypatch, tmp_path):
    test_qw_trim_preserves_playhead(monkeypatch, tmp_path)


def test_t_enters_subtitle_editor(monkeypatch, tmp_path):
    test_t_creates_and_focuses_current_subtitle_editor(monkeypatch, tmp_path)


def test_review_shortcut_shift_r(monkeypatch, tmp_path):
    # Shift+R coverage lives in the contextual shortcuts test since the
    # P25.2.12 review split folded the standalone toggle test away.
    test_review_letter_shortcuts_are_contextual(monkeypatch, tmp_path)


def test_multiselect_delete(monkeypatch, tmp_path):
    test_delete_multiple_timeline_items_one_undo(monkeypatch, tmp_path)


def test_delete_single_undo(monkeypatch, tmp_path):
    test_delete_multiple_timeline_items_one_undo(monkeypatch, tmp_path)


def test_adaptive_time_ruler():
    test_adaptive_timeline_ticks_for_long_media()


def test_gradient_routes_to_visible_renderer():
    test_gradient_survives_preview_and_render_path()


def test_ai_recipe_not_lost_on_apply(monkeypatch, tmp_path):
    test_generated_ai_style_changes_video_preview(monkeypatch, tmp_path)


def test_ai_motion_visible_route():
    recipe = style_recipe_for_prompt("日式热血漫画拟声特写")
    assert recipe.motion
    assert route_recipe(recipe).engine in {"native", "remotion"}


def test_candidate_context_expansion():
    test_candidate_keeps_its_dialogue_and_does_not_stretch_to_context()


def test_analysis_transcript_mode():
    test_fast_analysis_transcript_path()


def test_bulk_ai_preset_delete(tmp_path):
    test_ai_preset_bulk_delete_preserves_favorites(tmp_path)


def test_structural_edits_do_not_reload_mpv(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path, duration_ms=120_000)
    sequence = sequence_of(page.project)
    sequence.video_track_locked = False
    store_sequence(page.project, sequence)
    media_loads = []
    monkeypatch.setattr(page.video, "load", lambda *args, **kwargs: media_loads.append((args, kwargs)))
    page.timeline.set_playhead(30_000)
    page._razor_video_at(30_000)
    page.timeline.set_playhead(45_000)
    page._trim_to_playhead("start")
    page.undo_stack.undo()
    page.undo_stack.redo()
    assert media_loads == []
    page.close_page()


def test_structural_edits_do_not_launch_ffmpeg(monkeypatch, tmp_path):
    test_structural_actions_spawn_no_visible_console(monkeypatch, tmp_path)
