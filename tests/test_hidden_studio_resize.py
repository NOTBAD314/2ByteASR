"""Resize work belongs to the loading request that queued it, never its successor."""
from types import MethodType, SimpleNamespace as NS

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget
from shiboken6 import isValid

from twobyteasr.app import ui
from twobyteasr.studio.studio_loading import StudioLoadingView
from twobyteasr.studio.studio_readiness import StudioReadiness

APP = QApplication.instance() or QApplication([])


class Shell(QWidget):
    _queue_hidden_studio_geometry = ui.MainWindow._queue_hidden_studio_geometry
    _prepare_hidden_studio_geometry = ui.MainWindow._prepare_hidden_studio_geometry

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.pages = QStackedWidget(self)
        layout.addWidget(self.pages)
        self.home, self.studio, self.loading = QWidget(), QWidget(), QWidget()
        self.studio.project = object()
        for page in (self.home, self.studio, self.loading):
            self.pages.addWidget(page)
        self.pages.setCurrentWidget(self.loading)
        self._studio_loading_session = NS(active=True, state='preparing', generation=7,
                                          path='A', view=self.loading)
        self.resize(900, 600)

    def built_page(self, name):
        return self.studio if name == 'studio' else None


@pytest.fixture
def shell(monkeypatch):
    window = Shell()
    window.show()
    APP.processEvents()
    queued = []
    monkeypatch.setattr(ui, 'QTimer', NS(singleShot=lambda ms, receiver, callback:
        queued.append((ms, receiver, callback))))
    yield window, queued
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def pending_callback(queued, index=0):
    milliseconds, receiver, callback = queued[index]
    assert milliseconds == 0 and isValid(receiver)
    return callback


def attach_gate(window):
    session = window._studio_loading_session
    completed = {'读取工程', '首屏绘制'}
    session.completed = completed
    gate = NS(page=window.studio, loading=session, generation=session.generation,
              loading_generation=session.generation, path=session.path, active=True, ready=False,
              painted=True, completed=completed,
              profile={'timeline_surface_prepared':True, 'timeline_prepared_hidden':True})
    gate._owns_request = MethodType(StudioReadiness._owns_request, gate)
    gate.invalidate_surface_geometry = MethodType(StudioReadiness.invalidate_surface_geometry, gate)
    window.studio._readiness = gate
    return gate


def test_resize_burst_commits_latest_stack_rect_once(shell, monkeypatch):
    window, queued = shell
    from twobyteasr.design import ui_motion
    settled = []
    monkeypatch.setattr(ui_motion, 'settle_layout', lambda page:settled.append(page))
    window.studio.setGeometry(0, 0, 100, 30)
    window._queue_hidden_studio_geometry()
    window.resize(1100, 720)
    window.layout().activate()
    window._queue_hidden_studio_geometry()
    window.resize(1000, 680)
    window.layout().activate()
    window._queue_hidden_studio_geometry()
    assert len(queued) == 1
    pending_callback(queued)()
    assert window.studio.geometry() == window.pages.contentsRect()
    assert settled == [window.studio]
    assert not window.studio.isVisible()
    assert window.pages.currentWidget() is window.loading


def test_unbound_Hub_cannot_consume_initial_workspace_geometry(shell):
    window, queued = shell
    window.studio.project = None
    window.studio.setGeometry(0, 0, 100, 30)
    window._queue_hidden_studio_geometry()
    assert queued == [] and window.studio.geometry() == QRect(0, 0, 100, 30)


def test_late_A_callback_cannot_size_B_without_B_notification(shell):
    window, queued = shell
    window.studio.setGeometry(0, 0, 100, 30)
    window._queue_hidden_studio_geometry()
    window._studio_loading_session.generation += 1
    window._studio_loading_session.path = 'B'
    pending_callback(queued)()
    assert window.studio.geometry() == QRect(0, 0, 100, 30)


def test_B_notification_replaces_pending_A_without_A_consuming_B(shell):
    window, queued = shell
    window.studio.setGeometry(0, 0, 100, 30)
    window._queue_hidden_studio_geometry()
    window._studio_loading_session.generation += 1
    window._studio_loading_session.path = 'B'
    window._queue_hidden_studio_geometry()
    assert len(queued) == 2
    pending_callback(queued, 0)()
    assert window.studio.geometry() == QRect(0, 0, 100, 30)
    pending_callback(queued, 1)()
    assert window.studio.geometry() == window.pages.contentsRect()


@pytest.mark.parametrize('state', ['cancelled', 'ready', 'home', 'visible', 'close_pending',
                                  'close_finalizing', 'page_closing', 'new_session'])
