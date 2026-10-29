"""Formal save durability and GUI responsiveness at the real controller boundary."""
import json
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QUndoCommand, QUndoStack
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from twobyteasr.projects.autosave_deadline import AutosaveDeadline
from twobyteasr.projects.project_dirty_guard import DirtyGuardChoice, ProjectDirtyGuard
from twobyteasr.projects.studio_project import (
    StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, load_project,
    project_backup_path, save_autosave_revision, save_project,
)
from twobyteasr.projects.studio_project_controller import StudioProjectController
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.projects.studio_save import capture_manual_save
from twobyteasr.projects.studio_session import StudioSession


class _Page(QWidget):
    def __init__(self, project, target):
        super().__init__()
        self.session = StudioSession(project=project, project_path=target, undo_stack=QUndoStack(self))
        self._revision_store = StudioRevisionStore(project)
        self._autosave_timer = QTimer(self)
        self._autosave_deadline = AutosaveDeadline()
        self.save_state = QLabel("", self)
        self._recovered_autosave_pending = False
        self._canvas_editor = None
        self.scheduled = 0
        self.errors = []
        self.project_controller = StudioProjectController(self, self.session)

    @property
    def project(self):
        return self.session.project

    @property
    def undo_stack(self):
        return self.session.undo_stack

    def _capture_studio_state(self):
        self.project.studio_state["playhead_ms"] = 350

    def _schedule_autosave(self):
        self.scheduled += 1

    def save(self):
        self.project_controller.save(message_box_fn=lambda *args: self.errors.append(str(args[-1])))


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, tmp_path):
    project = SubtitleProject(
        media=StudioMedia(path="", duration_ms=2_000),
        cues=[StudioCue("cue-a", 100, 900, "before", speaker_id="speaker-a")],
        speakers=[StudioSpeaker("speaker-a", "host", hidden=True, is_host=True)],
        asr_evidence={"local-private-evidence": {"text": "before"}},
    )
    target = save_project(project, tmp_path / "save.2byteproj")
    widget = _Page(project, target)
    widget.undo_stack.push(QUndoCommand("edited"))
    project.cues[0].text = "after direct edit"
    yield widget
    widget.deleteLater()
    app.processEvents()


def test_formal_save_slow_disk_keeps_timers_and_blocks_reentrant_navigation(page, monkeypatch):
    import twobyteasr.projects.studio_project as persistence
    original = persistence._atomic_json_blob_write
    gui_thread = threading.get_ident()
    worker_threads = []
    tick_times = []
    navigation = []

    def slow_write(path, payload):
        worker_threads.append(threading.get_ident())
        time.sleep(.22)
        return original(path, payload)

    monkeypatch.setattr(persistence, "_atomic_json_blob_write", slow_write)
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: tick_times.append(time.perf_counter()))
    timer.start()
    QTimer.singleShot(35, lambda: navigation.append(
        page.project_controller.show_project_hub(skip_dirty_guard=True)))
    QTimer.singleShot(55, lambda: page.project_controller.open_project_entry(
        "must-not-open.2byteproj", skip_dirty_guard=True, single_shot_fn=lambda *args: None))
    QTimer.singleShot(75, page.save)
    QTimer.singleShot(95, lambda: navigation.append(page.close()))
    target = page.session.project_path
    old_bytes = target.read_bytes()
    try:
        allowed = ProjectDirtyGuard(page).confirm(
            "关闭", choice_provider=lambda _: DirtyGuardChoice.SAVE)
    finally:
        timer.stop()
    assert allowed is True
    assert len(tick_times) >= 10
    assert max(b - a for a, b in zip(tick_times, tick_times[1:])) < .15
    assert worker_threads and all(tid != gui_thread for tid in worker_threads)
    assert navigation == [False, False]
    assert page.errors == []
    assert not page._manual_save_in_progress
    assert page.isEnabled()
    assert page.undo_stack.isClean()
    assert page.session.project_path == target
    assert project_backup_path(target).read_bytes() == old_bytes
    loaded = load_project(target)
    assert loaded.cues[0].text == "after direct edit"
    assert loaded.speakers[0].hidden is True
    assert loaded.speakers[0].is_host is True
    assert loaded.studio_state["playhead_ms"] == 350


