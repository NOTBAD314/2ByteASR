import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from twobyteasr.rendering.advanced_preview import AdvancedPreviewCache
from twobyteasr.rendering.advanced_renderer import advanced_preview_cache_key, split_renderer_cues
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.exports.studio_render import STAGE_ENCODE, export_progress
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.design.studio_theme import SURFACE_DARK_PREVIEW, TEXT_PRIMARY
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def _app():
    return QApplication.instance() or QApplication([])


def _studio(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "media.mp4"), duration_ms=10_000, width=1920, height=1080),
        cues=[StudioCue("a", 0, 3_000, "原文", style_id="Default")],
    )
    path = save_project(project, tmp_path / "inline.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    page.show()
    page._begin_canvas_inline_edit()
    app.processEvents()
    return app, page


def test_inline_editor_e_not_commit(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    editor = page._canvas_editor
    before = page.undo_stack.count()
    key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_E, Qt.KeyboardModifier.NoModifier, "e")
    assert not page.eventFilter(editor, key)
    editor.setPlainText(editor.toPlainText() + "e")
    app.processEvents()
    assert page._canvas_editor is editor
    assert editor.toPlainText().endswith("e")
    assert page.undo_stack.count() == before
    page.close_page(); page.deleteLater()


def test_inline_editor_enter_commit(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    page._canvas_editor.setPlainText("已提交")
    key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r")
    assert page.eventFilter(page._canvas_editor, key)
    app.processEvents()
    assert page._canvas_editor is None
    assert page.project.cues[0].text == "已提交"
    page.close_page(); page.deleteLater()


def test_inline_editor_window_press_is_not_a_widget_press(tmp_path, monkeypatch):
    # 2026-10-22 report-eb10: Qt delivers a press to the top-level QWindow
    # first. isAncestorOf(QWindow) raised TypeError (~2 s each in the frozen
    # app); the QWindow press must neither raise nor commit the edit.
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    app, page = _studio(tmp_path, monkeypatch)
    editor = page._canvas_editor
    editor.setPlainText("窗口按下")

    def press():
        return QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(2, 2), QPointF(2, 2),
                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)

    window = page.window().windowHandle()
    assert window is not None
    assert not page.eventFilter(window, press())
    app.processEvents()
    assert page._canvas_editor is editor
    assert not page.eventFilter(page.timeline, press())
    app.processEvents()
    assert page._canvas_editor is None
    assert page.project.cues[0].text == "窗口按下"
    page.close_page(); page.deleteLater()


def test_inline_editor_shift_enter_newline(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    editor = page._canvas_editor
    editor.setPlainText("第一行")
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier, "\n")
    assert not page.eventFilter(editor, key)
    editor.setPlainText(editor.toPlainText() + "\nsecond")
    app.processEvents()
    assert page._canvas_editor is editor
    assert editor.toPlainText() == "第一行\nsecond"
    page.close_page(); page.deleteLater()


def _export_workspace(tmp_path):
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "media.mp4"), duration_ms=40_000, width=1920, height=1080))
    return StudioExportWorkspace(project, str(tmp_path / "preview.ass"))


def test_export_layout_compact(tmp_path):
    _app(); workspace = _export_workspace(tmp_path)
    # The settings pane switches between a compact and a full layout by size.
    workspace.resize(1000, 600)
    workspace._apply_responsive_layout()
    assert workspace.settings_scroll.maximumWidth() == 460
    assert workspace.settings_scroll.minimumWidth() == 360
    workspace.resize(1400, 900)
    workspace._apply_responsive_layout()
    assert workspace.settings_scroll.maximumWidth() == 680
    assert workspace.settings_scroll.minimumWidth() == 480
    assert workspace.preview_host.maximumHeight() == 410
    assert workspace.queue_button.size().width() == 170
    assert workspace.export_button.size().width() == 220
    workspace.deleteLater()


def test_export_pipeline_stage_state(tmp_path):
    _app(); workspace = _export_workspace(tmp_path)
    workspace._last_job = SimpleNamespace(output_path=str(tmp_path / "partial.mp4"))
    workspace._advanced_route = False
    workspace._apply_progress(40, export_progress(
        STAGE_ENCODE, out_time_us="10000000", fps="30", speed="2.0x", indeterminate=False,
    ))
    assert workspace._pipeline_stage_states[0] == ("complete", "complete", "running", "waiting")
    encode_label=next(widget for widget,(key,_name) in zip(workspace.render_stage_labels,workspace._stage_specs) if key==STAGE_ENCODE)
    assert encode_label.property("stageState") == "running" and not encode_label.isHidden()
    assert "视频编码" in workspace.current_stage_title.text()
    workspace.deleteLater()