def test_queued_update_is_inert_after_ownership_is_lost(shell, state):
    window, queued = shell
    window.studio.setGeometry(0, 0, 100, 30)
    window._queue_hidden_studio_geometry()
    session = window._studio_loading_session
    if state in ('cancelled','ready'):
        session.active = False
        session.state = state
    elif state == 'home': window.pages.setCurrentWidget(window.home)
    elif state == 'visible': window.pages.setCurrentWidget(window.studio)
    elif state == 'close_pending': window._studio_close_pending = True
    elif state == 'close_finalizing': window._studio_close_finalizing = True
    elif state == 'page_closing': window.studio._close_requested = True
    else: window._studio_loading_session = NS(**session.__dict__)
    before = window.studio.geometry()
    pending_callback(queued)()
    assert window.studio.geometry() == before


def test_queued_update_does_not_call_a_deleted_Qt_page(shell):
    window, queued = shell
    window._queue_hidden_studio_geometry()
    window.studio.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(window.studio)
    pending_callback(queued)()  # A stale Python wrapper must not be dereferenced.


def test_same_rect_does_not_settle_or_invalidate_paint(shell, monkeypatch):
    window, queued = shell
    window.studio.setGeometry(window.pages.contentsRect())
    gate = attach_gate(window)
    from twobyteasr.design import ui_motion
    def forbidden(_): raise AssertionError('same rectangle walked the widget tree')
    monkeypatch.setattr(ui_motion, 'settle_layout', forbidden)
    window._queue_hidden_studio_geometry()
    pending_callback(queued)()
    assert gate.painted and '首屏绘制' in gate.completed
    assert gate.profile['timeline_surface_prepared']


def test_first_restore_settles_placeholder_children_even_when_root_rect_is_correct(shell):
    window, _ = shell
    page = window.studio
    page.setGeometry(window.pages.contentsRect())
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    page.timeline = QWidget(page)
    layout.addWidget(page.timeline)
    page.timeline.setGeometry(0, 0, 100, 30)
    layout.invalidate()
    gate = attach_gate(window)
    root_rect = page.geometry()
    # Reproduces the root-only Hub preparation: a normal same-rect callback
    # intentionally cannot consume the first project subtree's layout work.
    assert window._prepare_hidden_studio_geometry(page)
    assert page.geometry() == root_rect and page.timeline.size().width() == 100
    assert gate.painted
    assert window._prepare_hidden_studio_geometry(page, force_settle=True)
    assert page.geometry() == root_rect and page.timeline.rect() == page.rect()
    assert not gate.painted and '首屏绘制' not in gate.completed
    assert not page.isVisible()


def test_actual_size_change_retires_only_current_paint_witness(shell):
    window, queued = shell
    window.studio.setGeometry(0, 0, 100, 30)
    gate = attach_gate(window)
    window._queue_hidden_studio_geometry()
    pending_callback(queued)()
    assert not gate.painted and gate.completed == {'读取工程'}
    assert 'timeline_surface_prepared' not in gate.profile
    assert gate.generation == gate.loading.generation == 7


def test_only_position_change_keeps_existing_paint_witness(shell):
    window, queued = shell
    target = window.pages.contentsRect()
    window.studio.setGeometry(target.translated(1, 1))
    gate = attach_gate(window)
    window._queue_hidden_studio_geometry()
    pending_callback(queued)()
    assert window.studio.geometry() == target
    assert gate.painted and '首屏绘制' in gate.completed


@pytest.mark.parametrize('stale', ['generation', 'path', 'closed'])
def test_geometry_invalidation_cannot_retire_another_readiness_request(shell, stale):
    window, _ = shell
    gate = attach_gate(window)
    if stale == 'generation': gate.generation -= 1
    elif stale == 'path': gate.path = 'old'
    else: window.studio._close_requested = True
    assert not gate.invalidate_surface_geometry()
    assert gate.painted and '首屏绘制' in gate.completed


def test_loading_view_reports_only_stack_geometry_events(shell):
    window, _ = shell
    view = StudioLoadingView(window.pages, window, page_stack=True)
    calls = []
    view.geometry_changed.connect(lambda:calls.append(True))
    try:
        view.eventFilter(window.pages, QEvent(QEvent.Type.Resize))
        view.eventFilter(window.pages, QEvent(QEvent.Type.LayoutRequest))
        view.eventFilter(window, QEvent(QEvent.Type.Resize))
        view.eventFilter(window.pages, QEvent(QEvent.Type.Paint))
        assert len(calls) == 2
    finally:
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
