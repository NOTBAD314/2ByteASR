import os
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QImage, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QToolButton,
)

import twobyteasr.studio.studio_ass_flow as studio_ass_flow
import twobyteasr.projects.studio_project_controller as studio_project_controller
import twobyteasr.studio.studio_project_flow as studio_project_flow
import twobyteasr.studio.studio_ui as studio_ui
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    load_project,
    save_autosave,
    save_project,
    create_studio_outputs,
)
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.caption_design.studio_ai import request_style_design
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.caption_design.visual_design_graph import compile_live_scene
from twobyteasr.studio.studio_ui import (
    CueTableModel,
    MpvCanvas,
    ScrubDoubleSpinBox,
    ScrubSpinBox,
    SubtitlePositionOverlay,
    SubtitleStudioPage,
    WaveformTimeline,
    media_relink_warning,
    render_style_sample,
)


def test_style_sample_pixels_use_fill_not_outline():
    app = QApplication.instance() or QApplication([])
    for fill, predicate in (
        ("#FFFFFFFF", lambda c: c.red() > 220 and c.green() > 220 and c.blue() > 220),
        ("#FFFF0000", lambda c: c.red() > 180 and c.green() < 100 and c.blue() < 100),
    ):
        image = QImage(420, 100, QImage.Format.Format_ARGB32)
        image.fill("#343A38")
        painter = QPainter(image)
        render_style_sample(
            painter,
            text="Sample",
            font=QFont("Arial", 36),
            baseline=QPointF(35, 70),
            fill=fill,
            outline="#FF000000",
            outline_width=3,
            rect=image.rect(),
        )
        painter.end()
        assert sum(predicate(image.pixelColor(x, y)) for y in range(image.height()) for x in range(image.width())) > 500


def test_style_sample_pixels_include_enabled_glow():
    app = QApplication.instance() or QApplication([])
    image = QImage(420, 100, QImage.Format.Format_ARGB32)
    image.fill("#343A38")
    painter = QPainter(image)
    render_style_sample(
        painter,
        text="Sample",
        font=QFont("Arial", 36),
        baseline=QPointF(35, 70),
        fill="#FFFFFFFF",
        outline="#FF000000",
        outline_width=3,
        rect=image.rect(),
        glow={"enabled": True, "color": "#FFFF0000", "blur": 8, "opacity": 1.0},
    )
    painter.end()
    red_pixels = sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if (lambda c: c.red() > 100 and c.green() < 150 and c.blue() < 150)(image.pixelColor(x, y))
    )
    assert red_pixels > 100


