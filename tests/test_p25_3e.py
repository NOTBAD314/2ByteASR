import copy
import time
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QInputDialog, QLabel, QWidget

from twobyteasr.advanced_preview import (
    AdvancedPreviewIdentity,
    AdvancedPreviewPhase,
    AdvancedPreviewStateMachine,
)
from twobyteasr.motion_library import MotionPreset, MotionPresetStore, SYSTEM_MOTIONS
from twobyteasr.advanced_renderer import normalized_visual_snapshot
from twobyteasr.studio_ai import style_recipe_for_prompt
from twobyteasr.studio_project import (
    StudioCue, StudioMedia, SubtitleProject, SubtitleStyle, save_project,
)
from twobyteasr.studio_ui import (
    AdvancedLiveCanvas, FillEditorDialog, MotionBrowserDialog, SubtitleStudioPage,
)
from twobyteasr.style_recipe import FillSpec, StyleRecipe, VisualStyleRecipe
from twobyteasr.visual_design_graph import clean_subtitle_graph, style_recipe_from_graph
from twobyteasr.visual_snapshot import build_visual_cue_snapshot


def _app():
    return QApplication.instance() or QApplication([])


def _advanced_project() -> SubtitleProject:
    recipe = style_recipe_for_prompt("Cyberpunk HUD")
    return SubtitleProject(
        media=StudioMedia(path="source.mp4", duration_ms=8_000, width=1920, height=1080),
        cues=[StudioCue("cue", 500, 5_000, "稳定字幕", style_id="advanced")],
        styles=[
            SubtitleStyle("default", "Default"),
            SubtitleStyle(
                "advanced", "Cyberpunk", font_size=64, position_x=820,
                position_y=910, scale_x=112, scale_y=94,
            ),
        ],
        style_recipes={"advanced": recipe.to_dict()},
    )


def test_preview_identity_reuses_one_motion_cache_bucket():
    snapshot = build_visual_cue_snapshot(_advanced_project(), "cue", width=640, height=360)
    early = AdvancedPreviewIdentity.from_snapshot(snapshot, width=640, height=360, motion_time_ms=120)
    later = AdvancedPreviewIdentity.from_snapshot(snapshot, width=640, height=360, motion_time_ms=960)
    assert early.glyph_key == later.glyph_key
    assert early.motion_key == later.motion_key
    assert early.request_key != later.request_key


def test_ready_preview_reselect_is_immediate():
    snapshot = build_visual_cue_snapshot(_advanced_project(), "cue", width=640, height=360)
    identity = AdvancedPreviewIdentity.from_snapshot(snapshot, width=640, height=360, motion_time_ms=300)
    machine = AdvancedPreviewStateMachine()
    generation = machine.select(identity, cache_hit=False)
    assert machine.phase == AdvancedPreviewPhase.PREPARING
    assert machine.publish_ready(identity, generation, "cached.png")
    machine.mark_visible(identity)
    assert machine.phase == AdvancedPreviewPhase.ADVANCED_VISIBLE
    second_generation = machine.select(identity, cache_hit=True)
    assert second_generation == generation
    assert machine.phase == AdvancedPreviewPhase.ADVANCED_READY


