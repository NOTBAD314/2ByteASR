"""The open tool page is saved with the project and comes back on reopen.

0.8.0 added 动效 but kept a five-entry id table: saving with 素材 open raised
IndexError before anything was written (autosave too), and 动效 / 视频 /
剪辑助手 were saved as the next page's id.
"""
from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr import studio_ui
from twobyteasr.studio_context_tabs import CONTEXT_TAB_IDS, context_tab_layout, restored_context_tab
from twobyteasr.studio_ui import SubtitleStudioPage
from tests.test_studio_cue_controller import _finish

PAGE_IDS = {"AI设计": "ai", "样式": "style", "动效": "motion", "视频": "video", "剪辑助手": "highlight", "素材": "media"}


def _no_message_box(*args, **_kwargs):
    raise AssertionError(f"unexpected message box: {args[2:]}")


def _project_file(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"mp4")
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=5_000),
        cues=[StudioCue("a", 0, 1_200, "第一句"), StudioCue("b", 1_400, 2_600, "第二句")],
    )
    return save_project(project, tmp_path / "tabs.2byteproj")


def _open(path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(path.parent / "local"))
    monkeypatch.setattr(studio_ui, "studio_message_box", _no_message_box)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_project_waveforms", lambda *_a, **_k: None)
    page.open_project(path)
    app.processEvents()
    return page


def _show_page(page, index):
    drawer = page.context_drawer
    # Start from another page so currentChanged fires like a click.
    drawer.setCurrentIndex((index + 1) % drawer.count())
    drawer.setCurrentIndex(index)


def test_save_and_autosave_write_the_project_with_every_tool_page_open(tmp_path, monkeypatch):
    path = _project_file(tmp_path)
    page = _open(path, monkeypatch)
    drawer = page.context_drawer
    assert [PAGE_IDS[drawer.tabToolTip(i)] for i in range(drawer.count())] == list(CONTEXT_TAB_IDS)
    for index in range(drawer.count()):
        page.cue_controller.set_text("a", f"改过的 {index}")
        _show_page(page, index)
        autosave = page.flush_autosave()
        assert autosave is not None and autosave.is_file()
        path.unlink()
        page.save()
        assert path.is_file() and page.undo_stack.isClean()
        saved = json.loads(path.read_text("utf-8"))
        assert saved["cues"][0]["text"] == f"改过的 {index}"
        layout = saved["studio_state"]["layout"]
        assert layout["context_tab_id"] == PAGE_IDS[drawer.tabToolTip(index)]
        assert layout["context_tab_ids"] == list(CONTEXT_TAB_IDS)
    _finish(page)


@pytest.mark.parametrize("index", range(len(CONTEXT_TAB_IDS)))
def test_each_tool_page_reopens_after_save(tmp_path, monkeypatch, index):
    path = _project_file(tmp_path)
    page = _open(path, monkeypatch)
    _show_page(page, index)
    page.save()
    _finish(page)
    reopened = _open(path, monkeypatch)
    assert reopened.context_drawer.currentIndex() == index
    assert PAGE_IDS[reopened.context_drawer.tabToolTip(index)] == CONTEXT_TAB_IDS[index]
    _finish(reopened)


def test_old_readers_keep_their_numbering():
    # context_tab is the numbering from before 检查 was removed; 动效 had no page then.
    assert [context_tab_layout(i)["context_tab"] for i in range(len(CONTEXT_TAB_IDS))] == [0, 2, 2, 3, 4, 5]
    assert context_tab_layout(99)["context_tab_id"] == "style"


def test_release_080_files_reopen_on_the_page_they_were_saved_from():
    after_080 = "2026-10-18T09:00:00+00:00"
    before_080 = "2026-10-16T09:00:00+00:00"
    written_by_080 = ("ai", "style", "video", "highlight", "media")  # for AI设计 … 剪辑助手
    assert [restored_context_tab({"context_tab_id": v}, saved_at=after_080) for v in written_by_080] == [0, 1, 2, 3, 4]
    # 0.7.x had no 动效 page and saved true ids.
    assert [restored_context_tab({"context_tab_id": v}, saved_at=before_080) for v in written_by_080] == [0, 1, 3, 4, 5]
    assert restored_context_tab({"context_tab_id": "video"}, saved_at="") == 3
    # Files written with the six-page table are read as they are.
    marked = {"context_tab_ids": list(CONTEXT_TAB_IDS)}
    assert [
        restored_context_tab({**marked, "context_tab_id": v}, saved_at=after_080) for v in CONTEXT_TAB_IDS
    ] == list(range(len(CONTEXT_TAB_IDS)))
