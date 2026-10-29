import inspect
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QSplitter

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_session import StudioSession
from twobyteasr.studio.studio_ui import (
    MpvCanvas,
    SubtitlePositionOverlay,
    SubtitleStudioPage,
    WaveformTimeline,
)
from twobyteasr.studio.studio_workspace import StudioWorkspaceBuilder


def _app():
    return QApplication.instance() or QApplication([])


def test_workspace_builder_is_a_transient_plain_python_collaborator():
    assert not issubclass(StudioWorkspaceBuilder, QObject)
    assert not any(
        isinstance(value, Signal)
        for value in StudioWorkspaceBuilder.__dict__.values()
    )
    assert not {
        name
        for name in StudioWorkspaceBuilder.__dict__
        if "timer" in name.lower() or "thread" in name.lower()
    }
    source = inspect.getsource(inspect.getmodule(StudioWorkspaceBuilder))
    assert "from .studio_ui" not in source
    assert "import twobyteasr.studio.studio_ui" not in source
    assert "_build" not in SubtitleStudioPage.__dict__


def test_workspace_builder_retains_page_fields_and_qt_parent_hierarchy():
    app = _app()
    page = SubtitleStudioPage()
    app.processEvents()

    assert "workspace_builder" not in page.__dict__
    assert isinstance(page.workspace_splitter, QSplitter)
    assert isinstance(page.upper_splitter, QSplitter)
    assert isinstance(page.center_splitter, QSplitter)
    assert isinstance(page.video, MpvCanvas)
    assert isinstance(page.timeline, WaveformTimeline)
    assert isinstance(page.position_overlay, SubtitlePositionOverlay)
    assert "position_overlay_visual" not in page.__dict__

    assert page.workspace_splitter.parentWidget() is page.workspace_host
    assert page.workspace_host.parentWidget() is page
    assert page.workspace_splitter.widget(0) is page.upper_splitter
    assert page.upper_splitter.parentWidget() is page.workspace_splitter
    assert [
        page.upper_splitter.widget(index)
        for index in range(page.upper_splitter.count())
    ] == [page.cue_list_panel, page.center_splitter, page.context_panel]
    assert page.video.parentWidget().objectName() == "studioVideoOverlayHost"
    assert page.video.parentWidget().parentWidget().parentWidget() is page.center_splitter
    assert page.position_overlay.parentWidget() is page.video
    assert not page.position_overlay.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    assert page.timeline.parentWidget().parentWidget() is page.workspace_splitter
    assert all(
        not splitter.childrenCollapsible()
        for splitter in (
            page.workspace_splitter,
            page.upper_splitter,
            page.center_splitter,
        )
    )

    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_studio_session_is_plain_python_canonical_state():
    assert not issubclass(StudioSession, QObject)
    assert not any(
        isinstance(value, Signal)
        for value in StudioSession.__dict__.values()
    )
    session = StudioSession()
    assert session.project is None
    assert session.project_path is None
    assert session.selected_cue_id == ""
    assert session._cue_lookup == {}
    assert session.undo_stack is None


def test_page_compatibility_properties_delegate_without_shadow_state():
    app = _app()
    page = SubtitleStudioPage()
    app.processEvents()
    initial_undo = page.undo_stack

    project_2 = SubtitleProject(
        media=StudioMedia(path="session-2.mp4", duration_ms=1000),
        cues=[StudioCue(id="cue-2", start_ms=0, end_ms=1000, text="two")],
    )
    project_3 = SubtitleProject(
        media=StudioMedia(path="session-3.mp4", duration_ms=1000),
        cues=[StudioCue(id="cue-3", start_ms=0, end_ms=1000, text="three")],
    )
    page.project = project_2
    assert page.session.project is project_2
    page.session.project = project_3
    assert page.project is project_3

    path_2 = Path("session-2.2byteproj")
    path_3 = Path("session-3.2byteproj")
    page.project_path = path_2
    assert page.session.project_path is path_2
    page.session.project_path = path_3
    assert page.project_path is path_3

    page.selected_cue_id = "cue-2"
    assert page.session.selected_cue_id == "cue-2"
    page.session.selected_cue_id = "cue-3"
    assert page.selected_cue_id == "cue-3"

    lookup_2 = {"cue-2": project_2.cues[0]}
    lookup_3 = {"cue-3": project_3.cues[0]}
    page._cue_lookup = lookup_2
    assert page.session._cue_lookup is lookup_2
    page.session._cue_lookup = lookup_3
    assert page._cue_lookup is lookup_3

    assert page.undo_stack is initial_undo
    assert page.session.undo_stack is initial_undo
    assert page.undo_stack.parent() is page
    replacement_undo = QUndoStack(page)
    page.session.undo_stack = replacement_undo
    assert page.undo_stack is replacement_undo
    page.undo_stack = initial_undo
    assert page.session.undo_stack is initial_undo

    assert not {
        "project",
        "project_path",
        "selected_cue_id",
        "_cue_lookup",
        "undo_stack",
    } & set(page.__dict__)

    replacement_undo.deleteLater()
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_session_fields_do_not_bypass_page_compatibility_properties():
    source = inspect.getsource(inspect.getmodule(SubtitleStudioPage))
    for field in (
        "project",
        "project_path",
        "selected_cue_id",
        "_cue_lookup",
        "undo_stack",
    ):
        assert f'__dict__["{field}"]' not in source
        assert f"__dict__['{field}']" not in source
    assert "object.__setattr__" not in source