def test_memory_frame_reentry_preserves_fidelity_cache_path(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        cue = page.project.cues[0]
        page.project.style_recipes[cue.style_id] = style_recipe_from_graph(
            clean_subtitle_graph()
        ).to_dict()
        monkeypatch.setattr(page, "_renderer_cue_at_playhead", lambda: cue)
        monkeypatch.setattr(
            page.video,
            "playback_position_snapshot",
            lambda: SimpleNamespace(
                presentation_media_ms=cue.start_ms + 700,
                paused=True,
            ),
        )
        page.timeline.playhead_ms = cue.start_ms + 700
        width, height = page._advanced_preview_size()
        snapshot = build_visual_cue_snapshot(
            page.project, cue.id, width=width, height=height, fps=30.0,
        )
        identity = page._advanced_preview_cache.identity(
            snapshot, relative_ms=700, width=width, height=height,
        )
        cached_path = page._advanced_preview_cache.path_for(identity.request_key)
        cached_path.parent.mkdir(parents=True, exist_ok=True)
        frame = QPixmap(width, height)
        frame.fill()
        assert frame.save(str(cached_path), "PNG")
        page._advanced_frame_memory[identity.request_key] = QPixmap(frame)

        # This test owns a ready immutable frame; worker preparation is covered separately.
        monkeypatch.setattr(page, "_prepared_caption_snapshot", lambda *_:snapshot)
        page._schedule_advanced_preview(
            page.project.style_recipes[cue.style_id], queue_fidelity=True,
        )

        assert page._advanced_preview_state.identity.request_key == identity.request_key
        assert page._advanced_preview_state.identity.snapshot_hash == identity.snapshot_hash
        # LIVE rasterization is asynchronous; a validated memory frame may
        # win first. The cache path and visible pixels must survive either.
        deadline=time.monotonic()+2
        while (page._advanced_preview_state.frame_path!=str(cached_path) or page._advanced_canvas_source_kind=='none') and time.monotonic()<deadline:
            QTest.qWait(10)
        assert page._advanced_canvas_source_kind in {'live','fidelity'}
        live = page.advanced_cue_overlay._source_image.convertToFormat(
            QImage.Format.Format_RGBA8888
        )
        live_bytes = bytes(live.constBits())[:live.sizeInBytes()]
        assert max(live_bytes[3::4], default=0) > 8
        QTest.qWait(80)
        app.processEvents()
        assert page._advanced_preview_state.frame_path == str(cached_path)
        assert Path(page._advanced_preview_state.frame_path).is_file()
    finally:
        page.close_page()
        page.deleteLater()


def test_stale_worker_cannot_take_visual_ownership():
    snapshot = build_visual_cue_snapshot(_advanced_project(), "cue", width=640, height=360)
    first = AdvancedPreviewIdentity.from_snapshot(snapshot, width=640, height=360, motion_time_ms=120)
    changed_project = _advanced_project()
    changed_project.cues[0].text = "新的字幕"
    changed = build_visual_cue_snapshot(changed_project, "cue", width=640, height=360)
    second = AdvancedPreviewIdentity.from_snapshot(changed, width=640, height=360, motion_time_ms=120)
    machine = AdvancedPreviewStateMachine()
    first_generation = machine.select(first, cache_hit=False)
    second_generation = machine.select(second, cache_hit=False)
    assert second_generation > first_generation
    assert not machine.publish_ready(first, first_generation, "stale.png")
    assert machine.phase == AdvancedPreviewPhase.PREPARING


def test_paused_duplicate_time_keeps_exact_canvas_frame():
    _app()
    snapshot = build_visual_cue_snapshot(_advanced_project(), "cue", width=640, height=360)
    owner = QWidget()
    canvas = AdvancedLiveCanvas(owner)
    pixmap = QPixmap(640, 360)
    pixmap.fill()
    canvas.set_base_geometry(QRect(0, 0, 640, 360))
    canvas.set_visual(pixmap, snapshot)
    canvas.sync_time(900, paused=True)
    first = (QRect(canvas.geometry()), canvas.pixmap().cacheKey(), canvas.graphicsEffect().opacity())
    canvas.sync_time(900, paused=True)
    second = (QRect(canvas.geometry()), canvas.pixmap().cacheKey(), canvas.graphicsEffect().opacity())
    assert second == first
    canvas.deleteLater()
    owner.deleteLater()


def test_paused_canvas_ignores_duplicate_geometry_and_visual_sync():
    _app()
    snapshot = build_visual_cue_snapshot(_advanced_project(), "cue", width=640, height=360)
    owner = QWidget()
    canvas = AdvancedLiveCanvas(owner)
    pixmap = QPixmap(640, 360)
    pixmap.fill()
    base_rect = QRect(40, 30, 640, 360)
    canvas.set_base_geometry(base_rect)
    canvas.set_visual(pixmap, snapshot)
    canvas.sync_time(833, paused=True)
    first = (
        QRect(canvas.geometry()),
        canvas.pixmap().toImage(),
        canvas.graphicsEffect().opacity(),
        canvas._last_frame_signature,
    )

    canvas.set_base_geometry(base_rect)
    canvas.set_visual(pixmap, snapshot)
    canvas.sync_time(833, paused=True)
    second = (
        QRect(canvas.geometry()),
        canvas.pixmap().toImage(),
        canvas.graphicsEffect().opacity(),
        canvas._last_frame_signature,
    )

    # P9A-R3: graph-less motion recipes now compile through the shared graph
    # compiler, so a repeated set_visual recomposites (new pixmap identity).
    # The duplicate paused sync must still be visually identical.
    assert second == first
    assert canvas._base_rect == base_rect
    canvas.deleteLater()
    owner.deleteLater()


def test_unrelated_widget_move_does_not_resync_advanced_canvas(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    calls = []
    page._sync_advanced_cue_overlay = lambda: calls.append(True)

    unrelated = QWidget()
    page.eventFilter(unrelated, QEvent(QEvent.Type.Move))
    app.processEvents()

    assert calls == []
    unrelated.deleteLater()
    page.close_page(); page.deleteLater()


def test_fill_change_preserves_geometry():
    project = _advanced_project()
    before = build_visual_cue_snapshot(project, "cue")
    recipe = StyleRecipe.from_dict(project.style_recipes["advanced"])
    recipe.set_fill(FillSpec.linear([
        {"color": "#FFFFD84A", "position": 0.0},
        {"color": "#FF20D9FF", "position": 1.0},
    ], angle=25))
    project.style_recipes["advanced"] = recipe.to_dict()
    after = build_visual_cue_snapshot(project, "cue")
    assert after.geometry_signature() == before.geometry_signature()
    assert after.font_size == before.font_size
    assert (after.scale_x, after.scale_y) == (before.scale_x, before.scale_y)


def test_solid_gradient_solid_preserves_bbox_inputs():
    project = _advanced_project()
    recipe = StyleRecipe.from_dict(project.style_recipes["advanced"])
    original = build_visual_cue_snapshot(project, "cue")
    for fill in (
        FillSpec.linear([
            {"color": "#FFFFFFFF", "position": 0.0},
            {"color": "#FF20D9FF", "position": 1.0},
        ]),
        FillSpec.radial([
            {"color": "#FFFFFFFF", "position": 0.0},
            {"color": "#FF20D9FF", "position": 1.0},
        ]),
        FillSpec.solid("#FFFFFFFF"),
    ):
        recipe.set_fill(fill)
        project.style_recipes["advanced"] = copy.deepcopy(recipe.to_dict())
        current = build_visual_cue_snapshot(project, "cue")
        assert current.geometry_signature() == original.geometry_signature()


def test_fill_spec_is_shared_by_visual_recipe_snapshot_and_renderer():
    fill = FillSpec.radial([
        {"color": "#FFFFD84A", "position": 0.0},
        {"color": "#FFFF4FA3", "position": 0.5},
        {"color": "#FF20D9FF", "position": 1.0},
    ])
    visual = VisualStyleRecipe(
        name="Radial",
        engine_requirement="advanced",
        fill=fill.to_dict(),
    ).validate()
    assert FillSpec.from_value(visual.fill) == fill

    project = _advanced_project()
    recipe = StyleRecipe.from_dict(project.style_recipes["advanced"])
    recipe.set_fill(fill)
    project.style_recipes["advanced"] = recipe.to_dict()
    snapshot = build_visual_cue_snapshot(project, "cue")
    normalized = normalized_visual_snapshot(snapshot)
    assert FillSpec.from_value(snapshot.fill) == fill
    assert normalized["fill"]["type"] == "gradient"
    assert normalized["fill"]["kind"] == "radial"
    assert len(normalized["fill"]["stops"]) == 3


def _page(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = save_project(_advanced_project(), tmp_path / "p25.3e.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    page.show()
    app.processEvents()
    return app, page


def test_style_panel_has_one_fill_entry(tmp_path, monkeypatch):
    _app_instance, page = _page(tmp_path, monkeypatch)
    labels = [label.text() for label in page.context_panel.findChildren(QLabel)]
    assert "填充" in labels
    assert "填充类型" not in labels
    assert not hasattr(page, "style_fill_type")
    assert not hasattr(page, "gradient_editor")
    page.close_page(); page.deleteLater()


def test_fill_only_commit_preserves_geometry_and_effect(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    before = build_visual_cue_snapshot(page.project, "cue")
    effect_id = page.project.cues[0].effect_id
    page._apply_fill_spec(FillSpec.radial([
        {"color": "#FFFFD84A", "position": 0.0},
        {"color": "#FFFF4FA3", "position": 0.5},
        {"color": "#FF20D9FF", "position": 1.0},
    ]))
    app.processEvents()
    after = build_visual_cue_snapshot(page.project, "cue")
    assert after.geometry_signature() == before.geometry_signature()
    assert page.project.cues[0].effect_id == effect_id
    assert FillSpec.from_value(after.fill).kind == "radial-gradient"
    page.undo_stack.undo(); app.processEvents()
    restored = build_visual_cue_snapshot(page.project, "cue")
    assert restored.stable_hash() == before.stable_hash()
    page.close_page(); page.deleteLater()


def test_gradient_stop_uses_main_color_picker():
    _app()
    dialog = FillEditorDialog({
        "type": "linear-gradient",
        "stops": [
            {"color": "#FFFFFFFF", "position": 0.0},
            {"color": "#FF000000", "position": 1.0},
        ],
    })
    dialog.mode_group.button(1).setChecked(True)
    dialog.gradient._selected = dialog.gradient._stops[1]
    dialog.gradient._sync_stop_controls()
    dialog._select_gradient_stop(1)
    # P4: the picker itself is the color surface — selecting a stop syncs it.
    assert dialog.picker.color().rgb() == QColor("#FF000000").rgb()
    assert dialog.picker.alpha_spin is not None  # alpha channel stays editable
    dialog.deleteLater()


def test_style_color_dialog_is_themed_simple_picker(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.color_picker import SimpleColorDialog

    page = SubtitleStudioPage()
    page._generate_waveform = lambda *_args, **_kwargs: None
    dialog = page._create_style_color_dialog(page.style_outline_color)
    try:
        assert isinstance(dialog, SimpleColorDialog)
        dialog.picker.set_color(QColor("#8044AAEE"))
        selected = dialog.selectedColor()
        assert selected.rgb() == QColor("#8044AAEE").rgb()
        assert selected.alpha() == 0x80  # #AARRGGBB: alpha survives the picker
    finally:
        dialog.deleteLater()
        page.close_page()
        page.deleteLater()


def test_motion_library_catalog_and_ownership(tmp_path):
    store = MotionPresetStore(tmp_path)
    assert {
        "glitch_reveal", "digital_scan", "chromatic_split", "gaming_impact",
        "bounce", "punch", "soft_fade", "float", "typewriter", "slide",
        "zoom", "shake",
    } <= set(store.all())
    with __import__("pytest").raises(ValueError, match="read-only"):
        store.upsert(SYSTEM_MOTIONS["glitch_reveal"])
    custom = MotionPreset(
        "my_motion", "我的 Motion",
        {"entrance": {"type": "custom_reveal", "duration_ms": 240}, "hold": {}, "exit": {}},
        system=False,
    )
    store.upsert(custom)
    assert "my_motion" in store.all()
    store.delete("my_motion")
    assert "my_motion" not in store.all()
    with __import__("pytest").raises(ValueError, match="cannot be deleted"):
        store.delete("glitch_reveal")


def test_motion_browser_cards_are_live(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    dialog = MotionBrowserDialog(page.project.styles[-1], page)
    dialog.show(); app.processEvents()
    cards = dialog.findChildren(__import__("twobyteasr.studio_motion_browser", fromlist=["MotionCard"]).MotionCard)
    # 0.8.0: the library opens on 精选字效; 基础动效 / 旧版动效 hold the rest.
    featured = [preset for preset in dialog.store.all().values() if preset.category == "精选字效"]
    assert dialog._active_filter() == "featured"
    assert len(cards) == len(featured) >= 6
    assert len(dialog.store.all()) >= 12

    def animating(card):
        # Featured / 基础 cards draw with MotionSample (its clock loops the
        # sample); 旧版动效 cards keep StylePreview's looping motion timer.
        if hasattr(card.preview, "clock"):
            return card.preview.timer.isActive()
        return card.preview._motion_timer.isActive()

    assert all(not animating(card) for card in cards)
    cards[0].start_preview()
    app.processEvents()
    assert animating(cards[0])
    cards[0].stop_preview()
    assert not animating(cards[0])
    legacy = next(button for button in dialog.filter_group.buttons() if button.property("filterKind") == "legacy")
    legacy.click()
    app.processEvents()
    cards = [dialog.grid.itemAt(index).widget() for index in range(dialog.grid.count())]
    assert cards and all(not animating(card) for card in cards)
    cards[0].start_preview()
    app.processEvents()
    assert cards[0].preview._motion_timer.isActive()
    assert cards[0].preview._motion_loop
    dialog.close(); page.close_page(); page.deleteLater()


def test_motion_browser_saves_current_user_motion(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    dialog = MotionBrowserDialog(
        _advanced_project().styles[-1],
        current_motion=SYSTEM_MOTIONS["glitch_reveal"].motion,
        current_preview_effect_id="punch",
    )
    # The save form is a modal QDialog; driving exec() offscreen would block
    # forever, so inject the accepted form values instead.
    monkeypatch.setattr(
        dialog,
        "_run_motion_save_form",
        lambda: ("我的 Glitch", "描述", "故障", False),
    )
    dialog._save_current_motion()
    saved = list(dialog.store.load_user().values())
    assert len(saved) == 1
    assert saved[0].name == "我的 Glitch"
    assert saved[0].motion["entrance"]["type"] == "glitch_reveal"
    dialog.deleteLater()


def test_glitch_motion_updates_advanced_recipe(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    before = build_visual_cue_snapshot(page.project, "cue")
    page._apply_advanced_motion(MotionPresetStore().all()["glitch_reveal"])
    app.processEvents()
    cue = page.project.cues[0]
    recipe = StyleRecipe.from_dict(page.project.style_recipes[cue.style_id])
    after = build_visual_cue_snapshot(page.project, "cue")
    assert recipe.motion["entrance"]["type"] == "glitch_reveal"
    assert recipe.motion["entrance"]["slice_count"] == 5
    assert after.geometry_signature() == before.geometry_signature()
    page.close_page(); page.deleteLater()


def test_high_dpi_logical_width_keeps_three_panels(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    page.resize(1097, 720)
    page._apply_default_workspace_layout()
    app.processEvents()
    sizes = page.upper_splitter.sizes()
    assert all(size > 0 for size in sizes)
    assert page.cue_list_panel.width() >= 280
    assert page.context_panel.width() >= 370
    assert page.center_splitter.width() >= 360
    page.close_page(); page.deleteLater()


def test_motion_simple_controls_and_system_fonts_are_primary(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    page.context_drawer.setCurrentIndex(2)
    app.processEvents()
    assert page.effect_strength.isVisibleTo(page)
    assert page.effect_duration.isVisibleTo(page)
    assert [page.effect_strength.itemText(index) for index in range(3)] == [
        "轻微", "标准", "强烈",
    ]
    labels = [label.text() for label in page.context_panel.findChildren(QLabel)]
    assert "优先使用 Windows 已安装字体" in labels
    assert "安装推荐开源字体" not in labels
    page.close_page(); page.deleteLater()


def test_editable_font_surface_opens_picker(monkeypatch):
    _app()
    page = SubtitleStudioPage()
    calls = []
    monkeypatch.setattr(page.style_font, "showPopup", lambda: calls.append("open"))
    line_edit = page.style_font.lineEdit()
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPoint(12, 12),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPoint(12, 12),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    line_edit.resize(200, 30)
    # 2026-10-18: the press only focuses; the list opens on the release, so the
    # same click cannot close it again (or pick the font under the pointer).
    assert page.style_font.eventFilter(line_edit, press)
    assert calls == []
    assert page.style_font.eventFilter(line_edit, release)
    assert calls == ["open"]
    page.close_page(); page.deleteLater()
