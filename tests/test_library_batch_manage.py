"""工程库批量选取/删除（2026-09-18）：管理模式、空工程快捷选择、批量删除语义。"""

import json
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton

import twobyteasr.projects.studio_project as studio_project
import twobyteasr.studio.studio_project_flow as studio_project_flow
import twobyteasr.studio.studio_ui as studio_ui
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio.studio_ui import SubtitleStudioPage


@pytest.fixture
def hub_project_dir(tmp_path):
    base = tmp_path.resolve()
    root = (base / "projects").resolve()
    assert root.parent == base
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        try:
            base.rmdir()
        except OSError:
            pass


def _hub_page(tmp_path, monkeypatch, hub_project_dir, records_spec):
    """records_spec: list of dicts {name, cues, media} -> writes projects + settings."""
    settings = tmp_path / "settings.json"
    records = []
    for spec in records_spec:
        path = hub_project_dir / f"{spec['name']}.2byteproj"
        media_path = spec.get("media")
        project = SubtitleProject(
            media=StudioMedia(path=str(hub_project_dir / media_path)) if media_path else StudioMedia(path=""),
            cues=[
                StudioCue(id=str(index + 1), start_ms=0, end_ms=1000, text=f"字幕 {index}")
                for index in range(spec.get("cues", 0))
            ],
        )
        save_project(project, path)
        records.append({
            "path": str(path.resolve()),
            "name": spec["name"],
            "cue_count": spec.get("cues", 0),
            "source_media": spec.get("media", ""),
        })
    settings.write_text(json.dumps({"recent_projects": records}), encoding="utf-8")
    monkeypatch.setattr(studio_ui, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project_flow, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project, "studio_settings_path", lambda: settings)
    import twobyteasr.studio.studio_hub as _hub_module
    monkeypatch.setattr(_hub_module, "studio_settings_path", lambda: settings)
    monkeypatch.setattr("twobyteasr.studio.studio_hub.project_library_root", lambda: hub_project_dir)
    QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    # 同步走真实扫描路径（含 enrich/_summary_loaded），不等待后台线程
    page._hub_library_records = page._project_library_records()
    page._rebuild_project_library()
    return page, settings


def test_manage_mode_makes_cards_checkable_and_blocks_open(tmp_path, monkeypatch, hub_project_dir):
    page, _settings = _hub_page(tmp_path, monkeypatch, hub_project_dir, [
        {"name": "real", "cues": 2, "media": "offline.mp4"},
    ])
    try:
        app = QApplication.instance()
        cards = list(page._hub_card_widgets)
        assert cards and not cards[0].isCheckable()
        assert page.project_manage_bar.isHidden()
        page._set_library_manage_mode(True)
        app.processEvents()
        assert not page.project_manage_bar.isHidden()
        assert page.project_manage_button.text() == "完成"
        cards = list(page._hub_card_widgets)
        assert cards[0].isCheckable()
        open_button = cards[0].findChildren(type(page.project_new_button), "projectCardOpen")[0]
        assert not open_button.isEnabled()
        # 点击卡片 = 勾选，不触发打开工程
        cards[0].click()
        app.processEvents()
        assert cards[0].isChecked()
        assert page._library_selected_paths
        assert "已选 1 项" in page.project_manage_count_label.text()
        assert page.project_delete_button.isEnabled()
        page._set_library_manage_mode(False)
        app.processEvents()
        assert page.project_manage_bar.isHidden()
        assert page.project_manage_button.text() == "管理"
        cards = list(page._hub_card_widgets)
        assert not cards[0].isCheckable()
        assert not page._library_selected_paths
    finally:
        page.close_page()


