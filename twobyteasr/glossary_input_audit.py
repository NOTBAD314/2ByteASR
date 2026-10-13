"""Opt-in normal-window local input audit over a fresh isolated glossary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .terminology import snapshot_glossaries, TermResolver

    output = Path(output)
    restoring = os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-input-restore'
    receipt = output / ('input-restore-result.json' if restoring else 'input-result.json')
    result = dict(passed=False, checks=[], screenshots=[], pid=os.getpid(),
                  identity=load_build_identity().to_dict(), scope='normal UI; isolated fresh glossary; no AI/ASR/media',
                  ime_scope='Qt preedit/commit event path; human physical IME is not certified')

    def check(name, passed, detail=None):
        result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))
        if not passed:
            raise AssertionError(name + ': ' + str(detail))

    def settle():
        QApplication.instance().processEvents()
        QTest.qWait(120)

    def click(button):
        check('visible enabled action ' + button.text(), button.isVisible() and button.isEnabled())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        settle()

    def shot(name):
        settle()
        _capture(window, output / (name + '.png'))
        result['screenshots'].append(name + '.png')

    def write():
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

    def run():
        try:
            store = Path(window.legacy.LEARNED_TERMS_PATH).resolve()
            check('real storage stays under the isolated root', store.is_relative_to(output), str(store))
            window._manage_terms()
            settle()
            page = window.term_library_page._ensure_library()
            if not restoring:
                page.game_input.setText('本地输入验收')
                click(page.add_game_button)
            library_id = window.legacy.resolve_glossary_identity('本地输入验收')
            check('stable library ID exists', bool(library_id), library_id)
            page.add_game_item('本地输入验收', library_id=library_id, select=True)
            page.refresh_current_game()
            settle()
            before = snapshot_glossaries(window.legacy, (library_id,))
            if not restoring:
                check('fresh isolated library', not before.canonical_terms, before.summary())
                page.term_alias_editor.setFocus()
                QTest.keyClicks(page.term_alias_editor, 'NoxMist')
                QTest.keyClick(page.term_alias_editor, Qt.Key.Key_Tab)
                check('normal Tab reaches canonical field', page.term_editor.hasFocus())
                QTest.keyClicks(page.term_editor, 'NoX7')
                QTest.keyClick(page.term_editor, Qt.Key.Key_Return)
                settle()
                check('Return saves through original persistence',
                      any(row['from'] == 'NoxMist' and row['to'] == 'NoX7'
                          for row in window.legacy.learned_mappings_for_game(library_id)))
                page.term_editor.setText('Silent Hill')
                click(page.add_term_button)
                # Qt composition carries spaces without generating mappings.
                QApplication.sendEvent(page.term_editor, QInputMethodEvent('夜 星', []))
                check('IME preedit does not write input or database', page.term_editor.text() == '')
                commit = QInputMethodEvent()
                commit.setCommitString('夜星')
                QApplication.sendEvent(page.term_editor, commit)
                check('IME commit waits for explicit save', page.term_editor.text() == '夜星')
                click(page.add_term_button)
                click(page.quick_mapping_button)
                text = '\n'.join(['SkyDust → SkY9', 'MoonAsh -> MooN6', 'StarMist - StaR5',
                    'BlueAsh Blue7', 'RedAsh    Red8', 'GoldAsh\tGoLD2', 'GreenAsh => GreeN3',
                    'common Alpha', 'common Beta', 'Spider-Man', 'one two three',
                    '"Quiet Echo" "QuieT Echo"', 'NoxMist nox7'])
                page.import_editor.setPlainText(text)
                settle()
                check('all seven supported separators preview as valid mappings',
                      all(row['status'] == 'ready' for row in page._import_rows[:7]))
                check('both sides of batch conflict remain unsaved',
                      all(row['status'] == 'conflict' for row in page._import_rows[7:9]))
                check('names with hyphens and ambiguous spaces require review',
                      all(row['status'] == 'invalid' for row in page._import_rows[9:11]))
                check('duplicate case preserves NoX7', page._import_rows[-1]['status'] == 'duplicate'
                      and page._import_rows[-1]['to'] == 'NoX7')
                shot('input-batch-mapping-preview')
                # Edit both reviewed columns in the actual table delegates.
                for column, value in ((1, 'spider'), (2, 'Spider-Man')):
                    cell = page.import_table.item(9, column)
                    page.import_table.scrollToItem(cell)
                    page.import_table.editItem(cell)
                    settle()
                    editor = QApplication.focusWidget()
                    check('table opens editable field', hasattr(editor, 'setText'))
                    editor.setText(value)
                    QTest.keyClick(editor, Qt.Key.Key_Return)
                    settle()
                check('explicit table edit resolves hyphen row', page._import_rows[9]['status'] == 'ready')
                click(page.import_save_button)
                # Existing draft guard saves a normal dual-field draft on
                # batch enable; it never freezes an unsubmitted alias.
                page.term_alias_editor.setText('GhostDust')
                page.term_editor.setText('GhoST8')
                def save_draft():
                    dialog = page.pending_draft_dialog
                    if dialog is None:
                        return
                    button = next(button for button in dialog.buttons() if button.text() == '保存并继续')
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                QTimer.singleShot(150, save_draft)
                click(page.use_game)
                check('draft saved before enable', not page.has_pending_edits())
                check('library enabled for actual batch', library_id in window._enabled_glossary_ids())
                shot('input-normal-save-and-enable')
                page.term_alias_editor.setText('UnsubmittedNebula')
                page.term_editor.setText('NeBula4')
                def keep_draft():
                    dialog = page.pending_draft_dialog
                    if dialog is not None:
                        button = next(button for button in dialog.buttons() if button.text() == '返回编辑')
                        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                QTimer.singleShot(150, keep_draft)
                window.close()
                settle()
                check('close with draft can cancel and keep editing', window.isVisible()
                      and page.term_editor.text() == 'NeBula4' and page.has_pending_edits())
                page.term_alias_editor.clear()
                page.term_editor.clear()
            current = snapshot_glossaries(window.legacy, (library_id,))
            pairs = {(row['from'], row['to']) for row in window.legacy.learned_mappings_for_game(library_id)}
            check('canonical names, case and confirmed aliases survive persistence',
                {('NoxMist', 'NoX7'), ('Silent Hill', 'Silent Hill'), ('SkyDust', 'SkY9'),
                 ('spider', 'Spider-Man'), ('GhostDust', 'GhoST8'), ('夜星', '夜星')} <= pairs, sorted(pairs))
            check('conflicting alias never entered database', not any(source == 'common' for source, _ in pairs))
            expected = 'NoX7 SkY9 MooN6 GhoST8'
            resolved = TermResolver(current).resolve('NoxMist SkyDust MoonAsh GhostDust')
            check('real current snapshot performs replacements', resolved.text == expected, resolved.text)
            check('persisted enabled library restored', library_id in window._enabled_glossary_ids())
            if page.term_try_panel.isHidden():
                click(page.term_try_toggle)
            page.term_try_input.setText('NoxMist SkyDust MoonAsh GhostDust')
            QTest.keyClick(page.term_try_input, Qt.Key.Key_Return)
            settle()
            check('normal visible trial uses actual enabled resolver', expected in page.term_try_result.text(), page.term_try_result.text())
            shot('input-restored-trial' if restoring else 'input-actual-replacement')
            result['snapshot'] = current.summary()
            result['database_sha256'] = hashlib.sha256(store.read_bytes()).hexdigest()
            if restoring:
                previous = json.loads((output / 'input-result.json').read_text('utf8'))
                check('second process restores exact revision and snapshot', current.summary() == previous['snapshot'])
                check('second process database bytes remain unchanged', result['database_sha256'] == previous['database_sha256'])
            else:
                check('saving increments revision and changes snapshot', before.digest != current.digest
                      and before.libraries[0].revision != current.libraries[0].revision)
                check('original frozen snapshot remains empty', not before.canonical_terms)
            from . import blank_project_audit
            result['provider_calls'] = blank_project_audit._provider_calls
            check('zero provider calls', result['provider_calls'] == 0)
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            try:
                shot('input-failure')
            except Exception:
                pass
        window.result_exit_code = 0 if result['passed'] else 1
        write()
        def stopped():
            result['gui_shutdown'] = True
            write()
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()

    QTimer.singleShot(900, run)
