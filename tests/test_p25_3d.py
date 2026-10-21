import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.rendering.advanced_preview import (
    AdvancedPreviewCache,
    AdvancedPreviewIdentity,
    AdvancedPreviewStateMachine,
)
from twobyteasr.caption_style.font_system import resolve_font_weight, resolve_style_font, system_font_inventory
from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, SubtitleStyle, save_project
from twobyteasr.studio.studio_ui import AdvancedLiveCanvas, FillEditorDialog, SubtitleStudioPage
from twobyteasr.caption_style.visual_snapshot import VisualCueSnapshot, build_visual_cue_snapshot


def _app():
    return QApplication.instance() or QApplication([])


def _project(advanced=False):
    styles = [SubtitleStyle("default", "Default"), SubtitleStyle("game", "Game", font_size=64, bold=True)]
    recipes = {}
    if advanced:
        recipe = style_recipe_for_prompt("Cyberpunk HUD")
        styles.append(SubtitleStyle("advanced", "Cyberpunk", position_x=710, position_y=880, scale_x=120))
        recipes["advanced"] = recipe.to_dict()
    return SubtitleProject(
        media=StudioMedia(path="media.mp4", duration_ms=5000, width=1920, height=1080),
        cues=[
            StudioCue("a", 0, 1500, "第一条", speaker_id="S01", style_id="advanced" if advanced else "default"),
            StudioCue("b", 1600, 3000, "第二条", speaker_id="S02"),
            StudioCue("c", 3100, 4500, "第三条", speaker_id="S01"),
        ],
        styles=styles,
        speakers=[StudioSpeaker("S01", "S01"), StudioSpeaker("S02", "S02")],
        style_recipes=recipes,
    )


