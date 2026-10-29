"""Keep daily Markdown/style/quick-paste behavior when integrating manual translations."""
from types import SimpleNamespace
import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QWidget

from twobyteasr.caption_style.text_marks import layer_marks
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.caption_text_tools import CaptionTextTools
from twobyteasr.studio.studio_cue_controller import StudioCueController
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.studio_translation_edit import TranslationTextEdit, sync_editor_layer
from twobyteasr.subtitle_rules import subtitle_translation as st


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    QApplication.clipboard().clear()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def page(app, monkeypatch):
    page = QWidget()
    page.project = SubtitleProject(StudioMedia("", duration_ms=5000),
        cues=[StudioCue("a", 0, 2000, "original a"), StudioCue("b", 2500, 4500, "original b")])
    page.project.validate()
    page.undo_stack = QUndoStack(page)
    page.selected_cue_id = "a"
    page.session = SimpleNamespace(project=page.project, undo_stack=page.undo_stack,
                                   _cue_lookup={c.id:c for c in page.project.cues}, selected_cue_id="a")
    page._text_input_in_progress = False
    page._updating_editor = False
    page._changed = lambda *args, **kwargs: None
    page._editing_has_focus = lambda: False
    page.save_state = QLabel(page)
    page.timeline = WaveformTimeline(page)
    page.timeline.set_project(page.project)
    page.timeline.set_bilingual(True)
    page.cue_controller = StudioCueController(page, page.session)
    monkeypatch.setattr(StudioCueController, "cue_changed", lambda *args, **kwargs: None)
    page.translation_text = TranslationTextEdit(page, page)
    page.translation_text_tools = CaptionTextTools(page, page.translation_text, "translation")
    page.translation_text.bind(page.project, "a", "")
    yield page
    page.timeline._cancel_inline_edit()
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_markdown_draft_commits_body_and_marks_once(page):
    editor, tools = page.translation_text, page.translation_text_tools
    tools.mode.setCurrentIndex(1)
    editor.setPlainText("使用 **DaVinci YRGB**")
    assert page.undo_stack.count() == 0
    editor.commit()
    assert st.records_of(page.project)["a"]["text"] == "使用 DaVinci YRGB"
    assert st.cue_status(page.project, "a") == "manual"
    assert layer_marks(page.project.cues[0], "translation") == [{"start":3,"end":15,"bold":True}]
    assert page.undo_stack.count() == 1
    page.undo_stack.undo()
    assert not st.records_of(page.project).get("a")
    assert not layer_marks(page.project.cues[0], "translation")


def test_plain_edit_remaps_translation_marks_and_preserves_source_style(page):
    st.set_manual(page.project, "a", "hello world")
    cue = page.project.cues[0]
    cue.appearance_override = {"text_marks":[{"start":0,"end":2,"bold":True}],
        "translation":{"style":{"font_size":29},"text_marks":[{"start":6,"end":11,"italic":True}]}}
    assert page.cue_controller.set_translation("a", "hello brave world")
    assert layer_marks(cue, "translation") == [{"start":12,"end":17,"italic":True}]
    assert cue.appearance_override["translation"]["style"] == {"font_size":29}
    assert layer_marks(cue, "original") == [{"start":0,"end":2,"bold":True}]
    assert page.undo_stack.count() == 1
    page.undo_stack.undo()
    assert st.records_of(page.project)["a"]["text"] == "hello world"
    assert layer_marks(cue, "translation") == [{"start":6,"end":11,"italic":True}]


def test_switching_cue_commits_bound_draft_to_old_id(page):
    page.translation_text.setPlainText("旧目标的草稿")
    page.selected_cue_id = page.session.selected_cue_id = "b"
    page.translation_text.bind(page.project, "b", "")
    assert st.records_of(page.project)["a"]["text"] == "旧目标的草稿"
    assert "b" not in st.records_of(page.project)
    assert page.undo_stack.count() == 1


def test_markdown_mode_switch_keeps_pending_plain_input(page):
    page.translation_text.setPlainText("保留这段输入")
    page.translation_text_tools.mode.setCurrentIndex(1)
    assert st.records_of(page.project)["a"]["text"] == "保留这段输入"
    assert page.translation_text.toPlainText() == "保留这段输入"
    assert page.undo_stack.count() == 1


def test_native_paste_sequence_targets_translation_before_link_card(page):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    page.timeline.select_translation("a")
    page._shortcut_lookup = {"Ctrl+V":"paste_link"}
    page._command_callbacks = {"paste_link":lambda: pytest.fail("link card stole translation paste")}
    page._review_mode = False
    QApplication.clipboard().setText("https://example.test/a-video")
    assert SubtitleStudioPage._dispatch_shortcut_sequence(page, "Ctrl+V")
    assert st.records_of(page.project)["a"]["text"] == "https://example.test/a-video"
    assert len(page.project.cues) == 2


def test_translation_selection_uses_daily_language_layer_controls(page):
    page.style_layer = QComboBox(page)
    for name in ("original", "translation", "group"):
        page.style_layer.addItem(name, name)
    page.timeline.select_translation("a")
    sync_editor_layer(page)
    assert page.timeline.selected_lane == "translation"
    assert page.style_layer.currentData() == "translation"
    page.timeline.set_subtitle_layer("original")
    sync_editor_layer(page)
    assert page.style_layer.currentData() == "original"
    page.style_layer.setCurrentIndex(2)
    sync_editor_layer(page)
    assert page.style_layer.currentData() == "group"


def test_formatted_clipboard_rebinds_to_new_translation_once(page):
    st.set_manual(page.project, "a", "hello world")
    page.project.cues[0].appearance_override = {"translation":{"text_marks":[{"start":6,"end":11,"bold":True}]}}
    editor = page.translation_text
    editor.bind(page.project, "a", "hello world")
    editor.selectAll()
    mime = editor.createMimeDataFromSelection()
    payload = json.loads(bytes(mime.data(editor.MIME)))
    assert mime.text() == "hello world" and payload["layer"] == "translation" and payload["target"] == "zh-Hans"
    page.selected_cue_id = page.session.selected_cue_id = "b"
    editor.bind(page.project, "b", "")
    editor.insertFromMimeData(mime)
    assert st.records_of(page.project)["b"]["text"] == "hello world"
    assert layer_marks(page.project.cues[1], "translation") == [{"start":6,"end":11,"bold":True}]
    assert page.undo_stack.count() == 1
    page.undo_stack.undo()
    assert "b" not in st.records_of(page.project) and not layer_marks(page.project.cues[1], "translation")


def test_overlap_does_not_reuse_cancelled_explicit_selection(page):
    from PySide6.QtCore import QPoint
    from twobyteasr.timeline.selection_scope import SelectionScope
    page.project.cues[1].start_ms = 500
    page.project.cues[1].end_ms = 1500
    timeline = page.timeline
    timeline.resize(1200, 600)
    timeline.set_project(page.project)
    timeline.set_visible_window(0, 5000)
    point = QPoint(round(timeline._time_to_x(1000)), round(timeline._track_layout()[1].center().y()))
    timeline.set_selected("a")
    assert timeline._cue_at(point)[0].id == "a"
    timeline.set_selection_scope(SelectionScope.empty())
    assert timeline._cue_at(point) == (None, "translation")
    timeline.set_selection_scope(SelectionScope.explicit(("b",), "b"))
    assert timeline._cue_at(point) == (None, "translation")
    timeline.set_selected("b")
    assert timeline._cue_at(point)[0].id == "b"
