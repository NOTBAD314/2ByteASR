"""2026-11-12 speaker board (方案 B): boxes, drops and whole-group merges, each one undo."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.speaker_organization import apply_new_project_policy
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.recognition.speaker_recovery import candidate_snapshot
from twobyteasr.recognition.speaker_roles import KEY, decide
from twobyteasr.studio.studio_speaker_manager import SpeakerManagerDialog
from tests.test_speaker_manager_cards import _page

APP = QApplication.instance() or QApplication([])
# Two talkative labels and four that say little: S01/S02 main, the rest grouped.
COUNTS = {"API_S01": 6, "API_S02": 5, "API_S03": 2, "API_S04": 2, "API_S05": 1, "API_S06": 1}


def _rows():
    rows, start = [], 0.0
    for label, count in COUNTS.items():
        for index in range(count):
            rows.append({"speaker": label, "start": start, "end": start + 0.8, "text": f"{label}第{index}句",
                         "utterance_id": len(rows) + 1})
            start += 1.0
    return rows


def _project(grouped=True):
    rows = _rows()
    cues = [StudioCue(f"c{i}", round(r["start"] * 1000), round(r["end"] * 1000), r["text"], speaker_id=r["speaker"])
            for i, r in enumerate(rows)]
    project = SubtitleProject(media=StudioMedia("fixture.mp4", duration_ms=20_000),
                              speakers=[StudioSpeaker(label, label.replace("API_", "")) for label in COUNTS], cues=cues)
    snapshot = candidate_snapshot(rows, source="filetrans")
    snapshot["allow_raw_recovery"] = False
    project.generation_metadata["speaker_recovery"] = snapshot
    apply_new_project_policy(project)
    if grouped:
        project.studio_state[KEY] = decide(project, manual={}, cap=2)
    return project


@pytest.fixture
def board():
    page = _page(_project())
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    APP.processEvents()
    yield dialog
    dialog.close()
    page.deleteLater()
    APP.processEvents()


def ids(dialog):
    return [speaker.id for speaker in dialog.page.project.speakers]


def drop(dialog, keys, kind, target=""):
    dialog._drop(keys, kind, target)
    APP.processEvents()
    APP.processEvents()


def test_frameless_window_and_four_boxes_follow_timeline_groups(board):
    assert board.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert board._box_keys("main") == ["API_S01", "API_S02"]
    assert set(board._box_keys("secondary")) == {"API_S03", "API_S04", "API_S05", "API_S06"}
    assert board._box_keys("game") == [] and board._box_keys("ignore") == []
    assert board.group_merge_button.isVisible() and board.group_merge_button.isEnabled()
    assert not board.tiles["API_S03"].main and board.tiles["API_S01"].main


def test_drop_into_game_and_back_are_one_undo_each(board):
    drop(board, ["API_S05", "API_S06"], "game")
    assert ids(board) == ["API_S01", "API_S02", "API_S03", "API_S04", "GAME_BACKGROUND"]
    assert set(board._box_keys("game")) == {"GAME_BACKGROUND", "API_S05", "API_S06"}
    assert board.page.undo_stack.count() == 1
    drop(board, ["API_S05"], "secondary")
    assert "API_S05" in ids(board) and "API_S05" in board._box_keys("secondary")
    assert board.page.undo_stack.count() == 2
    board.page.undo_stack.undo()
    board.page.undo_stack.undo()
    assert ids(board) == list(COUNTS)


def test_drop_on_a_speaker_merges_and_keeps_text(board):
    texts = sorted(cue.text for cue in board.page.project.cues)
    board._tile_clicked("API_S03", Qt.KeyboardModifier.NoModifier)
    board._tile_clicked("API_S04", Qt.KeyboardModifier.ControlModifier)
    assert board._can_merge(["API_S03", "API_S04"], "API_S02")
    drop(board, ["API_S03", "API_S04"], "secondary", target="API_S02")
    assert ids(board) == ["API_S01", "API_S02", "API_S05", "API_S06"]
    assert sorted(cue.text for cue in board.page.project.cues) == texts
    roles = board.page.project.generation_metadata["speaker_recovery"]["roles"]
    assert roles["API_S03"] == roles["API_S04"] == "merge:API_S02"
    assert board.page.undo_stack.count() == 1
    card = board.cards["API_S02"]
    assert [label for label, _name in card.data["merged"]] == ["API_S03", "API_S04"]
    board.page.undo_stack.undo()
    assert ids(board) == list(COUNTS)


def test_whole_secondary_group_merges_into_one_named_speaker_with_one_undo(board):
    board.group_merge_button.click()
    APP.processEvents()
    assert board.inspector.currentWidget() is board.merge_panel
    assert board._selection == {"API_S03", "API_S04", "API_S05", "API_S06"}
    assert board.merge_panel.target() in {"API_S03", "API_S04"}
    assert board.merge_panel.name() == "次要角色"
    board.merge_panel.name_edit.setText("路人")
    board.merge_panel.confirm_button.click()
    APP.processEvents()
    target = next(s for s in board.page.project.speakers if s.id not in {"API_S01", "API_S02"})
    assert len(board.page.project.speakers) == 3 and target.name == "路人"
    assert sum(cue.speaker_id == target.id for cue in board.page.project.cues) == 6
    assert board.page.undo_stack.count() == 1
    board.page.undo_stack.undo()
    assert ids(board) == list(COUNTS)
    assert all(s.name == s.id.replace("API_", "") for s in board.page.project.speakers)


def test_moving_between_main_and_secondary_changes_only_the_timeline_group(board):
    cues = [(c.id, c.speaker_id) for c in board.page.project.cues]
    drop(board, ["API_S01"], "secondary")
    assert "API_S01" in board._box_keys("secondary")
    assert board.page.project.studio_state[KEY]["manual"]["API_S01"] == "secondary"
    assert [(c.id, c.speaker_id) for c in board.page.project.cues] == cues
    board.page.undo_stack.undo()
    assert board._box_keys("main") == ["API_S01", "API_S02"]


def test_ignored_label_is_dropped_back_and_gets_its_captions():
    page = _page(_project())
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    drop(dialog, ["API_S06"], "ignore")
    assert dialog._box_keys("ignore") == ["API_S06"] and "API_S06" not in ids(dialog)
    assert not dialog.tiles["API_S06"].data["present"]
    drop(dialog, ["API_S06"], "main")
    assert "API_S06" in ids(dialog) and "API_S06" in dialog._box_keys("main")
    assert sum(c.speaker_id == "API_S06" for c in page.project.cues) == 1
    dialog.close()


def test_ungrouped_project_offers_organize_and_plain_speakers_cannot_be_ignored():
    page = _page(_project(grouped=False))
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    APP.processEvents()
    assert dialog._box_keys("secondary") == [] and dialog.organize_button.isVisible()
    dialog.organize_button.click()
    APP.processEvents()
    assert len(dialog._box_keys("secondary")) == 4
    dialog.close()
    plain = SubtitleProject(media=StudioMedia("x.mp4", duration_ms=3000),
                            speakers=[StudioSpeaker("S01", "甲"), StudioSpeaker("S02", "乙")],
                            cues=[StudioCue("a", 0, 900, "一", speaker_id="S01"), StudioCue("b", 1000, 1900, "二", speaker_id="S02")])
    page = _page(plain)
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    assert not dialog._can_move(["S02"], "ignore") and dialog._can_move(["S02"], "game")
    drop(dialog, ["S02"], "game")
    assert [s.id for s in plain.speakers] == ["S01", "GAME_BACKGROUND"]
    dialog.close()


def test_escape_clears_selection_before_closing(board):
    from PySide6.QtTest import QTest
    board._tile_clicked("API_S03", Qt.KeyboardModifier.NoModifier)
    QTest.keyClick(board, Qt.Key.Key_Escape)
    assert board.isVisible() and not board._selection
    assert board.inspector.currentWidget() is board.empty_page