def _page(tmp_path, monkeypatch, *, advanced=False):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = save_project(_project(advanced), tmp_path / "p.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    page.resize(1500, 900); page.show(); app.processEvents()
    return app, page


def test_advanced_cue_never_falls_through_to_native_ass(tmp_path, monkeypatch):
    _app(); _, page = _page(tmp_path, monkeypatch, advanced=True)
    snapshot = page._ass_preview_snapshot(page.project)
    assert [cue.id for cue in snapshot.cues] == ["b", "c"]
    visual = build_visual_cue_snapshot(page.project, "a", width=640, height=360)
    identity = AdvancedPreviewIdentity.from_snapshot(
        visual, width=640, height=360, motion_time_ms=300,
    )
    page._advanced_preview_state = AdvancedPreviewStateMachine()
    generation = page._advanced_preview_state.select(identity, cache_hit=False)
    assert page._advanced_preview_state.publish_ready(identity, generation, "cached.png")
    assert page._advanced_preview_state.mark_visible(identity)
    # Canonical Advanced routing owns the cue before readiness. Native ASS must
    # not flash a solid approximation while LIVE pixels are being prepared.
    snapshot = page._ass_preview_snapshot(page.project)
    assert "a" not in [cue.id for cue in snapshot.cues]
    page._advanced_visual_owner_cue_id = "a"
    snapshot = page._ass_preview_snapshot(page.project)
    assert "a" not in [cue.id for cue in snapshot.cues]
    page._live_edit_text_overrides["a"] = "正在输入"
    snapshot = page._ass_preview_snapshot(page.project)
    assert "a" not in [cue.id for cue in snapshot.cues]
    page.close_page(); page.deleteLater()


def test_advanced_live_uses_visual_snapshot():
    _app(); project = _project(True)
    snapshot = build_visual_cue_snapshot(project, "a", width=640, height=360)
    owner = SubtitleStudioPage(); canvas = AdvancedLiveCanvas(owner)
    canvas.set_visual(QPixmap(640, 360), snapshot)
    assert isinstance(canvas._snapshot, VisualCueSnapshot)
    assert canvas._snapshot.stable_hash() == snapshot.stable_hash()
    owner.close_page(); owner.deleteLater()


def test_advanced_transform_preserves_style():
    project = _project(True); before = build_visual_cue_snapshot(project, "a")
    project.styles[-1].position_x = 999; project.styles[-1].scale_x = 180
    after = build_visual_cue_snapshot(project, "a")
    # P24B/P25 几何契约：placement（positionX/scaleX）随样式编入 recipe 的
    # layout/typography，作为双渲染器统一编译事实源；快照层 transform 同步暴露。
    assert after.style_recipe["layout"]["positionX"] == 999
    assert after.style_recipe["typography"]["scaleX"] == 180.0
    # 守卫本意保持：除这两个 placement 字段外，recipe 的其余内容不得漂移。
    def strip_placement(recipe):
        recipe = {k: (dict(v) if isinstance(v, dict) else v) for k, v in recipe.items()}
        recipe["layout"] = {k: v for k, v in recipe["layout"].items() if k != "positionX"}
        recipe["typography"] = {k: v for k, v in recipe["typography"].items() if k != "scaleX"}
        return recipe
    assert strip_placement(after.style_recipe) == strip_placement(before.style_recipe)
    assert (after.position_x, after.scale_x) == (999, 1.8)


def test_gradient_live_pending_does_not_restore_native_fallback(tmp_path, monkeypatch):
    _, page = _page(tmp_path, monkeypatch, advanced=True)
    page._advanced_preview_state.fallback()
    assert "a" not in [
        cue.id for cue in page._ass_preview_snapshot(page.project).cues
    ]
    assert page.video._native_subtitle_visible is False
    page.close_page(); page.deleteLater()


def test_missing_font_fallback():
    family, installed = resolve_style_font("Cyberpunk HUD", ["Microsoft YaHei UI"])
    assert family == "Microsoft YaHei UI" and not installed


def test_fill_editor_gradient():
    _app(); dialog = FillEditorDialog("#FFFFFFFF")
    dialog.mode_group.button(1).setChecked(True); dialog.gradient._add_stop()
    value = dialog.value()
    assert value["type"] == "linear-gradient" and len(value["stops"]) == 3


class _FakeFontDb:
    def families(self): return ["Example Sans", "Example Serif"]
    def styles(self, family): return ["Regular", "SemiBold", "Black"] if family == "Example Sans" else ["Regular"]


def test_system_font_inventory():
    inventory = system_font_inventory(_FakeFontDb())
    assert [item.family for item in inventory] == ["Example Sans", "Example Serif"]


def test_font_weight_resolution():
    assert resolve_font_weight("Example Sans", "Heavy", _FakeFontDb()) == ("Black", 900)
    assert resolve_font_weight("Example Sans", 620, _FakeFontDb()) == ("SemiBold", 600)


def _apply_scope(tmp_path, monkeypatch, scope, selected=()):
    app, page = _page(tmp_path, monkeypatch)
    if selected:
        selection = page.cue_table.selectionModel(); selection.clearSelection()
        for cue_id in selected:
            row = page.cue_model.row_for_cue_id(cue_id)
            selection.select(page.cue_model.index(row, 0), selection.SelectionFlag.Select | selection.SelectionFlag.Rows)
    page.style_scope.setCurrentIndex(page.style_scope.findData(scope))
    page.style_preset.setCurrentIndex(page.style_preset.findData("game")); page._apply_style(); app.processEvents()
    return page


def test_apply_style_current(tmp_path, monkeypatch):
    page = _apply_scope(tmp_path, monkeypatch, "current")
    assert page.project.cues[0].style_id.startswith("game") and page.project.cues[1].style_id == "default"
    page.close_page(); page.deleteLater()


def test_apply_style_selected(tmp_path, monkeypatch):
    page = _apply_scope(tmp_path, monkeypatch, "selected", ("a", "b"))
    assert all(cue.style_id.startswith("game") for cue in page.project.cues[:2])
    assert page.project.cues[2].style_id == "default"
    page.close_page(); page.deleteLater()


def test_apply_style_speaker(tmp_path, monkeypatch):
    page = _apply_scope(tmp_path, monkeypatch, "speaker")
    assert page.project.cues[0].style_id.startswith("game") and page.project.cues[2].style_id.startswith("game")
    assert page.project.cues[1].style_id == "default"
    page.close_page(); page.deleteLater()


def test_copy_paste_style(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    page.project.styles[0].position_x = 300; page.project.styles[1].position_x = 900
    page.project.cues[0].style_id = "game"; page.select_cue("a"); page._copy_subtitle_style()
    page.select_cue("b"); before = (page.project.cues[1].text, page.project.cues[1].start_ms)
    page._paste_subtitle_style(); app.processEvents()
    style = next(s for s in page.project.styles if s.id == page.project.cues[1].style_id)
    assert (page.project.cues[1].text, page.project.cues[1].start_ms) == before
    assert style.font_size == 64 and style.position_x == 300
    page.close_page(); page.deleteLater()


def test_default_workspace_panels_visible(tmp_path, monkeypatch):
    _, page = _page(tmp_path, monkeypatch)
    assert page.cue_list_panel.isVisible() and page.context_panel.isVisible()
    sizes = page.upper_splitter.sizes(); assert sizes[0] > 0 and sizes[2] > 0
    page.close_page(); page.deleteLater()


def test_whole_toolbar_button_click(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    QTest.mouseClick(page.cue_list_toggle_button, Qt.MouseButton.LeftButton, pos=page.cue_list_toggle_button.rect().center())
    app.processEvents(); assert not page.cue_list_panel.isVisible()
    QTest.mouseClick(page.cue_list_toggle_button, Qt.MouseButton.LeftButton, pos=QPoint(page.cue_list_toggle_button.width() // 4, page.cue_list_toggle_button.height() // 2))
    app.processEvents(); assert page.cue_list_panel.isVisible()
    page.close_page(); page.deleteLater()


def test_advanced_preview_cache_stale_discard(tmp_path):
    cache = AdvancedPreviewCache(tmp_path / "cache", budget_bytes=16 * 1024 * 1024)
    assert cache.discard_if_stale(2, 3)
    assert not cache.discard_if_stale(3, 3)