def test_formal_save_failure_preserves_formal_copy_and_stays_dirty(page, monkeypatch):
    import twobyteasr.projects.studio_project as persistence
    target = page.session.project_path
    original = target.read_bytes()

    def fail_write(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(persistence, "_atomic_json_blob_write", fail_write)
    allowed = ProjectDirtyGuard(page).confirm(
        "关闭", choice_provider=lambda _: DirtyGuardChoice.SAVE)
    assert allowed is False
    assert target.read_bytes() == original
    assert project_backup_path(target).read_bytes() == original
    assert not page.undo_stack.isClean()
    assert page.errors == ["simulated disk failure"]
    assert page.scheduled == 1
    assert page.isEnabled() and not page._manual_save_in_progress


def test_formal_save_as_failure_does_not_install_unsaved_path(page, monkeypatch, tmp_path):
    import twobyteasr.projects.studio_project as persistence
    from PySide6.QtWidgets import QFileDialog
    page.session.project_path = None
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *args: (str(tmp_path / "failed.2byteproj"), ""))
    monkeypatch.setattr(persistence, "_atomic_json_blob_write",
                        lambda *args: (_ for _ in ()).throw(OSError("full")))
    page.save()
    assert page.session.project_path is None
    assert not page.undo_stack.isClean()


def test_programmatic_edit_during_save_cannot_mark_newer_state_clean(page, monkeypatch):
    import twobyteasr.projects.studio_project as persistence
    original = persistence._atomic_json_blob_write

    def slow_write(path, content):
        time.sleep(.12)
        return original(path, content)

    def newer():
        page.undo_stack.push(QUndoCommand("newer edit"))
        page.project.cues[0].text = "newer committed change"

    monkeypatch.setattr(persistence, "_atomic_json_blob_write", slow_write)
    QTimer.singleShot(30, newer)
    page.save()
    assert load_project(page.session.project_path).cues[0].text == "after direct edit"
    assert page.project.cues[0].text == "newer committed change"
    assert not page.undo_stack.isClean()
    assert page.scheduled == 1


def test_snapshot_detaches_full_formal_schema_and_preserves_automatic_speaker_flags(page, tmp_path):
    project = page.project
    project.studio_state["review_risks"] = {"transient": "do not save"}
    # Capture following the same viewport step as the controller.
    page._capture_studio_state()
    snapshot = capture_manual_save(page, project, 3)
    expected = project.to_dict()
    expected["updated_at"] = snapshot.updated_at
    payload = snapshot.to_payload()
    payload["studio_state"].pop("review_risks", None)
    assert payload == expected
    project.cues[0].text = "later edit"
    project.speakers[0].hidden = False
    assert snapshot.to_payload()["cues"][0]["text"] == "after direct edit"
    assert snapshot.to_payload()["speakers"][0]["hidden"] is True
    # This is the existing automatic-save API, not the new manual writer.
    autosave, _ = save_autosave_revision(snapshot, base=tmp_path)
    recovered = load_project(autosave)
    assert recovered.speakers[0].hidden is True
    assert recovered.speakers[0].is_host is True


def test_late_save_result_does_not_publish_into_replaced_session(page, monkeypatch):
    import twobyteasr.projects.studio_project as persistence
    original = persistence._atomic_json_blob_write
    old_target = page.session.project_path
    replacement = SubtitleProject(media=StudioMedia(path="", duration_ms=0))
    replacement.validate()

    def slow_write(path, content):
        time.sleep(.12)
        return original(path, content)

    def bypass_navigation_guard():
        page.session.close("programmatic replacement")
        page.session.project = replacement
        page.undo_stack.push(QUndoCommand("replacement edit"))

    monkeypatch.setattr(persistence, "_atomic_json_blob_write", slow_write)
    QTimer.singleShot(30, bypass_navigation_guard)
    page.save()
    assert page.project is replacement
    assert page.session.project_path is None
    assert not page.undo_stack.isClean()
    assert load_project(old_target).cues[0].text == "after direct edit"



def test_pending_older_autosave_finishes_before_formal_file_without_gui_join(page):
    from twobyteasr.projects.studio_project import recoverable_autosave
    old_revision = page._revision_store._persistence
    page._autosave_write_lock = threading.Lock()
    written = []

    def older_autosave():
        with page._autosave_write_lock:
            time.sleep(.15)
            written.append(save_autosave_revision(
                old_revision, page.session.project_path, session_id="older")[0])

    page._autosave_thread = threading.Thread(target=older_autosave)
    page._autosave_thread.start()
    timeouts = []
    page._autosave_timer.setSingleShot(True)
    page._autosave_timer.timeout.connect(lambda: timeouts.append("new autosave"))
    # Simulate an older completion scheduling its next generation during Save.
    QTimer.singleShot(25, lambda: page._autosave_timer.start(1))
    page.save()
    assert written and not page._autosave_thread.is_alive()
    assert timeouts == []
    assert not page._autosave_timer.signalsBlocked()
    assert recoverable_autosave(page.session.project_path) is None
    assert load_project(page.session.project_path).cues[0].text == "after direct edit"


def test_invalid_captured_cue_is_rejected_before_replacing_formal_file(page):
    target = page.session.project_path
    old_bytes = target.read_bytes()
    page.project.cues[0].end_ms = -1
    page.save()
    assert page.errors and "invalid timing" in page.errors[0]
    assert target.read_bytes() == old_bytes
    assert not page.undo_stack.isClean()
