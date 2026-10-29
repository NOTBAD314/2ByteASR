"""Queued terminal events must never steal/delete Studio's shared canvas."""
import threading
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QEvent, Signal, QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout
from shiboken6 import isValid
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia

APP = QApplication.instance() or QApplication([])


class Preview(QWidget):
    position_changed = Signal(float)
    playback_state_changed = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.paused = False
        self.controller = SimpleNamespace(set_volume=lambda v: setattr(self, 'volume', v))

    def set_paused(self, value):
        self.paused = value


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr(StudioExportWorkspace, '_populate_encoders', lambda self: None)
    parent = QWidget()
    layout = QGridLayout(parent)
    preview = Preview(parent)
    layout.addWidget(preview, 0, 0)
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path/'media.mp4'), duration_ms=2000))
    workspace = StudioExportWorkspace(project, '', parent=parent, preview_widget=preview)
    yield workspace, parent, preview
    if isValid(workspace):
        workspace.release_preview()
        workspace.deleteLater()
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize('terminal', ['success', 'failure', 'cancelled'])
def test_queued_terminal_after_release_cannot_reparent_or_destroy_canvas(ui, terminal):
    workspace, parent, preview = ui
    workspace._running = True
    workspace._run_generation = 7
    producer = threading.Thread(target=lambda: workspace.run_event.emit(7, terminal, 'unused.mp4'))
    producer.start(); producer.join()
    workspace.release_preview()
    workspace.deleteLater()
    APP.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert isValid(preview)
    assert preview.parentWidget() is parent
    assert preview.paused
    assert workspace._cancelled.is_set()


def test_release_cancels_only_owned_run_restores_volume_and_is_idempotent(ui):
    workspace, parent, preview = ui
    workspace._preview_volume_before_export = 35.
    workspace.release_preview()
    workspace.release_preview()
    workspace._show_cancelled()
    workspace._show_failure('late')
    workspace._show_success('late.mp4')
    assert preview.parentWidget() is parent and preview.volume == 35.
    assert workspace._preview_widget is None


def test_stale_run_event_cannot_change_new_run_or_timer(ui):
    workspace, _, _ = ui
    workspace._running = True
    workspace._run_generation = 9
    workspace._receive_run_event(8, 'cancelled', None)
    workspace._receive_run_event(8, 'progress', {'stage': 'encoding', 'percent': '95'})
    assert workspace._running
    assert not workspace._progress_clock.isActive()


def test_terminal_state_stops_progress_clock_and_keeps_preview_paused(ui):
    workspace, _, preview = ui
    workspace._running = True
    workspace._progress_clock.start()
    workspace._show_cancelled()
    assert not workspace._running
    assert not workspace._progress_clock.isActive()
    assert preview.paused


def test_initialization_failure_returns_borrowed_canvas(tmp_path, monkeypatch):
    parent = QWidget()
    layout = QGridLayout(parent)
    preview = Preview(parent)
    layout.addWidget(preview, 0, 0)
    def fail_after_borrow(workspace):
        host = QWidget(workspace)
        QGridLayout(host).addWidget(preview, 0, 0)
        raise RuntimeError('controlled constructor failure')
    monkeypatch.setattr(StudioExportWorkspace, '_build', fail_after_borrow)
    with pytest.raises(RuntimeError, match='controlled'):
        StudioExportWorkspace(SubtitleProject(media=StudioMedia(path='')), '', parent=parent, preview_widget=preview)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert isValid(preview) and preview.parentWidget() is parent
    assert preview.paused
    parent.deleteLater()


def test_closing_export_surface_releases_owned_run_and_borrowed_canvas(ui):
    workspace,parent,preview=ui
    workspace._running=True
    workspace.close()
    assert workspace._released and workspace._cancelled.is_set()
    assert preview.parentWidget() is parent and isValid(preview)


def test_dead_preview_transport_cannot_prevent_canvas_return(ui):
    workspace,parent,preview=ui
    def unavailable(*_args):raise RuntimeError('controlled dead transport')
    preview.controller.set_volume=unavailable
    preview.set_paused=unavailable
    workspace._preview_volume_before_export=20.
    workspace.release_preview()
    assert workspace._released and workspace._cancelled.is_set()
    assert preview.parentWidget() is parent and isValid(preview)


@pytest.mark.parametrize('mode',['current','speaker','all'])
def test_return_preserves_style_target_scope_while_restoring_selection(mode):
    from PySide6.QtWidgets import QComboBox
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.timeline.selection_scope import SelectionScope
    combo=QComboBox()
    for key in ('current','selected','speaker','all'):combo.addItem(key,key)
    combo.setCurrentIndex(combo.findData(mode))
    project=object()
    desired=SelectionScope.explicit(['a'],'a')
    page=SimpleNamespace(project=project,export_workspace=None,style_scope=combo,
        selection_model=SimpleNamespace(scope=SelectionScope.explicit(['b'],'b')),
        _export_return_ui=dict(project=project,scope=desired,style_scope=mode,
            clips={},viewport=(1200,6000),vertical=0),
        _cancel_scrub=lambda:None,unsetCursor=lambda:None,_sync_navigation_chrome=lambda:None)
    def select(scope):
        page.selection_model.scope=scope
        combo.setCurrentIndex(combo.findData('selected'))
    page.cue_controller=SimpleNamespace(apply_selection_scope=select)
    page.timeline=SimpleNamespace(selected_video_clip_id='',set_visible_window=lambda *_args:None,
        vertical_scrollbar=SimpleNamespace(setValue=lambda _value:None))
    page.video_compositor=SimpleNamespace(set_selected_clip=lambda _value:None)
    SubtitleStudioPage._close_export_workspace(page)
    assert page.selection_model.scope==desired and combo.currentData()==mode
    combo.deleteLater()
