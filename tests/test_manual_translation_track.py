"""Manual translation transactions, hit targets and ordinary clipboard behavior."""
import copy
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QInputMethodEvent, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project, load_project
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.studio.studio_bilingual import set_manual_translation
from twobyteasr.studio.studio_cue_controller import StudioCueController
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.studio_translation_edit import (
    MIME, TranslationTextEdit, copy_translation, paste_translation, clear_translation,
)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.clipboard().clear()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def project():
    p = SubtitleProject(media=StudioMedia(path="", duration_ms=660000),
        cues=[StudioCue("before", 635000, 638000, "before", speaker_id="S01"),
              StudioCue("171", 640333, 644625, "but davinci yrgb color managed", speaker_id="S01"),
              StudioCue("after", 644625, 649542, "after", speaker_id="S01")],
        speakers=[StudioSpeaker("S01", "Speaker")],
        generation_metadata={"language": "en"}, studio_state={"bilingual": {"mode": "bilingual"}})
    for cue in p.cues:
        cue.original_text = cue.text
        cue.base_preset_id = "default"
    return p


def pending(p, *, failure=False, overwrite=True):
    source = st.translation_source(p)
    cue = source.cue("171")
    result = st.TranslationResult(target="zh-Hans", model="fake", provider="fake", overwrite_manual=overwrite,
        project_instance=source.project_instance, project_id=source.project_id, content_revisions=dict(source.content_revisions), revisions=dict(source.revisions), baseline_records=dict(source.records),
        target_at_start=source.target_at_start, sources={cue.id: cue.text},
        source_bounds={cue.id: (cue.start_ms, cue.end_ms, cue.speaker_id)})
    if failure:
        result.failed[cue.id] = "provider_error:offline"
    else:
        result.translations[cue.id] = st.TranslatedItem(cue.id, "旧 AI 译文", cue.text, st.source_sha(cue.text), "")
    return result


@pytest.fixture
def page(app, monkeypatch):
    p = project()
    timeline = WaveformTimeline()
    timeline.resize(1200, 600)
    timeline.set_project(p)
    timeline.set_bilingual(True)
    timeline.set_visible_window(630000, 26000)
    timeline.show()
    session = SimpleNamespace(project=p, undo_stack=QUndoStack(), selected_cue_id="171")
    page = SimpleNamespace(project=p, session=session, undo_stack=session.undo_stack, timeline=timeline,
                           save_state=QLabel(), _editing_has_focus=lambda: False)
    controller = StudioCueController(page, session)
    monkeypatch.setattr(StudioCueController, "cue_changed", lambda *args, **kwargs: timeline.update())
    page.cue_controller = controller
    timeline.text_edit_committed.connect(lambda cue, translation, text: controller.set_translation(cue, text))
    yield page
    timeline._cancel_inline_edit()
    timeline.close()
    timeline.deleteLater()
    app.processEvents()


def point(timeline, ms):
    return QPoint(round(timeline._time_to_x(ms)), round(timeline._track_layout()[1].center().y()))


def test_missing_position_double_click_paste_commit_undo_save_export(page, app, tmp_path):
    p, t = page.project, page.timeline
    original = copy.deepcopy(p.cues)
    st.apply_translation_result(p, pending(p, failure=True))
    before = st.status_counts(p)
    QTest.mouseDClick(t, Qt.LeftButton, pos=point(t, 640750))
    assert t._inline_target == ("171", True)
    QApplication.clipboard().setText("但 DaVinci YRGB\n采用色彩管理")
    QTest.keySequence(t._inline_editor, "Ctrl+V")
    QTest.keyClick(t._inline_editor, Qt.Key_Return)
    assert st.cue_status(p, "171") == "manual"
    assert st.status_counts(p)["failed"] == before["failed"] - 1
    assert p.cues == original and len(p.cues) == 3
    assert copy_translation(page)
    assert QApplication.clipboard().text() == "但 DaVinci YRGB\n采用色彩管理"
    page.undo_stack.undo()
    assert st.cue_status(p, "171") == "failed"
    page.undo_stack.redo()
    saved = load_project(save_project(p, tmp_path / "manual.2byteproj"))
    assert st.records_of(saved)["171"] == st.records_of(p)["171"]
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    assert any(c.text == "但 DaVinci YRGB\n采用色彩管理" for c in project_display_cues(saved))


