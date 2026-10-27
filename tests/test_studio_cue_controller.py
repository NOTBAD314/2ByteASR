import ast
import inspect
import os
from time import perf_counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication

from twobyteasr.studio.studio_cue_controller import StudioCueController
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.studio.studio_ui import SubtitleStudioPage


CUE_WRAPPERS = {
    "selected_cue_ids": "selected_cue_ids",
    "_timeline_selection_changed": "timeline_selection_changed",
    "_smart_align_current": "smart_align_current",
    "_smart_align_selected": "smart_align_selected",
    "_speaker_structure_changed": "speaker_structure_changed",
    "select_cue": "select_cue",
    "_changed": "changed",
    "_cue_changed": "cue_changed",
    "_text_changed": "text_changed",
    "_commit_manual_term_learning": "commit_manual_term_learning",
    "_translation_changed": "translation_changed",
    "_speaker_changed": "speaker_changed",
    "_timing_fields_changed": "timing_fields_changed",
    "_push_timing": "set_timing",
    "_timeline_timing_changed": "timeline_timing_changed",
    "_add_subtitle_at_playhead": "add_subtitle_at_playhead",
    "_timeline_speaker_changed": "timeline_speaker_changed",
    "_timeline_text_edited": "timeline_text_edited",
    "_nudge": "nudge",
    "_trim_to_playhead": "trim_to_playhead",
    "_split_at": "split_at",
    "_split_current": "split_current",
    "_merge_next": "merge_next",
    "_delete_current": "delete_current",
    "_apply_timing_offset": "apply_timing_offset",
    "_table_activated": "table_activated",
}


def _app():
    return QApplication.instance() or QApplication([])


def _page(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "missing.mp4"), duration_ms=5_000),
        speakers=[StudioSpeaker("S01", "One"), StudioSpeaker("S02", "Two")],
        cues=[
            StudioCue("a", 0, 1_200, "第一句", speaker_id="S01"),
            StudioCue("b", 1_400, 2_600, "第二句", speaker_id="S02"),
        ],
    )
    page.project = project
    page.project_path = tmp_path / "cue-controller.2byteproj"
    page._cue_lookup = {cue.id: cue for cue in project.cues}
    page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page._populate_speakers()
    page.select_cue("a")
    page.undo_stack.clear()
    page.undo_stack.setClean()
    app.processEvents()
    return page


def _finish(page):
    app = _app()
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_cue_controller_is_plain_session_first_collaborator():
    assert not issubclass(StudioCueController, QObject)
    assert StudioCueController.__slots__ == ("page", "session")
    assert not any(
        isinstance(value, Signal) for value in StudioCueController.__dict__.values()
    )
    source = inspect.getsource(inspect.getmodule(StudioCueController))
    assert "from .studio_ui" not in source
    assert "import twobyteasr.studio.studio_ui" not in source
    assert "QObject" not in source
    assert "QTimer" not in source
    assert "QThread" not in source
    assert "threading" not in source
    assert "Thread(" not in source

    tree = ast.parse(source)
    controller = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StudioCueController"
    )
    forbidden = []
    for node in ast.walk(controller):
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
            forbidden.append((node.lineno, node.attr))
    assert forbidden == []


def test_cue_page_wrappers_are_single_call_delegations():
    tree = ast.parse(inspect.getsource(inspect.getmodule(SubtitleStudioPage)))
    page_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SubtitleStudioPage"
    )
    methods = {
        node.name: node for node in page_class.body if isinstance(node, ast.FunctionDef)
    }
    for page_name, controller_name in CUE_WRAPPERS.items():
        wrapper = methods[page_name]
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
        assert call.func.value.attr == "cue_controller"
        assert not any(
            isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With))
            for node in ast.walk(wrapper)
        )
        assert not any(
            isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
            for node in ast.walk(wrapper)
        )


