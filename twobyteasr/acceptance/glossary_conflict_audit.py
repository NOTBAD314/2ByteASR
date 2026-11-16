"""Opt-in Windows acceptance using isolated historical conflicting mappings."""
from pathlib import Path
import json
import os
import traceback


def start(window, output):
    from PySide6.QtCore import QItemSelectionModel, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ..design.theme_manager import apply_theme
    from .blank_project_audit import _capture

    out = Path(output)
    app, legacy = QApplication.instance(), window.legacy
    page = None
    result = dict(passed=False, checks=[], screenshots=[], pid=os.getpid(),
                  scope='normal Windows app; isolated synthetic libraries; no cloud or user data')

    def check(name, ok, detail=''):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=str(detail)))
        if not ok:
            raise AssertionError(name + ': ' + str(detail))

    def settle(ms=160):
        app.processEvents()
        QTest.qWait(ms)

    def wait_for(name, predicate):
        for _ in range(160):
            settle(50)
            if predicate():
                check(name, True)
                return
        detail = ''
        if page is not None:
            detail = dict(rows=page._term_model.rowCount(), conflict=page.status_buttons['conflict'].text(),
                          game=page.state.get('game'), library_id=page.state.get('library_id'),
                          mapping_count=len(page.state.get('mappings', ())), batch_status=page.batch_status.text(),
                          summary_running=page._batch_running)
        check(name, False, detail)

    def click(button):
        check('visible enabled ' + button.text(), button.isVisible() and button.isEnabled())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        settle()

    def shot(name):
        settle(250)
        _capture(window, out / (name + '.png'))
        result['screenshots'].append(name + '.png')
        if 'conflicts' in name and 'resolved' not in name:
            page.status_segment.grab().save(str(out / (name + '-segment.png')))
            region = page.library_content.rect()
            region.setBottom(page.status_segment.mapTo(page.library_content,
                             page.status_segment.rect().bottomLeft()).y() + 8)
            page.library_content.grab(region).save(str(out / (name + '-header.png')))

    def run():
        nonlocal page
        try:
            from ..i18n import save_language
            save_language('zh')  # The explicit segment-copy assertions below use Chinese.
            store = Path(legacy.LEARNED_TERMS_PATH).resolve()
            check('storage isolated', store.is_relative_to(out), store)
            own = legacy.create_learned_content('鸣潮 · 冲突筛选验收', create_new=True)
            other = legacy.create_learned_content('跨库验收', create_new=True)
            payload = legacy.load_learned_term_payload(strict=True)

            def mapping(source, target, category='角色'):
                return dict(**{'from': source, 'to': target}, category=category,
                            confirmed=True, origin='手动', provenance='user_confirmed')

            payload['games'][own]['mappings'] = [
                mapping('漂泊者', '漂泊者'), mapping('漂流者', '漂泊者'),
                mapping('飘泊者', '飘泊者'), mapping('漂流者', '飘泊者'),
                mapping('长离', '长离'), mapping('库间同音', '长离'),
                *[mapping(f'无冲突术语{i:04}', f'无冲突术语{i:04}') for i in range(855)]]
            payload['games'][other]['mappings'] = [mapping('库间同音', '炽霞')]
            legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
            legacy.RUNTIME_SETTINGS.setdefault('glossary', {})['enabled_glossary_ids'] = [own, other]
            window.terms.setChecked(True)
            window._manage_terms()
            settle()
            page = window.term_library_page._ensure_library()
            for index in range(page.game_list.count()):
                if page._library_key(page.game_list.item(index).data(Qt.ItemDataRole.UserRole)) == own:
                    page.game_list.setCurrentRow(index)
                    break
            page.state.update(game='鸣潮 · 冲突筛选验收', library_id=own)
            page._notify_library_changed()
            page.refresh_current_game()
            wait_for('858 cards and three participating conflicts', lambda:
                     page.status_buttons['conflict'].text() == '有冲突 3' and page._term_model.rowCount() == 858)
            check('same segment object names', {b.objectName() for b in page.status_buttons.values()} == {'termSegmentButton'})
            check('hidden then conflict', list(page.status_buttons)[-2:] == ['hidden', 'conflict'])
            for theme in ('cinema', 'warm'):
                apply_theme(theme)
                for width in (1760, 1100):
                    window.resize(width, 1000)
                    settle(300)
                    display_rect = page.term_actions.rect()
                    display_bottom = page.term_actions.mapTo(window, display_rect.bottomLeft()).y()
                    status_top = page.status_segment.mapTo(window, page.status_segment.rect().topLeft()).y()
                    check('card display above conflict segment', display_bottom < status_top)
                    check('card display removed from filter toolbar', page.term_tools_layout.indexOf(page.term_actions) < 0)
                    click(page.status_buttons[''])
                    shot(f'{theme}-{width}-all')
                    click(page.status_buttons['conflict'])
                    check('three cards in conflict filter', page._term_model.rowCount() == 3)
                    check('single selected segment', sum(b.isChecked() for b in page.status_buttons.values()) == 1)
                    check('segment fully reachable', page.status_segment.width() >= page.status_segment.minimumSizeHint().width())
                    shot(f'{theme}-{width}-conflicts')
            page.search.setText('长离')
            settle()
            check('search combines with conflict', page._term_model.rowCount() == 1)
            page.search.clear()
            settle()
            index = page._term_model.index(0, 0)
            page.listing.scrollTo(index)
            settle()
            QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier, page.listing.visualRect(index).center())
            settle()
            check('existing name editor opens', page.names_drawer.isVisible())
            shot('conflict-existing-name-editor')
            page.names_drawer.hide()
            payload = legacy.load_learned_term_payload(strict=True)
            payload['games'][own]['mappings'] = [r for r in payload['games'][own]['mappings']
                if (r['from'], r['to']) != ('漂流者', '飘泊者')]
            legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
            page.refresh_current_game()
            wait_for('resolved local conflict leaves cross-library one', lambda:
                     page.status_buttons['conflict'].text() == '有冲突 1' and page._term_model.rowCount() == 1)
            legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] = [own]
            page._refresh_batch_bar()
            wait_for('disabling other library resolves remaining conflict', lambda:
                     page.status_buttons['conflict'].text() == '有冲突 0' and page._term_model.rowCount() == 0)
            shot('conflicts-resolved')
            # Keep the exact first screenshot fixture; then cross the 1000-row
            # background-preparation threshold for the scroll regression.
            click(page.status_buttons[''])
            payload = legacy.load_learned_term_payload(strict=True)
            payload['games'][own]['mappings'].extend(
                mapping(f'异步词条{i:04}', f'异步词条{i:04}') for i in range(400))
            legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
            page.refresh_current_game()
            wait_for('large library async rows ready', lambda:
                     page._term_model.rowCount() == 1258 and page.listing.isEnabled())
            window.resize(1760, 1000)
            settle(300)
            index = page._term_model.index(600, 0)
            identity = page._term_model.data_for_row(600)['concept_id']
            page.listing.cancel_position_restore()
            page.listing.scrollTo(index)
            settle(200)
            before_top = page.listing.visualRect(index).top()
            check('editing starts in middle', page.listing.verticalScrollBar().value() > 500)
            shot('position-before-click')
            QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier, page.listing.visualRect(index).center())
            settle(300)

            def current_index():
                return next((page._term_model.index(i, 0) for i in range(page._term_model.rowCount())
                             if page._term_model.data_for_row(i).get('concept_id') == identity), None)

            rect = page.listing.visualRect(current_index())
            editing_top = min(before_top, max(0, page.listing.viewport().height() - rect.height()))
            check('drawer click preserves card vertical position within visible area',
                  abs(rect.top() - editing_top) <= 2)
            editor = page._names_editor
            editor.open_language(editor.current)
            editor.standard.setText(editor.standard.text() + '改字验收')
            click(editor.save_button)
            wait_for('actual name edit saved and async rebuild settled', lambda:
                     page.listing.isEnabled() and current_index() is not None and
                     page._term_model.data_for_row(current_index().row())['target'].endswith('改字验收'))
            settle(300)
            rect = page.listing.visualRect(current_index())
            check('save preserves card position', abs(rect.top() - editing_top) <= 2)
            check('saved card stays in view', page.listing.verticalScrollBar().value() > 500 and
                  rect.top() >= -1 and rect.bottom() < page.listing.viewport().height())
            shot('position-after-save')
            click(editor.close_button)
            settle(300)
            check('closing drawer preserves position', abs(page.listing.visualRect(current_index()).top() - editing_top) <= 2)
            page.listing.selectionModel().select(current_index(),
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
            settle()
            before_scroll = page.listing.verticalScrollBar().value()

            def confirm_delete():
                dialog = app.activeModalWidget()
                check('real deletion confirmation', isinstance(dialog, QMessageBox))
                QTest.mouseClick(dialog.button(QMessageBox.StandardButton.Yes), Qt.MouseButton.LeftButton)

            QTimer.singleShot(120, confirm_delete)
            click(page.remove_terms)
            wait_for('actual delete and async rebuild settled', lambda:
                     page.listing.isEnabled() and page._term_model.rowCount() == 1257)
            settle(300)
            check('deleted identity absent', current_index() is None)
            check('delete stays at neighboring rows', page.listing.verticalScrollBar().value() > 500 and
                  abs(page.listing.verticalScrollBar().value() - before_scroll) <= page.listing.gridSize().height())
            shot('position-after-delete')
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            _capture(window, out / 'conflict-failure.png')
        window.result_exit_code = 0 if result['passed'] else 1

        def write():
            (out / 'conflict-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

        def stopped():
            result['gui_shutdown'] = True
            write()

        write()
        app.aboutToQuit.connect(stopped)
        window.close()

    QTimer.singleShot(900, run)
