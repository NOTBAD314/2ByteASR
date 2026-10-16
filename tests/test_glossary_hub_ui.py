"""2026-10-17: the online glossary sheets inside the real term library page.

Network calls are replaced by fakes; the learned-terms file, the downloads
folder, the browser and Explorer are redirected. Exercises: open the hub,
preview, install into a new library, then submit a library through GitCode.
"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QWidget

import subtitle_core as legacy
from twobyteasr import glossary_hub as hub
from twobyteasr import glossary_hub_ui as hub_ui
from twobyteasr.main_ui_glossary import TermLibraryDialog

APP = QApplication.instance() or QApplication([])

ENTRY = {"id": "genshin", "game": "原神", "title": "原神（至冬 7.x）", "version": 1, "rows": 3,
         "path": "libraries/genshin.json", "sha256": "0" * 64, "size": 100, "updated": "2026-10-17"}
LIBRARY = {"schema": 1, "id": "genshin", "game": "原神", "mappings": [
    {"from": "芙宁娜", "to": "芙宁娜", "category": "角色"},
    {"from": "福宁娜", "to": "芙宁娜", "category": "角色"},
    {"from": "落地", "to": "跺地", "category": "技能", "verified_audio": True}]}


class Owner(QWidget):
    def __init__(self):
        super().__init__()
        self.legacy = legacy
        self.game_box = QComboBox()
        self.terms = QCheckBox()
        self.term_hint = QLabel()

    def _enabled_glossary_ids(self):
        return []

    def _save_glossary_settings(self):
        pass

    def _refresh_content_choices(self):
        pass


def _wait(condition, timeout_ms=5000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    assert condition()


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "2ByteASR" / "terms.json"))
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: {})
    monkeypatch.setattr(legacy, "RUNTIME_SETTINGS", {"glossary": {}})
    catalog = hub.Catalog({"schema": 1, "serial": 1, "libraries": [ENTRY]}, "GitCode", 1_000_000.0)
    monkeypatch.setattr(hub, "fetch_catalog", lambda **_kwargs: catalog)
    monkeypatch.setattr(hub, "fetch_library", lambda entry, _catalog=None, **_kwargs: json.loads(json.dumps(LIBRARY)))
    owner = Owner()
    page = TermLibraryDialog(owner, page_mode=True)
    page.resize(1200, 850)
    page.show()
    APP.processEvents()
    yield page
    if page._task_manager:
        page._task_manager.shutdown(wait_ms=300)
    page.close()
    owner.close()


def test_hub_lists_previews_and_installs_into_a_new_library(page):
    page.hub_button.click()
    sheet = page._hub_sheet
    _wait(lambda: sheet.table.rowCount() == 1)
    assert sheet.table.item(0, 0).text() == "原神（至冬 7.x）" and "GitCode" in sheet.source.text()
    sheet.table.selectRow(0)
    assert sheet.primary.isEnabled()
    sheet.primary.click()
    _wait(lambda: sheet.preview is not None)
    preview = sheet.preview
    checks = {item.row["from"]: check.checkState() for check, item in preview._checks}
    assert checks == {"芙宁娜": Qt.CheckState.Checked, "福宁娜": Qt.CheckState.Checked,
                      "落地": Qt.CheckState.Unchecked}
    preview.install_button.click()
    APP.processEvents()
    games = legacy.load_learned_term_payload()["games"]
    (key, entry), = games.items()
    assert entry["game"] == "原神" and entry["hub"]["declined"] == ["落地→跺地"]
    assert {(row["from"], row["to"]) for row in entry["mappings"]} == {("芙宁娜", "芙宁娜"), ("福宁娜", "芙宁娜")}
    names = [page.game_list.item(i).data(Qt.ItemDataRole.UserRole + 1) for i in range(page.game_list.count())]
    assert key in names
    assert sheet.table.item(0, 5).text() in {"已安装", "Installed"}


def test_submit_exports_the_cleaned_file_and_opens_gitcode(page, tmp_path, monkeypatch):
    opened, revealed = [], []
    monkeypatch.setattr(hub_ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    monkeypatch.setattr(hub_ui, "_downloads_folder", lambda: tmp_path / "Downloads")
    monkeypatch.setattr(hub_ui, "_reveal", revealed.append)
    page.game_input.setText("洛克王国：世界")
    page.create_game()
    APP.processEvents()
    library_id = page._library_key()
    legacy.add_learned_mapping(library_id, "迪莫", "迪莫", category="角色")
    legacy.add_learned_mapping(library_id, "迪毛", "迪莫", category="角色")
    page.refresh_current_game()
    page.submit_terms.click()
    sheet = page._hub_submit
    assert not sheet.gitcode_button.isEnabled()          # CC0 consent first
    sheet.consent.setChecked(True)
    assert sheet.gitcode_button.isEnabled()
    sheet.author.setText("兔白")
    sheet.gitcode_button.click()
    files = list((tmp_path / "Downloads").glob("2byteasr-glossary-*.json"))
    assert len(files) == 1 and revealed == files
    document = json.loads(files[0].read_text("utf-8"))
    assert document["authors"] == ["兔白"] and len(document["mappings"]) == 2
    assert opened == [hub.ISSUE_PAGES["gitcode"]]
    assert QApplication.clipboard().text().startswith("[投稿] 洛克王国：世界 · 2 条")


def test_hub_explains_that_it_is_not_published_yet(page, monkeypatch):
    def unpublished(**_kwargs):
        raise hub.HubError("线上词库还没有发布")
    monkeypatch.setattr(hub, "fetch_catalog", unpublished)
    page.hub_button.click()
    sheet = page._hub_sheet
    _wait(lambda: "还没有上线" in sheet.status.text() or "not online" in sheet.status.text().lower())
    assert sheet.table.rowCount() == 0 and not sheet.primary.isEnabled()
