from __future__ import annotations

import copy
import json
import os
import time

import twobyteasr.studio.studio_ai_flow as studio_ai_flow
import twobyteasr.rendering.studio_live_canvas as studio_live_canvas
import twobyteasr.studio.studio_ui as studio_ui_module

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QFontDatabase, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.rendering.advanced_preview import AdvancedPreviewIdentity, AdvancedPreviewPhase, AdvancedPreviewStateMachine
from twobyteasr.rendering.advanced_renderer import (
    css_color_to_project,
    normalized_visual_snapshot,
    project_color_to_css,
)
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.caption_style.font_system import SystemFontEntry
from twobyteasr.system.processes import child_process_start_count
from twobyteasr.caption_design.studio_ai import (
    AIDesignSuggestion,
    request_style_design,
    style_recipe_for_prompt,
    visual_design_variants,
)
from twobyteasr.timeline.studio_edit_sequence import ensure_edit_sequence, sequence_of, store_sequence
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleStyle
from twobyteasr.studio.studio_ui import LazyFontComboBox, SubtitleStudioPage
from twobyteasr.caption_style.style_presets import BUILTIN_PRESETS
from twobyteasr.caption_style.style_recipe import FillSpec, VisualStyleRecipe, route_recipe
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.caption_design.visual_design_graph import comic_burst_graph, compile_live_scene, style_recipe_from_graph


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _page(monkeypatch, tmp_path, *, cue: bool = True) -> SubtitleStudioPage:
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page.project.media = StudioMedia(path="D:/fixture.mp4", duration_ms=60_000, width=1280, height=720)
    page.project.edit_sequence = {}
    page._media_ingest_state = "READY"
    sequence = ensure_edit_sequence(page.project)
    sequence.video_track_locked = False
    store_sequence(page.project, sequence)
    if cue:
        page.project.cues = [StudioCue("cue", 0, 2_000, "真实字幕", style_id="default")]
    page.cue_controller.model_changed()
    page.timeline.reindex_project()
    if cue:
        page.select_cue("cue")
    page._sync_video_empty_state()
    return page


class _FakeMpv:
    running = True

    def __init__(self):
        self.calls = []
        self.paused = True

    def clear_media(self):
        self.calls.append(("clear_media",))

    def load(self, path):
        self.calls.append(("load", str(path)))

    def set_paused(self, paused):
        self.paused = bool(paused)
        self.calls.append(("pause", self.paused))

    def get_property(self, name, default=None):
        return self.paused if name == "pause" else default

    def seek(self, seconds, *, accurate=True):
        self.calls.append(("seek", seconds, accurate))

    def frame_step(self, backwards=False):
        self.calls.append(("frame", backwards))

    def close(self):
        self.running = False


def _attach_fake_mpv(page: SubtitleStudioPage) -> _FakeMpv:
    controller = _FakeMpv()
    page.video.controller = controller
    page.video._media_attached = True
    page.video._media_path = page.project.media.path
    return controller


def _delete_only_segment(page: SubtitleStudioPage) -> None:
    segment = sequence_of(page.project).segments[0]
    page.timeline.selected_segment_id = segment.id
    page.timeline.selected_segment_ids = {segment.id}
    page._delete_selected_timeline_segments()