def test_same_candidate_text_becomes_manual_and_clear_is_undoable(page):
    st.apply_translation_result(page.project, pending(page.project))
    page.timeline.select_translation("171")
    assert page.cue_controller.set_translation("171", "旧 AI 译文")
    assert st.cue_status(page.project, "171") == "manual"
    assert clear_translation(page)
    assert st.cue_status(page.project, "171") == "untranslated"
    assert st.records_of(page.project)["171"]["cleared"]
    page.undo_stack.undo()
    assert st.cue_status(page.project, "171") == "manual"
    assert len(page.project.cues) == 3


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("commit", [False, True])
@pytest.mark.parametrize("action", ["edit", "clear", "undo", "draft", "source", "timing", "target", "project"])
def test_inflight_results_do_not_overwrite_newer_edits(failure, action, commit):
    p = project()
    st.set_manual(p, "171", "旧人工内容")
    result = pending(p, failure=failure)
    if action in {"edit", "clear", "undo"}:
        before, _ = st.set_manual(p, "171", "" if action == "clear" else "DaVinci YRGB")
        if action == "undo":
            st.restore_snapshot(p, before)
    elif action == "draft":
        st.mark_manual_intent(p, "171")
    elif action == "source":
        p.cues[1].text = "changed source"
    elif action == "timing":
        p.cues[1].start_ms += 10
    elif action == "target":
        p.generation_metadata[st.RECORDS_KEY]["target"] = "ja"
    else:
        p = copy.deepcopy(p)
    expected = st.snapshot(p)
    st.apply_translation_result(p, result, commit=commit)
    assert st.snapshot(p) == expected
    assert set(result.discarded) == {"171"}
    assert not result.translations and not result.failed


def test_new_request_respects_clear_unless_explicitly_overridden():
    p = project()
    st.set_manual(p, "171", "text")
    st.set_manual(p, "171", "")
    result = pending(p, overwrite=False)
    st.apply_translation_result(p, result)
    assert st.cue_status(p, "171") == "untranslated"
    assert not result.translations
    result = pending(p, overwrite=True)
    st.apply_translation_result(p, result)
    assert p.generation_metadata["translations"]["171"] == "旧 AI 译文"


def test_clear_already_missing_still_revokes_pending_result_without_fake_record(page):
    result = pending(page.project)
    page.timeline.select_translation("171")
    clear_translation(page)
    st.apply_translation_result(page.project, result)
    assert not st.records_of(page.project)
    assert set(result.discarded) == {"171"}


def test_unchanged_legacy_view_can_be_explicitly_replaced(monkeypatch):
    p = project()
    p.generation_metadata["translations"] = {"171": "旧导入译文"}
    monkeypatch.setattr(st, "_now", lambda: "request-time")
    result = pending(p, overwrite=True)
    monkeypatch.setattr(st, "_now", lambda: "reply-time")
    st.apply_translation_result(p, result)
    assert p.generation_metadata["translations"]["171"] == "旧 AI 译文"
    assert not result.discarded


def test_paste_rebinds_target_keeps_multiline_and_does_not_clone_source(page):
    st.set_manual(page.project, "before", "第一行\n第二行")
    page.timeline.select_translation("before")
    assert copy_translation(page)
    data = json.loads(bytes(QApplication.clipboard().mimeData().data(MIME)))
    assert data["layer"] == "translation" and data["target"] == "zh-Hans"
    assert "id" not in data["entries"][0]
    page.timeline.select_translation("171")
    original = copy.deepcopy(page.project.cues)
    assert paste_translation(page)
    assert page.project.generation_metadata["translations"] == {"before": "第一行\n第二行", "171": "第一行\n第二行"}
    assert page.project.cues == original


