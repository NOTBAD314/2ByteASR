"""2026-10-25 user report: terms could not hold symbols, built-in libraries could not be deleted.

Saving a term ran the subtitle cleanup, which turned 漂泊者·男 into 漂泊者男 and
Re:Zero into ReZero without saying so. Terms now keep what the user typed; a
confirmed spelling with symbols survives the Chinese cleanup of a run, and the
cleanup's symbol-free spelling reads as the term again. Built-in libraries
(原神, 明日方舟 …) can be deleted from the list and restored from 新建.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QWidget

import subtitle_core as legacy
from twobyteasr.glossary import glossary_hub as hub
from twobyteasr.glossary.terminology import (
    GlossaryLibrary, GlossarySnapshot, TermEntry, TermResolver)
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context

APP = QApplication.instance() or QApplication([])

SYMBOL_TERMS = ["漂泊者·男", "Re:Zero", "洛克王国：世界", "S.A.T.", "Mr. X", "《鸣潮》", "(笑)", "C-4", "A&B"]


@pytest.fixture
def terms_file(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "2ByteASR" / "terms.json"))
    return tmp_path


def _snapshot(*terms):
    return GlossarySnapshot((GlossaryLibrary("lib", "测试", "1", tuple(terms)),))


def test_saved_terms_keep_their_symbols(terms_file):
    for value in SYMBOL_TERMS:
        assert legacy.add_learned_mapping("符号", value, value) is True
    assert legacy.add_learned_mapping("符号", "漂泊者难", "漂泊者·男") is True
    assert legacy.add_learned_mapping("符号", "  A \n  B\u200b  ", "  A \n  B\u200b  ") is True
    rows = {(row["from"], row["to"]) for row in legacy.learned_mappings_for_game("符号")}
    assert {(value, value) for value in SYMBOL_TERMS} <= rows
    assert ("漂泊者难", "漂泊者·男") in rows
    assert ("A B", "A B") in rows


def test_editing_a_term_keeps_its_symbols(terms_file):
    legacy.add_learned_mapping("符号", "漂泊者男", "漂泊者男")
    assert legacy.edit_learned_mapping("符号", ("漂泊者男", "漂泊者男"), "漂泊者·男", "漂泊者·男") is True
    assert [(row["from"], row["to"]) for row in legacy.learned_mappings_for_game("符号")] == [
        ("漂泊者·男", "漂泊者·男")]


def test_symbol_free_spelling_only_for_symbols_inside_the_term():
    from twobyteasr.glossary.terminology import symbol_free_spelling
    assert symbol_free_spelling("漂泊者·男") == "漂泊者男"
    assert symbol_free_spelling("Re:Zero") == "ReZero"
    assert symbol_free_spelling("Mr. X") == "Mr X"
    for value in ("《鸣潮》", "(笑)", "S.A.T.", "C-4", "A&B", "芙宁娜", "·男"):
        assert symbol_free_spelling(value) == ""


def test_the_cleaned_spelling_reads_as_the_term_again():
    resolver = TermResolver(_snapshot(TermEntry("漂泊者·男"), TermEntry("Re:Zero")))
    assert resolver.resolve("我是漂泊者男").text == "我是漂泊者·男"
    assert resolver.resolve("看了rezero").text == "看了Re:Zero"
    assert resolver.resolve("我是漂泊者·男").text == "我是漂泊者·男"
    assert not resolver.conflicts


def test_symbols_at_the_ends_apply_only_through_an_alias():
    assert TermResolver(_snapshot(TermEntry("《鸣潮》"))).resolve("玩鸣潮").text == "玩鸣潮"
    resolver = TermResolver(_snapshot(TermEntry("《鸣潮》", ("鸣潮",))))
    assert resolver.resolve("玩鸣潮").text == "玩《鸣潮》"
    assert resolver.resolve("玩《鸣潮》").text == "玩《鸣潮》"


def test_a_written_out_term_wins_over_the_symbol_free_reading():
    resolver = TermResolver(_snapshot(TermEntry("洛克王国：世界"), TermEntry("洛克王国世界")))
    assert resolver.resolve("洛克王国世界").text == "洛克王国世界"
    assert not resolver.conflicts


def test_run_cleanup_keeps_confirmed_terms_written_with_symbols():
    from twobyteasr.subtitle_rules.text_rules import clean_subtitle_text, normalize_output_text
    snapshot = _snapshot(TermEntry("漂泊者·男"), TermEntry("S.A.T."), TermEntry("Mr. X"))
    assert clean_subtitle_text("漂泊者·男，你好。") == "漂泊者男你好"
    with activate_runtime_context(RuntimeContext(enable_domain_terms=True, glossary_snapshot=snapshot)):
        assert clean_subtitle_text("漂泊者·男，你好。") == "漂泊者·男你好"
        assert clean_subtitle_text("队长 S.A.T. 来了") == "队长 S.A.T. 来了"
        assert clean_subtitle_text("找 mr. x 吧") == "找 mr. x 吧"
        assert clean_subtitle_text("别的·符号：照删") == "别的符号照删"
        assert normalize_output_text("（漂泊者·男）说：好") == "漂泊者·男说好"
        # What a recognition run does: confirmed terms, cleanup, then the final pass.
        resolver = TermResolver(snapshot)
        cleaned = normalize_output_text(resolver.resolve("漂泊者男，来了。").text)
        assert resolver.resolve(cleaned).text == "漂泊者·男来了"
    with activate_runtime_context(RuntimeContext(enable_domain_terms=False, glossary_snapshot=snapshot)):
        assert clean_subtitle_text("漂泊者·男") == "漂泊者男"


# ---------------------------------------------------------------- built-in libraries

class Owner(QWidget):
    def __init__(self):
        super().__init__()
        self.legacy = legacy
        self.game_box = QComboBox()
        self.game_box.setEditable(True)
        self.terms = QCheckBox()
        self.term_hint = QLabel()

    def _enabled_glossary_ids(self):
        return list(legacy.RUNTIME_SETTINGS.setdefault("glossary", {}).get("enabled_glossary_ids", []))

    def _save_glossary_settings(self):
        pass

    def _refresh_content_choices(self):
        pass


@pytest.fixture
def make_page(terms_file, monkeypatch):
    from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog
    profiles = {"原神": {"terms": [{"canonical": "芙宁娜"}, {"canonical": "那维莱特"}]}}
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: profiles)
    monkeypatch.setattr(legacy, "load_runtime_game_history", lambda: [])
    monkeypatch.setattr(legacy, "save_runtime_game_history", lambda _name: None, raising=False)
    monkeypatch.setattr(legacy, "RUNTIME_SETTINGS", {"glossary": {"enabled_glossary_ids": ["原神"]}})
    monkeypatch.setattr(hub, "fetch_catalog", lambda **_kwargs: (_ for _ in ()).throw(hub.HubError("offline")))
    pages = []

    def make():
        owner = Owner()
        page = TermLibraryDialog(owner, page_mode=True)
        page.resize(1280, 900)
        page.show()
        APP.processEvents()
        pages.append((page, owner))
        return page

    yield make
    for page, owner in pages:
        if page._task_manager:
            page._task_manager.shutdown(wait_ms=300)
        page.close()
        owner.close()


def _names(page):
    return [str(page.game_list.item(i).data(0x0100)) for i in range(page.game_list.count())]


def _select(page, name):
    item = next(page.game_list.item(i) for i in range(page.game_list.count())
                if page.game_list.item(i).data(0x0100) == name)
    page.game_list.setCurrentItem(item)
    APP.processEvents()
    page.refresh_current_game()
    APP.processEvents()
    return item


def _confirm_delete(page):
    sheet = page._del_game_sheet
    assert sheet is not None and sheet.isVisibleTo(page)
    text = " ".join(label.text() for label in sheet.findChildren(QLabel))
    button = next(b for b in sheet.findChildren(QPushButton) if b.text() == "删除")
    button.click()
    APP.processEvents()
    return text


def test_builtin_library_can_be_deleted_and_restored(make_page):
    page = make_page()
    assert "原神" in _names(page)
    _select(page, "原神")
    assert page._game_identity("原神") in page.protected_game_ids
    assert page.delete_game_button.isEnabled()
    assert not page.rename_game_button.isEnabled()
    legacy.add_learned_mapping(page._library_key("原神"), "芙宁那", "芙宁娜")
    page.delete_current_game()
    text = _confirm_delete(page)
    assert "软件自带" in text and "1 条" in text and "恢复自带词库" in text
    assert "原神" not in _names(page)
    assert legacy.is_runtime_game_profile_hidden("原神")
    assert legacy.learned_mappings_for_game("原神") == []
    assert legacy.load_game_profiles()["原神"]["terms"][0]["canonical"] == "芙宁娜"
    assert "原神" not in legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"]

    page.sidebar_new_button.click()
    APP.processEvents()
    assert page.restore_builtin_button.isVisibleTo(page)
    assert "1" in page.restore_builtin_button.text()
    page.restore_builtin_button.click()
    APP.processEvents()
    restore = next(b for b in page.restore_builtin_popup.findChildren(QPushButton) if b.text() == "原神")
    restore.click()
    APP.processEvents()
    assert "原神" in _names(page) and page.state["game"] == "原神"
    assert not legacy.is_runtime_game_profile_hidden("原神")
    assert legacy.hidden_runtime_game_profile_names() == []


def test_right_click_on_a_library_offers_delete(make_page):
    page = make_page()
    page.sidebar_new_button.click()
    page.game_input.setText("我的词库")
    page.add_game_button.click()
    APP.processEvents()
    item = _select(page, "我的词库")
    row = page.game_list.itemWidget(item)
    row.menu_requested.emit(row.mapToGlobal(row.rect().center()))
    APP.processEvents()
    menu = page._game_menu
    labels = [action.text() for action in menu.actions() if action.text()]
    assert labels == ["改名…", "导出词库", "删除词库…"]
    menu.hide()
    next(a for a in menu.actions() if a.text() == "删除词库…").trigger()
    APP.processEvents()
    _confirm_delete(page)
    assert "我的词库" not in _names(page)
    _select(page, "原神")
    row = page.game_list.itemWidget(page.game_list.currentItem())
    row.menu_requested.emit(row.mapToGlobal(row.rect().center()))
    APP.processEvents()
    assert [a.text() for a in page._game_menu.actions() if a.text()] == ["导出词库", "删除词库…"]
    page._game_menu.hide()


def test_deleted_builtin_stays_deleted_after_reopening(make_page, monkeypatch):
    """Opening the page migrates user-verified profile rows; that must not bring a deleted library back."""
    profiles = {"原神": {"terms": [{"canonical": "芙宁娜"}]},
                "洛克王国：世界": {"terms": [{"canonical": "迪莫", "aliases": ["迪摩"], "source": "user_verified"},
                                       {"canonical": "喵喵", "source": "builtin"}]}}
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: profiles)
    page = make_page()
    key = page._library_key("洛克王国：世界")
    migrated = legacy.learned_mappings_for_game(key)
    assert migrated and all(row["verification"] == "user_profile_migration" for row in migrated)
    legacy.add_learned_mapping(key, "洛克", "洛克", category="其他")
    _select(page, "洛克王国：世界")
    page.delete_current_game()
    text = _confirm_delete(page)
    assert "1 条" in text  # only the row the user added; migrated rows come back with the library
    reopened = make_page()  # opening again runs the migration again
    assert legacy.learned_mappings_for_game(key)  # the profile rows are back in the file …
    assert "洛克王国：世界" not in _names(reopened)  # … but the library stays deleted
    assert all(row["name"] != "洛克王国：世界" for row in legacy.glossary_catalog())
    reopened.restore_builtin_library("洛克王国：世界")
    assert "洛克王国：世界" in _names(reopened)
    assert {row["to"] for row in legacy.learned_mappings_for_game(key)} == {"迪莫"}