def test_controller_identity_selection_and_timeline_sync(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    assert page.cue_controller.page is page
    assert page.cue_controller.session is page.session
    assert page.session._cue_lookup is page._cue_lookup
    assert page.session.undo_stack is page.undo_stack

    page.timeline.set_selected("b")
    page._timeline_selection_changed({"b"})
    assert page.session.selected_cue_id == "b"
    assert page.selection_model.active_id == "b"
    assert page.selected_cue_ids() == ["b"]
    assert page.cue_table.selectionModel().selectedRows()[0].row() == 1
    _finish(page)


def test_ctrl_a_is_cue_list_scoped_and_batched(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    page.resize(1400, 850)
    page.show()
    app = _app()
    app.processEvents()

    page.cue_text.setFocus()
    page.cue_text.setPlainText("focus contract")
    QTest.keyClick(
        page.cue_text, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier
    )
    assert page.cue_text.textCursor().selectedText() == "focus contract"
    assert len(page.cue_table.selectionModel().selectedRows()) == 1

    page.cue_table.setFocus()
    app.processEvents()
    QTest.keyClick(
        page.cue_table, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier
    )
    assert len(page.cue_table.selectionModel().selectedRows()) == 2
    assert page.timeline.selection_scope.mode.value == "ALL"
    assert page.timeline.selection_scope.count() == 2
    assert page.timeline.selected_ids == set()
    assert page.cue_table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert page.cue_table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    _finish(page)


def test_10k_ctrl_a_and_bulk_delete_are_one_transaction(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    cues = [
        StudioCue(
            f"cue-{index:05d}", index * 500, index * 500 + 450,
            f"subtitle {index}", speaker_id="S01",
        )
        for index in range(10_000)
    ]
    page.project.cues = cues
    page.session.runtime.reindex_cues(page.project)
    page._cue_lookup = {cue.id: cue for cue in cues}
    page.cue_model.set_project(page.project)
    page.timeline.set_project(page.project)
    page.select_cue(cues[0].id)
    page.undo_stack.clear()
    page.resize(1400, 850)
    page.show()
    page.cue_table.setFocus()
    app = _app()
    app.processEvents()

    started = perf_counter()
    QTest.keyClick(
        page.cue_table, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier
    )
    app.processEvents()
    select_all_ms = (perf_counter() - started) * 1000.0
    # The callback records its own latency, so a generous harness wait does
    # not relax the production <250 ms gate below.
    settled_deadline = perf_counter() + 1.0
    latency = page.selection_latency_snapshot()
    while (
        "T6_event_loop_settled" not in latency["markers_ms"]
        and perf_counter() < settled_deadline
    ):
        QTest.qWait(5)
        latency = page.selection_latency_snapshot()
    markers = latency["markers_ms"]
    assert "T6_event_loop_settled" in markers

    assert select_all_ms < 100.0, (select_all_ms, markers)
    assert len(page.cue_table.selectionModel().selectedRows()) == 10_000
    assert page.timeline.selection_scope.mode.value == "ALL"
    assert page.timeline.selection_scope.count() == 10_000
    assert page.timeline.selected_ids == set()
    assert markers["T3_selection_model_correct"] < 50.0
    assert markers["T4_first_visible_selected_row_paint"] < 100.0
    assert markers["T6_event_loop_settled"] < 250.0

    commits_before = page.session.runtime.commit_count
    page._delete_current()
    assert page.undo_stack.count() == 1
    assert page.session.runtime.commit_count == commits_before + 1
    assert page.project.cues == []
    assert page._autosave_timer.isActive()

    page.undo_stack.undo()
    assert len(page.project.cues) == 10_000
    assert [cue.id for cue in page.project.cues[:3]] == [
        "cue-00000", "cue-00001", "cue-00002",
    ]
    save_project(page.project, page.project_path)
    reopened = load_project(page.project_path)
    assert len(reopened.cues) == 10_000
    assert (reopened.cues[0].id, reopened.cues[0].text) == (
        "cue-00000", "subtitle 0",
    )
    assert (reopened.cues[-1].id, reopened.cues[-1].end_ms) == (
        "cue-09999", 4_999_950,
    )
    page.undo_stack.redo()
    assert page.project.cues == []
    _finish(page)


def test_hidden_transform_panel_refreshes_current_selection_when_shown(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    page.resize(1400, 850)
    page.show()
    page.context_stack.setCurrentWidget(page.context_drawer)
    page.context_panel.show()
    page.workspace_splitter.show()
    page.context_drawer.setCurrentIndex(1)  # style tab
    _app().processEvents()
    panel = page.caption_transform_panel
    assert not panel.isVisible()
    page._select_all_timeline_cues()
    assert panel._needs_refresh
    page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
    QTest.qWait(100)
    _app().processEvents()
    parents = []
    current = panel
    while current is not None:
        parents.append((current.objectName(), current.isVisible(), current.isHidden()))
        current = current.parentWidget()
    assert panel.isVisible(), '\n'.join(map(str, parents))
    assert not panel._needs_refresh
    assert panel.controls['position_x'].isEnabled()
    assert '2' in page.video_transform_selection_label.text()
    _finish(page)


def test_text_translation_timing_and_speaker_keep_one_undo_each(
    tmp_path, monkeypatch
):
    page = _page(tmp_path, monkeypatch)
    controller = page.cue_controller

    assert controller.set_text("a", "修改文本")
    assert page.undo_stack.count() == 1
    assert page.project.cues[0].text == "修改文本"
    assert page._pending_qc_cue_ids == {"a"}
    assert page._autosave_timer.isActive()
    assert page.position_overlay.text == "修改文本"
    page.undo_stack.undo()
    assert page.project.cues[0].text == "第一句"
    page.undo_stack.redo()
    assert page.project.cues[0].text == "修改文本"

    page.undo_stack.clear()
    assert controller.set_translation("a", "First")
    assert page.undo_stack.count() == 1
    assert page.project.generation_metadata["translations"]["a"] == "First"
    page.undo_stack.undo()
    assert "a" not in page.project.generation_metadata["translations"]

    page.undo_stack.clear()
    assert controller.set_timing("a", 100, 1_300)
    assert page.undo_stack.count() == 1
    assert (page.project.cues[0].start_ms, page.project.cues[0].end_ms) == (
        100,
        1_300,
    )
    page.undo_stack.undo()
    assert (page.project.cues[0].start_ms, page.project.cues[0].end_ms) == (
        0,
        1_200,
    )

    page.undo_stack.clear()
    assert controller.set_speaker("a", "S02")
    assert page.undo_stack.count() == 1
    assert page.project.cues[0].speaker_id == "S02"
    page.undo_stack.undo()
    assert page.project.cues[0].speaker_id == "S01"
    _finish(page)


def test_nudge_split_merge_delete_and_add_keep_one_undo_each(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)

    page._nudge(50)
    assert page.undo_stack.count() == 1
    assert page.project.cues[0].start_ms == 50
    page.undo_stack.undo()
    assert page.project.cues[0].start_ms == 0

    page.undo_stack.clear()
    page._split_current()
    assert page.undo_stack.count() == 1
    assert len(page.project.cues) == 3
    assert set(page._cue_lookup) == {cue.id for cue in page.project.cues}
    assert page._qc_full_scan_pending
    page.undo_stack.undo()
    assert len(page.project.cues) == 2

    page.undo_stack.clear()
    page.select_cue("a")
    page._merge_next()
    assert page.undo_stack.count() == 1
    assert len(page.project.cues) == 1
    page.undo_stack.undo()
    assert [cue.id for cue in page.project.cues] == ["a", "b"]

    page.undo_stack.clear()
    page.select_cue("a")
    page._delete_current()
    assert page.undo_stack.count() == 1
    assert [cue.id for cue in page.project.cues] == ["b"]
    assert page.session.selected_cue_id == "b"
    assert "a" not in page.session._cue_lookup
    page.undo_stack.undo()
    assert [cue.id for cue in page.project.cues] == ["a", "b"]

    page.undo_stack.clear()
    page.timeline.set_playhead(3_000)
    monkeypatch.setattr(page.timeline, "_open_inline_editor", lambda *_args: None)
    page._add_subtitle_at_playhead()
    assert page.undo_stack.count() == 1
    assert len(page.project.cues) == 3
    assert page.selected_cue_id.startswith("cue-")
    page.undo_stack.undo()
    assert len(page.project.cues) == 2
    _finish(page)


def test_ordinary_inline_commit_routes_through_canonical_text_api():
    wrapper=inspect.getsource(SubtitleStudioPage._commit_canvas_inline_edit)
    assert "self._commit_canvas_inline_edit_impl(" in wrapper
    source = inspect.getsource(SubtitleStudioPage._commit_canvas_inline_edit_impl)
    assert "self.cue_controller.set_text(" in source
    assert "SetCueFieldsCommand(" not in source


def test_controller_mutation_survives_save_and_reopen(tmp_path, monkeypatch):
    app = _app()
    page = _page(tmp_path, monkeypatch)
    target = page.project_path
    page.cue_controller.set_text("a", "保存后文本")
    page.save()
    assert load_project(target).cues[0].text == "保存后文本"
    _finish(page)

    reopened = SubtitleStudioPage()
    monkeypatch.setattr(reopened, "_generate_waveform", lambda *_args, **_kwargs: None)
    reopened.open_project(target)
    app.processEvents()
    assert reopened.project.cues[0].text == "保存后文本"
    assert reopened.session._cue_lookup["a"] is reopened.project.cues[0]
    _finish(reopened)
