"""Canonical reentry and case edits through the actual Qt library forms."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QWidget
import subtitle_core as legacy
from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog
from twobyteasr.glossary.terminology import snapshot_glossaries

APP = QApplication.instance() or QApplication([])


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


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "terms.json"))
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: {})
    monkeypatch.setattr(legacy, "RUNTIME_SETTINGS", {"glossary": {}})
    owner = Owner()
    page = TermLibraryDialog(owner, page_mode=True)
    page.resize(1200, 850)
    page.game_input.setText("选手库")
    page.create_game()
    APP.processEvents()
    yield page
    if page._task_manager:
        page._task_manager.shutdown(wait_ms=300)
    page.close()
    owner.close()


@pytest.mark.parametrize("old,canonical", [("berlin", "BerLIN"), ("s0pp", "S0pp"), ("zhe", "Zhe")])
@pytest.mark.parametrize("action", ["add", "edit"])
def test_forms_persist_case_revision_and_reopen_same_canonical(page, old, canonical, action):
    library_id = page._library_key()
    legacy.add_learned_mapping(library_id, old, old)
    original = snapshot_glossaries(legacy, [library_id])
    page.refresh_current_game()
    if action == "add":
        page.term_editor.setText(canonical)
        page.add_term_button.click()
    else:
        page._show_edit_sheet(legacy.learned_mappings_for_game(library_id)[0])
        page.edit_canonical.setText(canonical)
        page.edit_save_button.click()
    APP.processEvents()
    assert page.term_editor.text() == ""
    assert page._unified_term_rows()[0]["term_text"] == canonical
    reopened = TermLibraryDialog(page.owner, page_mode=True)
    try:
        reopened.add_game_item("选手库", library_id=library_id, select=True)
        reopened.refresh_current_game()
        assert reopened._unified_term_rows()[0]["term_text"] == canonical
        current = snapshot_glossaries(legacy, [library_id])
        assert current.canonical_terms == (canonical,)
        assert current.digest != original.digest
    finally:
        reopened.close()
