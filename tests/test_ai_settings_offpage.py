"""The AI settings form lives off the home page and appears only inside its
dialog (2026-10-09: a re-parented, never-hidden panel floated over the home
page's top-left corner at startup)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


def test_ai_panel_is_hidden_on_the_home_page_and_shown_in_its_dialog():
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow([], legacy, object(), None)
    try:
        window.resize(1600, 960)
        window.show()
        for _ in range(5):
            app.processEvents()
        panel = window.ai_panel
        assert not panel.isVisible()
        # Even when the form starts expanded (keys missing), it stays off-page.
        panel.set_expanded(True, animate=False)
        app.processEvents()
        assert not panel.isVisible()
        window._open_ai_settings_dialog()
        app.processEvents()
        dialog = window._ai_settings_dialog
        assert dialog is not None and dialog.isAncestorOf(panel) and panel.isVisible()
        dialog.reject()
        from PySide6.QtTest import QTest
        for _ in range(60):  # the dialog closes with a short animation
            QTest.qWait(50)
            if not panel.isVisible():
                break
        assert not panel.isVisible()
        assert panel.parentWidget() is window.settings_page_widget  # returned off-page
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
