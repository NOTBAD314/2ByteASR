"""Unit tests for Task 03: default 'all' style scope, single-cue hint, and visual preset previews."""

from __future__ import annotations

import ast
import inspect
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from twobyteasr.caption_style import preset_preview_delegate as ppd
from twobyteasr.caption_style.preset_preview_delegate import (
    PRESET_PREVIEW_ROLE,
    PresetPreviewDelegate,
    PresetPreviewSpec,
    install_preset_preview_delegate,
    render_preset_preview_pixmap,
)
from twobyteasr.caption_style.scoped_style import effective_layer_style
from twobyteasr.caption_style.style_presets import BUILTIN_PRESETS, StylePresetStore
from twobyteasr.caption_style.style_recipe import FillSpec, StyleRecipe
from twobyteasr.design.studio_theme import STYLE_FIELD_HEIGHT, StudioComboBox
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
)
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _isolate_env(tmp_path, monkeypatch) -> None:
    root = tmp_path / "user_data"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", str(root))
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    ini_path = str(tmp_path / "qsettings.ini")
    from twobyteasr.design import theme_manager

    monkeypatch.setattr(
        theme_manager,
        "_settings",
        lambda: QSettings(ini_path, QSettings.Format.IniFormat),
    )
    theme_manager._forget_theme_key()


def _make_project(tmp_path, tag: str = "p1") -> SubtitleProject:
    return SubtitleProject(
        media=StudioMedia(
            path=str(tmp_path / f"{tag}.mp4"),
            duration_ms=6_000,
            width=1920,
            height=1080,
        ),
        speakers=[StudioSpeaker("S01", "主播A"), StudioSpeaker("S02", "主播B")],
        styles=[SubtitleStyle("default", "默认样式", font_size=48)],
        cues=[
            StudioCue("a", 0, 1_200, "第一句字幕", speaker_id="S01", transform={"position_x": 960, "position_y": 980}),
            StudioCue("b", 1_400, 2_600, "第二句字幕", speaker_id="S02", transform={"position_x": 960, "position_y": 940}),
            StudioCue("c", 2_800, 4_000, "第三句字幕", speaker_id="S01", transform={"position_x": 960, "position_y": 900}),
        ],
    )


def _bind_project(app: QApplication, page: SubtitleStudioPage, project: SubtitleProject, path) -> None:
    page.project = project
    page.project_path = path
    page._cue_lookup = {cue.id: cue for cue in project.cues}
    page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page._populate_speakers()
    page.select_cue(project.cues[0].id)
    page.undo_stack.clear()
    page.undo_stack.setClean()
    app.processEvents()


def _page(tmp_path, monkeypatch) -> tuple[QApplication, SubtitleStudioPage]:
    app = _app()
    _isolate_env(tmp_path, monkeypatch)
    page = SubtitleStudioPage()
    project = _make_project(tmp_path, "proj1")
    _bind_project(app, page, project, tmp_path / "proj1.2byteproj")
    return app, page


def _finish(page: SubtitleStudioPage) -> None:
    app = _app()
    page.close_page()
    page.deleteLater()
    app.processEvents()


def _non_bg_pixel_count(image: QImage) -> int:
    bg = QColor(ppd.CHIP_BG_HEX)
    count = 0
    for y in range(2, image.height() - 2):
        for x in range(2, image.width() - 2):
            px = image.pixelColor(x, y)
            if (
                abs(px.red() - bg.red())
                + abs(px.green() - bg.green())
                + abs(px.blue() - bg.blue())
                > 24
            ):
                count += 1
    return count


