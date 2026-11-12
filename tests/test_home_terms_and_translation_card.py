"""2026-11-11 (user): choosing a game switches 原文校对术语库 on; no home 翻译词库 button; a round translation card."""
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class _Switch:
    def __init__(self, checked=False):
        self.checked = checked
        self.calls = 0

    def isChecked(self):
        return self.checked

    def setChecked(self, value):
        self.calls += 1
        self.checked = bool(value)


def test_choosing_a_content_switches_the_source_glossary_on_once():
    from twobyteasr.app.ui import MainWindow
    text = {'value': '原神'}
    window = SimpleNamespace(game_box=SimpleNamespace(currentText=lambda: text['value']), terms=_Switch(False))
    window.__dict__['_terms_auto_for'] = None
    MainWindow._content_chosen(window)
    assert window.terms.isChecked()
    window.terms.setChecked(False)              # the user turns it off again for the same content
    MainWindow._content_chosen(window)
    assert not window.terms.isChecked()         # ...and it stays off
    text['value'] = '洛克王国：世界'               # another content: on again
    MainWindow._content_chosen(window)
    assert window.terms.isChecked()
    text['value'] = '   '
    window.terms.setChecked(False)
    MainWindow._content_chosen(window)
    assert not window.terms.isChecked()          # nothing chosen: nothing changes


def test_the_home_row_has_no_translation_library_button():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'twobyteasr' / 'app' / 'ui.py').read_text(encoding='utf-8')
    assert 'output_row.addWidget(self.translation_term_libraries' not in source
    assert 'self.translation_term_libraries.hide()' in source


def test_the_translation_dialog_is_a_frameless_round_card():
    from PySide6.QtCore import Qt
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
    from twobyteasr.studio.translation_dialog_parts import build_translation_dialog_qss
    from twobyteasr.design.studio_theme import _active_theme
    qss = build_translation_dialog_qss(_active_theme(None))
    assert 'QFrame#translationCard' in qss and 'border-radius: 26px' in qss
    # Qt ignores a radius over half the height (the button looked square): 21 px on a 48 px button.
    assert 'QDialog#translationDialog QPushButton#translationStart { border-radius: 21px; min-height: 48px' in qss
    assert SubtitleTranslationDialog.SHADOW > 0 and hasattr(SubtitleTranslationDialog, '_drag_window')
    assert Qt.WindowType.FramelessWindowHint  # the flag the dialog sets (checked in the real-window audit)
