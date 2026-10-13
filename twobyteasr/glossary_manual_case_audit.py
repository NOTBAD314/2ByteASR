"""Normal-entry Qt case revision audit over an isolated real glossary copy."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .runtime import activate_runtime_context
    from .service import RunOptions
    from .terminology import snapshot_glossaries

    output = Path(output)
    restoring = os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-manual-case-restore'
    receipt = output / ('case-restore-result.json' if restoring else 'case-result.json')
    desired = {'berlin': 'BerLIN', 's0pp': 'S0pp', 'zhe': 'Zhe'}
    result = {'passed': False, 'checks': [], 'screenshots': [], 'executable': sys.executable,
              'identity': load_build_identity().to_dict(), 'pid': os.getpid(),
              'sample': 'isolated copy of actual user glossary; canonical inputs only; no alias answers'}

    def check(name, passed, detail=None):
        result['checks'].append({'name': name, 'passed': bool(passed), 'detail': detail})
        if not passed:
            raise AssertionError(f'{name}: {detail}')

    def settle():
        QApplication.instance().processEvents()
        QTest.qWait(100)

    def click(button):
        check('visible enabled button ' + button.text(), button.isVisible() and button.isEnabled())
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
            store_path = Path(window.legacy.LEARNED_TERMS_PATH).resolve()
            check('store is inside isolated audit root', store_path.is_relative_to(output), str(store_path))
            library_id = window.legacy.resolve_glossary_identity('瓦罗兰特')
            check('real copied glossary identity', library_id == '瓦罗兰特', library_id)
            window._manage_terms()
            settle()
            page = window.term_library_page._ensure_library()
            page.add_game_item('瓦罗兰特', library_id=library_id, select=True)
            page.refresh_current_game()
            settle()
            before = snapshot_glossaries(window.legacy, [library_id])
            result['snapshot_before'] = before.summary()
            if not restoring:
                initial = window.legacy.learned_mappings_for_game(library_id)
                check('real baseline 157 mapping records', len(initial) == 157, len(initial))
                check('real baseline 81 canonical terms', len(before.canonical_terms) == 81, before.summary())
                check('real lowercase data retained before user action',
                      all(any(row['from'] == row['to'] == old for row in initial) for old in desired))
                shot('glossary-real-lowercase-before-manual-input')
                for old, canonical in desired.items():
                    page.term_alias_editor.clear()
                    page.term_editor.setText(canonical)
                    click(page.add_term_button)
                    rows = window.legacy.learned_mappings_for_game(library_id)
                    check('manual reentry persisted ' + canonical,
                          any(row['from'] == row['to'] == canonical for row in rows))
                    visible = page._unified_term_rows()
                    check('list displays saved canonical ' + canonical,
                          any(row['term_text'] == canonical for row in visible))
                after = snapshot_glossaries(window.legacy, [library_id])
                check('case revision invalidates new task snapshot', before.digest != after.digest)
                check('case revision increments effective library revision',
                      before.libraries[0].revision != after.libraries[0].revision)
                check('old task snapshot stays immutable', all(old in before.canonical_terms for old in desired))
                check('mapping aggregation does not lose rows', len(window.legacy.learned_mappings_for_game(library_id)) == 157)
                check('canonical count remains 81', len(after.canonical_terms) == 81)
                # Exercise the separate edit form with case-only writes, then
                # restore precisely the user's stated spelling in the copy.
                for old, canonical in desired.items():
                    for spelling in (old, canonical):
                        mapping = next(row for row in window.legacy.learned_mappings_for_game(library_id)
                                       if row['from'].casefold() == row['to'].casefold() == old)
                        page._show_edit_sheet(mapping)
                        page.edit_canonical.setText(spelling)
                        click(page.edit_save_button)
                        check('case-only edit persisted ' + spelling,
                              any(row['from'] == row['to'] == spelling
                                  for row in window.legacy.learned_mappings_for_game(library_id)))
                click(page.use_game)
                # These are attempted AI/learning writes, with no model request.
                protected = window.legacy.persist_learned_mappings(library_id, [
                    {'from': old, 'to': old, 'confirmed': True, 'verification': 'web_official'}
                    for old in desired])
                check('automatic learning cannot override user-confirmed case', protected.get('protected') == 3, protected)
                page._mappings_cache.pop('瓦罗兰特', None)
                page.refresh_current_game()
                shot('glossary-real-user-canonical-after-save')
                for canonical in desired.values():
                    page.search.setText(canonical)
                    page.apply_filter()
                    shot('glossary-real-filtered-' + canonical)
                page.search.clear()
                page.apply_filter()
            rows = window.legacy.learned_mappings_for_game(library_id)
            current = snapshot_glossaries(window.legacy, [library_id])
            check('persisted canonical spelling and digit zero',
                  all(canonical in current.canonical_terms for canonical in desired.values()), current.canonical_terms[:3])
            check('lowercase canonical fields no longer used',
                  not any(row['to'] in desired for row in rows))
            options = RunOptions(content_name='瓦罗兰特', enabled_glossary_ids=(library_id,),
                                 enable_domain_terms=True,
                                 glossary_snapshot_json=json.dumps(current.to_dict(), ensure_ascii=False))
            context = options.create_runtime_context(window.legacy)
            with activate_runtime_context(context):
                check('background actual task canonical forms',
                      all(canonical in window.legacy.learned_canonical_terms() for canonical in desired.values()))
            if restoring:
                previous = json.loads((output / 'case-result.json').read_text('utf8'))
                check('new process restores exact stored snapshot', current.digest == previous['snapshot_after']['snapshot_digest'])
                shot('glossary-real-canonical-after-process-restart')
            result['snapshot_after'] = current.summary()
            result['database_sha256'] = hashlib.sha256(store_path.read_bytes()).hexdigest()
            result['module_sources'] = {'subtitle_core': window.legacy.__file__, 'audit': __file__}
            from . import blank_project_audit
            result['provider_calls_attempted'] = blank_project_audit._provider_calls
            result['external_connections_blocked'] = list(blank_project_audit._blocked_external_connections)
            check('no provider calls in local spelling verification', result['provider_calls_attempted'] == 0)
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            try:
                shot('glossary-case-audit-failure')
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