def test_default_style_scope_is_all_and_single_cue_hint_tracks_scope(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        # Fresh panel defaults to 'all' (全片) with no single-cue warning hint.
        assert page.style_scope.currentData() == "all"
        all_idx = page.style_scope.findData("all")
        assert page.style_scope._buttons[all_idx].text() == "全片"
        assert page.style_single_cue_hint.text() == "仅改当前句"
        assert page.style_single_cue_hint.isHidden()

        # Switching to 'current' shows the 5-char hint and stays across cue switches in this project.
        page.style_scope.setCurrentIndex(page.style_scope.findData("current"))
        app.processEvents()
        assert page.style_scope.currentData() == "current"
        assert not page.style_single_cue_hint.isHidden()

        page.select_cue("b")
        app.processEvents()
        assert page.style_scope.currentData() == "current"
        assert not page.style_single_cue_hint.isHidden()

        # Switching to 'selected' with 1 cue selected shows the hint; selecting 2 cues hides it.
        page.style_scope.setCurrentIndex(page.style_scope.findData("selected"))
        app.processEvents()
        assert page.selection_model.selected_count() == 1
        assert not page.style_single_cue_hint.isHidden()

        selection = page.cue_table.selectionModel()
        selection.clearSelection()
        for cue_id in ("a", "b"):
            row = page.cue_model.row_for_cue_id(cue_id)
            selection.select(
                page.cue_model.index(row, 0),
                selection.SelectionFlag.Select | selection.SelectionFlag.Rows,
            )
        app.processEvents()
        assert page.selection_model.selected_count() == 2
        assert page.style_single_cue_hint.isHidden()

        # Switching to 'speaker' or 'all' keeps the hint hidden.
        page.style_scope.setCurrentIndex(page.style_scope.findData("speaker"))
        app.processEvents()
        assert page.style_single_cue_hint.isHidden()

        # Reopening/switching to another project restores the default 'all' scope.
        page.style_scope.setCurrentIndex(page.style_scope.findData("current"))
        app.processEvents()
        assert page.style_scope.currentData() == "current"

        project2 = _make_project(tmp_path, "proj2")
        _bind_project(app, page, project2, tmp_path / "proj2.2byteproj")
        assert page.style_scope.currentData() == "all"
        assert page.style_single_cue_hint.isHidden()
    finally:
        _finish(page)


def test_preset_preview_delegate_no_qfontdatabase_and_renders_all_styles(tmp_path, monkeypatch):
    # Static guardrail: paint module must never import or invoke QFontDatabase (Windows GDI crash).
    source = inspect.getsource(ppd)
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "QFontDatabase" not in names and "QFontDatabase" not in attrs

    app = _app()
    _isolate_env(tmp_path, monkeypatch)
    delegate = PresetPreviewDelegate(cache_limit=128)

    # All built-in presets render valid non-empty 92x28 thumbnails with visible glyphs.
    rendered_images = {}
    for preset_id, style in BUILTIN_PRESETS.items():
        spec = PresetPreviewSpec(preset_id=preset_id, name=style.name, style=style)
        pix = delegate.pixmap_for_spec(spec, dpr=1.0)
        assert not pix.isNull()
        assert (pix.width(), pix.height()) == (ppd.CHIP_WIDTH, ppd.CHIP_HEIGHT)
        img = pix.toImage()
        assert _non_bg_pixel_count(img) > 40, preset_id
        rendered_images[preset_id] = img

    # Distinct visual presets produce distinct pixel output.
    assert rendered_images["livestream"] != rendered_images["dialogue-b"]
    assert rendered_images["clean-white"] != rendered_images["game"]

    # Cache hit check on second fetch.
    hits_before = delegate.cache.hits
    misses_before = delegate.cache.misses
    spec_game = PresetPreviewSpec(preset_id="game", name="游戏字幕", style=BUILTIN_PRESETS["game"])
    pix_again = delegate.pixmap_for_spec(spec_game, dpr=1.0)
    assert not pix_again.isNull()
    assert delegate.cache.hits == hits_before + 1
    assert delegate.cache.misses == misses_before

    # HiDPI dpr=2.0 produces crisp 2x backing pixmap with dpr=2.0.
    pix_2x = delegate.pixmap_for_spec(spec_game, dpr=2.0)
    assert pix_2x.devicePixelRatio() == 2.0
    assert (pix_2x.width(), pix_2x.height()) == (ppd.CHIP_WIDTH * 2, ppd.CHIP_HEIGHT * 2)

    # Rich presets: gradient + glow, background box, double stroke, shadow, missing font, huge size.
    rich_cases = [
        (
            "grad-glow",
            SubtitleStyle("grad-glow", "霓虹渐变", font_size=58, bold=True, outline_width=4, shadow=2),
            StyleRecipe(
                name="霓虹渐变",
                colors={"fill": FillSpec.linear(
                    [{"color": "#FF00F0FF", "position": 0.0}, {"color": "#FFFF3CAC", "position": 1.0}],
                    angle=45,
                ).to_dict()},
                effects={"glow": {"enabled": True, "color": "#FF00F0FF", "blur": 10.0, "opacity": 0.9}},
            ).to_dict(),
        ),
        (
            "radial-fill",
            SubtitleStyle("radial-fill", "径向渐变", font_size=54, bold=True, outline_width=3),
            {
                "colors": {
                    "fill": {
                        "type": "radial-gradient",
                        "stops": [
                            {"color": "#FFFFF275", "position": 0.0},
                            {"color": "#FFFF5E62", "position": 1.0},
                        ],
                        "radius": 0.9,
                    }
                }
            },
        ),
        (
            "bg-box",
            SubtitleStyle(
                "bg-box", "暗底条", font_size=50, primary_color="#FFFFFF",
                outline_width=0, border_style=3, back_color="#DD1A2B44",
            ),
            None,
        ),
        (
            "double-stroke",
            SubtitleStyle(
                "double-stroke", "双层描边", font_size=56, primary_color="#FF4040",
                outline_color="#000000", outline_width=5,
                outline2_color="#FFFFFF", outline2_width=2, shadow=3, bold=True,
            ),
            None,
        ),
        (
            "missing-font",
            SubtitleStyle(
                "missing-font", "缺失字体回退", font_family="NonExistentFont_2ByteASR_XYZ_999",
                font_size=240, primary_color="#80FFAA", outline_width=3, italic=True, underline=True,
            ),
            None,
        ),
    ]
    for preset_id, style, recipe in rich_cases:
        pix = render_preset_preview_pixmap(style, recipe=recipe, dpr=1.0)
        assert not pix.isNull(), preset_id
        assert _non_bg_pixel_count(pix.toImage()) > 40, preset_id

    # Bounded LRU eviction at 128 entries.
    bounded = PresetPreviewDelegate(cache_limit=128)
    for i in range(145):
        style = SubtitleStyle(f"u-{i}", f"自定义预设 {i}", font_size=40 + (i % 20), primary_color=f"#{(i * 19) % 256:02X}CC88")
        bounded.pixmap_for_spec(PresetPreviewSpec(preset_id=style.id, name=style.name, style=style), dpr=1.0)
    assert bounded.cache_size() == 128


def test_preset_combo_binding_width_height_and_35_preset_paint_speed(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        # Collapsed height stays compact (<= STYLE_FIELD_HEIGHT and strictly below expanded 42px row height).
        assert page.style_preset.minimumHeight() == page.style_layer.minimumHeight()
        assert page.style_preset.maximumHeight() == page.style_layer.maximumHeight()
        assert page.style_preset.maximumHeight() <= STYLE_FIELD_HEIGHT
        assert page.style_preset.maximumHeight() < PresetPreviewDelegate.ROW_HEIGHT
        page.resize(1360, 860)
        page.show()
        page.context_drawer.setCurrentIndex(1)
        app.processEvents()
        assert page.style_preset.height() == page.style_layer.height()
        assert page.style_preset.height() <= STYLE_FIELD_HEIGHT
        delegate = page.style_preset.view().itemDelegate()
        assert isinstance(delegate, PresetPreviewDelegate)
        assert page.style_preset.view().minimumWidth() >= 264

        # Seed 35 custom presets (with favorites & a long name) and refresh.
        store = StylePresetStore()
        for i in range(35):
            style = SubtitleStyle(
                f"user-perf-{i:02d}",
                "北枫版正式超级长名称测试" if i == 0 else f"实况预设 {i:02d}",
                font_size=44 + (i % 18),
                primary_color=f"#{(50 + i * 5) % 255:02X}{(200 - i * 3) % 255:02X}FF",
                outline_width=float(1 + (i % 5)),
                border_style=3 if i % 7 == 0 else 1,
                back_color="#CC223344",
                shadow=float(i % 4),
                bold=(i % 2 == 0),
            )
            store.upsert(style)
            if i in (0, 3):
                store.set_favorite(style.id, True)
        page._refresh_style_presets()
        app.processEvents()

        assert page.style_preset.count() >= 41
        # Popup width grows to accommodate chip + long preset name + favorite star without truncation.
        popup_width = delegate.popup_width_for_combo(page.style_preset)
        assert popup_width >= 280
        assert page.style_preset.view().minimumWidth() >= popup_width

        # Paint all rows into an offscreen image (warm cache pass must be < 20ms).
        canvas = QImage(popup_width, PresetPreviewDelegate.ROW_HEIGHT * 10, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        model = page.style_preset.model()

        def paint_all_rows() -> None:
            painter = QPainter(canvas)
            try:
                for row in range(page.style_preset.count()):
                    opt = QStyleOptionViewItem()
                    opt.rect = QRect(0, (row % 10) * PresetPreviewDelegate.ROW_HEIGHT, popup_width, PresetPreviewDelegate.ROW_HEIGHT)
                    opt.font = page.style_preset.view().font()
                    opt.state = QStyle.StateFlag.State_Enabled | (
                        QStyle.StateFlag.State_Selected if row == 0 else QStyle.StateFlag.State_None
                    )
                    delegate.paint(painter, opt, model.index(row, 0))
            finally:
                painter.end()

        paint_all_rows()  # warm cache
        t0 = time.perf_counter()
        paint_all_rows()  # cached scroll pass
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert elapsed_ms < 20.0, f"cached paint of {page.style_preset.count()} presets took {elapsed_ms:.2f}ms"
        assert delegate.sizeHint(QStyleOptionViewItem(), model.index(0, 0)) == QSize(264, PresetPreviewDelegate.ROW_HEIGHT)
    finally:
        _finish(page)


def test_all_scope_applies_preset_to_whole_project_and_undoes_cleanly(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        assert page.style_scope.currentData() == "all"
        assert page.style_apply_style_only.isChecked()
        assert not page.style_apply_geometry.isChecked()

        positions_before = {cue.id: dict(cue.transform) for cue in page.project.cues}
        colors_before = {
            cue.id: effective_layer_style(page.project, cue, "original").primary_color
            for cue in page.project.cues
        }

        idx = page.style_preset.findData("livestream")
        assert idx >= 0
        page.style_preset.setCurrentIndex(idx)
        page.style_preset.activated.emit(idx)
        app.processEvents()

        assert page.undo_stack.count() == 1
        for cue in page.project.cues:
            eff = effective_layer_style(page.project, cue, "original")
            assert eff.primary_color.upper() == "#FFF4B8"
            assert eff.bold is True
            # '只套样式' keeps each cue's existing position untouched.
            assert cue.transform.get("position_x") == positions_before[cue.id]["position_x"]
            assert cue.transform.get("position_y") == positions_before[cue.id]["position_y"]

        # Ctrl+Z / undo atomically restores all 3 cues.
        page.undo_stack.undo()
        app.processEvents()
        for cue in page.project.cues:
            eff = effective_layer_style(page.project, cue, "original")
            assert eff.primary_color == colors_before[cue.id]

        # Redo reapplies to all 3 cues.
        page.undo_stack.redo()
        app.processEvents()
        for cue in page.project.cues:
            eff = effective_layer_style(page.project, cue, "original")
            assert eff.primary_color.upper() == "#FFF4B8"

        # Switching to '连位置与缩放' and undoing keeps the undo chain intact.
        page.style_apply_geometry.setChecked(True)
        app.processEvents()
        assert not page.style_apply_style_only.isChecked()
        while page.undo_stack.canUndo():
            page.undo_stack.undo()
        app.processEvents()
        for cue in page.project.cues:
            eff = effective_layer_style(page.project, cue, "original")
            assert eff.primary_color == colors_before[cue.id]
    finally:
        _finish(page)


def test_preset_delegate_paints_cleanly_in_warm_and_grape_themes(tmp_path, monkeypatch):
    app = _app()
    _isolate_env(tmp_path, monkeypatch)
    from twobyteasr.design import theme_manager

    combo = StudioComboBox()
    delegate = install_preset_preview_delegate(combo)
    for preset_id, style in BUILTIN_PRESETS.items():
        combo.addItem(style.name, preset_id)
        combo.setItemData(
            combo.count() - 1,
            PresetPreviewSpec(
                preset_id=preset_id,
                name=style.name,
                style=style,
                favorite=(preset_id == "game"),
            ),
            PRESET_PREVIEW_ROLE,
        )

    for theme_name in ("warm", "grape"):
        theme_manager.save_theme_key(theme_name)
        canvas = QImage(320, PresetPreviewDelegate.ROW_HEIGHT * 3, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        try:
            for row, state in (
                (0, QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected),
                (1, QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_MouseOver),
                (2, QStyle.StateFlag.State_Enabled),
            ):
                opt = QStyleOptionViewItem()
                opt.rect = QRect(0, row * PresetPreviewDelegate.ROW_HEIGHT, 320, PresetPreviewDelegate.ROW_HEIGHT)
                opt.font = combo.view().font()
                opt.state = state
                delegate.paint(painter, opt, combo.model().index(row, 0))
        finally:
            painter.end()
        assert not canvas.isNull()
        # Verify selected row painted a visible tinted background around the text area.
        probe = canvas.pixelColor(240, PresetPreviewDelegate.ROW_HEIGHT // 2)
        assert probe.alpha() > 0, theme_name

    combo.deleteLater()
    app.processEvents()

