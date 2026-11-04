"""Page visibility callbacks cannot release native video before destination paint."""
import pytest
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from twobyteasr.app.ui import MainWindow
from twobyteasr.studio.studio_video_canvas import MpvCanvas

APP = QApplication.instance() or QApplication([])


class Studio(QWidget):
    def __init__(self):
        super().__init__()
        self.video = MpvCanvas(self)
        self.video._studio_page = lambda: self
        self.studio_toolbar = QWidget(self)
        self.visible_reasons = []

    def showEvent(self, event):
        self.video.set_navigation_visible(True)
        self.visible_reasons.append(set(self.video._presentation_block_reasons))
        super().showEvent(event)

    def hideEvent(self, event):
        self.video.set_navigation_visible(False)
        super().hideEvent(event)


class Shell(QWidget):
    def __init__(self):
        super().__init__()
        self.content_layout = QVBoxLayout(self)
        self.pages = QStackedWidget(self)
        self.content_layout.addWidget(self.pages)
        self.app_header = QWidget(self)
        self.settings_scroll = QWidget()
        self.studio = Studio()
        self.pages.addWidget(self.settings_scroll)
        self.pages.addWidget(self.studio)
        self.paints = []
        self.paint_masks = []
        self.fail_paint = False

    def built_page(self, name):
        return self.studio if name == 'studio' else None

    def _ensure_recognition_page(self):
        pass

    def _prepare_page_presentation(self, widget):
        MainWindow._prepare_page_presentation(self, widget)

    def _native_video_handoff(self):
        return MainWindow._native_video_handoff(self)

    def _flush_native_page_presentation(self, receipt):
        return MainWindow._flush_native_page_presentation(self, receipt)

    def repaint(self, *args):
        self.paints.append(set(self.studio.video._presentation_block_reasons))
        self.paint_masks.append(self.studio.video.mask())
        if self.fail_paint:
            raise RuntimeError('injected destination paint failure')
        return super().repaint(*args)


@pytest.fixture
def shell(monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_DIAGNOSTIC_NO_PLAYER', '1')
    window = Shell()
    window.show()
    APP.processEvents()
    window.studio.video.set_navigation_visible(False)
    yield window
    window.studio.video.close_player()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_hot_entry_holds_video_when_show_event_releases_navigation(shell):
    MainWindow._switch_page(shell, shell.studio)
    assert shell.studio.visible_reasons[-1] == {'page-handoff'}
    assert shell.paints[-1] == {'page-handoff'}
    assert not shell.studio.video.presentation_blocked


def test_home_handoff_keeps_navigation_block_after_paint(shell):
    MainWindow._switch_page(shell, shell.studio)
    MainWindow._switch_page(shell, shell.settings_scroll)
    assert shell.paints[-1] == {'navigation'}
    assert shell.paint_masks[-1].isEmpty()
    assert shell.studio.video._presentation_block_reasons == {'navigation'}
    assert not shell.studio.video.mask().isEmpty()


def test_native_cover_mode_retires_video_before_home_destination_paint(shell):
    shell._studio_loading_session = SimpleNamespace(uses_native_cover=True)
    MainWindow._switch_page(shell, shell.studio)
    MainWindow._switch_page(shell, shell.settings_scroll)
    assert shell.paints[-1] == {'navigation'}
    assert not shell.paint_masks[-1].isEmpty()
    assert shell.studio.video._presentation_defer_depth == 0
    assert '_studio_native_visibility' not in shell.__dict__


def test_native_cover_mode_hot_entry_waits_for_destination_paint(shell):
    shell._studio_loading_session = SimpleNamespace(uses_native_cover=True)
    MainWindow._switch_page(shell, shell.studio)
    assert shell.studio.visible_reasons[-1] == {'page-handoff'}
    assert shell.paints[-1] == {'page-handoff'}
    assert not shell.studio.video.presentation_blocked
    assert '_studio_native_visibility' not in shell.__dict__


def test_failed_paint_does_not_leave_an_orphan_handoff_owner(shell):
    shell.fail_paint = True
    with pytest.raises(RuntimeError, match='injected destination paint failure'):
        MainWindow._switch_page(shell, shell.studio)
    assert 'page-handoff' not in shell.studio.video._presentation_block_reasons


def test_owned_hidden_page_uses_stack_extent_before_layout_restore(shell):
    loading_view = QWidget()
    shell.pages.addWidget(loading_view)
    shell.pages.setCurrentWidget(loading_view)
    shell._studio_loading_session = SimpleNamespace(active=True, view=loading_view)
    shell.studio.setGeometry(0, 0, 100, 30)
    assert not shell.studio.isVisible()
    assert MainWindow._prepare_hidden_studio_geometry(shell, shell.studio)
    assert shell.studio.geometry() == shell.pages.contentsRect()
    assert not shell.studio.isVisible()
    assert shell.pages.currentWidget() is loading_view


@pytest.mark.parametrize('state', ['cancelled', 'different_page', 'already_visible'])
def test_hidden_geometry_cannot_take_over_an_unowned_or_visible_page(shell, state):
    loading_view = QWidget()
    shell.pages.addWidget(loading_view)
    shell.pages.setCurrentWidget(loading_view)
    shell._studio_loading_session = SimpleNamespace(active=state != 'cancelled', view=loading_view)
    if state == 'different_page':
        shell.pages.setCurrentWidget(shell.settings_scroll)
    elif state == 'already_visible':
        shell.pages.setCurrentWidget(shell.studio)
    before = shell.studio.geometry()
    assert not MainWindow._prepare_hidden_studio_geometry(shell, shell.studio)
    assert shell.studio.geometry() == before
