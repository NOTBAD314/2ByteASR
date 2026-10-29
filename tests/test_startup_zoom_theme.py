"""2026-10-10 evening: faster start (pages built on first use), the interface
zoom and theme-following input boxes."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (QApplication, QDialog, QGraphicsView, QHBoxLayout, QLabel,  # noqa: E402
                               QPushButton, QVBoxLayout, QWidget)

APP = QApplication.instance() or QApplication([])


def _reset_zoom():
    from twobyteasr.app import ui_zoom
    ui_zoom.set_zoom_percent(100)


def test_dark_themes_never_leave_input_states_white():
    """The home content-name box turned white on hover/focus/open (background-color)."""
    from twobyteasr.design.main_ui_theme import APP_QSS
    from twobyteasr.design.qss_retheme import retheme_qss
    from twobyteasr.design.ui_theme import THEMES
    assert "background-color: #ffffff" in APP_QSS
    for key, theme in THEMES.items():
        sheet = retheme_qss(APP_QSS, theme)
        if theme.surface_elevated.lower() != "#ffffff":  # the light theme's raised surface is white
            assert "background-color: #ffffff" not in sheet.lower(), key
        assert f"background-color: {theme.surface_elevated}" in sheet, key


def test_zoom_scales_stylesheet_geometry_but_keeps_hairlines():
    from twobyteasr.app.ui_zoom import scale_qss
    sheet = "QPushButton { font-size: 14px; padding: 6px 16px; border: 1px solid #fff; min-height: 30px; }"
    assert scale_qss(sheet, 1.5) == ("QPushButton { font-size: 21px; padding: 9px 24px; border: 1px solid #fff;"
                                     " min-height: 45px; }")
    assert scale_qss(sheet, 1.0) == sheet
    assert scale_qss("width: 2px; margin: 3.5px", 2.0) == "width: 2px; margin: 7px"


def test_zoom_round_trip_restores_code_sizes_and_skips_stylesheet_minimums():
    from twobyteasr.app import ui_zoom
    root = QWidget()
    layout = QVBoxLayout(root)
    layout.setContentsMargins(10, 12, 10, 12)
    layout.setSpacing(8)
    fixed = QLabel("固定")
    fixed.setFixedHeight(42)
    qss = QPushButton("样式")
    qss.setStyleSheet("QPushButton { min-height: 30px; font-size: 14px; }")
    layout.addWidget(fixed)
    layout.addWidget(qss)
    root.show()
    APP.processEvents()
    qss_minimum = qss.minimumHeight()
    try:
        ui_zoom.set_zoom_percent(150)
        ui_zoom.apply_to(root)
        APP.processEvents()
        assert fixed.minimumHeight() == fixed.maximumHeight() == 63
        assert layout.contentsMargins().top() == 18 and layout.spacing() == 12
        assert "min-height: 45px" in qss.styleSheet() and "font-size: 21px" in qss.styleSheet()
        # Qt applies the (already scaled) stylesheet minimum itself: never twice.
        assert qss.minimumHeight() <= round(qss_minimum * 1.5) + 2
        ui_zoom.set_zoom_percent(200)
        ui_zoom.apply_to(root)
        assert fixed.minimumHeight() == 84  # from the logical 42, not compounding
        ui_zoom.set_zoom_percent(100)
        ui_zoom.apply_to(root)
        APP.processEvents()
        assert fixed.minimumHeight() == 42 and layout.contentsMargins().top() == 12 and layout.spacing() == 8
        assert qss.styleSheet() == "QPushButton { min-height: 30px; font-size: 14px; }"
    finally:
        _reset_zoom()
        root.close()
        root.deleteLater()


def test_set_size_keeps_logical_values_for_responsive_code():
    from twobyteasr.app import ui_zoom
    root = QWidget()
    widget = QWidget(root)
    try:
        ui_zoom.set_zoom_percent(150)
        ui_zoom.set_size(widget, fixed_h=104, min_w=36)
        assert widget.minimumHeight() == widget.maximumHeight() == 156 and widget.minimumWidth() == 54
        ui_zoom.apply_to(root)
        assert widget.minimumHeight() == 156  # the walker does not scale it again
        ui_zoom.set_zoom_percent(100)
        ui_zoom.apply_to(root)
        assert widget.minimumHeight() == 104 and widget.minimumWidth() == 36
    finally:
        _reset_zoom()
        root.deleteLater()


def test_zoomed_page_takes_the_layout_of_a_smaller_window():
    """At 200% on a maximized window the role cards kept the wide-window
    profile, doubled, and clipped the model name (EXE check, 2026-10-10)."""
    from twobyteasr.app import ui_zoom
    from twobyteasr.app.ui_recognition import RecognitionPlanWidget
    plan = RecognitionPlanWidget()
    plan.resize(1400, 480)
    plan.show()
    APP.processEvents()
    try:
        plan._responsive_profile = ""
        plan._update_responsive_profile(True)
        assert plan._responsive_profile == "extra_large"
        ui_zoom.set_zoom_percent(200)
        assert ui_zoom.logical(1600) == 800 and ui_zoom.px(800) == 1600
        plan._responsive_profile = ""
        plan._update_responsive_profile(True)
        assert plan._responsive_profile == "normal"  # what a 700x240 band gets at 100%
    finally:
        _reset_zoom()
        plan.close()
        plan.deleteLater()


def test_studio_and_canvases_keep_their_own_ctrl_wheel():
    from twobyteasr.app.ui_zoom import _zoomable
    window = QWidget()
    studio = QWidget(window)
    studio.setObjectName("subtitleStudio")
    timeline = QWidget(studio)
    canvas = QGraphicsView(window)
    other = QLabel(window)
    try:
        assert not _zoomable(timeline) and not _zoomable(studio) and not _zoomable(canvas.viewport())
        assert _zoomable(other) and _zoomable(window)
    finally:
        window.deleteLater()


def test_studio_sheet_shields_it_from_the_scaled_window_sheet():
    from twobyteasr.app import ui_zoom
    APP._theme_window_qss = "QPushButton { padding: 8px; }"
    window = QWidget()
    studio = QWidget(window)
    studio.setObjectName("subtitleStudio")
    studio.setStyleSheet("QWidget#subtitleStudio { background: #000; }")
    try:
        ui_zoom.set_zoom_percent(150)
        ui_zoom.apply_to(window)
        assert studio.styleSheet().startswith("QPushButton { padding: 8px; }")  # unscaled
        ui_zoom.set_zoom_percent(100)
        ui_zoom.apply_to(window)
        assert studio.styleSheet() == "QWidget#subtitleStudio { background: #000; }"
    finally:
        _reset_zoom()
        del APP._theme_window_qss
        window.deleteLater()


def test_dialogs_grow_with_the_zoom_within_the_screen():
    from twobyteasr.app import ui_zoom
    dialog = QDialog()
    QHBoxLayout(dialog).addWidget(QLabel("设置"))
    dialog.resize(600, 400)
    try:
        ui_zoom.set_zoom_percent(150)
        ui_zoom.apply_to(dialog)
        area = dialog.screen().availableGeometry()
        assert dialog.width() == min(900, int(area.width() * 0.92))
        assert dialog.height() == min(600, int(area.height() * 0.92))
        ui_zoom.set_zoom_percent(100)
        ui_zoom.apply_to(dialog)
        assert (dialog.width(), dialog.height()) == (600, 400)
    finally:
        _reset_zoom()
        dialog.deleteLater()


def test_read_only_glossary_view_follows_writes(tmp_path, monkeypatch):
    import json
    import subtitle_core as legacy
    path = tmp_path / "learned.json"
    path.write_text(json.dumps({"schema": 1, "games": {}, "hidden_profile_ids": ["a"]}), encoding="utf-8")
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(path))
    assert legacy.hidden_runtime_game_profile_ids() == {"a"}
    first = legacy._learned_term_payload_view()
    assert legacy._learned_term_payload_view() is first  # parsed once
    path.write_text(json.dumps({"schema": 1, "games": {}, "hidden_profile_ids": ["a", "b"]}), encoding="utf-8")
    assert legacy.hidden_runtime_game_profile_ids() == {"a", "b"}  # a write is seen at once
    mapping = {"from": "古龙", "to": "骨龙", "aliases": ["x"]}
    path.write_text(json.dumps({"schema": 1, "games": {"g": {"game": "g", "mappings": [mapping]}}}), encoding="utf-8")
    [item] = legacy.learned_mappings_for_game("g")
    item["aliases"].append("changed")  # callers may edit what they get ...
    assert legacy._learned_term_payload_view()["games"]["g"]["mappings"][0]["aliases"] == ["x"]  # ... not the cache


def test_main_window_builds_heavy_pages_on_first_use():
    """Studio, the model workshop and history were ~82% of start-up widgets."""
    import moss_firered_pipeline
    import subtitle_core as legacy
    from twobyteasr.app.lazy_pages import existing_page
    from twobyteasr.app.ui import MainWindow
    window = MainWindow([], legacy, moss_firered_pipeline, None)
    try:
        for name in ("studio", "workshop", "history"):
            assert window.built_page(name) is None and existing_page(window, name) is None
        window._page_changed(window.pages.currentIndex())
        window.apply_density()
        window._refresh_studio_entry_card()
        assert window.built_page("studio") is None  # passive checks never build it
        workshop = window.workshop_page
        assert workshop is window.built_page("workshop") and window.pages.indexOf(workshop) >= 0
        assert window.workshop_page is workshop  # built once
        history = window.history_page
        assert window.pages.indexOf(history) >= 0
    finally:
        window.close()
        window.deleteLater()
        APP.processEvents()
