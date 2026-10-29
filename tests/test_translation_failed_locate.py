"""Finding failed translations from the translation dialog (2026-10-27, user report).

The dialog only said 「失败 1」; in a 1,561-caption video the failed line could not be found.
"""
from types import SimpleNamespace

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog, failure_reason
from twobyteasr.subtitle_rules import subtitle_translation as st


def _project():
    project = SubtitleProject(media=StudioMedia(path="synthetic.mp4", duration_ms=60_000),
        cues=[StudioCue(f"c{i}", i * 1000, i * 1000 + 900, f"Line {i} where we open the big door.") for i in range(6)])
    project.generation_metadata["language"] = {"code": "en"}
    return project


def _fail(project, reasons):
    result = st.TranslationResult(target="zh-Hans", model="fixture", provider="fixture",
                                  failed=dict(reasons), sources={cue.id: cue.text for cue in project.cues})
    st.apply_translation_result(project, result)


class _Page(SimpleNamespace):
    """The workbench calls the dialog uses; list order differs from cue ids on purpose."""

    def __init__(self, project):
        order = list(reversed(project.cues))
        super().__init__(project=project, selected_cue_ids=lambda: [], undo_stack=QUndoStack(),
                         _cue_jump_order=order, _cue_jump_index={cue.id: index for index, cue in enumerate(order)},
                         visited=[], _review_mode=False,
                         cue_model=SimpleNamespace(filter_status="critical", row_for_cue_id=lambda _cue_id: -1),
                         filters=[])

    def _go_to_listed_cue(self, cue):
        self.visited.append(cue.id)

    def _activate_filter(self, status):
        self.filters.append(status)
        self.cue_model.filter_status = status


def test_failed_captions_are_named_and_located_one_after_another():
    QApplication.instance() or QApplication([])
    project = _project()
    _fail(project, {"c4": "english_output", "c1": "missing"})
    page = _Page(project)
    dialog = SubtitleTranslationDialog(page)
    try:
        assert not dialog.failed_note.isHidden() and not dialog.locate_failed_button.isHidden()
        # Timeline order (c1 before c4); numbers are the workbench list's #.
        assert dialog.failed_note.text() == "失败的字幕：#5 模型没有给出这一条 · #2 译文不是所选语言"
        assert dialog.locate_failed_button.text() == "定位下一条 1/2"
        dialog.locate_failed_button.click()
        assert page.visited == ["c1"] and page.filters == ["all"]
        assert dialog.locate_failed_button.text() == "定位下一条 2/2"
        dialog.locate_failed_button.click()
        dialog.locate_failed_button.click()
        assert page.visited == ["c1", "c4", "c1"]
    finally:
        dialog.deleteLater()


def test_no_failure_hides_the_locate_row_and_a_retry_success_clears_it():
    QApplication.instance() or QApplication([])
    project = _project()
    page = _Page(project)
    dialog = SubtitleTranslationDialog(page)
    try:
        assert dialog.failed_note.isHidden() and dialog.locate_failed_button.isHidden()
        _fail(project, {"c2": "echo_source"})
        dialog._refresh_counts()
        assert dialog.failed_note.text() == "失败的字幕：#4 模型照抄了原文"
        assert dialog.locate_failed_button.text() == "定位"
        result = st.TranslationResult(target="zh-Hans", model="fixture", provider="fixture",
                                      sources={"c2": project.cues[2].text})
        source = project.cues[2].text
        result.translations["c2"] = st.TranslatedItem("c2", "第 2 行，我们打开大门。", source, st.source_sha(source), "")
        st.apply_translation_result(project, result)
        dialog._refresh_counts()
        assert dialog.failed_note.isHidden() and dialog.locate_failed_button.isHidden()
    finally:
        dialog.deleteLater()


def test_more_than_three_failures_are_summarised():
    QApplication.instance() or QApplication([])
    project = _project()
    _fail(project, {cue.id: "provider_error:timeout: read timed out" for cue in project.cues[:5]})
    dialog = SubtitleTranslationDialog(_Page(project))
    try:
        assert dialog.failed_note.text().endswith("· 等 5 条")
        assert dialog.failed_note.text().count("请求出错") == 3
    finally:
        dialog.deleteLater()


def test_failure_codes_in_plain_words():
    assert failure_reason("english_output") == failure_reason("not_russian") == "译文不是所选语言"
    assert failure_reason("no_chinese") == "译文不是所选语言"
    assert failure_reason("duplicate_id") == "模型没有给出这一条"
    assert failure_reason("timestamp") == "译文格式不对"
    assert failure_reason("something_new") == "没有通过检查"
