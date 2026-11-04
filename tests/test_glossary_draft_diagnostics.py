"""Storage ownership and truthful preview boundaries for normal glossary forms."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QWidget
import subtitle_core as legacy
from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog
from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry, snapshot_glossaries
from twobyteasr.recognition.content_scene import ContentScene
from twobyteasr.glossary.glossary_diagnostics import diagnose_sentence

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
        return legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids']

    def _save_glossary_settings(self):
        pass

    def _refresh_content_choices(self):
        pass


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, 'LEARNED_TERMS_PATH', str(tmp_path / 'terms.json'))
    monkeypatch.setattr(legacy, 'load_game_profiles', lambda: {})
    monkeypatch.setattr(legacy, 'RUNTIME_SETTINGS', {'glossary': {'enabled_glossary_ids': []}})
    owner = Owner()
    dialog = TermLibraryDialog(owner, page_mode=True)
    owner.resize(1300, 1000)
    dialog.resize(1250, 900)
    owner.show()
    dialog.show()
    yield dialog
    if dialog._task_manager:
        dialog._task_manager.shutdown(wait_ms=300)
    dialog.close()
    owner.close()


def create(page, name):
    page.game_input.setText(name)
    page.create_game()
    APP.processEvents()
    page.refresh_current_game()


def confirm_pending(page, label='保存并继续'):
    def click():
        message = page.pending_draft_dialog
        QTest.mouseClick(next(button for button in message.buttons() if button.text() == label), Qt.LeftButton)
    QTimer.singleShot(10, click)


def test_pending_quick_input_commits_even_alias_editor_had_focus(page):
    create(page, '领域一')
    page.term_editor.setText('ZeRo7')
    page.term_alias_editor.setText('阿七')
    page.term_alias_editor.setFocus()
    before = snapshot_glossaries(legacy, [page._library_key()])
    confirm_pending(page)
    assert page.prepare_for_task()
    after = snapshot_glossaries(legacy, [page._library_key()])
    assert not page.has_pending_edits()
    assert before.digest != after.digest
    assert any(term.canonical == 'ZeRo7' and '阿七' in term.aliases for term in after.libraries[0].terms)


def test_pending_default_save_does_not_reenter_or_create_nested_dialog(page):
    create(page, '领域一')
    page.term_editor.setText('ZeRo7')
    page.term_alias_editor.setText('阿七')
    observed = []
    def reenter_then_default_save():
        first = page.pending_draft_dialog
        observed.append(page.prepare_for_task())
        observed.append(page.pending_draft_dialog is first)
        QTest.keyClick(first, Qt.Key_Return)
    QTimer.singleShot(10, reenter_then_default_save)
    assert page.prepare_for_task()
    assert observed == [False, True]
    assert page.pending_draft_dialog is None
    assert len(legacy.learned_mappings_for_game(page._library_key())) == 2


def test_pending_draft_keeps_original_library_when_browser_switches(page):
    create(page, '领域一')
    first = page._library_key()
    page.term_editor.setText('ZeRo7')
    page.term_alias_editor.setText('阿七')
    create(page, '领域二')
    assert page._library_key() != first
    assert page.add_single_term()
    assert any(row['from'] == '阿七' for row in legacy.learned_mappings_for_game(first))
    assert not legacy.learned_mappings_for_game(page._library_key())


def test_failed_pending_save_retains_input_and_blocks_snapshot(page, monkeypatch):
    create(page, '领域一')
    page.term_editor.setText('ZeRo7')
    page.term_alias_editor.setText('阿七')
    def denied(*args, **kwargs):
        raise OSError('controlled disk error')
    monkeypatch.setattr(legacy, 'add_learned_mapping', denied)
    confirm_pending(page)
    assert not page.prepare_for_task()
    assert page.term_editor.text() == 'ZeRo7'
    assert page.term_alias_editor.text() == '阿七'


def test_unfocused_edit_save_is_actual_pending_commit(page):
    create(page, '领域一')
    legacy.add_learned_mapping(page._library_key(), '阿七', 'old7')
    page._show_edit_sheet(legacy.learned_mappings_for_game(page._library_key())[0])
    page.edit_canonical.setText('ZeRo7')
    page.edit_canonical.setFocus()
    confirm_pending(page)
    assert page.prepare_for_task()
    assert any(row['from'] == '阿七' and row['to'] == 'ZeRo7'
               for row in legacy.learned_mappings_for_game(page._library_key()))


def test_association_preview_blocks_conflict_without_merging_canonical(page):
    create(page, '领域一')
    legacy.add_learned_mapping(page._library_key(), '阿七', 'old7')
    page._show_association_sheet()
    page.association_alias.setText('阿七')
    page.association_target.setCurrentText('ZeRo7')
    assert not page.association_save_button.isEnabled()
    assert '冲突' in page.association_preview.text()
    assert [row['to'] for row in legacy.learned_mappings_for_game(page._library_key())] == ['old7']
    page.association_dialog.reject()


def test_diagnostics_distinguish_preview_batch_missing_alias_reference_context_and_stale():
    browsed = GlossarySnapshot((GlossaryLibrary('game', '领域一', '2',
        (TermEntry('ZeRo7', ('阿七',), category='选手 ID'), TermEntry('Hero9')), ('OnlyReference',)),))
    empty = GlossarySnapshot()
    result = diagnose_sentence('阿七上场', browsed, empty)
    assert result['preview'].text == 'ZeRo7上场' and result['actual'].text == '阿七上场'
    assert 'library_not_enabled' in dict(result['reasons'])
    assert 'term_missing' in dict(diagnose_sentence('阿七', browsed, browsed, expected_canonical='Missing')['reasons'])
    assert 'alias_unlinked' in dict(diagnose_sentence('另一个昵称', browsed, browsed, expected_canonical='Hero9')['reasons'])
    assert 'reference_only' in dict(diagnose_sentence('参考', browsed, browsed, expected_canonical='OnlyReference')['reasons'])
    assert 'snapshot_changed' in dict(diagnose_sentence('阿七', browsed, browsed, task_snapshot=empty)['reasons'])
    ordinary = diagnose_sentence('小时候喜欢看阿七动画', browsed, browsed, scene=ContentScene())
    assert ordinary['actual'].text == '小时候喜欢看阿七动画'
    assert 'context_filtered' in dict(ordinary['reasons'])
    conflicted = GlossarySnapshot((GlossaryLibrary('game', '领域一', '2',
        (TermEntry('First', ('重名',)), TermEntry('Second', ('重名',)),
         TermEntry('ZeRo7', ('阿七',)))),))
    assert 'ambiguous' not in dict(diagnose_sentence('阿七上场', conflicted, conflicted)['reasons'])
    assert 'ambiguous' in dict(diagnose_sentence('重名上场', conflicted, conflicted)['reasons'])


def test_studio_local_preview_keeps_ordinary_topic_and_original_alias_span():
    from twobyteasr.studio.studio_text_tools import glossary_occurrences
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    snapshot = GlossarySnapshot((GlossaryLibrary('game', '领域一', '2',
        (TermEntry('ZeRo7', ('阿七',), category='选手 ID'),),
        profile_json='{"identity":"game"}'),))
    project = SubtitleProject(media=StudioMedia(path='isolated.mp4'), cues=[
        StudioCue('player', 100, 1000, '阿七上场了'),
        StudioCue('ordinary', 1000, 2000, '小时候喜欢看阿七动画')])
    hits = glossary_occurrences(project, ['player', 'ordinary'], snapshot=snapshot)
    assert [(hit.cue_id, hit.original, hit.replacement, hit.span) for hit in hits] == [
        ('player', '阿七', 'ZeRo7', (0, 2))]
