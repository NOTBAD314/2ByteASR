"""Every ordinary Studio entry uses the same additive import transaction."""
import os
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.projects.subtitle_import import IMPORT_KEY
from twobyteasr.exports.studio_subtitle_export import compile_srt
from twobyteasr.studio.studio_ui import SubtitleStudioPage


@pytest.fixture
def page(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio import studio_media_flow
    messages = []
    monkeypatch.setattr(studio_media_flow, "studio_message_box", lambda *args: messages.append(str(args[-1])))
    page = SubtitleStudioPage()
    page.project = SubtitleProject(StudioMedia(""), render_settings={"_cue_domain": "timeline"})
    page.project_path = tmp_path / "test.2byteproj"
    page.cue_model.set_project(page.project)
    page.timeline.set_project(page.project)
    page._populate_speakers()
    page._import_test_messages = messages
    yield page
    page.undo_stack.setClean()
    page.close_page()
    page.deleteLater()
    app.processEvents()


def fixture(tmp_path, name):
    path = tmp_path / (name + ".srt")
    path.write_text(compile_srt([StudioCue("outside-1", 100, 2000, "普通 S00 / IT（保留）")]), "utf-8")
    return path


def test_file_dialog_batch_model_and_undo_redo(page, tmp_path, monkeypatch):
    from twobyteasr.studio import studio_media_flow
    paths = [fixture(tmp_path, "S00zh"), fixture(tmp_path, "s01IT")]
    monkeypatch.setattr(studio_media_flow.QFileDialog, "getOpenFileNames", lambda *a: (list(map(str, paths)), ""))
    page._open_subtitle_import_dialog()
    assert len(page.project.cues) == page.cue_model.rowCount() == 2
    assert {page.speaker.itemText(i) for i in range(page.speaker.count())} == {"S00 · 中文", "S01 · 意大利语"}
    assert len(page.timeline._track_layout()[0]) == 2
    assert state_for(page.project).commit_count == 1
    page._undo_interactive()
    assert page.cue_model.rowCount() == 0 and page.speaker.count() == 1  # empty editor's S00 fallback
    page._redo_interactive()
    assert page.cue_model.rowCount() == 2 and page.speaker.count() == 2
    assert not page._import_test_messages


def test_multi_file_drop_preserves_existing_edits_and_language_tracks(page, tmp_path):
    page._import_subtitle_file(fixture(tmp_path, "S00it"))
    old = page.project.cues[0]
    page._timeline_text_edited(old.id, False, "已有人工编辑")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(fixture(tmp_path, name))) for name in ("S00zh", "S01it", "S01zh")])
    event = QDropEvent(QPointF(600, 600), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    page.dropEvent(event)
    assert len(page.project.cues) == page.cue_model.rowCount() == 4
    assert page.project.cues[0].text == "已有人工编辑"
    assert len(page.timeline._track_layout()[0]) == 4
    assert {(c.start_ms, c.end_ms) for c in page.project.cues} == {(100, 2000)}


def test_explicit_target_replace_and_locked_target_guard(page, tmp_path):
    path = fixture(tmp_path, "S00zh")
    page._import_subtitle_files([path, fixture(tmp_path, "S00it")])
    target = page.project.cues[0].speaker_id
    old_ids = [c.id for c in page.project.cues]
    page.timeline.locked_speakers.add(target)
    page._import_subtitle_files([path], replace_track_id=target)
    assert [c.id for c in page.project.cues] == old_ids and page._import_test_messages
    page.timeline.locked_speakers.clear()
    page._import_subtitle_files([path], replace_track_id=target)
    assert len(page.project.cues) == 2 and old_ids[1] in {c.id for c in page.project.cues}
    assert old_ids[0] not in {c.id for c in page.project.cues}


def test_desktop_batch_dispatches_all_paths_in_one_import(page, tmp_path):
    from twobyteasr.app.desktop_intake import DesktopIntake
    from PySide6.QtWidgets import QWidget, QLabel
    window = QWidget()
    window._run_in_progress, window.worker = False, None
    window.header_status = QLabel(window)
    window.studio_page = page
    window._switch_page = lambda p: None
    intake = DesktopIntake(window)
    try:
        intake.submit([str(fixture(tmp_path, name)) for name in ("S00zh", "S00it", "S01it")])
        assert len(page.project.cues) == page.cue_model.rowCount() == 3
        assert state_for(page.project).commit_count == 1 and not intake.requests
    finally:
        intake.timer.stop()
        window.deleteLater()


def test_imported_language_cue_uses_normal_edit_copy_delete_paths(page, tmp_path):
    page._import_subtitle_files([fixture(tmp_path, "S00it"), fixture(tmp_path, "S00zh")])
    source = page.project.cues[0].id
    target = page.project.cues[1].id
    page.select_cue(target)
    page._timeline_text_edited(target, False, "独立中文译文\n仍可编辑")
    page.select_cue(target)
    page.cue_text.selectAll()
    assert page.cue_text.createMimeDataFromSelection().text() == "独立中文译文\n仍可编辑"
    page.timeline.setFocus()
    page._delete_current()
    assert {c.id for c in page.project.cues} == {source}
    page._undo_interactive()
    assert {c.id for c in page.project.cues} == {source, target}
    assert page.session._cue_lookup[target].text == "独立中文译文\n仍可编辑"


def test_media_and_subtitles_drop_reaches_ingest_completion(page, tmp_path):
    import time
    import wave
    from PySide6.QtTest import QTest
    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0" * 32000)
    subtitle = fixture(tmp_path, "S00it")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in (path, subtitle)])
    event = QDropEvent(QPointF(600, 600), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    page.dropEvent(event)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline and not page.project.cues:
        QTest.qWait(50)
    assert len(page.project.cues) == page.cue_model.rowCount() == 1
    assert page.project.media_pool
    assert (page.project.cues[0].start_ms, page.project.cues[0].end_ms) == (100, 2000)