def test_select_empty_targets_only_empty_projects(tmp_path, monkeypatch, hub_project_dir):
    page, _settings = _hub_page(tmp_path, monkeypatch, hub_project_dir, [
        {"name": "empty-1", "cues": 0, "media": ""},
        {"name": "empty-2", "cues": 0, "media": "missing-media.flv"},
        {"name": "has-cues-no-media", "cues": 3, "media": ""},
    ])
    try:
        page._set_library_manage_mode(True)
        page._library_select_empty_projects()
        selected_names = {
            Path(path).stem for path in page._library_selected_paths
        }
        assert selected_names == {"empty-1", "empty-2"}, selected_names
        # 有字幕的工程即使无媒体也不算空工程
        cards = {
            widget._library_item_path: widget
            for widget in page._iter_library_item_widgets()
        }
        by_stem = {Path(path).stem: widget for path, widget in cards.items()}
        assert by_stem["empty-1"].isChecked()
        assert by_stem["empty-2"].isChecked()
        assert not by_stem["has-cues-no-media"].isChecked()
        assert "已选 2 项" in page.project_manage_count_label.text()
    finally:
        page.close_page()


def test_batch_delete_removes_files_and_recent_metadata(tmp_path, monkeypatch, hub_project_dir):
    page, settings = _hub_page(tmp_path, monkeypatch, hub_project_dir, [
        {"name": "junk-1", "cues": 0, "media": ""},
        {"name": "junk-2", "cues": 0, "media": ""},
        {"name": "keep", "cues": 4, "media": "keep.mp4"},
    ])
    try:
        page._set_library_manage_mode(True)
        page._library_select_empty_projects()
        monkeypatch.setattr(
            QMessageBox, "exec",
            classmethod(lambda cls, *args, **kwargs: QMessageBox.StandardButton.Yes),
            raising=False,
        )
        from twobyteasr.studio import studio_hub as hub_module
        monkeypatch.setattr(
            hub_module, "studio_message_box",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        page._delete_selected_library_projects()
        page._hub_library_records = None  # 删除后走 recent 记录直读路径（真机由后台扫描刷新）
        app = QApplication.instance()
        app.processEvents()
        remaining = sorted(path.name for path in hub_project_dir.glob("*.2byteproj"))
        assert remaining == ["keep.2byteproj"], remaining
        payload = json.loads(settings.read_text(encoding="utf-8"))
        recent_names = {Path(item["path"]).stem for item in payload["recent_projects"]}
        assert recent_names == {"keep"}, recent_names
        assert not page._library_selected_paths
        # 管理模式保持，列表已刷新且新卡可继续勾选
        cards = list(page._hub_card_widgets)
        assert len(cards) == 1
        assert not cards[0].isChecked()
        assert "已选 0 项" in page.project_manage_count_label.text()
    finally:
        page.close_page()


def test_batch_delete_cancel_keeps_everything(tmp_path, monkeypatch, hub_project_dir):
    page, settings = _hub_page(tmp_path, monkeypatch, hub_project_dir, [
        {"name": "junk-1", "cues": 0, "media": ""},
    ])
    try:
        page._set_library_manage_mode(True)
        page._library_select_displayed(select_all=True)
        from twobyteasr.studio import studio_hub as hub_module
        monkeypatch.setattr(
            hub_module, "studio_message_box",
            lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
        )
        page._delete_selected_library_projects()
        assert Path(hub_project_dir / "junk-1.2byteproj").is_file()
        payload = json.loads(settings.read_text(encoding="utf-8"))
        assert payload["recent_projects"]
        assert page._library_selected_paths  # 取消不清空选择
    finally:
        page.close_page()


def test_list_view_rows_checkable_in_manage_mode(tmp_path, monkeypatch, hub_project_dir):
    page, _settings = _hub_page(tmp_path, monkeypatch, hub_project_dir, [
        {"name": "row-project", "cues": 1, "media": "a.mp4"},
    ])
    try:
        app = QApplication.instance()
        page._set_project_library_view("list")
        rows = list(page._hub_row_widgets)
        assert rows and not rows[0].isCheckable()
        page._set_library_manage_mode(True)
        app.processEvents()
        rows = list(page._hub_row_widgets)
        assert rows[0].isCheckable()
        rows[0].click()
        assert rows[0].isChecked()
        assert page._library_selected_paths
    finally:
        page.close_page()
