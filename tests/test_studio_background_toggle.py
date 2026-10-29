"""Style tab: the background switch / color reach the renderer; one label grid (2026-10-17/18)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QCheckBox, QScrollArea, QToolButton

from tests.test_studio_style_controller import _finish, _page
from twobyteasr.caption_design.visual_design_graph import apply_background_to_graph
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _panel(page, cue_id="a"):
    recipe = build_visual_cue_snapshot(page.session.project, cue_id).style_recipe or {}
    panel = (recipe.get("visualGraph") or {}).get("panelLayer") or {}
    return panel.get("primitive"), (panel.get("params") or {}).get("color")


def _border(page, cue_id="a"):
    cue = page.session._cue_lookup[cue_id]
    return resolve_cue_visual(page.session.project, cue).style.border_style


def _rich_shadow(page):
    page._updating_style_ui = True
    try:
        page.style_shadow_opacity.setValue(48)
        page.style_shadow_blur.setValue(3)
        page.style_shadow_offset_x.setValue(2)
        page.style_shadow_offset_y.setValue(2)
    finally:
        page._updating_style_ui = False
    page._apply_style()


def test_background_switch_commits_and_color_turns_background_back_on(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    page._set_style_color(page.style_back_color, "#FFFF0000")
    assert _border(page) == 3 and page.style_background.isChecked()
    steps = page.undo_stack.count()

    page.style_background.click()  # switch off
    app.processEvents()
    assert _border(page) == 1
    assert page.undo_stack.count() == steps + 1
    assert not page.style_background.isChecked()

    page._set_style_color(page.style_back_color, "#FFFFC0CB")
    assert _border(page) == 3
    assert page.style_background.isChecked()
    assert resolve_cue_visual(page.session.project, page.session._cue_lookup["a"]).style.back_color == "#FFFFC0CB"
    _finish(page)


def test_graph_panel_follows_background_edits_after_rich_shadow(tmp_path, monkeypatch):
    # A rich shadow turns the style into a visual graph; its panel layer is
    # what LIVE and Remotion draw, so it must follow every background edit.
    app, page = _page(tmp_path, monkeypatch)
    page._set_style_color(page.style_back_color, "#FFFF0000")
    _rich_shadow(page)
    assert _panel(page) == ("ROUNDED_PANEL", "#FFFF0000")

    page._set_style_color(page.style_back_color, "#FFFFC0CB")
    assert _panel(page) == ("ROUNDED_PANEL", "#FFFFC0CB")

    page.style_background.click()
    app.processEvents()
    assert _panel(page)[0] == "NONE"

    page.style_background.click()
    app.processEvents()
    assert _panel(page) == ("ROUNDED_PANEL", "#FFFFC0CB")
    _finish(page)


def test_unrelated_edit_keeps_a_designed_panel(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    _rich_shadow(page)
    cue = page.session._cue_lookup["a"]
    recipes = page.session.project.style_recipes
    graph = dict(recipes[cue.style_id]["visualGraph"])
    graph["panelLayer"] = {"id": "panel", "primitive": "COMIC_BURST",
                           "params": {"color": "#FF112233", "gradient": {"type": "linear-gradient"}}}
    recipes[cue.style_id] = dict(recipes[cue.style_id], visualGraph=graph)
    page._load_style_inspector()
    page._updating_style_ui = True
    try:
        page.style_font_size.setValue(60)
    finally:
        page._updating_style_ui = False
    page._apply_style()
    payload = page.session.project.style_recipes[page.session._cue_lookup["a"].style_id]
    assert payload["visualGraph"]["panelLayer"]["primitive"] == "COMIC_BURST"
    assert "gradient" in payload["visualGraph"]["panelLayer"]["params"]
    _finish(page)


def test_saved_stale_panel_renders_the_overridden_background(tmp_path, monkeypatch):
    # Projects saved before the fix keep a red panel although the cue's
    # explicit override says pink (the user's 未命名工程 36).
    app, page = _page(tmp_path, monkeypatch)
    page._set_style_color(page.style_back_color, "#FFFF0000")
    _rich_shadow(page)
    page._set_style_color(page.style_back_color, "#FFFFC0CB")
    cue = page.session._cue_lookup["a"]
    recipes = page.session.project.style_recipes
    graph = dict(recipes[cue.style_id]["visualGraph"])
    graph["panelLayer"] = {"id": "panel", "primitive": "ROUNDED_PANEL", "params": {"color": "#FFFF0000"}}
    recipes[cue.style_id] = dict(recipes[cue.style_id], visualGraph=graph)
    assert cue.appearance_override.get("back_color") == "#FFFFC0CB"
    assert _panel(page) == ("ROUNDED_PANEL", "#FFFFC0CB")
    _finish(page)


def test_apply_background_to_graph_keeps_shape_and_unchanged_gradient():
    graph = {"panelLayer": {"id": "panel", "primitive": "COMIC_BURST",
                            "params": {"color": "#CC111111", "gradient": {"type": "linear-gradient"}}}}
    same = apply_background_to_graph(graph, enabled=True, color="#CC111111")
    assert same["panelLayer"]["primitive"] == "COMIC_BURST"
    assert "gradient" in same["panelLayer"]["params"]

    off = apply_background_to_graph(graph, enabled=False, color="#CC111111")
    assert off["panelLayer"]["primitive"] == "NONE"
    back_on = apply_background_to_graph(off, enabled=True, color="#FF00FF00")
    assert back_on["panelLayer"]["primitive"] == "COMIC_BURST"
    assert back_on["panelLayer"]["params"]["color"] == "#FF00FF00"
    assert "gradient" not in back_on["panelLayer"]["params"]
    assert graph["panelLayer"]["primitive"] == "COMIC_BURST"  # input untouched


def _shown_style_tab(page, app):
    page.resize(1700, 1000)
    page.show()
    page.context_drawer.setCurrentIndex(1)
    for row in page._appearance_rows.values():
        row.set_expanded(False)
    page._appearance_rows["outline"].set_expanded(True)
    app.processEvents()
    widget = page.style_apply_geometry.parentWidget()
    while not isinstance(widget, QScrollArea):
        widget = widget.parentWidget()
    root = widget.widget()
    for header in root.findChildren(QToolButton, "styleSectionHeader"):
        if header.isVisibleTo(root):
            header.setChecked(True)
    app.processEvents()
    return lambda item: item.mapTo(root, QPoint(0, 0)).x()


def test_style_tab_labels_controls_and_checkboxes_share_one_grid(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    x = _shown_style_tab(page, app)
    rows = page._appearance_rows
    labels = [row.title_label for row in rows.values()]
    column = page._style_label_column
    section_labels = [label for label, extra in column._labels if extra == 0]
    assert len({x(label) for label in section_labels}) == 1
    assert len({label.width() for label in section_labels}) == 1
    # Controls start in one column: font, size, swatches, scope, preset.
    swatches = [page.style_fill_swatch, page.style_outline_swatch, page.style_back_swatch,
                page.style_shadow_swatch, page.style_glow_swatch]
    starts = {x(item) for item in swatches + [page.style_font, page.style_font_size,
                                               page.style_scope, page.style_preset,
                                               page.style_apply_geometry, page.style_outline2,
                                               page.style_alignment, page.style_position_x]}
    assert len(starts) == 1, starts
    # Switches (background, shadow, glow) sit in the same trailing slot.
    assert x(page.style_shadow_switch) == x(page.style_glow) == x(page.style_background)
    assert all(label.objectName() == "stylePropertyRowTitle" for label in labels)
    checks = [box for box in page.findChildren(QCheckBox)
              if box.isVisibleTo(page) and box.text() and page.context_drawer.isAncestorOf(box)]
    assert {box.objectName() for box in checks} == {"styleInlineCheck"}
    _finish(page)


def test_label_column_grows_for_longer_translations(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    x = _shown_style_tab(page, app)
    column = page._style_label_column
    background = page._appearance_rows["background"].title_label
    background.setText("Background")
    app.processEvents()
    assert column.width >= column._text_width(background)
    assert page._appearance_rows["fill"].title_label.width() == background.width()
    assert x(page.style_fill_swatch) == x(page.style_font)
    _finish(page)


def test_preset_combo_ends_a_long_name_in_an_ellipsis(tmp_path, monkeypatch):
    from twobyteasr.caption_style.studio_style_widgets import ElidedComboBox

    app, page = _page(tmp_path, monkeypatch)
    assert isinstance(page.style_preset, ElidedComboBox)
    combo = ElidedComboBox()
    combo.addItem("2Byte 默认 · 已修改 · 一个很长很长的预设名字")
    combo.resize(120, 34)
    combo.show()
    app.processEvents()
    shown = combo.displayed_text()
    assert shown.endswith("…") and len(shown) < len(combo.currentText())
    combo.resize(900, 34)
    app.processEvents()
    assert combo.displayed_text() == combo.currentText()
    combo.grab()  # paints through the elided label without errors
    combo.deleteLater()
    _finish(page)


def test_grid_holds_when_the_tool_panel_is_wider(tmp_path, monkeypatch):
    # prepare_controls() caps combos at 360 px; the font and alignment rows then
    # centred their label + combo once the panel was wider than ~480 px.
    from PySide6.QtWidgets import QSplitter

    app, page = _page(tmp_path, monkeypatch)
    x = _shown_style_tab(page, app)
    splitter = page.context_drawer.parentWidget()
    while not isinstance(splitter, QSplitter):
        splitter = splitter.parentWidget()
    page.resize(2400, 1000)
    app.processEvents()
    controls = [page.style_scope, page.style_preset, page.style_font, page.style_font_size,
                page.style_fill_swatch, page.style_glow_swatch, page.style_alignment, page.style_position_x]
    for width in (440, 560, 640):
        splitter.setSizes([320, 2400 - 320 - width, width])
        app.processEvents()
        app.processEvents()
        assert len({x(item) for item in controls}) == 1, (width, [x(item) for item in controls])
        labels = [label for label, extra in page._style_label_column._labels if extra == 0 and label.isVisibleTo(page)]
        assert len({x(label) for label in labels}) == 1, width
    _finish(page)


def test_appearance_rows_are_square_swatches_without_captions(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel

    app, page = _page(tmp_path, monkeypatch)
    _shown_style_tab(page, app)
    for name in ("style_fill_swatch", "style_outline_swatch", "style_back_swatch",
                 "style_shadow_swatch", "style_glow_swatch"):
        swatch = getattr(page, name)
        assert abs(swatch.width() - swatch.height()) <= 2, (name, swatch.size())
    texts = {label.text() for row in page._appearance_rows.values() for label in row.findChildren(QLabel)
             if label.isVisibleTo(row)}
    assert not texts & {"宽度", "半径", "方向", "透明"}
    assert not page.style_preview.isVisibleTo(page)
    assert page.style_background.objectName() == "styleSwitch"
    _finish(page)


def test_shadow_editor_is_the_disc_beside_a_two_by_two_grid(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    x = _shown_style_tab(page, app)
    page._appearance_rows["shadow"].set_expanded(True)
    app.processEvents()
    assert not page.style_shadow_angle_value.isVisibleTo(page)
    disc = page.style_shadow_angle
    fields = [page.style_shadow_distance, page.style_shadow_opacity, page.style_shadow_blur, page.style_shadow_spread]
    assert all(x(field) > x(disc) + disc.width() for field in fields)
    columns = sorted({x(field) for field in fields})
    rows = sorted({field.mapTo(page, field.rect().topLeft()).y() for field in fields})
    assert len(columns) == 2 and len(rows) == 2
    top = disc.mapTo(page, disc.rect().topLeft()).y()
    assert top <= rows[1] and top + disc.height() >= rows[0]  # the disc spans both rows
    _finish(page)


def test_active_rows_fade_their_color_from_the_right(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    _shown_style_tab(page, app)
    rows = page._appearance_rows
    assert rows["fill"]._tint_colors  # the fill is always on
    assert not rows["background"]._tint_colors
    page._set_style_color(page.style_back_color, "#FFFF0000")
    app.processEvents()
    assert rows["background"]._tint_colors == ["#FFFF0000"]
    image = rows["background"].grab().toImage()
    right = image.pixelColor(image.width() - 3, image.height() // 2)
    left = image.pixelColor(3, image.height() // 2)
    assert right.red() > left.red() + 10
    page.style_background.click()
    app.processEvents()
    assert not rows["background"]._tint_colors
    _finish(page)


def test_new_font_family_drops_the_old_face_in_the_recipe(tmp_path, monkeypatch):
    from twobyteasr.projects.studio_project import default_style

    app, page = _page(tmp_path, monkeypatch)
    page.session.project.styles[0] = default_style()
    page._load_style_inspector()
    page._updating_style_ui = True
    try:
        page.style_shadow_opacity.setValue(48)
        page.style_shadow_blur.setValue(3)
    finally:
        page._updating_style_ui = False
    page._apply_style()
    page.style_font.commit_family("Microsoft YaHei UI")
    app.processEvents()
    cue = page.session._cue_lookup["a"]
    typography = page.session.project.style_recipes[cue.style_id]["typography"]
    assert typography["fontFamily"] == "Microsoft YaHei UI"
    assert typography["fontStyleName"] == "" and typography["fontWeight"] == 0
    _finish(page)


def test_missing_weight_message_names_the_face_in_use():
    from twobyteasr.caption_style.font_metadata import local_faces, resolve_local_face

    faces = [face for face in local_faces() if face.family == "Source Han Sans SC"]
    family = faces[0].aliases[0] if faces else "Source Han Sans SC"
    _face, reason = resolve_local_face(family, 950, "NoSuchStyle")
    assert "缺失" not in reason and "没有 NoSuchStyle 字重" in reason and "正在使用" in reason


def test_motion_category_filter_back_to_all_does_not_stack_tiles(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    page.resize(1700, 1000)
    page.show()
    page.context_drawer.setCurrentIndex(page.motion_tab_index)
    app.processEvents()
    panel = page.motion_inspector
    stage = panel.stages[panel.tabs.currentIndex()]

    def overlapping():
        rects = [tile.geometry() for (s, _key), tile in panel.cards.items() if s == stage and tile.isVisible()]
        return sum(1 for i, a in enumerate(rects) for b in rects[i + 1:] if a.intersects(b))

    first = next(category for category in panel.chips[stage] if category != "all")
    panel.chips[stage][first].click()
    app.processEvents()
    panel.chips[stage]["all"].click()
    app.processEvents()
    assert overlapping() == 0
    assert panel.stack.height() >= panel.hosts[stage].sizeHint().height()
    _finish(page)
