"""2026-10-10 (user): the main window opened large but not maximized, with a
margin of desktop showing around it."""
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])


def _start(values):
    from twobyteasr.app.ui import MainWindow
    settings = QSettings("2ByteASR", "2ByteASR")
    for key in ("mainWindow/geometry", "mainWindow/maximized"):
        settings.remove(key)
    for key, value in values.items():
        settings.setValue(key, value)
    settings.sync()
    widget = QWidget()
    widget.show()  # the real window is shown before its saved geometry is applied
    MainWindow._apply_sane_initial_geometry(widget)
    APP.processEvents()
    return widget


def test_startup_restores_maximized_state():
    avail = QApplication.primaryScreen().availableGeometry()
    small = [avail.left() + 40, avail.top() + 40, avail.width() - 100, avail.height() - 300]
    near_full = [avail.left() + 8, avail.top() + 8, avail.width() - 16, avail.height() - 16]
    cases = [
        ({"mainWindow/geometry": small, "mainWindow/maximized": True}, True, avail.width() - 100),
        # Older versions saved only the size; one that almost fills the screen was maximized.
        ({"mainWindow/geometry": near_full}, True, min(1320, avail.width() - 16)),
        ({"mainWindow/geometry": small}, False, avail.width() - 100),
        ({"mainWindow/geometry": near_full, "mainWindow/maximized": False}, False, None),
    ]
    for values, maximized, normal_width in cases:
        widget = _start(values)
        try:
            assert widget.isMaximized() is maximized, values
            if normal_width is None:  # a large normal window the user chose
                assert widget.width() >= avail.width() - 48, values
            else:
                assert widget.normalGeometry().width() == normal_width, values
        finally:
            widget.close()