def test_export_success_actions_differ(tmp_path):
    _app()
    output = tmp_path / "result.mp4"
    output.write_bytes(b"x")
    workspace = _export_workspace(tmp_path)
    previous_dir = workspace._settings.value("render/last_export_directory", "")
    workspace._show_success(str(output))
    workspace._settings.setValue("render/last_export_directory", previous_dir)
    assert workspace.pages.currentWidget() is workspace.success_page
    assert "播放成片" in workspace.open_video_button.text()
    assert "在文件夹中显示" in workspace.open_folder_button.text()
    workspace.deleteLater()


def test_project_card_visual_no_geometry_change(tmp_path, monkeypatch):
    app = _app(); page = SubtitleStudioPage()
    records = [{"path": str(tmp_path / f"p{i}.2byteproj"), "name": f"Project {i}",
                "source_media": str(tmp_path / f"v{i}.mp4"), "cue_count": i + 1,
                "duration_ms": 10_000, "cover_path": ""} for i in range(8)]
    monkeypatch.setattr(page, "_project_library_records", lambda: records)
    page.resize(1600, 1000); page.show(); page._refresh_studio_empty_state(); app.processEvents()
    QTest.qWait(100);app.processEvents()
    before = [(card.size(), card.parentWidget().layout().indexOf(card)) for card in page._hub_card_widgets]
    QTest.mouseMove(page._hub_card_widgets[0]); app.processEvents()
    after = [(card.size(), card.parentWidget().layout().indexOf(card)) for card in page._hub_card_widgets]
    assert len(before) == 8 and before == after
    page.deleteLater()


def _advanced_recipe():
    return {"name": "Cyberpunk HUD", "engine": "remotion",
            "typography": {"fontFamily": "Microsoft YaHei UI", "fontSize": 64},
            "layout": {}, "colors": {"fill": "#FFFFFF"}, "outline": {"width": 3},
            "background": {"marks": ["scanline"]}, "motion": {"entry": {"type": "glitch", "duration": 240}},
            "wordHighlight": {}, "effects": {"glow": {"blur": 12}}}


def test_advanced_preview_cache(tmp_path):
    recipe = _advanced_recipe()
    first = advanced_preview_cache_key(recipe, "字幕", width=640, height=360, fps=30, duration_seconds=1.2, font="A")
    second = advanced_preview_cache_key(recipe, "另一句", width=640, height=360, fps=30, duration_seconds=1.2, font="A")
    assert first != second
    cache = AdvancedPreviewCache(tmp_path)
    cached = cache.path_for(first); cached.parent.mkdir(parents=True, exist_ok=True); cached.write_bytes(b"png")
    key, path, hit = cache.render(recipe, "字幕", font="A")
    assert (key, path, hit) == (first, cached, True)


def test_mixed_native_advanced_render():
    project = SubtitleProject(media=StudioMedia(path="source.mp4", duration_ms=10_000), cues=[
        StudioCue("native-before", 0, 3_000, "NATIVE BEFORE", style_id="Default"),
        StudioCue("advanced", 3_000, 7_000, "ADVANCED", style_id="cyber"),
        StudioCue("native-after", 7_000, 10_000, "NATIVE AFTER", style_id="Default"),
    ])
    project.style_recipes["cyber"] = _advanced_recipe()
    native, advanced = split_renderer_cues(project)
    assert [cue.id for cue in native] == ["native-before", "native-after"]
    assert [cue.id for cue in advanced] == ["advanced"]
    assert not ({cue.id for cue in native} & {cue.id for cue in advanced})


def test_dark_surface_text_contrast():
    def rgb(value):
        return tuple(int(value[index:index + 2], 16) / 255 for index in (1, 3, 5))
    def luminance(value):
        values = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in rgb(value)]
        return .2126 * values[0] + .7152 * values[1] + .0722 * values[2]
    dark, light = luminance(SURFACE_DARK_PREVIEW), luminance("#F1EEE6")
    ratio = (max(dark, light) + .05) / (min(dark, light) + .05)
    assert TEXT_PRIMARY.startswith("#") and ratio >= 4.5
