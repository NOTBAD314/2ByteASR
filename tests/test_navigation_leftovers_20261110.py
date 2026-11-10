"""2026-11-10 user reports: a black player rectangle left over the library after
going back, and a tiny window flashing when 链接下载 opens."""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from tests.test_page_open_library import library, _wait_scan  # noqa: F401  (fixture)
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def test_return_home_from_library_keeps_editor_and_video_hidden(library):
    page = SubtitleStudioPage(deferred_build=True)
    try:
        page.finish_workspace_construction()
        page.resize(1400, 900)
        page.show()
        page.show_project_hub()
        _wait_scan(page)
        assert page.workspace_layers.currentWidget() is page.studio_empty
        assert not page.workspace_splitter.isVisible() and not page.video.isVisible()
        # Home calls this on every return, also from the library.
        page._close_export_workspace()
        assert page.studio_empty.isVisible()
        assert not page.workspace_splitter.isVisible()
        assert not page.video.isVisible()
    finally:
        page.close_page()


class _WindowShows(QObject):
    def __init__(self):
        super().__init__()
        self.names = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.names.append(obj.objectName() or type(obj).__name__)
        return False


def test_link_task_cards_never_open_their_own_windows():
    from twobyteasr.app.link_download_widgets import TaskCard
    app = QApplication.instance() or QApplication([])
    spy = _WindowShows()
    app.installEventFilter(spy)
    try:
        # A parentless label that is shown opens (and flashes) as a window
        # even if a layout reparents it a moment later.
        cards = [TaskCard("full"), TaskCard("compact", compact=True)]
        app.processEvents()
    finally:
        app.removeEventFilter(spy)
    assert spy.names == []
    full, compact = cards
    assert not full.state.isHidden() and not full.stepper.isHidden() and full.state_text.isHidden()
    assert compact.state.isHidden() and compact.stepper.isHidden() and not compact.state_text.isHidden()
    for card in cards:
        card.deleteLater()