def test_p237_style_fields_are_uniform_and_scrub_is_wheel_safe():
    app = _app()
    page = SubtitleStudioPage()
    app.processEvents()
    fields = (
        page.style_preset,
        page.style_font,
        page.style_font_size,
        page.style_spacing,
        page.style_outline_width,
        page.effect_preset,
        page.effect_duration,
        page.style_alignment,
    )
    assert page.style_shadow.isHidden()
    assert {field.height() for field in fields} == {28}
    # 2026-10-09 (M16): the scope is one row of chips at the top of the panel.
    assert page.style_scope.height() <= 34
    radios = page.style_scope.findChildren(QRadioButton)
    assert len(radios) == 4
    assert all(button.height() == page.style_scope.height() for button in radios), (
        page.style_scope.height(), [button.height() for button in radios])
    assert len({button.y() for button in radios}) == 1
    spin = ScrubSpinBox()
    spin.setRange(0, 500)
    spin.setValue(52)
    QTest.mousePress(spin, Qt.MouseButton.LeftButton, pos=QPoint(20, 10))
    spin.mouseMoveEvent(studio_ui.QMouseEvent(
        studio_ui.QMouseEvent.Type.MouseMove,
        QPointF(156, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    QTest.mouseRelease(spin, Qt.MouseButton.LeftButton, pos=QPoint(156, 10))
    assert spin.value() == 86
    wheel = QWheelEvent(
        QPointF(20, 10), QPointF(20, 10), QPoint(0, 120), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    before_wheel = spin.value()
    spin.wheelEvent(wheel)
    assert spin.value() == before_wheel
    page.close_page()
    page.deleteLater()


def test_p2525_motion_dropdown_configures_recipe_and_applies(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1500, 900)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()

    page.motion_preset.setCurrentIndex(page.motion_preset.findData("quick_pop"))
    app.processEvents()
    assert page.motion_preview._motion_timer.isActive()
    assert page.motion_preview._motion["entry"]["type"] == "soft_pop"
    assert page.effect_preset.currentData() == "soft_pop"
    assert page.effect_exit.currentData() == "soft_fade"
    assert page.project.cues[0].effect_id == "soft_pop"
    assert page.project.cues[1].effect_id == "none"
    ass = compile_ass(page.project)
    assert r"\fscx95\fscy95" in ass
    assert r"\fscx103\fscy103" in ass
    assert r"\alpha&HFF&" in ass
    page.close_page()
    page.deleteLater()


def test_recognition_output_project_opens_without_stale_ass_and_overlay_matches_cue(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("TWOBYTEASR_DEBUG_SUBTITLES", "1")
    media = tmp_path / "recognition.mp4"
    media.write_bytes(b"media")
    txt = tmp_path / "recognition.txt"
    srt = tmp_path / "recognition.srt"
    txt.write_text("真实识别字幕", encoding="utf-8")
    srt.write_text("1\n00:00:00,200 --> 00:00:01,800\n真实识别字幕\n", encoding="utf-8")

    class RuntimeCue:
        cue_id = "recognition-42"
        start = 0.2
        end = 1.8
        text = "真实识别字幕"
        speaker = "S01"

    class RuntimeSegment(RuntimeCue):
        segment_id = 42
        primary_source = "moss"
        moss_text = "真实识别字幕"
        firered_text = "真实识别字幕"
        firered_llm_text = ""
        qwen_asr_text = "真实识别字幕"
        alternate_text = ""
        confidence = 0.92

    outputs = create_studio_outputs(
        media, [RuntimeCue()], txt_path=str(txt), srt_path=str(srt), segments=[RuntimeSegment()]
    )
    page = SubtitleStudioPage()
    stale = tmp_path / "previous-project.ass"
    stale.write_text("Dialogue: stale", encoding="utf-8")
    page._preview_path = stale
    loads = []
    monkeypatch.setattr(page.video, "load", lambda *args, **_kwargs: loads.append(args))
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args: None)

    page.open_project(outputs["project"])
    app.processEvents()
    diagnostics = page.subtitle_render_diagnostics()

    assert loads and loads[0][1] == ""
    assert page.selected_cue_id == "recognition-42"
    assert page._overlay_cue_id == "recognition-42"
    assert page.position_overlay.text == "真实识别字幕"
    assert diagnostics["project_cue"] == diagnostics["selected_cue"] == diagnostics["overlay_cue"]
    assert "真实识别字幕" in diagnostics["ass_event"]
    page.close_page()
    page.deleteLater()


def test_ai_design_applies_native_style_recipe_without_rewriting_cue(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    original = page.project.cues[0].text
    suggestion = request_style_design(
        page.project, page.selected_cue_id,
        "赛博朋克 2077 故障 HUD 字幕，黄色与青色，不要太花。", {},
    )
    page._ai_ready(suggestion)
    card_scene = compile_live_scene(
        page._pending_suggestion.variants[0].visual_graph
    )
    page._apply_ai_preview()
    app.processEvents()

    cue = page.project.cues[0]
    assert cue.text == original
    assert cue.style_id.startswith("ai-recipe-")
    assert cue.effect_id.startswith("ai-recipe-")
    assert page.project.style_recipes
    assert page.project.style_recipes[cue.style_id]["name"] == suggestion.recipe.name
    applied_scene = compile_live_scene(
        page.project.style_recipes[cue.style_id]["visualGraph"]
    )
    assert card_scene.graph_hash == applied_scene.graph_hash
    assert (
        card_scene.graph.motion_graph.duration_ms
        == applied_scene.graph.motion_graph.duration_ms
        == cue.end_ms - cue.start_ms
    )
    ass = compile_ass(page.project)
    assert cue.style_id in {style.id for style in page.project.styles}
    assert r"\t(" in ass
    page.close_page()
    page.deleteLater()


def test_motion_replay_waits_until_new_authoritative_ass_is_loaded(tmp_path, monkeypatch):
    app = _app()
    page = SubtitleStudioPage()
    generated = tmp_path / "studio-preview.ass"
    generated.write_text("[Script Info]", encoding="utf-8")
    loaded = []
    replayed = []
    scheduled = []
    monkeypatch.setattr(page.video, "reload_subtitle", lambda path: loaded.append(path))
    monkeypatch.setattr(page, "_replay_motion", lambda cue_id="": replayed.append(cue_id))
    class SingleShotCapture:
        singleShot = staticmethod(lambda delay, *callbacks: scheduled.append((delay, callbacks[-1])))

    monkeypatch.setattr(studio_ass_flow, "QTimer", SingleShotCapture)
    page._ass_generation = 7
    page._ass_worker_running = True
    page._pending_motion_replay_cue_id = "cue-42"

    page._ass_ready(7, str(generated))
    assert scheduled and scheduled[0][0] == 120
    scheduled[0][1]()

    assert loaded == [str(generated)]
    assert replayed == ["cue-42"]
    page.close_page()
    page.deleteLater()


def test_review_inline_editor_accepts_newline_and_ctrl_enter_is_one_undo(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    before = page.undo_stack.count()
    page._begin_canvas_inline_edit()
    editor = page._canvas_editor
    editor.setPlainText("第一行\n第二行")
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()

    assert page._canvas_editor is None
    assert page.project.cues[0].text == "第一行\n第二行"
    assert page.undo_stack.count() == before + 1
    assert page.undo_stack.command(before).origin == studio_ui.MutationOrigin.USER_EDIT
    page.undo_stack.undo()
    assert page.project.cues[0].text != "第一行\n第二行"
    page.close_page()
    page.deleteLater()


def test_e_key_opens_canvas_editor_outside_review_without_stealing_text_input(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1400, 850)
    page.show()
    page.activateWindow()
    page.open_project(_path(tmp_path))
    page.timeline.setFocus()
    QTest.keyClick(page, Qt.Key.Key_E)
    app.processEvents()
    assert page._canvas_editor is not None and page._canvas_editor.hasFocus()
    QTest.keyClick(page._canvas_editor, Qt.Key.Key_Escape)
    page.cue_search.setFocus()
    QTest.keyClick(page.cue_search, Qt.Key.Key_E)
    assert page.cue_search.text().endswith("e")
    assert page._canvas_editor is None
    page.close_page()
    page.deleteLater()


def test_review_mode_groups_candidates_and_numeric_shortcuts_use_unique_text(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    cue = page.project.cues[0]
    cue.text = "太赖了"
    cue.evidence_refs = ["e:review"]
    second = page.project.cues[1]
    second.evidence_refs = ["e:review-2"]
    page.project.asr_evidence["e:review"] = {
        "moss_text": "太赖了", "firered_text": "太赖了", "qwen_asr_text": "太烂了"
    }
    page.project.asr_evidence["e:review-2"] = {
        "moss_text": "第二句", "qwen_asr_text": "第二据"
    }
    page._refresh_review_risks()
    page.select_cue(cue.id)
    page._set_review_mode(True)
    app.processEvents()

    assert not page.review_summary_strip.isHidden()
    assert [(row.text, row.sources) for row in page._review_candidates] == [
        ("太赖了", ("Current", "MOSS", "FireRed")),
        ("太烂了", ("Qwen",)),
    ]
    assert page._dispatch_shortcut_sequence("2")
    assert page.project.cues[0].text == "太烂了"
    assert page.selected_cue_id == "b"
    assert page.project.studio_state["cue_statuses"]["a"] == "done"
    page.undo_stack.undo()
    assert page.project.cues[0].text == "太赖了"
    assert "a" not in page.project.studio_state["cue_statuses"]
    page.close_page()
    page.deleteLater()


def test_font_size_scrub_live_resizes_transform_and_commits_one_undo(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1500, 900)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()
    page.style_scope.setCurrentIndex(page.style_scope.findData("current"))
    page.style_font_size.setValue(52)
    page._commit_style_now()
    baseline = page.undo_stack.count()

    spin = page.style_font_size
    QTest.mousePress(spin, Qt.MouseButton.LeftButton, pos=QPoint(20, 10))
    spin.mouseMoveEvent(studio_ui.QMouseEvent(
        studio_ui.QMouseEvent.Type.MouseMove, QPointF(332, 10),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    assert spin.value() == 130
    assert page._scrub_active
    assert round(page.position_overlay.font_size) == 130
    QTest.mouseRelease(spin, Qt.MouseButton.LeftButton, pos=QPoint(332, 10))
    app.processEvents()

    assert page.undo_stack.count() == baseline + 1
    page.undo_stack.undo()
    assert round(next(style for style in page.project.styles if style.id == page.project.cues[0].style_id).font_size) == 52
    page.close_page()
    page.deleteLater()


def test_scrub_receives_real_mouse_events_from_spinbox_line_edit(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1500, 900)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()
    spin = page.style_font_size
    spin.setValue(48)
    page._commit_style_now()
    baseline = page.undo_stack.count()
    editor = spin.lineEdit()

    QTest.mousePress(editor, Qt.MouseButton.LeftButton, pos=QPoint(8, editor.height() // 2))
    QTest.mouseMove(editor, QPoint(200, editor.height() // 2), delay=20)
    QTest.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=QPoint(200, editor.height() // 2))
    app.processEvents()

    assert spin.value() == 96
    assert page.undo_stack.count() == baseline + 1
    page.undo_stack.undo()
    assert round(next(style for style in page.project.styles if style.id == page.project.cues[0].style_id).font_size) == 48
    page.close_page()
    page.deleteLater()


def test_five_style_presets_preserve_cue_text_and_single_transform_target(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.project.cues[0].text = "哦那再来一把吧"
    page.select_cue("a")
    before = [cue.text for cue in page.project.cues]

    for preset_id in ("default", "clean-white", "game", "livestream", "dialogue-a"):
        page.style_preset.setCurrentIndex(page.style_preset.findData(preset_id))
        page._apply_style()
        assert [cue.text for cue in page.project.cues] == before

    overlays = page.findChildren(SubtitlePositionOverlay)
    assert len([overlay for overlay in overlays if not overlay.isWindow()]) == 1
    assert len([overlay for overlay in overlays if overlay.isWindow()]) == 0
    assert page.position_overlay.text == "哦那再来一把吧"
    page.close_page()
    page.deleteLater()


def test_p251_motion_ui_progressively_discloses_advanced_controls():
    app = _app()
    page = SubtitleStudioPage()
    page.resize(1500, 900)
    page.show()
    app.processEvents()
    assert page.motion_advanced.isHidden()
    assert page.effect_strength.currentData() == "medium"
    assert page.effect_curve.currentData() == "soft"
    page.motion_advanced_button.click()
    app.processEvents()
    assert not page.motion_advanced.isHidden()
    assert page.effect_accel.value() == pytest.approx(0.72)
    page.close_page()
    page.deleteLater()


def test_p237_canvas_overlay_does_not_create_native_child_surface():
    _app()
    page = SubtitleStudioPage()
    assert page.position_overlay.parent() is page.video
    assert page.position_overlay._top_level_canvas is False
    assert not page.position_overlay.testAttribute(studio_ui.Qt.WidgetAttribute.WA_NativeWindow)
    page.close_page()
    page.deleteLater()


def test_transform_visuals_use_one_non_native_owned_layer():
    app = _app()
    page = SubtitleStudioPage()
    page.resize(1500, 900)
    page.show()
    page.position_overlay.setGeometry(page.video.rect())
    page.position_overlay.set_text("Transform visual")
    page.position_overlay.show()
    app.processEvents()

    interaction = page.position_overlay
    page._sync_transform_visual_overlay()
    assert not interaction.isWindow()
    assert not interaction.testAttribute(studio_ui.Qt.WidgetAttribute.WA_NativeWindow)
    assert interaction.geometry() == page.video.rect()
    assert len(page.findChildren(SubtitlePositionOverlay)) == 1
    assert not hasattr(page, "position_visual_overlay")

    image = interaction.grab().toImage()
    assert not image.isNull()
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )

    page.close_page()
    page.deleteLater()


def test_p237_primary_speaker_is_closest_to_waveform():
    _app()
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=20_000),
        cues=[
            StudioCue("a", 0, 1000, "a", speaker_id="S01"),
            StudioCue("b", 1000, 9000, "b", speaker_id="S02"),
            StudioCue("c", 9000, 12_000, "c", speaker_id="S03"),
        ],
    )
    timeline = WaveformTimeline()
    timeline.resize(1200, 500)
    timeline.set_waveform_visible(True)
    timeline.set_project(project)
    speaker_rects, _translation, waveform = timeline._track_layout()
    assert timeline.speaker_ids() == ["S01", "S03", "S02"]
    assert speaker_rects["S02"].bottom() == timeline._track_viewport().bottom()
    # The global waveform lane is gone; every A lane is pinned directly under
    # its linked V lane, so the last speaker stays closest to the audio rows.
    assert waveform.isNull()
    audio_rects = timeline._audio_track_rects()
    assert "A1" in audio_rects
    video_rects = timeline._video_track_rects()
    assert audio_rects["A1"].top() == video_rects["V1"].bottom()
    assert speaker_rects["S02"].bottom() <= audio_rects["A1"].top()
    assert all(rect.height() <= 96 for rect in speaker_rects.values())
    timeline.deleteLater()


def test_p74c_degenerate_graph_salvages_primary_preview(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "game.mp4"
    media.write_bytes(b"mp4")
    project = SubtitleProject(
        media=StudioMedia(path=str(media)),
        cues=[StudioCue("cue-1", 0, 1000, "黑屏回归")],
    )
    project.validate()
    assert project.video_tracks[0].clips[0].timeline_out_ms == 0

    page = SubtitleStudioPage()
    page.project = project
    layers = page._multitrack_preview_layers(0)
    assert len(layers) == 1
    salvage = layers[0]
    assert salvage["key"] == "primary-salvage"
    assert salvage["mode"] == "source"
    assert salvage["source_path"] == str(media.resolve())
    # A reachable media file keeps the playback state non-empty even while
    # the graph is degenerate, so mpv is never parked in the idle gap route.
    page._refresh_edit_playback_state()
    assert page._empty_playback_state is False

    # A healthy graph with a real gap at the playhead must NOT be salvaged.
    clip = project.video_tracks[0].clips[0]
    clip.source_out_ms = 1000
    clip.timeline_out_ms = 1000
    assert page._multitrack_preview_layers(2000) == []

    # Missing media keeps the empty-state contract intact: an offline asset
    # resolves no clip and no salvage layer can reference a missing file.
    asset = project.media_pool[0]
    asset.canonical_source = str(tmp_path / "missing.mp4")
    asset.offline = True
    project.media.path = str(tmp_path / "missing.mp4")
    assert page._multitrack_preview_layers(0) == []
    page.close_page()
    page.deleteLater()


def test_p74c_degenerate_preview_does_not_suspend_reachable_mpv(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "game.mp4"
    media.write_bytes(b"mp4")
    project = SubtitleProject(
        media=StudioMedia(path=str(media)),
        cues=[StudioCue("cue-1", 0, 1000, "黑屏回归")],
    )
    project.validate()
    page = SubtitleStudioPage()
    page.project = project
    suspended = []
    monkeypatch.setattr(page, "_multitrack_preview_target", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page.video, "suspend_media_async", lambda: suspended.append("suspend") or True)
    assert page._activate_multitrack_preview(0) is None
    assert suspended == []
    page.close_page()
    page.deleteLater()


def test_p237_timeline_cross_track_emits_speaker_change():
    app = _app()
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=10_000),
        speakers=[StudioSpeaker("S01"), StudioSpeaker("S02")],
        cues=[
            StudioCue("a", 1000, 3000, "a", speaker_id="S01"),
            StudioCue("b", 4000, 5000, "b", speaker_id="S02"),
        ],
    )
    timeline = WaveformTimeline()
    timeline.resize(1000, 360)
    timeline.set_project(project)
    timeline.set_visible_window(0, 10_000)
    speaker_rects, _translation, _waveform = timeline._track_layout()
    changes = []
    timeline.timing_edit_committed.connect(changes.append)
    origin = QPoint(round(timeline._time_to_x(2_000)), round(speaker_rects["S01"].center().y()))
    target = QPoint(origin.x(), round(speaker_rects["S02"].center().y()))
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=origin)
    QTest.mouseMove(timeline, target, delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=target)
    assert len(changes)==1 and (changes[0]["a"].start_ms,changes[0]["a"].end_ms,changes[0]["a"].speaker_id) == (1000,3000,"S02")
    timeline.deleteLater()


def test_p237_t_key_adds_selected_editable_cue(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.timeline.playhead_ms = 4_000
    before = len(page.project.cues)
    page._dispatch_shortcut_sequence("T")
    app.processEvents()
    assert len(page.project.cues) == before + 1
    assert page._canvas_editor is page.subtitle_edit_input
    assert not page.subtitle_edit_card.isHidden()
    created_id = page.selected_cue_id
    page.undo_stack.undo()
    assert all(cue.id != created_id for cue in page.project.cues)
    page.close_page()
    page.deleteLater()


def _app():
    return QApplication.instance() or QApplication([])


def _path(tmp_path):
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=120_000),
        cues=[
            StudioCue("a", 0, 1200, "第一句", speaker_id="S01", original_text="第一句"),
            StudioCue("b", 1500, 3000, "第二句", speaker_id="S02", original_text="第二句"),
        ],
    )
    return save_project(project, tmp_path / "studio.2byteproj")


def test_large_timeline_indexes_only_viewport_cues_and_maps_rows_directly():
    _app()
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=18_000_000),
        cues=[
            StudioCue(
                f"cue-{index}",
                index * 1_800,
                index * 1_800 + 1_300,
                f"字幕 {index}",
                speaker_id=f"S{index % 4:02d}",
            )
            for index in range(10_000)
        ],
    )
    timeline = WaveformTimeline()
    timeline.set_project(project)
    timeline.set_visible_window(9_000_000, 60_000)
    visible = timeline.visible_cues()

    assert 30 <= len(visible) <= 35
    assert all(cue.end_ms > 9_000_000 and cue.start_ms < 9_060_000 for cue in visible)

    model = CueTableModel(project)
    assert model.row_for_cue_id("cue-9999") == 9999
    changed_columns = []
    model.dataChanged.connect(
        lambda top_left, bottom_right, *_roles: changed_columns.append(
            (top_left.column(), bottom_right.column())
        )
    )
    project.cues[-1].text = "局部刷新"
    model.refresh_cue("cue-9999", (3, 4))
    assert model.data(model.index(9999, 3)) == "局部刷新"
    assert changed_columns == [(3, 3), (4, 4)]
    timeline.deleteLater()


def test_long_project_open_keeps_timeline_viewport_bounded(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=18_000_000),
        cues=[
            StudioCue(f"cue-{index}", index * 1_800, index * 1_800 + 1_300, f"字幕 {index}")
            for index in range(10_000)
        ],
    )
    path = save_project(project, tmp_path / "long.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)

    assert page.timeline.visible_duration_ms == 60_000
    assert len(page.timeline.visible_cues()) <= 35
    page.close_page()
    page.deleteLater()


def test_stale_background_results_return_to_debounce(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._ass_generation = 4
    page._ass_worker_running = True
    page._autosave_generation = 7
    page._autosave_worker_running = True
    monkeypatch.setattr(
        page,
        "_start_ass_worker",
        lambda *_args: (_ for _ in ()).throw(AssertionError("stale ASS restarted immediately")),
    )
    monkeypatch.setattr(
        page,
        "_start_autosave_worker",
        lambda *_args: (_ for _ in ()).throw(AssertionError("stale autosave restarted immediately")),
    )

    page._ass_ready(3, str(tmp_path / "stale.ass"))
    page._autosave_ready(6)

    assert page._preview_timer.isActive()
    assert page._autosave_timer.isActive()
    page._preview_timer.stop()
    page._autosave_timer.stop()
    page.deleteLater()


def test_open_project_recovers_newer_autosave_and_save_commits_it(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = _path(tmp_path)
    autosaved = load_project(path)
    autosaved.cues[0].text = "强退前修改"
    save_autosave(autosaved, path)

    page = SubtitleStudioPage()
    monkeypatch.setattr(page, "_recovery_choice", lambda _candidate: "recover")
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)

    assert page.project.cues[0].text == "强退前修改"
    assert page._recovered_autosave_pending is True
    assert "自动保存" in page.save_state.text() and "恢复" in page.save_state.text()
    page.save()
    assert page._recovered_autosave_pending is False
    assert load_project(path).cues[0].text == "强退前修改"
    page.close_page()
    page.deleteLater()


def test_formal_save_waits_for_running_autosave(tmp_path, monkeypatch):
    _app()
    page = SubtitleStudioPage()
    page.project = SubtitleProject(
        media=StudioMedia(str(tmp_path / "video.mp4")),
        cues=[StudioCue("cue-1", 0, 1000, "最新文本")],
    )
    page.project_path = tmp_path / "ordered.2byteproj"
    autosave_started = threading.Event()
    release_autosave = threading.Event()
    write_order = []
    real_save_project = studio_ui.save_project

    def blocking_autosave(_project, _path):
        autosave_started.set()
        assert release_autosave.wait(2)
        write_order.append("autosave")

    def tracked_formal_save(project, path):
        write_order.append("formal")
        return real_save_project(project, path)

    monkeypatch.setattr(studio_ui, "save_autosave", blocking_autosave)
    monkeypatch.setattr(studio_ui, "save_project", tracked_formal_save)
    page._start_autosave_worker(1)
    assert autosave_started.wait(2)
    page._autosave_timer.start()
    threading.Timer(0.05, release_autosave.set).start()

    page.save()

    assert write_order == ["autosave", "formal"]
    assert not page._autosave_timer.isActive()
    assert load_project(page.project_path).cues[0].text == "最新文本"
    page.close_page()
    page.deleteLater()


def test_relink_mismatch_requires_explicit_confirmation(tmp_path, monkeypatch):
    _app()
    page = SubtitleStudioPage()
    original = tmp_path / "missing.mp4"
    candidate = tmp_path / "different.mp4"
    candidate.write_bytes(b"candidate")
    page.project = SubtitleProject(
        media=StudioMedia(str(original), duration_ms=120_000, fingerprint="expected")
    )
    monkeypatch.setattr(
        studio_project_controller.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(candidate), ""),
    )
    monkeypatch.setattr(
        studio_project_flow,
        "probe_media_identity",
        lambda _path: {"duration_ms": 30_000, "fingerprint": "different"},
    )
    monkeypatch.setattr(
        studio_project_flow,
        "studio_message_box",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )

    page._relink_media()
    assert page.project.media.path == str(original)
    warning = media_relink_warning(
        page.project.media, {"duration_ms": 30_000, "fingerprint": "different"}
    )
    assert "时长不一致" in warning and "指纹不一致" in warning
    page.deleteLater()


def test_studio_page_load_edit_undo_and_drawers(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1366, 768)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()

    assert page.project is not None
    assert page.selected_cue_id == "a"
    assert page.cue_model.rowCount() == 2
    assert page.cue_text.toPlainText() == "第一句"

    page.cue_text.setPlainText("人工修正")
    app.processEvents()
    assert page.project.cues[0].text == "人工修正"
    assert page.undo_stack.canUndo()
    page.undo_stack.undo()
    assert page.project.cues[0].text == "第一句"

    assert page.context_drawer.isVisible()
    page.context_drawer.setCurrentIndex(2)
    page._collapse_context_panel()
    assert not page.context_panel.isVisible()
    assert page.context_expand_button.isVisible()
    page._toggle_drawer(0)
    assert page.context_panel.isVisible()
    assert page.context_drawer.currentIndex() == 0
    page.context_drawer.setCurrentIndex(2)
    page._collapse_context_panel()
    page._show_context_panel()
    assert page.context_drawer.currentIndex() == 2
    page._toggle_cue_list()
    assert not page.cue_table.isVisible()
    page.close_page()
    page.deleteLater()


def test_editor_defaults_collapsed_and_keeps_metadata_reachable(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()

    assert not page.cue_text.isVisibleTo(page)
    assert page.ai_optimize_button in page._timeline_overflow_widgets
    assert page.cue_more_button.isVisibleTo(page)
    assert not page.speaker.isVisibleTo(page)
    assert not page.start_ms.isVisibleTo(page)
    assert not page.duration_ms.isVisibleTo(page)
    assert not page.mono_button.isVisibleTo(page)

    page._show_current_cue_settings()
    assert page.cue_text.isVisibleTo(page)
    assert page.speaker.isVisibleTo(page)
    assert page.start_ms.isVisibleTo(page)
    assert page.duration_ms.isVisibleTo(page)

    page._set_bilingual_mode(True)
    assert page.project.studio_state["bilingual_mode"] is True
    assert page.bilingual_display_action.isChecked()
    assert page.translation_text.isVisibleTo(page)
    page.close_page()
    page.deleteLater()


def test_p2211_style_scope_is_compact_radio_selector(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()

    assert page.style_scope.currentData() == "current"
    speaker_index = page.style_scope.findData("speaker")
    page.style_scope.setCurrentIndex(speaker_index)
    assert page.style_scope.currentIndex() == speaker_index
    assert page.style_scope.currentData() == "speaker"
    assert len(page.style_scope.findChildren(QRadioButton)) == 4

    page.close_page()
    page.deleteLater()


def test_studio_layout_keeps_video_editor_and_waveform_visible_at_768p(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1180, 650)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()

    sizes = page.workspace_splitter.sizes()
    assert len(sizes) == 2
    assert sizes[0] >= 220
    assert sizes[1] >= 210
    # The pinned V1+A1 linked group adds one compact 36px audio lane; the
    # timeline floor keeps the editor and cue list usable at 768p.
    assert page.timeline.minimumHeight() <= 240
    assert page.timeline.minimumHeight() >= 160
    assert page.cue_list_panel.isVisible()
    assert page.context_panel.isVisible()
    assert page.cue_table.model().rowCount() == 2
    assert page.cue_table.indexWidget(page.cue_model.index(0, 4)) is None
    page.close_page()
    page.deleteLater()


def test_p202_context_tabs_timeline_tools_and_splitters(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1600, 900)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()

    drawer = page.context_drawer
    assert drawer.count() == 5
    expected = ("AI设计", "样式", "视频", "剪辑助手", "素材")
    # Full names stay reachable through tooltips in every width tier.
    assert [drawer.tabToolTip(index) for index in range(5)] == list(expected)
    # Widening the panel past the full-label threshold restores readable
    # labels; narrowing it again falls back to the icon-only tier. Both
    # transitions must work from splitter drags, not only page resizes.
    page.upper_splitter.setSizes([300, 660, 520])
    app.processEvents()
    assert [drawer.tabText(index) for index in range(5)] == list(expected)
    page.upper_splitter.setSizes([360, 860, 360])
    app.processEvents()
    assert [drawer.tabText(index) for index in range(5)] == [""] * 5
    assert not page.context_drawer.tabBar().usesScrollButtons()
    for index in range(3):
        area = page.context_drawer.widget(index)
        assert isinstance(area, QScrollArea)
        assert area.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff

    splitters = (page.workspace_splitter, page.upper_splitter, page.center_splitter)
    assert all(isinstance(splitter, QSplitter) for splitter in splitters)
    assert all(not splitter.childrenCollapsible() for splitter in splitters)
    assert all(splitter.handleWidth() >= 5 for splitter in splitters)

    tooltips = {
        button.toolTip() for button in page.findChildren(QToolButton) if button.toolTip()
    }
    assert "拆分当前字幕 (Ctrl+Shift+S)" in tooltips
    assert "与下一条合并 (Ctrl+Shift+M)" in tooltips
    assert "删除当前字幕 (Delete)" in tooltips

    page.context_drawer.setCurrentIndex(2)
    page._collapse_context_panel()
    page.workspace_splitter.setSizes([510, 330])
    page.upper_splitter.setSizes([410, 760, 390])
    page.center_splitter.setSizes([430, 170])
    page._capture_studio_state()
    layout = page.project.studio_state["layout"]
    assert layout["context_collapsed"] is True
    assert layout["context_tab"] == 3
    assert layout["context_tab_id"] == "video"
    assert len(layout["workspace_sizes"]) == 2
    assert len(layout["upper_sizes"]) == 3
    assert len(layout["center_sizes"]) == 1
    page.close_page()
    page.deleteLater()


def test_p20_cue_list_filters_bilingual_mode_and_speaker_tracks(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.project.generation_metadata["translations"] = {"a": "First line"}
    page._set_bilingual_mode(True)
    page.select_cue("a")
    app.processEvents()

    assert not page.translation_text.isHidden()
    assert page.translation_text.toPlainText() == "First line"
    assert page.timeline.bilingual
    # Speaker tracks are ordered from least speech at the top to the primary
    # (most speech) track directly above the waveform.
    assert page.timeline.speaker_ids() == ["S01", "S02"]
    page._set_cue_filter("pending")
    assert page.cue_model.rowCount() == 2
    page.cue_search.setText("第二")
    assert page.cue_model.rowCount() == 1
    page.close_page()
    page.deleteLater()


def test_style_scope_applies_to_speaker_and_undoes_atomically(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.project.cues.append(
        StudioCue("c", 3200, 4000, "第三句", speaker_id="S01", original_text="第三句")
    )
    page._updating_style_ui=True
    page.style_scope.setCurrentIndex(page.style_scope.findData("speaker"))
    page.style_preset.setCurrentIndex(page.style_preset.findData("game"))
    page.effect_preset.setCurrentText("Fade")
    page._updating_style_ui=False
    page._apply_style()
    app.processEvents()
    first, second, third = page.project.cues
    assert first.style_id.startswith("game") and first.effect_id == "fade"
    assert (second.style_id, second.effect_id) == ("default", "none")
    assert third.style_id.startswith("game") and third.effect_id == "fade"
    page.undo_stack.undo()
    assert all(cue.style_id == "default" and cue.effect_id == "none" for cue in page.project.cues)
    page.close_page()
    page.deleteLater()


def test_selected_style_scope_isolated_from_unselected_cues(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page._timeline_selection_changed({"a"})
    page.style_scope.setCurrentIndex(page.style_scope.findData("selected"))
    page.style_font_size.setValue(101)
    page._commit_style_now()
    assert page.project.cues[0].style_id.startswith("default-scope-")
    assert page.project.cues[1].style_id == "default"
    page.undo_stack.undo()
    assert all(cue.style_id == "default" for cue in page.project.cues)
    page.close_page()
    page.deleteLater()


def test_style_inspector_updates_project_style_and_undoes(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.select_cue("a")
    original_default_font = next(
        item.font_family for item in page.project.styles if item.id == "default"
    )

    page._updating_style_ui = True
    try:
        page.style_font.setEditText("Arial")
        page.style_font_size.setValue(61.0)
        page.style_spacing.setValue(2)
        page.style_bold.setChecked(True)
        page.style_italic.setChecked(True)
        page.style_underline.setChecked(True)
        page.style_alignment.setCurrentIndex(page.style_alignment.findData(8))
        page.style_position_x.setValue(640)
        page.style_position_y.setValue(96)
        page.style_margin_l.setValue(22)
        page.style_margin_r.setValue(24)
        page.style_margin_v.setValue(36)
        page.style_fill_color.setText("#F0E0D0")
        page.style_outline_color.setText("#102030")
        page.style_outline_width.setValue(4.5)
        page.style_shadow.setValue(2.0)
        page.style_background.setChecked(True)
        page.style_back_color.setText("#403020")
    finally:
        page._updating_style_ui = False

    page._apply_style()
    app.processEvents()
    style = next(
        item for item in page.project.styles
        if item.id == page.project.cues[0].style_id
    )
    assert (
        style.font_family,
        style.font_size,
        style.spacing,
        style.bold,
        style.italic,
        style.underline,
        style.alignment,
        style.position_x,
        style.position_y,
        style.margin_l,
        style.margin_r,
        style.margin_v,
        style.primary_color,
        style.outline_color,
        style.outline_width,
        style.shadow,
        style.border_style,
        style.back_color,
    ) == (
            "Arial", 61.0, 2.0, True, True, True, 8, 640, 96, 22, 24, 36,
        "#F0E0D0", "#102030", 4.5, 2.0, 3, "#403020",
    )
    page.undo_stack.undo()
    restored = next(item for item in page.project.styles if item.id == "default")
    assert restored.font_family == original_default_font
    assert restored.border_style == 1
    assert page.project.cues[0].style_id == "default"
    page.close_page()
    page.deleteLater()


def test_style_position_and_common_color_survive_save_and_compile(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    path = _path(tmp_path)
    page.open_project(path)
    page.select_cue("a")

    page._updating_style_ui = True
    page.style_position_x.setValue(730)
    page.style_position_y.setValue(880)
    page._updating_style_ui = False
    page._set_style_color(page.style_fill_color, "#F2A65A")
    app.processEvents()
    page.save()

    loaded = load_project(path)
    style = next(
        item for item in loaded.styles
        if item.id == loaded.cues[0].style_id
    )
    assert (style.position_x, style.position_y, style.primary_color) == (730, 880, "#F2A65A")
    from twobyteasr.rendering.ass_compiler import compile_ass
    from twobyteasr.rendering.ass_font_units import ass_font_style
    from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
    caption=resolve_caption_style(loaded.styles,loaded.speakers,loaded.cues[0],loaded.style_recipes,1920,1080)
    native=ass_font_style(caption.style,1920,1080,layout=caption.layout)
    assert f"\\pos({round(native.position_x,2):g},{round(native.position_y,2):g})" in compile_ass(loaded)
    page.close_page()
    page.deleteLater()


def test_timeline_inline_editor_stays_inside_short_cue_block():
    _app()
    project = SubtitleProject(
        media=StudioMedia(path="D:/short.mp4", duration_ms=10_000),
        cues=[StudioCue("short", 1000, 1100, "很短的字幕")],
    )
    timeline = WaveformTimeline()
    timeline.resize(900, 300)
    timeline.set_project(project)
    timeline._open_inline_editor(project.cues[0], False, project.cues[0].text)
    assert timeline._inline_editor is not None
    cue_width = round(
        timeline._time_to_x(project.cues[0].end_ms)
        - timeline._time_to_x(project.cues[0].start_ms)
    )
    assert timeline._inline_editor.width() == max(24, cue_width)
    timeline._cancel_inline_edit()
    timeline.deleteLater()


def test_timeline_inline_edit_focus_out_tab_and_undo(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1500, 900)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()

    first = page.project.cues[0]
    page.timeline._open_inline_editor(first, False, first.text)
    editor = page.timeline._inline_editor
    editor.selectAll()
    QTest.keyClicks(editor, "timeline edit")
    QTest.mouseClick(page.timeline, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    app.processEvents()
    assert page.project.cues[0].text == "timeline edit"
    assert page.timeline._inline_editor is None
    page.undo_stack.undo()
    assert page.project.cues[0].text == "第一句"

    page.timeline._open_inline_editor(first, False, first.text)
    QTest.keyClick(page.timeline._inline_editor, Qt.Key.Key_Tab)
    app.processEvents()
    assert page.timeline._inline_target == ("b", False)
    QTest.keyClick(page.timeline._inline_editor, Qt.Key.Key_Escape)
    page.close_page()
    page.deleteLater()


def test_subtitle_list_double_click_edits_through_unified_undo(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1500, 900)
    page.show()
    page.open_project(_path(tmp_path))
    app.processEvents()

    index = page.cue_model.index(0, 3)
    point = page.cue_table.visualRect(index).center()
    QTest.mouseClick(
        page.cue_table.viewport(), Qt.MouseButton.LeftButton, pos=point
    )
    QTest.mouseDClick(
        page.cue_table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=point,
    )
    app.processEvents()
    editor = QApplication.focusWidget()
    assert editor is not page.cue_table
    QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(editor, "list edit")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()

    assert page.project.cues[0].text == "list edit"
    assert page.cue_text.toPlainText() == "list edit"
    page.undo_stack.undo()
    assert page.project.cues[0].text == "第一句"
    page.close_page()
    page.deleteLater()


def test_style_wheel_never_changes_focused_value(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page.show()
    page.context_drawer.setCurrentIndex(2)
    app.processEvents()
    control = page.style_font_size
    control.setValue(52)
    control.setFocus()
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(control, event)
    assert control.value() == 52
    control.clearFocus()
    page.close_page()
    page.deleteLater()


def test_video_position_overlay_commits_one_style_change(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.position_edit_button.setChecked(True)
    before = page.undo_stack.count()

    page._position_overlay_moved(960, 972)
    assert (page.style_position_x.value(), page.style_position_y.value()) == (960, 972)
    assert page.undo_stack.count() == before
    page._position_overlay_committed(960, 972)

    cue = page.project.cues[0]
    cue_style = next(item for item in page.project.styles if item.id == cue.style_id)
    resolved = resolve_cue_visual(page.project, cue)
    assert (cue.transform["position_x"], cue.transform["position_y"]) == (960, 972)
    assert (resolved.style.position_x, resolved.style.position_y) == (960, 972)
    assert (cue_style.position_x, cue_style.position_y) == (None, None)
    assert cue.style_id == "default"
    assert page.project.cues[1].style_id == "default"
    assert page.undo_stack.count() == before + 1
    page.close_page()
    page.deleteLater()


def test_video_position_overlay_maps_and_snaps_video_coordinates():
    _app()
    from PySide6.QtCore import QPoint

    overlay = SubtitlePositionOverlay()
    overlay.resize(960, 540)
    overlay.set_video_position(100, 100, 1920, 1080)
    assert overlay._video_point(QPoint(486, 486)) == (960, 972)
    overlay.deleteLater()


def test_video_position_overlay_uses_ass_alignment_anchor():
    _app()
    overlay = SubtitlePositionOverlay()
    overlay.resize(960, 540)
    overlay.set_video_position(960, 540, 1920, 1080)

    expected_anchor = {
        1: ("left", "bottom"),
        2: ("center", "bottom"),
        3: ("right", "bottom"),
        4: ("left", "center"),
        5: ("center", "center"),
        6: ("right", "center"),
        7: ("left", "top"),
        8: ("center", "top"),
        9: ("right", "top"),
    }
    point = overlay._screen_point()
    for alignment, (horizontal, vertical) in expected_anchor.items():
        overlay.set_font_spec("Arial", 52, alignment=alignment)
        rect = overlay._rendered_text_rect()
        horizontal_value = {
            "left": rect.left(),
            "center": rect.center().x(),
            "right": rect.right(),
        }[horizontal]
        vertical_value = {
            "top": rect.top(),
            "center": rect.center().y(),
            "bottom": rect.bottom(),
        }[vertical]
        assert round(horizontal_value) == point.x()
        assert round(vertical_value) == point.y()
    overlay.deleteLater()


def test_video_position_overlay_left_top_text_and_box_share_one_center():
    _app()
    overlay = SubtitlePositionOverlay()
    overlay.resize(960, 540)
    overlay.set_video_size(1920, 800)
    overlay.set_video_position(120, 90, 1920, 1080)
    overlay.set_text("左上字幕")
    overlay.set_font_spec("Arial", 52, alignment=7, outline_width=3, shadow=2)

    rendered = overlay._rendered_text_rect()
    selection = overlay._subtitle_rect()
    assert selection.contains(rendered)
    assert selection.center().x() == pytest.approx(rendered.center().x())
    assert selection.center().y() == pytest.approx(rendered.center().y())
    assert abs(selection.center().x() - rendered.center().x()) < 1
    assert abs(selection.center().y() - rendered.center().y()) < 1
    overlay.deleteLater()


def test_video_position_overlay_has_eight_screen_space_handles_and_cursors():
    _app()
    overlay = SubtitlePositionOverlay()
    overlay.resize(960, 540)
    overlay.set_video_position(960, 540, 1920, 1080)
    overlay.set_font_spec("Arial", 52, alignment=5)
    centers = overlay._handle_centers(overlay._subtitle_rect())

    assert set(centers) == {"tl", "t", "tr", "r", "br", "b", "bl", "l"}
    assert overlay.HANDLE_VISUAL_SIZE == 11.0
    assert overlay.HANDLE_HIT_SIZE == 16.0
    assert overlay._cursor_for_handle("l") == Qt.CursorShape.SizeHorCursor
    assert overlay._cursor_for_handle("t") == Qt.CursorShape.SizeVerCursor
    assert overlay._cursor_for_handle("tl") == Qt.CursorShape.SizeFDiagCursor
    assert overlay._cursor_for_handle("tr") == Qt.CursorShape.SizeBDiagCursor
    for name, center in centers.items():
        assert overlay._handle_at(center.toPoint()) == name
    overlay.deleteLater()


def test_video_position_overlay_recomputes_multiline_geometry_after_resize():
    _app()
    overlay = SubtitlePositionOverlay()
    overlay.resize(960, 540)
    overlay.set_video_size(1080, 1920)
    overlay.set_video_position(960, 540, 1920, 1080)
    overlay.set_text("第一行\n第二行\n第三行")
    overlay.set_font_spec("Arial", 64, alignment=5, outline_width=4, shadow=3)
    first_content = overlay._content_rect()
    first_anchor = overlay._screen_point()
    first_text = overlay._rendered_text_rect()

    overlay.resize(1440, 810)
    second_content = overlay._content_rect()
    second_anchor = overlay._screen_point()
    second_text = overlay._rendered_text_rect()

    assert first_text.height() > 3 * 10
    assert second_text.height() > first_text.height()
    assert first_anchor == first_content.center().toPoint()
    assert second_anchor == second_content.center().toPoint()
    assert overlay._subtitle_rect().contains(second_text)
    overlay.deleteLater()


@pytest.mark.parametrize(
    ("handle", "delta"),
    [("l", QPoint(-20, 0)), ("r", QPoint(20, 0)), ("t", QPoint(0, -20)), ("b", QPoint(0, 20))],
)
def test_video_position_overlay_edge_handles_uniformly_resize_font(handle, delta):
    _app()
    overlay = SubtitlePositionOverlay()
    overlay.resize(960, 540)
    overlay.set_video_position(960, 540, 1920, 1080)
    overlay.set_font_spec("Arial", 52, alignment=5)
    start = overlay._handle_centers(overlay._subtitle_rect())[handle].toPoint()
    overlay.mousePressEvent(studio_ui.QMouseEvent(
        studio_ui.QMouseEvent.Type.MouseButtonPress,
        QPointF(start),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    overlay.mouseMoveEvent(studio_ui.QMouseEvent(
        studio_ui.QMouseEvent.Type.MouseMove,
        QPointF(start + delta),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    assert overlay._resize_handle == handle
    assert overlay.font_size > 52
    overlay.deleteLater()


def test_video_position_overlay_drags_from_any_body_point_without_jumping():
    _app()
    overlay = SubtitlePositionOverlay()
    overlay.resize(960, 540)
    overlay.set_video_position(960, 540, 1920, 1080)
    overlay.set_font_spec("Arial", 52, alignment=5)
    start = overlay._subtitle_rect().center().toPoint()

    overlay.mousePressEvent(studio_ui.QMouseEvent(
        studio_ui.QMouseEvent.Type.MouseButtonPress,
        QPointF(start),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    assert (overlay.position_x, overlay.position_y) == (960, 540)

    end = start + QPoint(100, 50)
    overlay.mouseMoveEvent(studio_ui.QMouseEvent(
        studio_ui.QMouseEvent.Type.MouseMove,
        QPointF(end),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    assert (overlay.position_x, overlay.position_y) == (1160, 640)
    overlay.deleteLater()


def test_video_position_overlay_all_four_corners_resize_outward():
    _app()
    overlay = SubtitlePositionOverlay()
    overlay.resize(960, 540)
    overlay.set_video_position(960, 540, 1920, 1080)
    overlay.set_font_spec("Arial", 52, alignment=5)
    outward = {
        "tl": QPoint(-20, -20),
        "tr": QPoint(20, -20),
        "bl": QPoint(-20, 20),
        "br": QPoint(20, 20),
    }
    for handle, delta in outward.items():
        overlay.set_font_size(52)
        rect = overlay._subtitle_rect()
        start = {
            "tl": rect.topLeft(),
            "tr": rect.topRight(),
            "bl": rect.bottomLeft(),
            "br": rect.bottomRight(),
        }[handle].toPoint()
        overlay.mousePressEvent(studio_ui.QMouseEvent(
            studio_ui.QMouseEvent.Type.MouseButtonPress,
            QPointF(start),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ))
        assert overlay._resize_handle == handle
        overlay.mouseMoveEvent(studio_ui.QMouseEvent(
            studio_ui.QMouseEvent.Type.MouseMove,
            QPointF(start + delta),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ))
        assert overlay.font_size > 52
        overlay._dragging = False
    overlay.deleteLater()


def test_canvas_style_reload_tracks_current_cue_derived_style(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))

    page._position_overlay_committed(321, 234)
    page._load_style_inspector()

    cue = page.project.cues[0]
    cue_style = next(
        item for item in page.project.styles
        if item.id == cue.style_id
    )
    resolved = resolve_cue_visual(page.project, cue)
    assert cue_style.id == "default"
    assert cue.transform == {"position_x": 321, "position_y": 234}
    assert (resolved.style.position_x, resolved.style.position_y) == (321, 234)
    assert (page.position_overlay.position_x, page.position_overlay.position_y) == (321, 234)
    assert page.position_overlay.alignment == cue_style.alignment
    page.close_page()
    page.deleteLater()


def test_project_restores_and_captures_studio_navigation_state(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = _path(tmp_path)
    project = SubtitleProject.from_dict(
        __import__("json").loads(path.read_text(encoding="utf-8"))
    )
    project.studio_state = {
        "last_selected_cue": "b",
        "playhead_ms": 2500,
        "zoom": 2.0,
        "scroll_ms": 1000,
        "layout": {
            "upper_sizes": [390, 720, 390],
            "workspace_sizes": [520, 280],
            "center_sizes": [360, 160],
            "context_collapsed": True,
            "context_tab": 3,
        },
    }
    save_project(project, path)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    app.processEvents()
    assert page.selected_cue_id == "b"
    assert page.timeline.playhead_ms == 2500
    assert page.timeline.visible_duration_ms == 60_000
    assert page.timeline.visible_start_ms == 1000
    assert page.context_drawer.currentIndex() == 2
    assert not page.context_panel.isVisible()
    page._show_context_panel()
    assert page.context_drawer.currentIndex() == 2
    page.timeline.set_playhead(2800)
    page.timeline.visible_start_ms = 1500
    page._capture_studio_state()
    assert page.project.studio_state["playhead_ms"] == 2800
    assert page.project.studio_state["scroll_ms"] == 1500
    page.close_page()
    page.deleteLater()


def test_recent_projects_store_structured_metadata_and_read_legacy_paths(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = _path(tmp_path)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)

    records = page.recent_project_records()
    assert records[0]["path"] == str(path.resolve())
    assert records[0]["source_media"].endswith("video.mp4")
    assert records[0]["cue_count"] == 2
    assert records[0]["status"] == "已保存"
    assert page.most_recent_project() == str(path.resolve())
    page.close_page()
    page.deleteLater()


def test_p203_trim_razor_follow_and_shortcut_registry(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))

    page.timeline.set_playhead(400)
    page._trim_to_playhead("start")
    assert page.project.cues[0].start_ms == 400
    page.timeline.set_playhead(1000)
    page._trim_to_playhead("end")
    assert page.project.cues[0].end_ms == 1000
    page.undo_stack.undo()
    assert page.project.cues[0].end_ms == 1200

    page._set_timeline_tool("razor")
    assert page.timeline.tool_mode == "razor"
    page._split_at("a", 800)
    assert len(page.project.cues) == 3
    page.undo_stack.undo()
    assert len(page.project.cues) == 2

    page.select_cue("a")
    page._position_changed(1.7)
    assert page.selected_cue_id == "a"  # Playback never steals the editing selection.
    assert set(page._shortcut_values) == set(__import__("twobyteasr.studio.studio_ui", fromlist=["STUDIO_COMMANDS"]).STUDIO_COMMANDS)
    app.processEvents()
    page.close_page()
    page.deleteLater()


def test_timeline_tool_switch_changes_cursor_without_repainting_content(monkeypatch):
    app = _app()
    paints = []
    monkeypatch.setattr(WaveformTimeline, "update", lambda self, *args: paints.append(args))
    timeline = WaveformTimeline()

    timeline.set_tool_mode("razor")
    timeline.set_tool_mode("razor")
    timeline.set_tool_mode("selection")

    assert timeline.tool_mode == "selection"
    assert paints == []
    timeline.deleteLater()
    app.processEvents()


def test_p204_window_shortcuts_cross_non_editing_focus_and_preserve_text_space(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.resize(1366, 768)
    page.show()
    page.activateWindow()
    QApplication.setActiveWindow(page)
    app.processEvents()

    dispatched = []
    page._command_callbacks["play_pause"] = lambda: dispatched.append("space")
    for widget in (page.video, page.timeline, page.cue_table, page.context_drawer.tabBar()):
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
        QTest.keyClick(widget, Qt.Key.Key_Space)
        QTest.qWait(90)
    assert dispatched == ["space"] * 4

    page.cue_text.setPlainText("")
    page.cue_text.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(page.cue_text, Qt.Key.Key_Space)
    assert page.cue_text.toPlainText() == " "
    assert dispatched == ["space"] * 4

    page.close_page()
    page.deleteLater()


def test_p204_shortcut_rebind_is_immediate(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page.resize(900, 700)
    page.show()
    page.activateWindow()
    QApplication.setActiveWindow(page)
    app.processEvents()

    page._shortcut_values["play_pause"] = "P"
    page._install_shortcuts()
    dispatched = []
    page._command_callbacks["play_pause"] = lambda: dispatched.append("play")
    page.timeline.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(page.timeline, Qt.Key.Key_Space)
    QTest.keyClick(page.timeline, Qt.Key.Key_P)
    assert dispatched == ["play"]

    page.close_page()
    page.deleteLater()


def test_p204_shortcut_rebind_persists_across_studio_instances(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    first = SubtitleStudioPage()
    first._shortcut_values["play_pause"] = "P"
    first._save_shortcut_values()
    first.close_page()
    first.deleteLater()

    reopened = SubtitleStudioPage()
    assert reopened._shortcut_values["play_pause"] == "P"
    assert reopened._shortcut_lookup["P"] == "play_pause"
    reopened.close_page()
    reopened.deleteLater()


def test_p204_delete_selects_valid_fallback_and_undo_restores_cue(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.select_cue("a")

    page._delete_current()
    assert [cue.id for cue in page.project.cues] == ["b"]
    assert page.selected_cue_id == "b"
    page.undo_stack.undo()
    assert [cue.id for cue in page.project.cues] == ["a", "b"]
    assert page.selected_cue_id == "a"  # Undo restores the pre-delete selection.

    page.close_page()
    page.deleteLater()


def test_p205_timeline_scroll_follow_and_inline_edit_undo(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1600, 900)
    page.show()
    page.open_project(_path(tmp_path))
    page.timeline.set_visible_window(5_000, 10_000)
    app.processEvents()

    scrollbar = page.timeline.horizontal_scrollbar
    assert scrollbar.isVisible()
    assert scrollbar.maximum() == 110_000
    assert scrollbar.pageStep() == 10_000
    assert page.timeline.reveal_playhead(14_000) is True
    assert page.timeline.visible_start_ms > 5_000
    unchanged = page.timeline.visible_start_ms
    assert page.timeline.reveal_playhead(page.timeline.visible_start_ms + 4_000) is False
    assert page.timeline.visible_start_ms == unchanged

    cue = page.project.cues[0]
    page.timeline._open_inline_editor(cue, False, cue.text)
    assert page.timeline._inline_editor is not None
    page.timeline._inline_editor.setText("时间轴直接修改")
    page.timeline._commit_inline_edit()
    assert cue.text == "时间轴直接修改"
    assert page.cue_text.toPlainText() == "时间轴直接修改"
    page.undo_stack.undo()
    assert cue.text == "第一句"
    page.close_page()
    page.deleteLater()


def test_p205_workspace_and_editor_field_visibility_persist(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page._set_major_panel_visible("cue_list", False)
    page._set_major_panel_visible("editor", False)
    page._set_editor_field_visible("start", False)
    page._capture_studio_state()

    layout = page.project.studio_state["layout"]
    assert layout["cue_list_visible"] is False
    assert layout["editor_visible"] is False
    assert layout["editor_fields"]["start"] is False
    assert not page.cue_list_panel.isVisible()
    assert not page.cue_editor.isVisible()
    page.close_page()
    page.deleteLater()


def test_project_open_restores_playhead_with_atomic_loadfile_start(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()

    class Controller:
        running = True

        def __init__(self):
            self.loads = []
            self.load_ats = []

        def set_paused(self, _value):
            pass

        def load(self, media_path):
            self.loads.append(media_path)

        def post_load_at(self, media_path, seconds, *, generation):
            self.load_ats.append((media_path, seconds, generation))
            return True

    controller = Controller()
    page.video.controller = controller
    media = str(tmp_path / "source.mp4")

    page.video.load(media, "", start_seconds=6.5)
    # The restore is one atomic loadfile-with-start command, never a bare
    # loadfile followed by a seek that mpv can drop during file init.
    assert controller.loads == []
    assert len(controller.load_ats) == 1
    assert controller.load_ats[0][0] == media
    assert controller.load_ats[0][1] == 6.5

    page.video.load(media, "")
    assert controller.loads == [media]

    page.video.controller = None
    page.close_page()
    page.deleteLater()


def test_p205_l_shuttle_steps_and_k_resets(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    # This is a controller-only fixture, with no project/media graph. The
    # normal buffered-play preparation belongs to the real-media audit.
    monkeypatch.setattr(page.video, "playback_prepare", None)
    monkeypatch.setattr(page.video, "playback_ready", None)

    class Controller:
        running = True

        def __init__(self):
            self.speeds = []
            self.paused = []

        def set_speed(self, value):
            self.speeds.append(value)

        def set_paused(self, value):
            self.paused.append(value)

    controller = Controller()
    page.video.controller = controller
    for _ in range(4):
        page._shuttle(1)
    assert controller.speeds == [1.0, 2.0, 4.0, 8.0]
    page._shuttle(0)
    page._shuttle(1)
    assert controller.speeds[-1] == 1.0
    assert float(page.speed_box.currentData()) == 1.0
    page.video.controller = None
    page.close_page()
    page.deleteLater()


def test_p213_ruler_click_and_drag_seek():
    app = _app()
    timeline = WaveformTimeline()
    timeline.resize(1000, 300)
    timeline.set_project(
        SubtitleProject(
            media=StudioMedia(path="D:/synthetic.mp4", duration_ms=120_000),
            cues=[],
        )
    )
    timeline.set_visible_window(20_000, 30_000)
    timeline.show()
    app.processEvents()
    seeks = []
    timeline.seek_requested.connect(seeks.append)
    click = QPoint(620, 15)
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=click)
    assert len(seeks) == 1
    assert 20.0 < seeks[0] < 50.0

    before = timeline.visible_start_ms
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(700, 15))
    QTest.mouseMove(timeline, QPoint(580, 15), delay=10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(580, 15))
    assert timeline.visible_start_ms == before
    assert len(seeks) >= 2
    assert seeks[-1] < seeks[-2]
    timeline.deleteLater()


def test_p213_style_defaults_to_current_and_fill_entry_has_no_menu(monkeypatch):
    _app()
    page = SubtitleStudioPage()
    assert page.style_scope.currentData() == "current"
    assert not page.style_anchor_buttons
    swatch = page.style_fill_swatch.findChild(QToolButton)
    assert swatch is not None and swatch.menu() is None
    opened = []
    monkeypatch.setattr(page, "_open_fill_editor", lambda: opened.append(True))
    swatch.click()
    assert opened == [True]
    page.close_page()
    page.deleteLater()


def test_p213_pause_preserves_speed_and_speed_ui(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()

    class Controller:
        running = True

        def __init__(self):
            self.speed = 1.0
            self.paused = False

        def set_speed(self, value):
            self.speed = float(value)

        def set_paused(self, value):
            self.paused = bool(value)

        def get_property(self, name, default=None):
            return {"pause": self.paused, "speed": self.speed}.get(name, default)

    controller = Controller()
    page.video.controller = controller
    page.video._playback_clock.set_local_state(
        0.0, paused=False, reason="fixture_playing_state"
    )
    page._set_speed(4.0)
    page._toggle_playback()
    assert controller.paused
    assert controller.speed == 4.0
    assert float(page.speed_box.currentData()) == 4.0
    page.video.controller = None
    page.close_page()
    page.deleteLater()


def test_p213_effect_duration_is_persisted_in_real_effect_data(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(_path(tmp_path))
    page.style_scope.setCurrentIndex(page.style_scope.findData("current"))
    page.effect_preset.setCurrentIndex(page.effect_preset.findData("fade"))
    page.effect_duration.setValue(420)
    page._commit_style_now()
    assert page.project.effects["fade"]["entry"]["duration"] == 420
    assert page.project.effects["fade"]["exit"]["duration"] == 420
    assert page.project.cues[0].effect_id == "fade"
    page.close_page()
    page.deleteLater()


def test_p212_playback_clock_clamps_at_duration_and_marks_eof():
    _app()
    canvas = MpvCanvas()
    canvas._duration = 18.0
    canvas._set_interpolation_base(17.999, paused=False, rate=8.0)
    canvas._clock = type(
        "Clock",
        (),
        {"elapsed": lambda self: 250, "restart": lambda self: None},
    )()

    assert canvas.visual_position() == 18.0
    canvas._visual_tick()
    assert canvas.at_eof
    assert canvas._paused
    assert canvas._base_time == 18.0
    canvas.deleteLater()


def test_mpv_canvas_reports_display_aspect_for_overlay_content_rect():
    _app()

    class Controller:
        running = True

        def get_property(self, name, default=None):
            return {
                "video-out-params": {"dw": 1920, "dh": 800},
                "duration": 8.0,
                "pause": True,
                "speed": 1.0,
                "eof-reached": False,
                "idle-active": False,
                "time-pos": 1.0,
            }.get(name, default)

    canvas = MpvCanvas()
    canvas.controller = Controller()
    sizes = []
    canvas.video_display_size_changed.connect(
        lambda width, height: sizes.append((width, height))
    )
    canvas._reconcile_position()

    assert sizes == [(1920, 800)]
    assert canvas._video_display_size == (1920, 800)
    canvas.deleteLater()


def test_p73b_speed_change_keeps_presentation_clock_and_uses_fast_sync():
    _app()

    class Controller:
        running = True

        def __init__(self):
            self.speed = 1.0

        def get_property(self, name, default=None):
            return {"time-pos": 7.25, "speed": self.speed}.get(name, default)

        def set_speed(self, value):
            self.speed = float(value)

    canvas = MpvCanvas()
    canvas.controller = Controller()
    canvas.set_speed(8.0)

    assert canvas._base_time == 0.0
    assert canvas.playback_position_snapshot().source == "local_speed_state"
    assert canvas._playback_rate == 8.0
    assert canvas._sync_timer.interval() == 50
    canvas.controller = None
    canvas.deleteLater()


def test_p212_space_at_eof_seeks_zero_and_replays(monkeypatch):
    _app()
    page = SubtitleStudioPage()

    class Controller:
        running = True

    page.video.controller = Controller()
    page.video._duration = 18.0
    page.video._eof_reached = True
    calls = []
    monkeypatch.setattr(page.video, "seek", lambda value, accurate=True, **kwargs: calls.append(("seek", value, accurate)))
    monkeypatch.setattr(page.video, "set_paused", lambda value, **kwargs: calls.append(("pause", value)))

    page._toggle_playback()

    assert calls == [("seek", 0.0, True), ("pause", False)]
    page.video.controller = None
    page.close_page()
    page.deleteLater()


def test_p212_ruler_and_middle_drag_pan_without_seeking():
    _app()
    timeline = WaveformTimeline()
    timeline.resize(1000, 300)
    timeline.set_project(
        SubtitleProject(media=StudioMedia(path="D:/video.mp4", duration_ms=120_000))
    )
    timeline.set_visible_window(30_000, 20_000)
    timeline.show()
    seeks = []
    timeline.seek_requested.connect(seeks.append)

    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos=QPoint(700, 12))
    QTest.mouseMove(timeline, QPoint(600, 12))
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos=QPoint(600, 12))
    after_ruler = timeline.visible_start_ms
    assert after_ruler > 30_000

    QTest.mousePress(timeline, Qt.MouseButton.MiddleButton, pos=QPoint(700, 100))
    QTest.mouseMove(timeline, QPoint(780, 100))
    QTest.mouseRelease(timeline, Qt.MouseButton.MiddleButton, pos=QPoint(780, 100))
    assert timeline.visible_start_ms < after_ruler
    assert seeks == []
    timeline.deleteLater()
