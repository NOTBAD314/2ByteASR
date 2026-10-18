"""2026-10-17: the online glossary inside the real term library page.

Network calls are replaced by fakes; the learned-terms file, the downloads
folder, the browser and Explorer are redirected. Exercises: open the
「线上词库」 tab, preview, install into a new library, then submit a library
through GitCode (the redesign of the same day made the hub a tab with cards).
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
    panel = page.hub_panel
    assert page.page_stack.currentWidget() is page.hub_page and page.hub_tab_button.isChecked()
    _wait(lambda: len(panel.cards) == 1)
    card = panel.cards[0]
    assert card.title.text() == "原神（至冬 7.x）" and "GitCode" in panel.source.text()
    assert "1" in page.hub_tab_button.count()  # the tab shows how many community libraries exist
    assert card.primary.isEnabled() and not card.remove_button.isVisibleTo(card)
    card.primary.click()
    _wait(lambda: panel.preview is not None)
    preview = panel.preview
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
    card = panel.cards[0]
    assert card.status == "installed" and card.remove_button.isVisibleTo(card)
    assert card.status_pill.text() in {"✓ 已安装", "✓ Installed"}


def _library(page, name, rows=()):
    """A personal library made in the page, its rows confirmed by the user.
    ``rows``: (from, to, category[, origin]); origin 用户整理 = heard in real audio."""
    page.game_input.setText(name)
    page.create_game()
    APP.processEvents()
    key = page._library_key()
    if rows:
        payload = legacy.load_learned_term_payload()
        payload["games"].setdefault(key, {"game": name, "mappings": []})["mappings"] = [
            {"from": row[0], "to": row[1], "category": row[2], "confirmed": True,
             "provenance": legacy.TERM_PROVENANCE_USER_CONFIRMED, "origin": row[3] if len(row) > 3 else "手动"}
            for row in rows]
        legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    page._notify_library_changed()  # what every in-app writer does after adding terms
    page.refresh_current_game()
    return key


def _redirect_submit(monkeypatch, tmp_path):
    opened, revealed = [], []
    monkeypatch.setattr(hub_ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    monkeypatch.setattr(hub_ui, "_downloads_folder", lambda: tmp_path / "Downloads")
    monkeypatch.setattr(hub_ui, "_reveal", revealed.append)
    return opened, revealed


def _source(widget):
    return widget._i18n_bindings["text"][0]


def test_submit_exports_the_cleaned_file_and_opens_gitcode(page, tmp_path, monkeypatch):
    opened, revealed = _redirect_submit(monkeypatch, tmp_path)
    _library(page, "洛克王国：世界", [("迪莫", "迪莫", "角色"), ("迪毛", "迪莫", "角色")])
    assert page.submit_terms.isEnabled()  # the share button needs confirmed terms
    page.submit_terms.click()
    sheet = page._hub_submit
    # The share button beside a library's title goes straight to its content.
    assert sheet.step == 1 and sheet.library.game == "洛克王国：世界" and len(sheet.rows) == 2
    assert [chip.state for chip in sheet.step_chips] == ["done", "on", "todo"]
    sheet.review_next.click()
    assert sheet.step == 2
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


def test_submit_from_the_hub_page_starts_by_choosing_a_library(page):
    # 2026-10-18: the old sheet silently took the library last selected on 我的词库.
    empty = _library(page, "新游戏")
    rock = _library(page, "洛克王国：世界", [("迪莫", "迪莫", "角色"), ("迪毛", "迪莫", "角色")])
    genshin = _library(page, "原神", [("芙宁娜", "芙宁娜", "角色")])
    page.hub_button.click()
    page.hub_panel.submit_button.click()
    sheet = page._hub_submit
    assert sheet.step == 0 and _source(sheet.title) == "投稿到线上词库"
    choices = {choice.library.key: choice for choice in sheet.library_choices}
    assert {rock, genshin} <= set(choices)
    assert choices[genshin].radio.isChecked()            # the library open on 我的词库 is preselected
    if empty in choices:
        assert not choices[empty].radio.isEnabled()      # nothing confirmed yet
    QTest.mouseClick(choices[rock], Qt.MouseButton.LeftButton)   # the whole row is the target
    assert choices[rock].radio.isChecked() and choices[rock].property("selected") is True
    sheet.choose_next.click()
    assert sheet.step == 1 and sheet.loaded_key == rock
    assert {item.pair for item in sheet.rows} == {("迪莫", "迪莫"), ("迪毛", "迪莫")}
    sheet.step_chips[0].clicked.emit()                   # a done step goes back
    assert sheet.step == 0 and choices[rock].radio.isChecked()


def test_review_says_each_kind_once_and_unticked_rows_stay_home(page, tmp_path, monkeypatch):
    opened, _revealed = _redirect_submit(monkeypatch, tmp_path)
    _library(page, "洛克王国：世界", [
        ("迪莫", "迪莫", "角色"), ("迪毛", "迪莫", "角色", "用户整理"), ("火深", "火神", "宠物", "用户整理"),
        ("雷吉", "雷姬", "宠物"), ("史来姆", "史莱姆", "宠物"), ("史来姆", "史莱母", "宠物")])
    page.submit_terms.click()
    sheet = page._hub_submit
    codes = [group.code for group in sheet.groups]
    assert codes[0] == "conflict" and codes.count("short_cjk") == 1
    assert len(sheet.notices) == len(sheet.groups)        # one notice per kind, not one line per rule
    short, show, bulk = next(notice for notice in sheet.notices if notice[0].code == "short_cjk")
    assert short.count == 3 and short.verified == 2
    ticks = {item.pair: item.ticked for item in sheet.rows}
    assert ticks[("史来姆", "史莱姆")] is False and ticks[("史来姆", "史莱母")] is False  # blocked rows start unticked
    assert ticks[("迪毛", "迪莫")] is True                 # a warning does not stop the upload
    assert sheet.rows[0].blocked and sheet.review_next.isEnabled()

    conflict = [item for item in sheet.rows if item.blocked]
    for item in conflict:
        item.check.setCheckState(Qt.CheckState.Checked)
    _wait(lambda: not sheet.review_next.isEnabled())       # both conflicting rules ticked: blocked again
    assert sheet.review_status.isVisibleTo(sheet.sheet.frame)
    next(item for item in conflict if item.pair[1] == "史莱母").check.setCheckState(Qt.CheckState.Unchecked)
    _wait(lambda: sheet.review_next.isEnabled())           # one of the two is fine on its own

    bulk.click()                                           # 都不上传
    assert all(not item.ticked for item in sheet.rows if item.pair in set(short.keys))
    assert _source(bulk) == "都上传"
    show.click()                                           # 只看这 3 条
    shown = {item.pair for index, item in enumerate(sheet.rows) if not sheet.table.isRowHidden(index)}
    assert shown == set(short.keys)
    assert _source(show) == "显示全部"

    sheet.review_next.click()
    assert sheet.step == 2
    sheet.consent.setChecked(True)
    sheet.export_button.click()
    files = list((tmp_path / "Downloads").glob("2byteasr-glossary-*.json"))
    document = json.loads(files[0].read_text("utf-8"))
    assert {(row["from"], row["to"]) for row in document["mappings"]} == {("迪莫", "迪莫"), ("史来姆", "史莱姆")}
    assert opened == []                                    # export only: no page opened


def test_hub_explains_that_it_is_not_published_yet(page, monkeypatch):
    def unpublished(**_kwargs):
        raise hub.HubError("线上词库还没有发布")
    monkeypatch.setattr(hub, "fetch_catalog", unpublished)
    page.hub_button.click()
    panel = page.hub_panel
    _wait(lambda: "还没有上线" in panel.status.text() or "not online" in panel.status.text().lower())
    assert panel.cards == [] and panel.submit_button.isEnabled()
