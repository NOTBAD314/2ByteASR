"""2026-10-18 workbench feedback: adjust menu, 跳转 number, toolbar fit, shortcut panel × and Ctrl+wheel.

The real-window run (two themes) is tmp/workbench-fixes-20261018/driver.py; these
cover the pieces offline.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QWidget)
from PySide6.QtCore import Qt

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------ 12: one-click re-layout


class Page(QWidget):
    def __init__(self, project):
        super().__init__()
        self.project = project
        self.undo_stack = QUndoStack(self)
        self.changes, self.hints = 0, []

    def _changed(self):
        self.changes += 1

    def _show_studio_hint(self, message):
        self.hints.append(str(message))


def _overlapping_project():
    return SubtitleProject(
        media=StudioMedia("missing-fixture.mp4", duration_ms=5000),
        styles=[SubtitleStyle("default", "Default", font_size=64, outline_width=4, shadow=0)],
        cues=[StudioCue("a", 0, 2000, "先说一句"), StudioCue("b", 500, 2500, "另一句插话"),
              StudioCue("manual", 200, 2600, "手动字幕", transform={"position_x": 800, "position_y": 900})])


def test_rearrange_now_is_one_undo_step_and_keeps_manual_positions():
    from twobyteasr.studio.subtitle_layout_ui import rearrange_now
    page = Page(_overlapping_project())
    before = {cue.id: dict(cue.transform) for cue in page.project.cues}
    moved = rearrange_now(page, ["a", "b", "manual"])
    assert moved >= 1 and page.undo_stack.count() == 1
    assert page.project.cues[2].transform == before["manual"]  # hand-placed: untouched
    assert "可撤销" in page.hints[-1] and "1 条手动摆放" in page.hints[-1]
    page.undo_stack.undo()
    assert {cue.id: dict(cue.transform) for cue in page.project.cues} == before
    page.close()


def test_rearrange_now_without_a_selection_says_so():
    from twobyteasr.studio.subtitle_layout_ui import rearrange_now
    page = Page(_overlapping_project())
    assert rearrange_now(page, []) == 0 and page.undo_stack.count() == 0
    assert page.hints == ["先选中要重新排版的字幕"]
    page.close()


# ------------------------------------------------------------ 13: 跳转 follows the selection


class JumpPage:
    from twobyteasr.studio.studio_review_ui import StudioReviewMixin as _Mixin
    _sync_jump_position = _Mixin._sync_jump_position
    _jump_to_row = _Mixin._jump_to_row

    def __init__(self, cues):
        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(1, len(cues))
        self.jump_spin.valueChanged.connect(lambda _value: setattr(self, "_jump_pending", True))
        self._cue_jump_order = list(cues)
        self._cue_jump_index = {cue.id: index for index, cue in enumerate(cues)}
        self.project = object()
        self.selected_cue_id = ""
        self.went = []

    def _go_to_listed_cue(self, cue):
        self.went.append(cue.id)


def test_jump_box_shows_the_selected_caption_and_jumps_only_when_changed():
    cues = [StudioCue(f"c{index}", index * 1000, index * 1000 + 800, "字") for index in range(5)]
    page = JumpPage(cues)
    page.selected_cue_id = "c3"
    page._sync_jump_position()
    assert page.jump_spin.value() == 4 and not getattr(page, "_jump_pending", False)
    page._jump_to_row()  # leaving the box unchanged is not a jump
    assert page.went == []
    page.jump_spin.setValue(2)  # the user's number
    page.selected_cue_id = "c4"
    page._sync_jump_position()  # playback must not overwrite it
    assert page.jump_spin.value() == 2
    page._jump_to_row()
    assert page.went == ["c1"] and not page._jump_pending
    page.selected_cue_id = "c1#split-a"  # a derived id resolves to its source
    page._cue_jump_index["c1"] = 1
    page._sync_jump_position()
    assert page.jump_spin.value() == 2


# ------------------------------------------------------------ 14: the toolbar fits, the status keeps its room


class FitPage(QWidget):
    from twobyteasr.studio.studio_project_flow import StudioProjectFlowMixin as _Mixin
    _fit_studio_toolbar = _Mixin._fit_studio_toolbar


def _toolbar_page(width):
    from twobyteasr.design.elided_label import ElidedLabel
    from twobyteasr.studio.studio_widgets import StudioStatusLabel
    page = FitPage()
    page.studio_toolbar = bar = QFrame(page)
    row = QHBoxLayout(bar)
    page.filename = ElidedLabel("录制-企鹅带带北极熊-2026_10_15-20_24_05-异环明音！抽卡看剧情！_1", minimum=120)
    page.filename.setMaximumWidth(420)
    row.addWidget(page.filename)
    page.save_state = StudioStatusLabel("已自动保存 · 00:12")
    page.save_state.setMinimumWidth(110)
    page.save_state.setMaximumWidth(220)
    row.addWidget(page.save_state)
    row.addStretch(1)
    page.home = QPushButton("主页")
    row.addWidget(page.home)
    commands = [QPushButton(f"命令按钮{index}" * 2) for index in range(6)]
    for index, button in enumerate(commands):
        button.setMinimumWidth(160)
        row.addWidget(button)
        if index % 2:  # groups of two, like the real bar
            divider = QFrame()
            divider.setObjectName("toolbarDivider")
            divider.setFixedWidth(1)
            row.addWidget(divider)
    row.addWidget(QPushButton("导出字幕"))
    page._studio_compact_commands = tuple(commands[:2])
    page._studio_toolbar_collapse_order = tuple(commands)
    page.resize(width, 60)
    bar.resize(width, 60)
    return page, commands


def test_toolbar_moves_commands_out_until_it_fits_and_restores_them():
    page, commands = _toolbar_page(900)
    page.show()
    page._fit_studio_toolbar(True, False)
    collapsed = page._studio_toolbar_collapsed
    assert collapsed and collapsed == commands[:len(collapsed)]  # in the given order
    assert page.studio_toolbar.layout().minimumSize().width() <= 900
    shown = [w for w in (page.studio_toolbar.layout().itemAt(i).widget()
                         for i in range(page.studio_toolbar.layout().count())) if w is not None and not w.isHidden()]
    kinds = [w.objectName() == "toolbarDivider" for w in shown]
    assert not any(a and b for a, b in zip(kinds, kinds[1:]))  # no empty group between two dividers
    page.resize(2600, 60)
    page._fit_studio_toolbar(True, False)
    assert page._studio_toolbar_collapsed == [] and all(button.isVisible() for button in commands)
    page._fit_studio_toolbar(False, True)  # the Hub: none of them
    assert not any(button.isVisible() for button in commands)
    page._fit_studio_toolbar(False, False)  # export view: only the editor-only ones leave
    assert [button.isVisible() for button in commands] == [False, False, True, True, True, True]
    page.close()


def test_hub_command_collapses_in_order_but_stays_in_the_hub():
    """回报问题 (2026-10-21): leaves a narrow bar before 字幕列表, yet the Hub still offers it."""
    page, commands = _toolbar_page(900)
    page._studio_hub_commands = (commands[3],)
    page.show()
    page._fit_studio_toolbar(True, False)
    collapsed = page._studio_toolbar_collapsed
    assert collapsed == commands[:len(collapsed)] and commands[3] in collapsed
    page._fit_studio_toolbar(False, True)  # the Hub: only the hub command
    assert [button.isVisible() for button in commands] == [False, False, False, True, False, False]
    page.close()


def test_small_command_returns_when_later_commands_made_room():
    """The flag leaves first, then comes back into the room the wide commands left (2026-10-21)."""
    page, commands = _toolbar_page(900)
    flag = commands[0]
    flag.setText("")
    flag.setMinimumWidth(36)
    flag.setMaximumWidth(36)
    page._studio_toolbar_return_commands = (flag,)
    layout = page.studio_toolbar.layout()
    page.show()
    page._fit_studio_toolbar(True, False)
    collapsed = page._studio_toolbar_collapsed
    assert collapsed and flag not in collapsed and flag.isVisible()  # a 160 px command made room
    assert collapsed == commands[1:1 + len(collapsed)]
    layout.invalidate()
    assert layout.minimumSize().width() + 8 <= 900
    again = list(collapsed)
    page._fit_studio_toolbar(True, False)  # same width, same answer: no flicker
    assert page._studio_toolbar_collapsed == again and flag.isVisible()
    page.resize(260, 60)  # nothing left makes room: the flag stays in ⋯
    page._fit_studio_toolbar(True, False)
    assert flag in page._studio_toolbar_collapsed and not flag.isVisible()
    page.close()


def test_status_label_asks_for_its_whole_message():
    from twobyteasr.studio.studio_widgets import StudioStatusLabel
    label = StudioStatusLabel("已自动保存 · 00:12")
    label.resize(40, 18)  # elided now
    assert label.sizeHint().width() >= label.fontMetrics().horizontalAdvance("已自动保存 · 00:12")


# ------------------------------------------------------------ 9: the drawer panel has a × at the top


def test_drawer_shortcut_panel_has_a_close_button_and_settings_page_does_not():
    from twobyteasr.studio.studio_shortcuts import ShortcutSettingsPanel
    panel = ShortcutSettingsPanel({}, None)
    asked = []
    panel.close_requested.connect(lambda: asked.append(True))
    assert panel.close_button is not None
    panel.close_button.click()
    assert asked == [True]
    embedded = ShortcutSettingsPanel({}, None, embedded=True)
    assert embedded.close_button is None
    panel.deleteLater()
    embedded.deleteLater()


# ------------------------------------------------------------ 11: no divider inside 保存当前帧


def test_save_frame_split_button_draws_no_divider():
    import inspect
    import importlib
    source = inspect.getsource(importlib.import_module("twobyteasr.design.studio_qss"))
    rule = next(line for line in source.splitlines()
                if "studioTimelineCommandBar QToolButton#rangeAction::menu-button" in line)
    assert "border-left" not in rule


# ------------------------------------------------------------ 5: the workbench owns Ctrl+wheel in its window


def test_window_showing_the_workbench_never_zooms_the_interface():
    from twobyteasr.app.ui_zoom import _zoomable
    window = QWidget()
    studio = QWidget(window)
    studio.setObjectName("subtitleStudio")
    edge = QLabel("outside the page", window)
    tool = QWidget(window, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    dialog = QDialog(window)
    try:
        assert _zoomable(edge) and _zoomable(window)  # workbench not on screen
        window.show()
        studio.show()
        assert not _zoomable(edge) and not _zoomable(window)
        assert not _zoomable(tool)  # a tool window floating over the workbench
        assert _zoomable(dialog)  # dialogs keep their zoom
        studio.hide()
        assert _zoomable(edge)
    finally:
        window.close()
        window.deleteLater()


def test_tool_panel_holds_save_undo_redo_and_usage_lives_in_overflow(app):
    """2026-10-21 (user): 保存/撤销/重做 sit in the Tool Panel header; API 用量与费用 only in ⋯."""
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    page = SubtitleStudioPage()
    app.processEvents()
    bar = page.studio_toolbar
    header = (page.save_button, page.studio_undo_button, page.studio_redo_button)
    for button in header:
        assert not bar.isAncestorOf(button) and page.context_panel.isAncestorOf(button)
    assert len({button.parentWidget() for button in header}) == 1  # one row
    assert not page.studio_undo_button.isEnabled() and not page.studio_redo_button.isEnabled()
    assert not bar.isAncestorOf(page.studio_usage_button) and page.studio_usage_button.isHidden()
    assert page.studio_usage_button in page._studio_toolbar_overflow_widgets
    page.close_page()
    page.deleteLater()
    app.processEvents()
