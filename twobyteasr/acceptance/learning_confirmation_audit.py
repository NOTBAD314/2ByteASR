"""Runtime evidence through the normal main window with isolated storage."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea, QListWidget, QPushButton
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..glossary.glossary_learning import GlossaryLearningStore
    from ..glossary.terminology import snapshot_glossaries
    from ..projects.studio_project import load_project, save_project
    from ..studio.studio_find_replace import replace_all
    from ..timeline.studio_commands import MutationOrigin

    output = Path(output)
    result = dict(passed=False, checks=[], screenshots=[], pid=os.getpid(), executable=sys.executable,
        identity=load_build_identity().to_dict(), dpr=window.devicePixelRatioF(), edit_ms=[])
    receipt = output/'result.json'
    legacy = window.legacy

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        if not value:
            raise AssertionError(name + ' ' + str(detail))

    def wait(predicate, seconds=70):
        until = time.monotonic() + seconds
        while time.monotonic() < until and not predicate():
            QTest.qWait(50)
        check('normal entry ready', predicate())

    def shot(name):
        _capture(window, output/(name+'.png'))
        result['screenshots'].append(name+'.png')

    def click(widget):
        parent = widget.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent:
            parent.ensureWidgetVisible(widget, 0, 30)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        QTest.qWait(120)

    def finish():
        window.result_exit_code = 0 if result['passed'] else 1
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        def stopped():
            result['gui_shutdown'] = True
            receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        page = window.built_page('studio')
        if page:
            page.undo_stack.setClean()
        window.close()

    def restart():
        try:
            state = json.loads(Path(os.environ['LEARNING_REVIEW_STATE']).read_text('utf8'))
            first, second = state['first'], state['second']
            check('new process reads three confirmed rules', len(legacy.user_confirmed_mappings_for_game(first)) == 3)
            check('new process preserves second library', legacy.user_confirmed_mappings_for_game(second) == [])
            check('new process preserves manual history term', len(legacy.user_confirmed_mappings_for_game(state['history'])) == 1)
            store = GlossaryLearningStore(state['learning'])
            store.sync_legacy(legacy)
            check('new process has no resurrected ignored candidates', store.pending() == [])
            window.open_studio_project(state['project'])
            wait(lambda: window.built_page('studio') is not None and window.studio_page.project is not None
                and window.studio_page._readiness.ready and not window.studio_page._readiness.active)
            check('new process reopens saved caption after candidate failure', window.studio_page._cue_lookup['cue-0'].text == '新字幕仍然保存')
            studio = window.studio_page
            studio.cue_controller.set_text('cue-4', '这把用福宁娜', origin=MutationOrigin.ASR)
            studio.cue_controller.set_text('cue-4', '这把用芙宁娜')
            studio.cue_controller.commit_manual_term_learning('cue-4')
            check('repeated correction respects persisted ignore', store.pending() == [])
            studio.save()
            wait(lambda: studio.undo_stack.isClean())
            window._return_to_settings()
            QTest.qWait(300)
            window._manage_terms()
            QTest.qWait(300)
            page = window.term_library_page._ensure_library()
            page.add_game_item('审核验收甲', select=True, library_id=first)
            page.refresh_current_game()
            check('new process UI separates empty pending from three confirmed', page.learning_panel.listing.count() == 0
                and len(page.state['mappings']) == 3)
            shot('restart-confirmed-and-pending')
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
        finish()

    def run():
        try:
            check('isolated formal storage', Path(legacy.LEARNED_TERMS_PATH).resolve().is_relative_to(output))
            first = legacy.create_learned_content('审核验收甲', create_new=True)
            second = legacy.create_learned_content('审核验收乙', create_new=True)
            legacy.add_learned_mapping(first, '芙宁娜', '芙宁娜', category='角色')
            initial = Path(legacy.LEARNED_TERMS_PATH).read_bytes()
            initial_rules = legacy.user_confirmed_mappings_for_game(first)
            window.open_studio_project(os.environ['LEARNING_REVIEW_PROJECT'])
            wait(lambda: window.built_page('studio') is not None and window.built_page('studio').project is not None
                and window.built_page('studio')._readiness.ready and not window.built_page('studio')._readiness.active)
            studio = window.studio_page
            studio.project.glossary_ids = [first]
            for i, text in enumerate(['我们去吃午饭吧', '你好！世界', '那维莱特登场', '星见雅很强', '这把用芙宁娜']):
                began = time.perf_counter()
                studio.cue_controller.set_text(f'cue-{i}', text)
                studio.cue_controller.commit_manual_term_learning(f'cue-{i}')
                result['edit_ms'].append((time.perf_counter()-began)*1000)
            check('five caption edits do not write formal glossary', Path(legacy.LEARNED_TERMS_PATH).read_bytes() == initial)
            check('only three local term candidates', len(studio._learning_store.pending()) == 3)
            check('pending absent from recognition and proofreading snapshot', snapshot_glossaries(legacy, [first]).canonical_terms == ('芙宁娜',))
            check('existing term has no automatic alias', legacy.user_confirmed_mappings_for_game(first)[0]['from'] == '芙宁娜'
                and len(legacy.user_confirmed_mappings_for_game(first)) == 1)
            studio.save()
            wait(lambda: studio.undo_stack.isClean())
            # Persist a separate review copy while the normal async save drains.
            saved = save_project(studio.project, output/'saved.2byteproj')
            check('saved captions preserved', load_project(saved).cues[2].text == '那维莱特登场')
            check('save does not write formal glossary', Path(legacy.LEARNED_TERMS_PATH).read_bytes() == initial)
            window._return_to_settings()
            QTest.qWait(400)
            window._manage_terms()
            QTest.qWait(300)
            page = window.term_library_page._ensure_library()
            page.add_game_item('审核验收甲', select=True, library_id=first)
            QTest.qWait(200)
            panel = page.learning_panel
            panel.refresh()
            wait(lambda: panel.isVisible())
            check('candidate review available and unchecked', panel.listing.count() == 3 and not panel.checked_ids())
            click(panel.toggle)
            panel.listing.setCurrentRow(0)
            click(panel.edit)
            panel.editor.grab().save(str(output/'candidate-editor.png'))
            result['screenshots'].append('candidate-editor.png')
            panel.editor.close()
            click(panel.select_all)
            check('checking all has no write authority', len(panel.checked_ids()) == 3
                and legacy.user_confirmed_mappings_for_game(first) == initial_rules,
                dict(checked=len(panel.checked_ids()), official=len(legacy.user_confirmed_mappings_for_game(first))))
            shot('01-review-before-confirmation')
            click(panel.select_all)
            # Ignore the alias of an already confirmed canonical, then repeat it.
            for i in range(panel.listing.count()):
                item = panel.listing.item(i)
                if panel.entries[item.data(Qt.ItemDataRole.UserRole)]['corrected_term'] == '芙宁娜':
                    panel.listing.setCurrentRow(i)
                    break
            click(panel.ignore)
            check('ignore leaves subtitle correction intact', studio._cue_lookup['cue-4'].text == '这把用芙宁娜')
            studio.cue_controller.set_text('cue-4', '这把用福宁娜', origin=MutationOrigin.LLM)
            studio.cue_controller.set_text('cue-4', '这把用芙宁娜')
            studio.cue_controller.commit_manual_term_learning('cue-4')
            panel.refresh()
            check('ignored candidate does not return', panel.listing.count() == 2)
            click(panel.select_all)
            shot('02-two-selected')
            click(panel.accept)
            check('explicit two-candidate confirmation adds exactly two rules', len(legacy.user_confirmed_mappings_for_game(first)) == 3)
            check('confirmed candidates leave review', panel.listing.count() == 0)
            panel.commit([])
            check('repeat confirmation idempotent', len(legacy.user_confirmed_mappings_for_game(first)) == 3)
            page._export_library_to(output/'export.json')
            check('export only confirmed rules', len(json.loads((output/'export.json').read_text('utf8'))['mappings']) == 3)
            check('confirmed state survives new store', len(GlossaryLearningStore(studio._learning_store.path).pending()) == 0)
            studio.save()
            wait(lambda: studio.undo_stack.isClean())
            window.open_studio_project(saved)
            wait(lambda: window.studio_page.project is not None and window.studio_page._readiness.ready
                and str(window.studio_page.project_path) == str(saved))
            studio = window.studio_page
            replace_all(studio, needle='那维来特', replacement='那维莱特', scope='all')
            studio.undo_stack.undo()
            studio.undo_stack.redo()
            check('batch undo redo cannot modify formal mappings', len(legacy.user_confirmed_mappings_for_game(first)) == 3)
            check('batch redo of existing mapping has no reverse or duplicate candidate', studio._learning_store.pending() == [])
            check('other target glossary untouched', legacy.user_confirmed_mappings_for_game(second) == [])
            # Candidate IO failure must not roll back a successfully edited caption.
            original_record = studio._learning_store.record_manual_edit
            def fail(*_args, **_kwargs):
                raise OSError('injected candidate write failure')
            studio._learning_store.record_manual_edit = fail
            studio.cue_controller.set_text('cue-0', '新字幕仍然保存')
            studio.cue_controller.commit_manual_term_learning('cue-0')
            studio._learning_store.record_manual_edit = original_record
            check('candidate failure preserves caption edit', studio._cue_lookup['cue-0'].text == '新字幕仍然保存')
            saved = save_project(studio.project, output/'final.2byteproj')
            check('candidate failure preserves saved text', load_project(saved).cues[0].text == '新字幕仍然保存')
            studio.save()
            wait(lambda: studio.undo_stack.isClean())
            # Exact automatic provenance is review-only. Unknown old provenance
            # stays effective until the user actively chooses its review action.
            history = legacy.create_learned_content('历史检查验收', create_new=True)
            legacy.add_learned_mapping(history, '人工词', '人工词')
            payload = legacy.load_learned_term_payload()
            auto = dict(**{'from': '历史听成', 'to': '历史自动词'}, confirmed=True,
                provenance='user_confirmed', sources=['user_manual'], verification='user_manual',
                origin='Studio 手动修改（自动记入）')
            unknown = dict(auto, **{'from': '来源未知听成', 'to': '来源未知词', 'origin': '旧版本信息不足'})
            payload['games'][history]['mappings'].extend([auto, unknown])
            legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
            window._return_to_settings()
            QTest.qWait(300)
            window._manage_terms()
            QTest.qWait(300)
            page = window.term_library_page._ensure_library()
            page.add_game_item('历史检查验收', select=True, library_id=history)
            panel = page.learning_panel
            panel.refresh()
            check('legacy automatic row quarantined while manual and unknown remain',
                len(legacy.user_confirmed_mappings_for_game(history)) == 2 and panel.listing.count() == 1)
            from ..recognition.transcript_data import SpeechSegment
            legacy_rows = legacy.prepared_learned_mappings(
                [SpeechSegment(1, 0, 1, '历史听成 来源未知听成', .8, [])], history)
            check('legacy hints and replacement gates exclude automatic rows',
                '历史自动词' not in legacy.learned_canonical_terms(history)
                and [row['to'] for row in legacy_rows] == ['来源未知词'])
            from types import SimpleNamespace
            from ..subtitle_rules.studio_qc import terminology_from_project
            check('Studio QC excludes automatic legacy row',
                {row.canonical for row in terminology_from_project(SimpleNamespace(glossary_ids=[history]))}
                == {'人工词', '来源未知词'})
            if panel.box.isHidden():
                click(panel.toggle)
            panel.listing.setCurrentRow(0)
            click(panel.ignore)
            click(panel.history)
            history_list = panel.history_dialog.findChild(QListWidget)
            check('unknown provenance requires active selection', history_list.count() == 1
                and history_list.item(0).checkState() == Qt.CheckState.Unchecked)
            panel.history_dialog.grab().save(str(output/'history-review.png'))
            result['screenshots'].append('history-review.png')
            history_list.item(0).setCheckState(Qt.CheckState.Checked)
            move = next(button for button in panel.history_dialog.findChildren(QPushButton)
                        if button.text() == '将所选移至待确认')
            click(move)
            check('explicit legacy move preserves backup and manual term',
                len(legacy.user_confirmed_mappings_for_game(history)) == 1 and panel.listing.count() == 1
                and panel.store.pending()[0].get('legacy_mapping'))
            panel.listing.setCurrentRow(0)
            click(panel.ignore)
            (output/'restart-state.json').write_text(json.dumps(dict(first=first, second=second,
                history=history, learning=str(studio._learning_store.path), project=str(saved))), 'utf8')
            shot('03-after-confirmation')
            from . import blank_project_audit
            check('zero model calls', blank_project_audit._provider_calls == 0)
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            try:
                shot('failure')
            except Exception:
                pass
        finish()

    QTimer.singleShot(1200, restart if os.environ.get('LEARNING_REVIEW_PHASE') == 'restart' else run)