def test_interactive_actions_spawn_zero_processes(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    before = child_process_start_count()
    page._razor_video_at(10_000)
    page.undo_stack.undo()
    page.undo_stack.redo()
    page._add_subtitle_at_playhead()
    page._cancel_canvas_inline_edit()
    assert child_process_start_count() == before
    assert all(record["child_process_starts"] == 0 for record in page._interaction_runtime_audit.records)
    page.close_page()


def test_interactive_actions_create_zero_top_level_windows(monkeypatch, tmp_path):
    app = _app()
    page = _page(monkeypatch, tmp_path)
    page.show()
    app.processEvents()
    before = {(type(item).__name__, item.objectName()) for item in app.topLevelWidgets() if item.isVisible()}
    page._razor_video_at(12_000)
    page.undo_stack.undo()
    page._add_subtitle_at_playhead()
    page._cancel_canvas_inline_edit()
    app.processEvents()
    after = {(type(item).__name__, item.objectName()) for item in app.topLevelWidgets() if item.isVisible()}
    assert after == before
    assert not page.advanced_cue_overlay.isWindow()
    assert not page.position_overlay.isWindow()
    page.close_page()


def test_empty_sequence_clears_mpv_source(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    controller = _attach_fake_mpv(page)
    _delete_only_segment(page)
    assert sequence_of(page.project).empty_timeline
    assert ("clear_media",) in controller.calls
    assert page.video._media_attached is False
    assert page._empty_playback_state is True
    page.close_page()


def test_empty_sequence_cannot_resume_old_media(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    controller = _attach_fake_mpv(page)
    _delete_only_segment(page)
    calls = list(controller.calls)
    page._toggle_playback()
    page._seek(9.0)
    page._frame_step(False)
    assert controller.calls == calls
    assert not page.play_button.isEnabled()
    page.close_page()


def test_undo_empty_sequence_restores_media(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    controller = _attach_fake_mpv(page)
    _delete_only_segment(page)
    page.undo_stack.undo()
    assert not sequence_of(page.project).empty_timeline
    assert ("load", "D:/fixture.mp4") in controller.calls
    assert page.video._media_attached is True
    assert page._empty_playback_state is False
    page.close_page()


def test_t_creation_hides_transform_until_commit(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path, cue=False)
    page.show()
    page.position_edit_button.setChecked(True)
    page._add_subtitle_at_playhead()
    _app().processEvents()
    assert page.subtitle_edit_card.isVisible()
    assert page.position_overlay.isHidden()
    page.subtitle_edit_input.setPlainText("提交后的字幕")
    page._commit_canvas_inline_edit()
    _app().processEvents()
    assert page.subtitle_edit_card.isHidden()
    assert page.position_overlay.isVisible()
    page.close_page()


def test_transform_box_moves_actual_subtitle(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page._position_overlay_moved(444, 555)
    snapshot = page._ass_preview_snapshot(page.project)
    cue = next(item for item in snapshot.cues if item.id == "cue")
    style = next(item for item in snapshot.styles if item.id == cue.style_id)
    assert (style.position_x, style.position_y) == (444, 555)
    ass = compile_ass(snapshot)
    import re
    pos = re.search(r'\\pos\(([^,]+),([^\)]+)\)', ass)
    assert float(pos[1]) == 444
    # The ASS adapter compensates its REAL_DIM line box; a 100px authored
    # drag must still move the actual ASS anchor exactly 100px.
    page._position_overlay_moved(444, 655)
    moved = compile_ass(page._ass_preview_snapshot(page.project))
    moved_pos = re.search(r'\\pos\(([^,]+),([^\)]+)\)', moved)
    assert float(moved_pos[2]) - float(pos[2]) == 100
    page.close_page()


def test_transform_single_source_of_truth(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.position_overlay.set_video_position(500, 600, 1920, 1080)
    page._position_overlay_committed(500, 600)
    cue = page._cue_lookup["cue"]
    style = next(item for item in page.project.styles if item.id == cue.style_id)
    assert (cue.transform["position_x"], cue.transform["position_y"]) == (500, 600)
    assert (style.position_x, style.position_y) == (None, None)
    assert (page.style_position_x.value(), page.style_position_y.value()) == (500, 600)
    assert not hasattr(page, "position_visual_overlay")
    page.close_page()


def _apply_game_preset(page: SubtitleStudioPage) -> None:
    index = page.style_preset.findData("game")
    assert index >= 0
    page.style_preset.setCurrentIndex(index)
    page._preset_activated(index)


def test_preset_materializes_full_style(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page._queue_advanced_preview = lambda *_a, **_k: None
    _apply_game_preset(page)
    cue = page._cue_lookup["cue"]
    style = next(item for item in page.project.styles if item.id == cue.style_id)
    preset = BUILTIN_PRESETS["game"]
    assert cue.base_preset_id == "game"
    assert (style.font_family, style.font_size, style.bold, style.outline_width) == (
        preset.font_family, preset.font_size, preset.bold, preset.outline_width,
    )
    assert cue.effect_id == "none"
    page.close_page()


def test_sparse_preset_overwrites_authored_color_and_keeps_unspecified_recipe(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    old = copy.deepcopy(style_recipe_for_prompt("赛博渐变 glitch"))
    page.project.style_recipes["default"] = old.to_dict()
    page._queue_advanced_preview = lambda *_a, **_k: None
    _apply_game_preset(page)
    cue = page._cue_lookup["cue"]
    assert cue.base_preset_id == "game"
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.rendering.advanced_renderer import normalized_visual_snapshot
    resolved = normalized_visual_snapshot(build_visual_cue_snapshot(page.project, cue.id))
    assert resolved['fill'] == {'type':'solid','color':'#FFFFFF'}
    page.close_page()


def test_font_combo_lists_installed_fonts(monkeypatch):
    _app()
    entries = tuple(SystemFontEntry(name, ("Regular",)) for name in (
        "Microsoft YaHei UI", "SimSun", "KaiTi", "Arial", "Consolas",
    ))
    monkeypatch.setattr("twobyteasr.caption_style.studio_font_combo.system_font_inventory", lambda: entries)
    combo = LazyFontComboBox()
    combo.setEditable(True)
    combo._load_full_font_list()
    assert set(item.family for item in entries) <= {combo.itemText(i) for i in range(combo.count())}
    combo._filter_families("Kai")
    assert combo.count() == 1 and combo.itemText(0) == "KaiTi"
    combo.showPopup()
    assert set(item.family for item in entries) <= {combo.itemText(i) for i in range(combo.count())}
    combo.hidePopup()


def test_gradient_rgba_roundtrip():
    for project, css in (("#FFFFE45E", "#FFE45EFF"), ("#8020D9FF", "#20D9FF80")):
        assert project_color_to_css(project) == css
        assert css_color_to_project(css) == project


def _gradient_project():
    recipe = style_recipe_for_prompt("黄色到青色渐变游戏字幕")
    recipe.engine = "remotion"
    recipe.colors["fill"] = FillSpec.linear([
        {"color": "#FFFFE45E", "position": 0.0},
        {"color": "#FF20D9FF", "position": 1.0},
    ]).to_dict()
    project = copy.deepcopy(_page_project())
    project.style_recipes["gradient"] = recipe.to_dict()
    project.cues[0].style_id = "gradient"
    project.styles.append(SubtitleStyle("gradient", "渐变", primary_color="#FFFFE45E"))
    return project


def _page_project():
    from twobyteasr.projects.studio_project import SubtitleProject
    return SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=10_000, width=1280, height=720),
        cues=[StudioCue("cue", 0, 2_000, "黄色到青色", style_id="default")],
    )


def test_gradient_preview_not_black():
    project = _gradient_project()
    snapshot = build_visual_cue_snapshot(project, "cue", width=640, height=360)
    visual = normalized_visual_snapshot(snapshot)
    colors = [item["color"].upper() for item in visual["fill"]["stops"]]
    assert colors == ["#FFE45EFF", "#20D9FFFF"]
    assert all(color not in {"#000000", "#000000FF"} for color in colors)


def test_gradient_routes_advanced():
    project = _gradient_project()
    assert route_recipe(project.style_recipes["gradient"]).engine == "remotion"


def test_ai_cards_use_real_renderer(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    frame = QPixmap(480, 270)
    frame.fill(QColor("#FFE45E"))
    target = tmp_path / "ai-card.png"
    assert frame.save(str(target), "PNG")
    calls = []

    def render_batch(requests, **kwargs):
        calls.extend(
            (snapshot.stable_hash(), relative_ms, kwargs.get("render_type"))
            for snapshot, relative_ms, _width, _height in requests
        )
        return [
            (snapshot.stable_hash(), target, False)
            for snapshot, _relative_ms, _width, _height in requests
        ]

    monkeypatch.setattr(page._advanced_preview_cache, "render_snapshot_batch", render_batch)
    live_samples = []
    real_composite = studio_live_canvas.composite_live_scene_layers

    def composite_live(layers, scene, relative_ms, **kwargs):
        live_samples.append(relative_ms)
        return real_composite(layers, scene, relative_ms, **kwargs)

    monkeypatch.setattr(studio_live_canvas, "composite_live_scene_layers", composite_live)
    monkeypatch.setattr(studio_ai_flow, "composite_live_scene_layers", composite_live)
    variants = tuple(visual_design_variants("1930s 橡皮管胶片"))
    assert len({json.dumps(_visual.to_dict(), sort_keys=True) for _visual in variants}) == 3
    assert all(_visual.engine_requirement == "advanced" for _visual in variants)
    assert all(_visual.motion.entrance or _visual.motion.hold or _visual.ass.enabled for _visual in variants)
    suggestion = AIDesignSuggestion("cue", variants[0].to_style_recipe(), variants=variants)
    page._ai_ready(suggestion)
    deadline = time.monotonic() + 1.0
    while (
        (len(calls) < 3 or not all(page._ai_variant_preview_paths))
        and time.monotonic() < deadline
    ):
        QTest.qWait(5)
    assert len(calls) == 3
    assert len(page._ai_variant_preview_labels) == 3
    assert all(label.pixmap() is not None and not label.pixmap().isNull() for label in page._ai_variant_preview_labels)
    assert all(page._ai_variant_preview_paths)
    page._play_ai_variant_motion(0, variants[0])
    deadline = time.monotonic() + 1.0
    while (len(live_samples) < 3 or 0 not in page._ai_variant_motion_timers) and time.monotonic() < deadline:
        QTest.qWait(5)
    assert 0 in page._ai_variant_motion_timers
    assert len(calls) == 3  # Card stills use Fidelity; motion uses the trusted LIVE compiler.
    assert len(live_samples) >= 3
    assert live_samples == sorted(live_samples)
    page.close_page()


def test_ai_generic_result_retries(monkeypatch):
    project = _page_project()
    valid = [item.to_style_recipe().to_dict() for item in visual_design_variants("复古动画")]
    responses = [
        {"design_intent": "generic", "visual_changes": [], "motion_reason": "", "variants": []},
        {
            "design_intent": "三套复古动态方向",
            "visual_changes": ["字体", "色彩", "描边"],
            "motion_reason": "动画方向需要可见动效",
            "variants": valid,
        },
    ]

    class Provider:
        provider_id = "fixture"
        def structured_complete(self, *_args, **_kwargs):
            return copy.deepcopy(responses.pop(0))

    provider = Provider()
    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.provider_for_stage", lambda *_a, **_k: provider)
    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.available_font_shortlist", lambda **_k: {
        "chinese_display": ["KaiTi"], "chinese_sans": ["Microsoft YaHei UI"],
        "serif": ["SimSun"], "handwriting": ["KaiTi"],
        "pixel_game": ["Consolas"], "cartoon": ["KaiTi"],
    })
    result = request_style_design(project, "cue", "复古动画", {"models": {"polish": "fixture"}})
    assert len(result.variants) == 3
    assert responses == []


def test_ai_apply_syncs_style_controls(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page._queue_advanced_preview = lambda *_a, **_k: None
    recipe = style_recipe_for_prompt("1930s 橡皮管胶片")
    assert page.style_controller._apply_style_recipe("cue", recipe)
    style = next(item for item in page.project.styles if item.id == page._cue_lookup["cue"].style_id)
    assert page.style_font.currentText() == style.font_family
    assert page.style_font_size.value() == round(style.font_size)
    assert FillSpec.from_value(page._fill_spec).to_dict() == FillSpec.from_value(recipe.colors["fill"]).to_dict()
    page.close_page()


def test_ai_apply_invalidates_same_cue_preview_and_queues_selected_graph(
    monkeypatch, tmp_path,
):
    page = _page(monkeypatch, tmp_path)
    queued = []
    monkeypatch.setattr(
        page,
        "_queue_advanced_preview",
        lambda payload, **kwargs: queued.append((copy.deepcopy(payload), kwargs)),
    )
    monkeypatch.setattr(
        page,
        "ensure_active_subtitle_renderer",
        lambda **_kwargs: {},
    )
    page._advanced_preview_state.generation = 7
    page._advanced_preview_state.identity = AdvancedPreviewIdentity(
        "cue", "old-snapshot", "old-glyph", "old-motion", "old-renderer",
        300, (640, 360), 30.0,
    )
    page._advanced_preview_expected_key = "old-request"
    page._advanced_preview_snapshot = object()
    page._advanced_active_cue_id = "cue"

    recipe = style_recipe_from_graph(comic_burst_graph())
    page._pending_suggestion = AIDesignSuggestion(
        "cue", recipe, "fixture", (), "fixture", (), "fixture", {}, False,
        "fixture", {}, (), (),
    )
    previous_style_id = page._cue_lookup["cue"].style_id

    page._apply_ai_preview()

    cue = page._cue_lookup["cue"]
    applied = page.project.style_recipes[cue.style_id]
    assert cue.style_id != previous_style_id
    assert compile_live_scene(applied["visualGraph"]).graph_hash == compile_live_scene(
        recipe.visual_graph
    ).graph_hash
    assert page._pending_suggestion is None
    assert page._advanced_preview_state.generation == 8
    assert page._advanced_preview_state.identity is None
    assert page._advanced_preview_expected_key == ""
    assert page._advanced_preview_snapshot is None
    assert page._advanced_active_cue_id == ""
    assert queued and queued[-1][1] == {"force": True, "delay_ms": 0}
    assert compile_live_scene(queued[-1][0]["visualGraph"]).graph_hash == compile_live_scene(
        recipe.visual_graph
    ).graph_hash
    page.close_page()


def test_ai_card_apply_button_commits_the_card_graph_with_qtest(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    monkeypatch.setattr(page, "_start_ai_variant_previews", lambda _variants: None)
    monkeypatch.setattr(page, "_queue_advanced_preview", lambda *_a, **_k: None)
    monkeypatch.setattr(
        page,
        "ensure_active_subtitle_renderer",
        lambda **_kwargs: {},
    )
    visual = VisualStyleRecipe.from_style_recipe(
        style_recipe_from_graph(comic_burst_graph())
    )
    suggestion = AIDesignSuggestion(
        "cue", visual.to_style_recipe(), "fixture", (visual,), "fixture", (),
        "fixture", {}, False, "fixture", {}, (), (),
    )
    page._ai_ready(suggestion)
    card_graph_hash = compile_live_scene(
        page._pending_suggestion.variants[0].visual_graph
    ).graph_hash
    card = page.ai_variant_row.itemAt(0).widget()
    apply = next(
        button for button in card.findChildren(__import__(
            "PySide6.QtWidgets", fromlist=["QPushButton"]
        ).QPushButton)
        if button.text() == "应用"
    )
    previous_style_id = page._cue_lookup["cue"].style_id

    QTest.mouseClick(apply, __import__(
        "PySide6.QtCore", fromlist=["Qt"]
    ).Qt.MouseButton.LeftButton)

    cue = page._cue_lookup["cue"]
    assert cue.style_id != previous_style_id
    assert compile_live_scene(
        page.project.style_recipes[cue.style_id]["visualGraph"]
    ).graph_hash == card_graph_hash
    page.close_page()


def test_preview_generation_drops_stale_jobs():
    state = AdvancedPreviewStateMachine()
    first = AdvancedPreviewIdentity("a", "s1", "g1", "m1", "r1", 300, (640, 360), 30.0)
    second = AdvancedPreviewIdentity("a", "s2", "g2", "m2", "r2", 300, (640, 360), 30.0)
    generation1 = state.select(first, cache_hit=False)
    generation2 = state.select(second, cache_hit=False)
    assert generation2 > generation1
    assert not state.publish_ready(first, generation1, "old.png")
    assert state.publish_ready(second, generation2, "new.png")
    assert state.phase == AdvancedPreviewPhase.ADVANCED_READY


def test_interactive_latency_does_not_wait_renderer(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    payload = style_recipe_for_prompt("复杂渐变动画").to_dict()
    called = []
    monkeypatch.setattr(page, "_schedule_advanced_preview", lambda *_a, **_k: (time.sleep(0.2), called.append(1)))
    started = time.perf_counter()
    page._queue_advanced_preview(payload)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.05
    assert called == []
    assert page._advanced_preview_timer.isActive()
    page.close_page()