def test_copy_order_deduplicates_only_translation_selection_and_multi_paste_is_explicit(page):
    for key, text in (("before", "前\n两行"), ("after", "后")):
        st.set_manual(page.project, key, text)
    page.timeline.translation_selected_ids = {"after", "before"}
    page.timeline.selected_ids = {"171"}  # an original selection is not copy input
    assert copy_translation(page)
    assert QApplication.clipboard().text() == "前\n两行\n\n后"
    before = st.snapshot(page.project)
    assert not paste_translation(page)
    assert st.snapshot(page.project) == before


def test_hit_ranges_overlap_zoom_scroll_and_blank_do_not_use_stale_selection(page, monkeypatch):
    t, p = page.timeline, page.project
    t.select_translation("before")
    assert t._cue_at(point(t, 640750))[0].id == "171"
    assert t._cue_at(point(t, 639000)) == (None, "translation")
    p.cues.append(StudioCue("overlap", 640000, 642000, "other", speaker_id="S01"))
    t.set_project(p)
    t.set_visible_window(639000, 9000)
    t.set_selected("before")
    assert t._cue_at(point(t, 640750)) == (None, "translation")
    t.set_selected("171")
    assert t._cue_at(point(t, 640750))[0].id == "171"
    t.set_selected("before")
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][0], True))
    assert t._resolve_translation_at(point(t, 640750), choose=True).id == "overlap"
    QTest.mouseClick(t, Qt.LeftButton, pos=point(t, 647000))
    QTest.mouseClick(t, Qt.LeftButton, pos=point(t, 639500))
    assert not t.translation_selected_ids


def test_cancel_and_empty_commit_do_not_create_records(page):
    t = page.timeline
    QTest.mouseDClick(t, Qt.LeftButton, pos=point(t, 640750))
    t._inline_editor.setPlainText("cancel me")
    QTest.keyClick(t._inline_editor, Qt.Key_Escape)
    assert not st.records_of(page.project)
    QTest.mouseDClick(t, Qt.LeftButton, pos=point(t, 640750))
    QTest.keyClick(t._inline_editor, Qt.Key_Return)
    assert not st.records_of(page.project)
    assert page.undo_stack.count() == 0


def test_inline_ime_enter_newline_and_language_switch(page):
    t = page.timeline
    QTest.mouseDClick(t, Qt.LeftButton, pos=point(t, 640750))
    editor = t._inline_editor
    QApplication.sendEvent(editor, QInputMethodEvent("中文", []))
    QTest.keyClick(editor, Qt.Key_Return)
    assert t._inline_editor is editor and not st.records_of(page.project)
    commit = QInputMethodEvent()
    commit.setCommitString("中文")
    QApplication.sendEvent(editor, commit)
    QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
    QTest.keyClicks(editor, " WASD ")
    assert "\n" in editor.toPlainText() and t._inline_editor is editor
    st.set_manual(page.project, "before", "前")
    page.project.generation_metadata[st.RECORDS_KEY]["target"] = "ja"
    QTest.keyClick(editor, Qt.Key_Return)
    assert "171" not in st.records_of(page.project)


def test_bound_panel_draft_is_one_command_and_switch_does_not_retarget(page):
    editor = TranslationTextEdit(page)
    editor.bind(page.project, "171", "")
    editor.setPlainText("Adobe")
    editor.insertPlainText(" Premiere Pro")
    assert page.undo_stack.count() == 0
    editor.bind(page.project, "after", "")
    assert page.undo_stack.count() == 1
    assert st.records_of(page.project)["171"]["origin"] == "manual"
    assert "after" not in st.records_of(page.project)
    editor.setPlainText("下一条")
    editor.commit()
    assert page.undo_stack.count() == 2
    page.undo_stack.undo()
    assert "after" not in st.records_of(page.project)
    editor.deleteLater()
