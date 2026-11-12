"""One application-only font for loading status artwork, never caption styles."""
import logging
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


def loading_font() -> QFont:
    app = QApplication.instance()
    result = getattr(app, '_loading_status_font', None)
    if result is None:
        from ..runtime_paths import detect_install_root
        path = detect_install_root() / 'assets/fonts/MaokenAssortedSans.otf'
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        font = QFont(families[0]) if families else QFont(app.font())
        app._loading_status_font = result = (font_id, families, font)
        if not families:
            logging.getLogger(__name__).warning('Loading font registration failed: %s (id=%s)', path, font_id)
    return QFont(result[2])
