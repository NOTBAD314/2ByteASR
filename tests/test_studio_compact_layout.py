"""Studio compact layout (2026-10-09, M16): I/O toggles and the range menu
text, the two-line subtitle list, the one-row scope chips and the style
preview of the selected line."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontMetrics, QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

APP = QApplication.instance() or QApplication([])


def _project():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    return SubtitleProject(media=StudioMedia(path="", duration_ms=20_000),
                           cues=[StudioCue("c1", 0, 20_000, "一句")])


def test_same_key_at_the_same_place_clears_the_point_with_one_undo_step():
    from twobyteasr.projects.project_range import range_points, range_summary
    from twobyteasr.studio.studio_edit_assembly import StudioEditAssemblyMixin

    project = _project()
    page = SimpleNamespace(project=project, undo_stack=QUndoStack(), save_state=QLabel(),
                           timeline=SimpleNamespace(playhead_ms=2_000, update=lambda: None))
    mark = StudioEditAssemblyMixin._mark_range_point
    assert range_summary(project) == ("", False)
    mark(page, 0)
    assert range_points(project) == (2_000, None)
    assert "再按 I 取消" in page.save_state.text()
    page.timeline.playhead_ms = 9_000
    mark(page, 1)
    assert range_points(project) == (2_000, 9_000)
    text, has_range = range_summary(project)
    assert has_range and text == "00:00:02.000 – 00:00:09.000 · 00:00:07.000"
    page.timeline.playhead_ms = 9_010  # same place within one frame
    mark(page, 1)
    assert range_points(project) == (2_000, None)
    assert "已取消" in page.save_state.text()
    page.timeline.playhead_ms = 12_000
    mark(page, 1)
    assert range_points(project) == (2_000, 12_000)
    page.undo_stack.undo()
    assert range_points(project) == (2_000, None)
    StudioEditAssemblyMixin._clear_range(page)
    assert range_points(project) == (None, None)


def test_reading_rows_show_two_lines_and_elide_only_past_them():
    from twobyteasr.studio.studio_cue_table import CueReadingDelegate
    delegate = CueReadingDelegate()
    font = delegate.text_font(QFont())
    short = delegate._wrapped("一句短字幕", font, 300)
    assert short == ["一句短字幕"]
    long_text = "这是一句很长很长的字幕" * 6
    lines = delegate._wrapped(long_text, font, 160)
    assert len(lines) == CueReadingDelegate.LINES
    assert lines[-1].endswith("…")
    assert all(QFontMetrics(font).horizontalAdvance(line) <= 160 + 2 for line in lines)
    assert CueReadingDelegate.row_height(QFont()) >= 2 * QFontMetrics(font).lineSpacing() + 22


def test_scope_chips_are_one_row_with_short_labels_and_full_tooltips():
    from PySide6.QtWidgets import QRadioButton
    from twobyteasr.caption_style.studio_style_widgets import StyleScopeSelector
    scope = StyleScopeSelector()
    for label, data in (("当前字幕", "current"), ("已选择字幕", "selected"), ("当前说话人", "speaker"), ("全部字幕", "all")):
        scope.addItem(label, data)
    scope.set_single_row({"current": "当前", "selected": "已选", "speaker": "说话人", "all": "全部"})
    buttons = scope.findChildren(QRadioButton)
    assert [button.text() for button in buttons] == ["当前", "已选", "说话人", "全部"]
    scope.setItemText(scope.findData("selected"), "选中字幕（3）")
    assert buttons[1].text() == "已选 3"
    assert "选中字幕（3）" in buttons[1].toolTip()
    scope.setCurrentIndex(scope.findData("speaker"))
    assert scope.currentData() == "speaker"


def test_style_preview_shows_the_selected_line_and_the_sample_on_demand():
    from twobyteasr.caption_style.studio_style_widgets import StylePreview
    preview = StylePreview()
    preview.enable_sample_toggle()
    assert preview.display_text() == "示例字幕 Aa 123"  # nothing selected yet
    preview.set_sample_text("  还是在等 Autumn   出结果 ")
    assert preview.display_text() == "还是在等 Autumn 出结果"
    preview.sample_toggle.setChecked(True)
    assert preview.display_text() == "示例字幕 Aa 123"
