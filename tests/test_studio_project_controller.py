import ast
import inspect
import os
import textwrap
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import twobyteasr.studio.studio_ui as studio_ui
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.projects.studio_project_controller import StudioProjectController
from twobyteasr.studio.studio_project_flow import StudioProjectFlowMixin
from twobyteasr.studio.studio_ui import SubtitleStudioPage


PROJECT_WRAPPERS = {
    "import_media_dialog": "import_media_dialog",
    "show_project_hub": "show_project_hub",
    "open_project_dialog": "open_project_dialog",
    "most_recent_project": "most_recent_project",
    "recent_project_records": "recent_project_records",
    "_remember_recent_project": "_remember_recent_project",
    "_ensure_project_cover": "_ensure_project_cover",
    "_relink_media": "_relink_media",
    "_open_or_create_media_project": "_open_or_create_media_project",
    "open_project": "open_project_entry",
    "_recovery_choice": "_recovery_choice",
    "_resolve_project_recovery": "_resolve_project_recovery",
    "_populate_speakers": "_populate_speakers",
    "save": "save",
}


def _app():
    return QApplication.instance() or QApplication([])


def test_project_controller_is_a_plain_state_free_collaborator():
    assert not issubclass(StudioProjectController, QObject)
    assert StudioProjectController.__slots__ == ("page", "session")
    assert not any(
        isinstance(value, Signal)
        for value in StudioProjectController.__dict__.values()
    )
    source = inspect.getsource(inspect.getmodule(StudioProjectController))
    assert "from .studio_ui" not in source
    assert "import twobyteasr.studio.studio_ui" not in source
    assert "QThread" not in source
    assert "threading" not in source
    assert "Thread(" not in source
    assert "QTimer(" not in source


def test_project_page_wrappers_are_single_call_delegations():
    # Since the studio_ui split the wrappers live on different mixins; resolve
    # each wrapper through the composed page class and check its own source.
    for page_name, controller_name in PROJECT_WRAPPERS.items():
        func = SubtitleStudioPage.__dict__.get(page_name) or next(
            klass.__dict__[page_name]
            for klass in SubtitleStudioPage.__mro__
            if page_name in klass.__dict__
        )
        source = textwrap.dedent(inspect.getsource(func))
        wrapper = ast.parse(source).body[0]
        assert wrapper.name == page_name
        assert len(wrapper.body) == 1
        statement = wrapper.body[0]
        assert isinstance(statement, (ast.Return, ast.Expr))
        call = statement.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        assert call.func.attr == controller_name
        assert isinstance(call.func.value, ast.Attribute)
        assert isinstance(call.func.value.value, ast.Name)
        assert call.func.value.value.id == "self"
        assert call.func.value.attr == "project_controller"
        assert not any(
            isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With))
            for node in ast.walk(wrapper)
        )
        assert not any(
            isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
            for node in ast.walk(wrapper)
        )


def test_controller_uses_session_canonical_state_without_page_aliases():
    tree = ast.parse(inspect.getsource(inspect.getmodule(StudioProjectController)))
    controller_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StudioProjectController"
    )
    forbidden_page_fields = []
    for node in ast.walk(controller_class):
        if not isinstance(node, ast.Attribute) or node.attr not in {
            "project",
            "project_path",
            "selected_cue_id",
            "_cue_lookup",
            "undo_stack",
        }:
            continue
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "self"
            and value.attr == "page"
        ):
            forbidden_page_fields.append((node.lineno, node.attr))
    assert forbidden_page_fields == []


def test_project_open_preserves_session_identity_and_undo(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "missing.mp4"), duration_ms=2_000),
        cues=[
            StudioCue("cue-a", 0, 900, "first"),
            StudioCue("cue-b", 1_000, 1_900, "second"),
        ],
        studio_state={"last_selected_cue": "cue-b"},
    )
    path = save_project(project, tmp_path / "identity.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    original_undo = page.undo_stack

    page.open_project(path)
    app.processEvents()

    assert page.project_controller.page is page
    assert page.project_controller.session is page.session
    assert page.project is page.session.project
    assert page.project_path is page.session.project_path
    assert page.project_path == path.resolve()
    assert page.selected_cue_id == page.session.selected_cue_id == "cue-b"
    assert page._cue_lookup is page.session._cue_lookup
    assert page._cue_lookup["cue-b"] is page.project.cues[1]
    assert page.undo_stack is page.session.undo_stack is original_undo
    assert page.undo_stack.isClean()

    page.project.cues[1].text = "saved through controller"
    page.save()
    assert load_project(path).cues[1].text == "saved through controller"

    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_save_without_project_path_uses_existing_save_as_flow(tmp_path, monkeypatch):
    app = _app()
    target = tmp_path / "save-as-copy.2byteproj"
    page = SubtitleStudioPage()
    page.project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "missing.mp4"), duration_ms=1_000),
        cues=[StudioCue("cue-a", 0, 900, "save as")],
    )
    page.project_path = None
    monkeypatch.setattr(
        studio_ui.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(target), ""),
    )

    page.save()

    assert page.project_path is page.session.project_path
    assert page.project_path == target.resolve()
    assert load_project(target).cues[0].text == "save as"
    assert page.undo_stack.isClean()

    page.close_page()
    page.deleteLater()
    app.processEvents()
