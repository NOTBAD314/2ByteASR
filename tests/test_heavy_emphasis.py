"""2026-11-13: emphasis (weight >= 600) uses the bundled Heavy face, body stays Medium."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re

from twobyteasr.design.typography import (
    MONO_FONT_STACK, TITLE_FONT_FAMILIES, TITLE_FONT_STACK, UI_FONT_FAMILIES, UI_FONT_STACK,
    emphasis_qss, heavy_font, weighted_font,
)


def _rule(sheet, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", sheet)
    assert match, selector
    return match.group(1)


def test_emphasis_rules_get_heavy_and_body_rules_get_medium():
    sheet = emphasis_qss(
        "QLabel#title { font-size: 18px; font-weight: 700; }\n"
        "QPushButton:checked { font-weight: 600 }\n"
        "QLabel#body { color: red; font-weight: 500; }\n"
        "QLabel#plain { color: red; }\n")
    assert f"font-family: {TITLE_FONT_STACK}" in _rule(sheet, "QLabel#title")
    assert f"font-family: {TITLE_FONT_STACK}" in _rule(sheet, "QPushButton:checked")
    assert f"font-family: {UI_FONT_STACK}" in _rule(sheet, "QLabel#body")
    assert "font-family" not in _rule(sheet, "QLabel#plain")


def test_explicit_families_are_respected_except_body_face_with_emphasis():
    sheet = emphasis_qss(
        f"QLabel#time {{ font-family: {MONO_FONT_STACK}; font-weight: 700; }}\n"
        f"QLabel#hero {{ font-family: {UI_FONT_STACK}; font-weight: 800; }}\n"
        "QFrame#bar { font-weight: 600; font-family: \"Source Han Sans SC\", sans-serif; }\n"
        f"QLabel#done {{ font-family: {TITLE_FONT_STACK}; font-weight: 800; }}\n")
    assert MONO_FONT_STACK in _rule(sheet, "QLabel#time")
    assert f"font-family: {TITLE_FONT_STACK};" in _rule(sheet, "QLabel#hero")
    assert TITLE_FONT_STACK in _rule(sheet, "QFrame#bar")
    assert _rule(sheet, "QLabel#done").count("font-family") == 1


def test_declaration_lists_keywords_and_idempotence():
    bare = emphasis_qss("color: #333; font-size: 13px; font-weight: bold")
    assert bare.endswith(f"font-weight: bold; font-family: {TITLE_FONT_STACK};")
    assert emphasis_qss(bare) == bare
    sheet = emphasis_qss("QLabel { /* font-weight: 900 */ font-weight: 400; }")
    assert UI_FONT_STACK in sheet and TITLE_FONT_STACK not in sheet
    assert emphasis_qss("") == "" and emphasis_qss("QLabel { color: red; }") == "QLabel { color: red; }"


def test_checked_emphasis_is_mirrored_and_applied_after_toggle():
    """Qt ignores fonts in widget-level :checked rules; the [checked] mirror plus a re-polish shows them."""
    from PySide6.QtWidgets import QApplication, QToolButton, QWidget
    from twobyteasr.design import theme_manager
    from twobyteasr.design.typography import CHECKED_EMPHASIS
    app = QApplication.instance() or QApplication([])
    sheet = emphasis_qss("QToolButton#heavyTab { font-weight: 500; }\n"
                         "QToolButton#heavyTab:checked { font-weight: 700; }\n"
                         "QTabBar::tab:selected { font-weight: 700; }")
    assert 'QToolButton#heavyTab[checked="true"]' in sheet
    assert "::tab[checked" not in sheet and "heavyTab" in CHECKED_EMPHASIS
    root = QWidget()
    root.setStyleSheet(sheet)
    button = QToolButton(root)
    button.setObjectName("heavyTab")
    button.setCheckable(True)
    root.show()
    app.processEvents()
    try:
        theme_manager._follow_checked_emphasis(button)
        assert button.font().families()[:1] == [UI_FONT_FAMILIES[0]]
        button.setChecked(True)
        app.processEvents()
        assert button.font().families()[:1] == [TITLE_FONT_FAMILIES[0]]
        button.setChecked(False)
        app.processEvents()
        assert button.font().families()[:1] == [UI_FONT_FAMILIES[0]]
    finally:
        root.close()


def test_painted_fonts_follow_the_same_split():
    from PySide6.QtGui import QFont
    font = QFont()
    font.setFamilies(list(UI_FONT_FAMILIES))
    heavy = heavy_font(QFont(font))
    assert heavy.families() == list(TITLE_FONT_FAMILIES) and heavy.weight() >= 800
    assert weighted_font(QFont(font), QFont.Weight.DemiBold).families() == list(TITLE_FONT_FAMILIES)
    back = weighted_font(QFont(heavy), QFont.Weight.Medium)
    assert back.families() == list(UI_FONT_FAMILIES) and back.weight() == 500
    mono = QFont("Cascadia Mono")
    assert weighted_font(mono, QFont.Weight.Normal).family() == "Cascadia Mono"


def test_theme_and_page_sheets_have_no_fake_bold_rules():
    """Every rule asking for >= 600 in the shipped sheets names a non-body family."""
    from twobyteasr.design.glossary_page_qss import build_glossary_page_qss
    from twobyteasr.design.home_qss import build_home_qss
    from twobyteasr.design.soft_dialog_qss import build_settings_qss
    from twobyteasr.design.studio_theme import build_secondary_surface_qss, build_studio_qss
    from twobyteasr.design.ui_theme import theme_definition
    theme = theme_definition("warm")
    weight = re.compile(r"font-weight\s*:\s*(\d+|bold)")
    for sheet in (build_studio_qss(theme), build_secondary_surface_qss(theme), build_home_qss(theme),
                  build_glossary_page_qss(theme), build_settings_qss(theme)):
        for body in re.findall(r"\{([^{}]*)\}", sheet):
            found = weight.findall(body)
            if found and (found[-1] == "bold" or int(found[-1]) >= 600):
                assert "font-family" in body, body
                assert not re.search(r"font-family\s*:\s*\"Source Han Sans SC Medium\"", body), body
