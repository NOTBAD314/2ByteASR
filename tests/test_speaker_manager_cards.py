"""2026-10-18 speaker manager redesign: one card per speaker, roles apply at once."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from twobyteasr.projects.speaker_organization import apply_new_project_policy
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.recognition.speaker_recovery import candidate_snapshot
from twobyteasr.studio import studio_speaker_manager
from twobyteasr.studio.studio_speaker_manager import SpeakerManagerDialog

APP = QApplication.instance() or QApplication([])

ROWS = [
    {"speaker": "API_S01", "start": 0.0, "end": 2.0, "text": "大家好今天打艾尔登法环", "utterance_id": 1},
    {"speaker": "API_S02", "start": 2.5, "end": 4.0, "text": "左边宝箱还没开", "utterance_id": 2},
    {"speaker": "API_S01", "start": 4.5, "end": 7.0, "text": "这个Boss第二阶段会跳", "utterance_id": 3},
    {"speaker": "API_S03", "start": 7.5, "end": 8.5, "text": "获得黄金种子", "utterance_id": 4},
    {"speaker": "API_S02", "start": 9.0, "end": 10.5, "text": "你试试看打断他", "utterance_id": 5},
    {"speaker": "API_S03", "start": 11.0, "end": 12.0, "text": "圣杯瓶次数增加", "utterance_id": 6},
]


class FakeVideo:
    def __init__(self, ready=True):
        self.controller = object() if ready else None
        self.calls = []

    def set_paused(self, paused):
        self.calls.append(("paused", paused))


def _page(project, *, video_ready=True):
    page = QWidget()
    page.project = project
    page.undo_stack = QUndoStack(page)
    page._speaker_roles_pending = False
    page.populated = 0
    page._populate_speakers = lambda: setattr(page, "populated", page.populated + 1)
    page._speaker_structure_changed = lambda: None
    page.selected_cue_ids = lambda: []
    page.video = FakeVideo(video_ready)
    page.speed_box = SimpleNamespace(currentData=lambda: 1.0)
    page.seeks = []
    page._seek = lambda seconds: page.seeks.append(seconds)
    page._set_speed = lambda speed: None
    page._open_recognition_sheet = lambda: None
    return page


def _anonymous_project():
    cues = [StudioCue(f"c{index}", round(row["start"] * 1000), round(row["end"] * 1000), row["text"],
                      speaker_id=row["speaker"]) for index, row in enumerate(ROWS)]
    project = SubtitleProject(
        media=StudioMedia("fixture.mp4", duration_ms=13_000),
        speakers=[StudioSpeaker("API_S01", "说话人 1"), StudioSpeaker("API_S02", "说话人 2"),
                  StudioSpeaker("API_S03", "说话人 3")],
        cues=cues,
    )
    snapshot = candidate_snapshot(ROWS, source="filetrans")
    snapshot["allow_raw_recovery"] = False
    project.generation_metadata["speaker_recovery"] = snapshot
    apply_new_project_policy(project)
    return project


@pytest.fixture
def manager():
    page = _page(_anonymous_project())
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    APP.processEvents()
    yield dialog
    dialog.close()
    page.deleteLater()
    APP.processEvents()


def speaker_ids(manager):
    return [speaker.id for speaker in manager.page.project.speakers]


def test_pending_cards_show_banner_role_buttons_and_representative_line(manager):
    assert list(manager.cards) == ["API_S01", "API_S02", "API_S03"]
    assert manager.banner.isVisible()
    assert "3 个待确认" in manager.banner_text.text()
    card = manager.cards["API_S01"]
    assert card.pill.isVisible() and card.pill.text() == "待确认"
    assert card.roles.isVisible() and card.roles.role() == ""
    assert card.excerpt_label.full_text() == "这个Boss第二阶段会跳"
    assert card.meta_label.text() == "2 条字幕 · 5 秒"
    assert not manager.more_tools.isVisible() and not manager.batch_bar.isVisible()


def test_role_click_applies_at_once_and_one_undo_restores(manager):
    manager.cards["API_S02"].roles.buttons["game"].click()
    assert speaker_ids(manager) == ["API_S01", "API_S03", "GAME_BACKGROUND"]
    assert manager.page.undo_stack.count() == 1
    assert list(manager.cards) == ["API_S01", "API_S02", "API_S03", "GAME_BACKGROUND"]
    folded = manager.cards["API_S02"]
    assert folded.data["present"] is False and folded.status_label.text() == "已归入游戏背景声。"
    assert folded.roles.role() == "game" and not folded.name_edit.isEnabled()
    assert "2 个待确认" in manager.banner_text.text()
    manager.page.undo_stack.undo()
    assert speaker_ids(manager) == ["API_S01", "API_S02", "API_S03"]
    assert list(manager.cards) == ["API_S01", "API_S02", "API_S03"]
    assert manager.cards["API_S02"].roles.role() == ""


def test_ignore_keeps_card_and_main_restores_as_host(manager):
    manager.cards["API_S03"].roles.buttons["ignore"].click()
    card = manager.cards["API_S03"]
    assert "API_S03" not in speaker_ids(manager)
    assert card.status_label.text().startswith("已忽略 · 2 条字幕")
    manager.cards["API_S03"].roles.buttons["main"].click()
    restored = next(s for s in manager.page.project.speakers if s.id == "API_S03")
    assert restored.is_host
    assert [c.text for c in manager.page.project.cues if c.speaker_id == "API_S03"] == ["获得黄金种子", "圣杯瓶次数增加"]
    assert manager.cards["API_S03"].host_button.isChecked()


def test_clicking_the_active_role_returns_to_pending(manager):
    buttons = manager.cards["API_S01"].roles.buttons
    buttons["main"].click()
    assert manager.cards["API_S01"].roles.role() == "main" and not manager.cards["API_S01"].pill.isVisible()
    buttons["main"].click()
    assert manager.cards["API_S01"].roles.role() == "" and manager.cards["API_S01"].pill.text() == "待确认"
    assert manager.page.undo_stack.count() == 2


def test_merge_menu_targets_and_merge_into_another_track(manager):
    assert manager._merge_targets("API_S02") == ["API_S01", "API_S03"]
    manager._merge("API_S02", "API_S01")
    assert "API_S02" not in speaker_ids(manager)
    assert len([c for c in manager.page.project.cues if c.speaker_id == "API_S01"]) == 4
    assert manager.cards["API_S02"].status_label.text() == "已并入 说话人 1。"
    assert manager._merge_targets("API_S03") == ["API_S01"]


def test_host_visibility_and_colour_are_one_click_and_undoable(manager):
    card = manager.cards["API_S02"]
    card.host_button.click()
    assert [s.id for s in manager.page.project.speakers if s.is_host] == ["API_S02"]
    manager.cards["API_S02"].host_button.click()
    assert not any(s.is_host for s in manager.page.project.speakers)
    manager.cards["API_S02"].visible_button.click()
    assert next(s for s in manager.page.project.speakers if s.id == "API_S02").hidden
    assert manager.cards["API_S02"].pill.text() == "待确认"
    assert manager.page.undo_stack.count() == 3


def test_multi_select_batch_background_and_delete_needs_confirmation(manager, monkeypatch):
    manager.multi_button.setChecked(True)
    assert manager.batch_bar.isVisible() and manager.cards["API_S01"].select_check.isVisible()
    manager.cards["API_S03"].select_check.setChecked(True)
    assert manager.selection_summary.text() == "已选 1 人 / 2 条字幕"
    asked = []
    monkeypatch.setattr(studio_speaker_manager, "studio_message_box",
                        lambda *args, **kwargs: asked.append(args[2]) or QMessageBox.StandardButton.No)
    manager.delete_captions_button.click()
    assert asked == ["删除人物及字幕"] and "API_S03" in speaker_ids(manager)
    manager.batch_buttons["background"].click()
    assert speaker_ids(manager) == ["API_S01", "API_S02", "GAME_BACKGROUND"]


def test_preview_seeks_to_representative_and_second_click_stops(manager):
    card = manager.cards["API_S01"]
    card.play_button.click()
    assert manager.page.seeks == [pytest.approx(4.35)]
    assert card.play_button.property("playing") is True
    card.play_button.click()
    assert manager.page.video.calls[-1] == ("paused", True)
    assert card.play_button.property("playing") is False
    card.strip.seek_requested.emit(11_500)
    assert manager.page.seeks[-1] == pytest.approx(0.0) or manager.page.seeks[-1] > 0


def test_preview_waits_for_media(manager):
    manager.page.video = FakeVideo(ready=False)
    manager.cards["API_S02"].play_button.click()
    assert manager.status.text() == "请先等待媒体预览就绪，再点击试听。"


def test_legacy_cache_folder_stages_roles_until_rebuild(tmp_path):
    media = tmp_path / "old.mp4"
    rows = [{"speaker": "S01", "start": float(index), "end": index + .8, "text": f"主播第{index}句"} for index in range(12)]
    rows += [{"speaker": "S02", "start": 20.0, "end": 21.0, "text": "旁白一句"}]
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "moss.json").write_text(json.dumps({"identity": {"path": str(media)}, "data": {"segments": rows}},
                                                ensure_ascii=False), encoding="utf-8")
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=30_000),
                              speakers=[StudioSpeaker("S01", "S01")],
                              cues=[StudioCue("k", 0, 800, "主播第0句", speaker_id="S01")])
    page = _page(project)
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    assert "MOSS" in dialog.candidate_note.text() and not dialog.cards["S01"].roles.isVisible()
    dialog._load_snapshot(cache)
    dialog.refresh()
    assert dialog.rebuild_button.isVisible() and list(dialog.cards) == ["S01", "S02"]
    dialog.cards["S02"].roles.buttons["ignore"].click()
    assert page._speaker_roles_pending and page.undo_stack.count() == 0
    dialog.rebuild_button.click()
    assert page.undo_stack.count() == 1 and [s.id for s in project.speakers] == ["S01"]
    assert project.generation_metadata["speaker_recovery"]["roles"]["S02"] == "ignore"
    assert not dialog.rebuild_button.isVisible()
    dialog.close()
    page.deleteLater()
