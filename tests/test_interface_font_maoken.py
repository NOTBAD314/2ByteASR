"""2026-11-26: the interface reads in the bundled 思源黑体; 猫啃什锦黑 is only an accent.

Morning: the whole interface went 猫啃什锦黑. Afternoon (user): too much of it, readability first;
the header's row of buttons (字幕工作台, 问问兔白 ...) and 「兔白字幕」 may use it, models and AI
text processing stay serious."""
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QWidget

ROOT = Path(__file__).resolve().parents[1]


def _app():
    app = QApplication.instance() or QApplication([])
    for name in ("MaokenAssortedSans.otf", "SourceHanSansSC-Medium.otf", "SourceHanSansSC-Heavy.otf"):
        assert QFontDatabase.addApplicationFont(str(ROOT / "assets/fonts" / name)) >= 0, name
    return app


def test_body_and_titles_are_source_han_and_maoken_is_only_the_accent_stack():
    from twobyteasr.design import typography as t
    assert t.MAOKEN_FAMILY == "MaokenAssortedSans"
    assert t.UI_FONT_FAMILIES[0] == "Source Han Sans SC Medium"
    assert t.MAOKEN_FAMILY not in t.UI_FONT_FAMILIES + t.TITLE_FONT_FAMILIES + t.CONTENT_FONT_FAMILIES
    assert t.PLAYFUL_FONT_FAMILIES[0] == t.MAOKEN_FAMILY
    # Its few missing glyphs fall back to the bundled faces, never straight to a system font.
    assert "Source Han Sans SC Heavy" in t.PLAYFUL_FONT_FAMILIES[:3]
    assert (ROOT / "assets/fonts/MaokenAssortedSans.otf").is_file()


def test_no_hand_written_style_sheet_puts_maoken_on_content():
    allowed = {"design/typography.py", "design/loading_font.py", "diagnostics/build_identity.py",
               "caption_style/font_picker_preview.py"}
    found = []
    for path in (ROOT / "twobyteasr").rglob("*.py"):
        rel = path.relative_to(ROOT / "twobyteasr").as_posix()
        if rel in allowed or rel.startswith("acceptance/"):
            continue
        if "MaokenAssortedSans" in path.read_text(encoding="utf-8", errors="ignore"):
            found.append(rel)
    assert not found, found


def test_labels_and_inputs_read_in_source_han_and_the_header_row_in_maoken():
    app = _app()
    previous = app.font()
    from twobyteasr.design.main_ui_theme import APP_QSS
    from twobyteasr.design.surface_qss import build_surface_qss
    from twobyteasr.design.ui_theme import THEMES, DEFAULT_THEME_KEY
    from twobyteasr.design.typography import emphasis_qss, install_application_fonts
    try:
        install_application_fonts(app)
        window = QWidget()
        window.setStyleSheet(emphasis_qss(APP_QSS) + build_surface_qss(THEMES[DEFAULT_THEME_KEY]))
        label, button = QLabel("主力模型", window), QPushButton("AI 文字处理", window)
        line, plain = QLineEdit("https://a.b/AbC", window), QPlainTextEdit(window)
        header = QFrame(window)
        header.setObjectName("appHeader")
        row = QHBoxLayout(header)
        nav = QPushButton("字幕工作台")
        nav.setObjectName("softAction")
        nav.setProperty("homeNavigation", True)
        title = QLabel("兔白字幕")
        title.setObjectName("headerSubtitle")
        row.addWidget(nav)
        row.addWidget(title)
        for widget in (label, button, line, plain, nav, title):
            widget.ensurePolished()          # class fonts are applied when a widget is polished
        for widget in (label, button, line, plain):
            # Requested families: the offscreen platform resolves registered faces unreliably.
            assert widget.font().families()[0] != "MaokenAssortedSans", widget.text() if hasattr(widget, "text") else type(widget).__name__
        assert label.font().families()[0] == "Source Han Sans SC Medium"
        for widget in (nav, title):
            assert widget.font().families()[0] == "MaokenAssortedSans", widget.text()
        # A widget that sets its own font keeps it (caption editors, the font picker).
        from PySide6.QtGui import QFont
        custom = QLineEdit(window)
        custom.setFont(QFont("Cascadia Mono", 10))
        custom.ensurePolished()
        assert custom.font().family() == "Cascadia Mono"
    finally:
        app.setFont(previous)
        for name in ("QLineEdit", "QTextEdit", "QPlainTextEdit"):
            app.setFont(previous, name)


def test_ask_bunny_button_paints_in_maoken():
    _app()
    from twobyteasr.app.ask_bunny_button import AskBunnyButton
    button = AskBunnyButton("问问兔白")
    assert button._font().families()[0] == "MaokenAssortedSans"


def test_helper_ships_the_same_font_unmodified_and_uses_it_only_for_accents():
    folder = ROOT / "assets/browser-helper/fonts"
    woff2 = folder / "MaokenAssortedSans.woff2"
    assert woff2.read_bytes()[:4] == b"wOF2"
    assert (folder / "MaokenAssortedSans-OFL.txt").read_text(encoding="utf-8").startswith("Copyright")
    css = (ROOT / "assets/browser-helper/popup.css").read_text(encoding="utf-8")
    assert 'url("fonts/MaokenAssortedSans.woff2")' in css
    assert '13px/1.42 "Source Han Sans SC"' in css
    assert 'h1, .primary { font-family: "MaokenAssortedSans"' in css
