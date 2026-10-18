"""2026-10-17 term library redesign (plan 2026-10-17-glossary-page-redesign).

Two tabs (我的词库 / 线上词库), one row of main actions per library with the
rarely used controls in menus, a selection bar, one switch for the batch,
start cards for an empty library and a one-time "share this library" prompt.
The learned-terms file and the hub cache live in a temporary folder.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QWidget

import subtitle_core as legacy
from twobyteasr import glossary_hub as hub
from twobyteasr.main_ui_glossary import TermLibraryDialog

APP = QApplication.instance() or QApplication([])


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
def make_page(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "2ByteASR" / "terms.json"))
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: {})
    monkeypatch.setattr(legacy, "save_runtime_game_history", lambda _name: None, raising=False)
    monkeypatch.setattr(legacy, "RUNTIME_SETTINGS", {"glossary": {}})
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


def _new_library(page, name="洛克王国：世界", rows=0):
    page.sidebar_new_button.click()
    assert page.new_library_panel.isVisibleTo(page)
    page.game_input.setText(name)
    page.add_game_button.click()
    APP.processEvents()
    key = page._library_key()
    for index in range(rows):
        legacy.add_learned_mapping(key, f"词{index}", f"词{index}", category="角色")
    page._notify_library_changed()
    page.refresh_current_game()
    APP.processEvents()
    return key


def test_two_tabs_show_library_and_community_counts(make_page, monkeypatch):
    catalog = hub.Catalog({"schema": 1, "serial": 1, "libraries": [
        {"id": "a", "game": "原神", "version": 1, "rows": 3}, {"id": "b", "game": "异环", "version": 1, "rows": 2}]},
        "GitCode", 1.0)
    monkeypatch.setattr(hub, "cached_catalog", lambda *_args, **_kwargs: catalog)
    page = make_page()
    assert page.my_tab_button.isChecked() and page.page_stack.currentWidget() is page.mine_page
    assert page.my_tab_button.count() == str(page.game_list.count())
    assert "2" in page.hub_tab_button.count() and page.hub_tab_button.note() == ""
    page.hub_tab_button.click()
    assert page.page_stack.currentWidget() is page.hub_page and page.hub_panel is not None
    page.my_tab_button.click()
    assert page.page_stack.currentWidget() is page.mine_page
    page.open_glossary_hub()  # older entry point (start cards, MCP and audits call it)
    assert page.page_stack.currentWidget() is page.hub_page and page.hub_tab_button.isChecked()


def test_new_library_form_opens_from_the_sidebar_and_closes_after_create(make_page):
    page = make_page()
    assert not page.new_library_panel.isVisibleTo(page)
    _new_library(page)
    assert not page.new_library_panel.isVisibleTo(page)
    assert page.state["game"] == "洛克王国：世界"


def test_rarely_used_actions_live_in_menus(make_page, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", ""))
    page = make_page()
    _new_library(page, rows=1)
    for button in (page.ai_update_button, page.ai_full_button, page.smart_build_button,
                   page.ai_batch_button, page.ai_history_button, page.ai_service_combo, page.ai_model_combo):
        assert button.window() is page.ai_popup
    for button in (page.rename_game_button, page.ai_note_button, page.export_terms, page.delete_game_button):
        assert button.window() is page.more_popup
    assert not page.more_popup.isVisible()
    page.more_button.click()
    assert page.more_popup.isVisible()
    page.export_terms.click()  # the save dialog is stubbed: only the popup is under test
    assert not page.more_popup.isVisible()
    page.ai_menu_button.click()
    assert page.ai_popup.isVisible()
    page.ai_popup.hide()


def test_selection_bar_appears_only_with_selected_terms(make_page):
    page = make_page()
    _new_library(page, rows=3)
    assert not page.selection_bar.isVisibleTo(page)
    model = page.listing.model()
    page.listing.selectionModel().select(
        model.index(0, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    APP.processEvents()
    assert page.selection_bar.isVisibleTo(page)
    assert "1" in page.selection_label.text()
    assert page.remove_terms.isEnabled() and page.remove_terms.isVisibleTo(page)
    assert not page.bulk_confirm.isVisibleTo(page)  # a confirmed term is not a reference
    page.clear_selection.click()
    APP.processEvents()
    assert not page.selection_bar.isVisibleTo(page)


def test_one_switch_adds_and_removes_the_library_for_this_batch(make_page):
    page = make_page()
    key = _new_library(page, rows=1)
    assert page.use_game is page.batch_toggle and page.use_game.isEnabled()
    assert not page.use_game.isChecked()
    page.use_game.click()
    assert key in page.owner._enabled_glossary_ids() and page.use_game.isChecked()
    assert page.owner.terms.isChecked()
    page.use_game.click()
    assert key not in page.owner._enabled_glossary_ids() and not page.use_game.isChecked()


def test_empty_library_shows_start_cards_and_the_hub_card_opens_the_tab(make_page):
    page = make_page()
    _new_library(page, rows=0)
    assert page.listing_empty.isVisibleTo(page) and page.start_cards.isVisibleTo(page)
    assert page.listing_empty_build.isVisibleTo(page)
    page.listing_empty_hub.click()
    assert page.page_stack.currentWidget() is page.hub_page


def test_share_prompt_shows_once_for_a_large_own_library(make_page, monkeypatch):
    catalog = hub.Catalog({"schema": 1, "serial": 1, "libraries": [{"id": "y", "game": "原神", "version": 1}]},
                          "GitCode", 1.0)
    monkeypatch.setattr(hub, "cached_catalog", lambda *_args, **_kwargs: catalog)
    page = make_page()
    _new_library(page, name="鸣潮", rows=hub.SHARE_PROMPT_MIN_ROWS)
    assert page.share_nudge.isVisibleTo(page) and "50" in page.share_nudge_text.text()
    page.share_nudge_later.click()
    assert not page.share_nudge.isVisibleTo(page)
    page.refresh_current_game()
    assert not page.share_nudge.isVisibleTo(page)
    again = make_page()
    item = next(again.game_list.item(i) for i in range(again.game_list.count())
                if again.game_list.item(i).data(0x0100) == "鸣潮")
    again.game_list.setCurrentItem(item)
    again.refresh_current_game()
    assert not again.share_nudge.isVisibleTo(again)


def test_share_prompt_stays_hidden_for_small_libraries_and_games_already_online(make_page, monkeypatch):
    catalog = hub.Catalog({"schema": 1, "serial": 1, "libraries": [{"id": "x", "game": "鸣潮", "version": 1}]},
                          "GitHub", 1.0)
    monkeypatch.setattr(hub, "cached_catalog", lambda *_args, **_kwargs: catalog)
    page = make_page()
    _new_library(page, name="鸣潮", rows=hub.SHARE_PROMPT_MIN_ROWS)
    assert not page.share_nudge.isVisibleTo(page)
    _new_library(page, name="异环", rows=hub.SHARE_PROMPT_MIN_ROWS - 1)
    assert not page.share_nudge.isVisibleTo(page)
    monkeypatch.setattr(hub, "cached_catalog", lambda *_args, **_kwargs: None)  # offline, never fetched
    _new_library(page, name="鸣潮二", rows=hub.SHARE_PROMPT_MIN_ROWS)
    assert not page.share_nudge.isVisibleTo(page)


def test_share_prompt_state_survives_in_the_hub_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "terms.json"))
    assert not hub.share_prompt_done("lib-1")
    hub.mark_share_prompt_done("lib-1")
    hub.mark_share_prompt_done("lib-1")
    assert hub.share_prompt_done("lib-1") and not hub.share_prompt_done("lib-2")
    assert (tmp_path / "glossary-hub" / "prompts.json").is_file()


def test_learning_notice_expands_on_request(make_page):
    page = make_page()
    assert page.learning_box.isHidden()
    page._toggle_learning_list()
    assert not page.learning_box.isHidden() and page.learning_toggle.text() in {"收起", "Collapse"}
    page._toggle_learning_list()
    assert page.learning_box.isHidden()
