"""Normal-entry UI save/enable/restart receipt over an isolated actual store."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .content_scene import resolve_content_scene
    from .service import RunOptions
    from .terminology import TermResolver, snapshot_glossaries
    from .runtime_paths import user_data_root
    output = Path(output)
    restoring = os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-chain-restore'
    receipt = output / ('chain-restore-result.json' if restoring else 'chain-result.json')
    wanted = [('球球', 'CHIOCHOO'), ('奥特曼', 'autumn'), ('星星七号', 'Sable7Alias')]
    result = {'passed': False, 'checks': [], 'screenshots': [], 'pid': os.getpid(),
        'identity': load_build_identity().to_dict(), 'executable': sys.executable,
        'scope': 'normal UI save/enable/close/restart; snapshot-only; no ASR or AI success injected'}

    def check(name, value, detail=None):
        result['checks'].append({'name': name, 'passed': bool(value), 'detail': detail})
        if not value:
            raise AssertionError(f'{name}: {detail}')

    def settle():
        QApplication.processEvents()
        QTest.qWait(120)

    def click(widget):
        page = getattr(getattr(window, 'term_library_page', None), 'library', None)
        scroll = getattr(page, 'library_content_scroll', None)
        if scroll is not None and scroll.isAncestorOf(widget):
            scroll.ensureWidgetVisible(widget, 16, 16)
            settle()
        check('control visible and enabled: ' + widget.text(), widget.isVisible() and widget.isEnabled())
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        settle()

    def enter(widget, text):
        edit = widget.lineEdit() if hasattr(widget, 'lineEdit') else widget
        edit.setFocus()
        QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        event = QInputMethodEvent()
        event.setCommitString(text)
        QApplication.sendEvent(edit, event)
        settle()
        check('editor submitted value: ' + text, edit.text() == text, edit.text())

    def shot(name):
        settle()
        _capture(window, output / (name + '.png'))
        result['screenshots'].append(name + '.png')

    def write():
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def run():
        try:
            path = Path(window.legacy.LEARNED_TERMS_PATH).resolve()
            check('database is isolated', path.is_relative_to(output), str(path))
            check('legacy and runtime user data roots match', path.parent == user_data_root(),
                {'database': str(path), 'runtime_user_data_root': str(user_data_root())})
            result['data_root'] = str(path.parent)
            result['store_path'] = str(path)
            from .settings import project_settings_path
            result['stable_settings_path'] = str(project_settings_path())
            configured_models = window.legacy.RUNTIME_SETTINGS.get('models', {})
            result['runtime_model_selection'] = {key: configured_models.get(key) for key in (
                'primary_asr_backend', 'qwen_asr_backend', 'firered_asr_backend',
                'ai_service', 'polish_model', 'group_model')}
            library_id = window.legacy.resolve_glossary_identity('瓦罗兰特')
            check('existing real library resolves by stable id', bool(library_id), library_id)
            window._return_to_settings()
            settle()
            result['visible_asr_selection'] = {key: getattr(window, key).currentData() for key in (
                'primary_asr_backend', 'qwen_asr_backend', 'firered_asr_backend')}
            click(window.add_glossary_button)
            page = window.term_library_page._ensure_library()
            settle()
            index = next(i for i in range(page.game_list.count())
                         if page.game_list.item(i).data(Qt.ItemDataRole.UserRole + 1) == library_id)
            item = page.game_list.item(index)
            page.game_list.scrollToItem(item)
            QTest.mouseClick(page.game_list.viewport(), Qt.MouseButton.LeftButton,
                             pos=page.game_list.visualItemRect(item).center())
            settle()
            check('selected actual existing library', page.state['library_id'] == library_id)
            baseline = snapshot_glossaries(window.legacy, [library_id])
            result['before'] = baseline.summary()
            existing_chichoo = [row for row in window.legacy.learned_mappings_for_game(library_id)
                if row.get('to') == 'CHICHOO']
            if not restoring:
                if page._current_game_in_batch():
                    click(page.batch_toggle)
                for alias, target in wanted[:2]:
                    check('real baseline lacks requested association ' + alias,
                          not any(alias in term.aliases and term.canonical == target
                                  for library in baseline.libraries for term in library.terms))
                click(page.term_try_toggle)
                enter(page.term_try_input, '球球能奶自己')
                enter(page.term_try_expected, 'CHIOCHOO')
                page.try_sentence()
                check('missing canonical diagnosed precisely', any(code == 'term_missing'
                      for code, _ in page.last_sentence_diagnostic['reasons']))
                shot('01-real-missing-diagnostic')
                for number, (alias, target) in enumerate(wanted[:2], 2):
                    enter(page.term_try_expected, target)
                    click(page.term_association_button)
                    enter(page.association_target, target)
                    enter(page.association_alias, alias)
                    check('visible association preview preserves exact target', target in page.association_preview.text())
                    shot(f'{number:02d}-association-preview')
                    _capture(page.association_dialog, output / f'{number:02d}-association-dialog.png')
                    result['screenshots'].append(f'{number:02d}-association-dialog.png')
                    check('alias editor remains focused at save', QApplication.focusWidget() is page.association_alias)
                    click(page.association_save_button)
                    rows = window.legacy.learned_mappings_for_game(library_id)
                    check('normal API stores alias not notes ' + alias, any(row.get('from') == alias
                        and row.get('to') == target and row.get('confirmed')
                        and row.get('provenance') == 'user_confirmed' for row in rows), rows[-2:])
                alias, target = wanted[2]
                enter(page.term_editor, target)
                enter(page.term_alias_editor, alias)
                check('pending third term has exact visible preview', alias in page.term_parse_preview.text()
                      and target in page.term_parse_preview.text())
                def confirm():
                    dialog = getattr(page, 'pending_draft_dialog', None)
                    if dialog is None:
                        QTimer.singleShot(20, confirm)
                        return
                    shot('04-pending-draft-preview')
                    _capture(dialog, output / '04-pending-draft-dialog.png')
                    result['screenshots'].append('04-pending-draft-dialog.png')
                    button = next(button for button in dialog.buttons() if button.text() == '保存并继续')
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                QTimer.singleShot(20, confirm)
                click(page.use_game)
                check('pending draft saved on normal enable without losing unfocused editor text', not page.has_pending_edits())
            snapshot = snapshot_glossaries(window.legacy, window._enabled_glossary_ids())
            check('normal enabled set persists actual library id', library_id in window._enabled_glossary_ids())
            check('terms enabled for actual batch', window.terms.isChecked())
            scene = resolve_content_scene(RunOptions(enable_domain_terms=True,
                enabled_glossary_ids=tuple(window._enabled_glossary_ids()),
                glossary_snapshot_json=json.dumps(snapshot.to_dict())).create_runtime_context(window.legacy), snapshot)
            for alias, target in wanted:
                enter(page.term_try_input, alias + '能奶自己')
                enter(page.term_try_expected, target)
                page.try_sentence()
                check('diagnostic actual batch applies ' + alias,
                    page.last_sentence_diagnostic['actual'].text == target + '能奶自己', page.term_try_result.text())
            check('ordinary media topic remains unchanged', TermResolver(snapshot).resolve(
                '小时候喜欢看奥特曼', scene=scene).text == '小时候喜欢看奥特曼')
            rows = window.legacy.learned_mappings_for_game(library_id)
            check('distinct existing CHICHOO rows preserved', [row for row in rows if row.get('to') == 'CHICHOO'] == existing_chichoo)
            result['saved_records'] = [row for row in rows if row.get('from') in {value for pair in wanted for value in pair}]
            result['snapshot'] = snapshot.to_dict()
            result['snapshot_summary'] = snapshot.summary()
            result['content_scene'] = scene.to_dict()
            result['inferred_scene'] = resolve_content_scene(RunOptions(enable_domain_terms=True,
                enabled_glossary_ids=tuple(window._enabled_glossary_ids()),
                glossary_snapshot_json=json.dumps(snapshot.to_dict())).create_runtime_context(window.legacy), snapshot).to_dict()
            result['store_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            shot('05-normal-enabled-actual-diagnostic')
            if restoring:
                previous = json.loads((output / 'chain-result.json').read_text('utf8'))
                check('second process restores exact saved snapshot', snapshot.digest == previous['snapshot_summary']['snapshot_digest'])
                check('second process DB bytes unchanged', result['store_sha256'] == previous['store_sha256'])
            else:
                check('saved revision refreshes snapshot', baseline.digest != snapshot.digest)
            from . import blank_project_audit
            check('zero model calls during UI-only audit', blank_project_audit._provider_calls == 0)
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            try:
                shot('glossary-chain-failure')
            except Exception:
                pass
        window.result_exit_code = 0 if result['passed'] else 1
        write()
        def stopped():
            result['gui_shutdown'] = True
            write()
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(750, run)
