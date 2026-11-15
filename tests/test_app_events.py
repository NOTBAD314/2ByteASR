"""One shared application filter instead of one Python call per listener per event (2026-11-14)."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])

from twobyteasr.design import app_events


class Recorder(QObject):
    def __init__(self, name, log, consume=False):
        super().__init__()
        self.name, self.log, self.consume = name, log, consume

    def eventFilter(self, watched, event):
        self.log.append((self.name, event.type()))
        return self.consume


def send(widget, kind):
    event = QEvent(kind)
    QCoreApplication.sendEvent(widget, event)


def test_listeners_only_see_their_event_types():
    log = []
    show_only = Recorder('show', log)
    app_events.listen(show_only, (QEvent.Type.Show,))
    try:
        widget = QWidget()
        send(widget, QEvent.Type.StyleChange)
        send(widget, QEvent.Type.Show)
        assert log == [('show', QEvent.Type.Show)]
    finally:
        app_events.unlisten(show_only)


def test_newest_listener_runs_first_and_can_consume():
    log = []
    older = Recorder('older', log)
    newer = Recorder('newer', log, consume=True)
    app_events.listen(older, (QEvent.Type.ToolTip,))
    app_events.listen(newer, (QEvent.Type.ToolTip,))
    try:
        send(QWidget(), QEvent.Type.ToolTip)
        assert [name for name, _ in log] == ['newer']
        log.clear()
        app_events.listen(older, (QEvent.Type.ToolTip,))  # registering again moves it to the front
        send(QWidget(), QEvent.Type.ToolTip)
        assert [name for name, _ in log] == ['older', 'newer']
    finally:
        app_events.unlisten(older)
        app_events.unlisten(newer)


def test_destroyed_owner_stops_listening():
    log = []
    owner = Recorder('gone', log)
    app_events.listen(owner, (QEvent.Type.Show,))
    hub = app_events.hub()
    assert hub.listening(owner)
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    send(QWidget(), QEvent.Type.Show)
    assert not log


def test_a_listener_may_unregister_while_an_event_is_dispatched():
    log = []

    class Once(Recorder):
        def eventFilter(self, watched, event):
            app_events.unlisten(self)
            return super().eventFilter(watched, event)
    once = Once('once', log)
    app_events.listen(once, (QEvent.Type.Show,))
    send(QWidget(), QEvent.Type.Show)
    send(QWidget(), QEvent.Type.Show)
    assert log == [('once', QEvent.Type.Show)]


def test_permanent_whole_app_listeners_share_one_application_filter():
    from twobyteasr.design.hover_hints import install_hover_hint_policy
    policy = install_hover_hint_policy(APP)
    assert app_events.hub().listening(policy)
    event = QEvent(QEvent.Type.ToolTip)
    assert QCoreApplication.sendEvent(QWidget(), event) is True  # consumed by the policy


def test_studio_keeps_its_own_size_without_a_second_restyle(monkeypatch):
    from twobyteasr.app import ui_zoom
    page = QWidget()
    window_sheet = 'QWidget { color: red; }\n'
    monkeypatch.setattr(APP, '_theme_window_qss', window_sheet, raising=False)
    prepared = window_sheet + 'QLabel { color: blue; }'
    page.setStyleSheet(prepared)  # theme_scopes.apply_scope prefixes the unscaled window sheet
    page.setProperty('_uiZoomStudioBase', prepared)
    page.setProperty('_uiZoomStudioLast', prepared)
    sets = []
    original = page.setStyleSheet
    monkeypatch.setattr(page, 'setStyleSheet', lambda sheet: (sets.append(sheet), original(sheet)))
    ui_zoom.protect_studio(page, factor=1.1)
    assert not sets and page.styleSheet() == prepared
    bare = QWidget()
    bare.setStyleSheet('QLabel { color: blue; }')
    ui_zoom.protect_studio(bare, factor=1.1)
    assert bare.styleSheet() == window_sheet + 'QLabel { color: blue; }'


def test_removed_later_listener_is_not_called_in_same_dispatch():
    log = []
    later = Recorder('later', log)

    class RemovesLater(Recorder):
        def eventFilter(self, watched, event):
            app_events.unlisten(later)
            return super().eventFilter(watched, event)

    first = RemovesLater('first', log)
    app_events.listen(later, (QEvent.Type.User,))
    app_events.listen(first, (QEvent.Type.User,))
    try:
        send(QWidget(), QEvent.Type.User)
        assert [name for name, _ in log] == ['first']
    finally:
        app_events.unlisten(first)
        app_events.unlisten(later)


def test_destroyed_later_listener_is_not_called_in_same_dispatch():
    import shiboken6
    log = []
    later = Recorder('later', log)

    class DestroysLater(Recorder):
        def eventFilter(self, watched, event):
            shiboken6.delete(later)
            return super().eventFilter(watched, event)

    first = DestroysLater('first', log)
    app_events.listen(later, (QEvent.Type.User,))
    app_events.listen(first, (QEvent.Type.User,))
    try:
        send(QWidget(), QEvent.Type.User)
        assert [name for name, _ in log] == ['first']
    finally:
        app_events.unlisten(first)
        app_events.unlisten(later)
