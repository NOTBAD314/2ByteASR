import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from twobyteasr.rendering.advanced_renderer import compile_composition_data
from twobyteasr.caption_style.font_system import resolve_style_font
from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
    save_project,
)
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.caption_style.style_recipe import StyleRecipe, route_recipe
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _app():
    return QApplication.instance() or QApplication([])


def _studio(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "media.mp4"), duration_ms=10_000, width=1920, height=1080),
        cues=[StudioCue("cue", 0, 3_000, "原文")],
    )
    path = save_project(project, tmp_path / "edit-card.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    page.show()
    app.processEvents()
    return app, page


def test_edit_card_hidden_until_e(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    assert not page.subtitle_edit_card.isVisible()
    page.close_page(); page.deleteLater()


def test_edit_card_e_opens(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    QTest.keyClick(page, Qt.Key.Key_E)
    app.processEvents()
    assert page._canvas_editor is page.subtitle_edit_input
    assert page.subtitle_edit_card.isVisible()
    assert page._canvas_editor.toPlainText() == "原文"
    page.close_page(); page.deleteLater()


def test_edit_card_enter_commit(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    page._begin_canvas_inline_edit()
    page._canvas_editor.setPlainText("可靠提交")
    QTest.keyClick(page._canvas_editor, Qt.Key.Key_Return)
    app.processEvents()
    assert page._canvas_editor is None
    assert page.project.cues[0].text == "可靠提交"
    assert not page.subtitle_edit_card.isVisible()
    page.close_page(); page.deleteLater()


def test_edit_card_shift_enter_newline(tmp_path, monkeypatch):
    app, page = _studio(tmp_path, monkeypatch)
    page._begin_canvas_inline_edit()
    editor = page._canvas_editor
    editor.setPlainText("第一行")
    cursor = editor.textCursor(); cursor.movePosition(cursor.MoveOperation.End); editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(editor, "second")
    app.processEvents()
    assert page._canvas_editor is editor
    assert editor.toPlainText() == "第一行\nsecond"
    page.close_page(); page.deleteLater()


def _advanced_project(name="Cyberpunk HUD"):
    recipe = style_recipe_for_prompt(name)
    style = SubtitleStyle(
        id="advanced", name=name, font_family=str(recipe.typography.get("fontFamily")),
        font_size=float(recipe.typography.get("fontSize", 58)), position_x=820,
        position_y=910, scale_x=112, scale_y=94,
    )
    return SubtitleProject(
        media=StudioMedia(path="source.mp4", duration_ms=8_000, width=1920, height=1080),
        cues=[StudioCue("cue", 500, 5_000, "权威字幕", style_id="advanced")],
        styles=[SubtitleStyle(id="default", name="Default"), style],
        style_recipes={"advanced": recipe.to_dict()},
    )


def test_visual_snapshot_preserves_recipe_on_transform():
    project = _advanced_project()
    before = build_visual_cue_snapshot(project, "cue")
    project.styles[1].position_x = 1110
    project.styles[1].scale_x = 137
    after = build_visual_cue_snapshot(project, "cue")
    # The snapshot recipe is the effective design: glyph appearance fields
    # (typography scale, layout position) re-resolve from the style record,
    # while motion stays owned by the recipe itself.
    assert after.position_x == 1110 and after.scale_x == 1.37
    assert after.style_recipe["typography"]["scaleX"] == 137.0
    assert after.style_recipe["layout"]["positionX"] == 1110
    assert after.motion_recipe == before.motion_recipe
    assert after.style_recipe["motion"] == before.style_recipe["motion"]


def test_visual_snapshot_preserves_recipe_on_text_edit():
    project = _advanced_project()
    before = build_visual_cue_snapshot(project, "cue")
    project.cues[0].text = "文本已修改"
    after = build_visual_cue_snapshot(project, "cue")
    assert after.text == "文本已修改"
    assert after.style_recipe == before.style_recipe
    assert after.motion_recipe == before.motion_recipe


def _gradient(stops, kind="linear"):
    return StyleRecipe(
        name="Gradient", colors={"fill": {"type": kind, "stops": stops}},
    )


def test_gradient_two_stop():
    recipe = _gradient([{"color": "#FFCC00", "pos": 0}, {"color": "#22DDEE", "pos": 1}])
    recipe.validate()
    assert len(recipe.colors["fill"]["stops"]) == 2


def test_gradient_three_stop():
    recipe = _gradient([
        {"color": "#FFCC00", "pos": 0}, {"color": "#FF44AA", "pos": .5},
        {"color": "#22DDEE", "pos": 1},
    ], "radial")
    recipe.validate()
    assert len(recipe.colors["fill"]["stops"]) == 3


def test_gradient_routes_advanced():
    recipe = _gradient([{"color": "#FFFFFF", "pos": 0}, {"color": "#000000", "pos": 1}])
    assert route_recipe(recipe).engine == "remotion"


def test_cyberpunk_motion_recipe():
    motion = style_recipe_for_prompt("Cyberpunk HUD").motion
    assert motion["entrance"]["type"] == "glitch_reveal"
    assert motion["hold"]["scanline"] is True
    assert motion["exit"]["type"] == "data_break"


def test_gaming_motion_recipe():
    motion = style_recipe_for_prompt("Gaming Impact").motion
    assert motion["entrance"]["scale_keyframes"] == [0.70, 1.18, 0.96, 1.0]
    assert motion["entrance"]["vertical_squash"] < 1
    assert motion["exit"]["type"] == "scale_fade"


def test_soft_neon_motion_recipe():
    motion = style_recipe_for_prompt("Soft Neon").motion
    assert motion["entrance"]["type"] == "soft_neon_reveal"
    assert motion["hold"]["glow_breathing"] is True
    assert motion["exit"]["type"] == "fade_float_up"


def _compiled():
    return compile_composition_data(
        _advanced_project(), width=1280, height=720, fps=30,
        start_seconds=0, duration_seconds=8,
    )["cues"][0]


def test_advanced_current_cue_text():
    assert _compiled()["text"] == "权威字幕"


def test_advanced_current_cue_position():
    layout = _compiled()["visual"]["layout"]
    assert (layout["positionX"], layout["positionY"]) == (820.0, 910.0)


def test_advanced_current_cue_scale():
    layout = _compiled()["visual"]["layout"]
    assert (layout["scaleX"], layout["scaleY"]) == (1.12, .94)


def test_success_actions(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    output = tmp_path / "result.mp4"
    output.write_bytes(b"x")
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "media.mp4"), duration_ms=1000))
    workspace = StudioExportWorkspace(project, str(tmp_path / "preview.ass"))
    previous_dir = workspace._settings.value("render/last_export_directory", "")
    workspace._show_success(str(output))
    workspace._settings.setValue("render/last_export_directory", previous_dir)
    assert workspace.pages.currentWidget() is workspace.success_page
    assert "播放成片" in workspace.open_video_button.text()
    workspace.deleteLater()
    app.processEvents()


def test_open_source_font_fallback():
    assert resolve_style_font("Cyberpunk HUD", ["Microsoft YaHei UI"] ) == (
        "Microsoft YaHei UI", False,
    )
    assert resolve_style_font("Soft Neon", ["Noto Sans SC"] ) == ("Noto Sans SC", True)
