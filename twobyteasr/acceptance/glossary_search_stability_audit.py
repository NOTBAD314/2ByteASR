"""Opt-in normal-entry glossary search and scrollbar convergence checks."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QMimeData, QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity

    output = Path(output)
    result = dict(passed=False, checks=[], idle=[], boundaries=[], pid=os.getpid(),
                  identity=load_build_identity().to_dict(), executable=sys.executable,
                  dpr=window.devicePixelRatioF(), ime_scope='Qt preedit/commit events',
                  screenshots=[], input_events='Qt QTest on normal Windows widgets')
    receipt = output / 'search-stability.json'
    dwell = float(os.environ.get('GLOSSARY_SEARCH_IDLE_SECONDS', '30'))

    def check(name, passed, detail=None):
        result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))
        if not passed:
            raise AssertionError(name + ' ' + str(detail))

    def settle(ms=250):
        QTest.qWait(ms)

    def pixels(view):
        image = view.viewport().grab().toImage()
        return hashlib.sha256(bytes(image.constBits())).hexdigest()

    def shot(name):
        _capture(window, output / (name + '.png'))
        result['screenshots'].append(name + '.png')

    def save():
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def run():
        try:
            check('isolated storage', Path(window.legacy.LEARNED_TERMS_PATH).resolve().is_relative_to(output))
            window.resize(1440, 900)
            window._manage_terms()
            settle()
            page = window.term_library_page._ensure_library()
            original_view = page.listing
            libraries = []
            words = ['悲鸣', '共鸣', '共鸣者', '鸣式', '二次共鸣', '共鸣スキル', '共鸣回路', '共鸣解放',
                     '鸣鐘の亀', '响き渡る共鸣天', '响き渡る共鸣地', '响き渡る共鸣风', '响き渡る共鸣海',
                     '鸣潮科学', '共鸣能力', '鸣潮', '长离', '日本語テスト']
            for count in (674, 2048):
                page.sidebar_new_button.click()
                page.game_input.setText('搜索稳定验收' + str(count))
                page.add_game_button.click()
                settle()
                key = page._library_key()
                references = [dict(name=words[i] if i < len(words) else f'验收词{i:04d}',
                                   category='角色' if i >= 16 else '机制') for i in range(count)]
                check('seed confirmed terms ' + str(count), window.legacy.confirm_reference_terms(key, references) == count)
                libraries.append((count, key, page.state['game']))
                page._notify_library_changed()
                page.refresh_current_game()
                settle()
                check('normal model count ' + str(count), page._term_model.rowCount() == count)

                for query, expected in (('鸣', 16), ('长离', 1), ('绝对没有这个名字', 0)):
                    page.search.setText(query)
                    page.search.setFocus()
                    settle(500)
                    check('query result ' + str(count) + query, page._term_model.rowCount() == expected)
                    before = page.search_diagnostics()
                    image_before = pixels(page.listing) if expected else None
                    started = time.monotonic()
                    settle(round(dwell * 1000))
                    after = page.search_diagnostics()
                    item = dict(count=count, query=query, seconds=time.monotonic() - started,
                                before=before, after=after, pixels_equal=(not expected or image_before == pixels(page.listing)))
                    result['idle'].append(item)
                    check('idle counts and geometry stable ' + str(count) + query, before == after, item)
                    check('idle card pixels stable ' + str(count) + query, item['pixels_equal'])
                    shot(f'terms-{count}-results-{expected}')
                    save()

            page.search.clear()
            settle()
            page.listing.verticalScrollBar().setValue(900)
            settle()
            scroll = page.listing.verticalScrollBar().value()
            before = page.search_diagnostics()
            for _ in range(5):
                page.refresh_current_game()
            settle()
            check('unchanged refresh preserves scroll', page.listing.verticalScrollBar().value() == scroll)
            check('unchanged refresh skips filtering and model updates', page.search_diagnostics()['counts'] == before['counts'])

            page.search.setFocus()
            page.search.clear()
            QTest.keyClicks(page.search, 'abcxyz', delay=4)
            for _ in range(6):
                QTest.keyClick(page.search, Qt.Key.Key_Backspace)
            QTest.keyClicks(page.search, 'not-found')
            page.search.selectAll()
            clipboard = QApplication.clipboard()
            saved_clipboard = QMimeData()
            if clipboard.mimeData() is not None:
                for mime in clipboard.mimeData().formats():
                    saved_clipboard.setData(mime, clipboard.mimeData().data(mime))
            try:
                clipboard.setText('鸣')
                QTest.keyClick(page.search, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            finally:
                clipboard.setMimeData(saved_clipboard)
            settle()
            check('rapid input backspace paste final result', page.search.text() == '鸣' and page._term_model.rowCount() == 16)
            for preedit, commit, expected in (('chang li', '长离', 1), ('にほんご', '日本語テスト', 1)):
                page.search.clear()
                QApplication.sendEvent(page.search, QInputMethodEvent(preedit, []))
                before = page.search_diagnostics()['counts']
                page.refresh_current_game()
                check('preedit refresh keeps uncommitted text ' + preedit,
                      page.search.text() == '' and page.search.hasFocus() and page.search_diagnostics()['counts'] == before)
                event = QInputMethodEvent()
                event.setCommitString(commit)
                QApplication.sendEvent(page.search, event)
                settle()
                check('IME committed query ' + commit, page.search.text() == commit and page._term_model.rowCount() == expected)

            for _ in range(3):
                for count, key, name in libraries:
                    page.add_game_item(name, library_id=key, select=True)
                    settle()
                    page.search.setText('鸣')
                    settle()
                    check('switch library latest query ' + str(count), page._term_model.rowCount() == 16 and page._library_key() == key)
                window._return_to_settings()
                window._manage_terms()
                settle()
                check('reenter retains same card view', window.term_library_page._ensure_library().listing is original_view)
            page.filter_category.setCurrentIndex(page.filter_category.findData('机制'))
            settle()
            check('category filter', page._term_model.rowCount() == 16)
            page.filter_category.setCurrentIndex(0)
            page.search.setText('长离')
            settle()
            before = page.search_diagnostics()['counts'].get('search_triggered', 0)
            page.search.setText('鸣')
            settle()
            check('no accumulated search connections', page.search_diagnostics()['counts']['search_triggered'] - before == 1)

            # Sweep both the five/six-column and scrollbar visibility boundary.
            for width in (1120, 1140, 1160, 1180, 1200, 1220, 1240, 1260, 1280, 1300, 1320, 1440):
                window.resize(width, 720)
                settle(150)
                before = page.search_diagnostics()
                settle(200)
                after = page.search_diagnostics()
                result['boundaries'].append(dict(window=window.size().toTuple(), before=before, after=after))
                check('boundary converges ' + str(width), before == after)
            shot('critical-width-final')
            window.resize(1240, 800)
            settle(500)
            before = page.search_diagnostics()
            started = time.monotonic()
            settle(round(dwell * 1000))
            after = page.search_diagnostics()
            result['critical_idle'] = dict(before=before, after=after, seconds=time.monotonic() - started)
            check('critical window remains stable for idle interval', before == after)
            check('actual wrapping matches column budget', after['layout']['actual_columns'] == after['layout']['columns'])
            shot('critical-width-idle')
            window.resize(1440, 900)
            page.search.clear()
            page.term_editor.setText('新增验收角色')
            page.term_alias_editor.setText('新增错字')
            QTest.mouseClick(page.add_term_button, Qt.MouseButton.LeftButton)
            settle()
            page.search.setText('新增验收角色')
            settle()
            check('add through normal button', page._term_model.rowCount() == 1)
            index = page._term_model.index(0, 0)
            QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton, pos=page.listing.visualRect(index).center())
            settle()
            check('normal card opens editor', getattr(page, '_edit_sheet', None) is not None)
            page.edit_canonical.setText('编辑后的验收角色')
            QTest.mouseClick(page.edit_save_button, Qt.MouseButton.LeftButton)
            settle()
            page.search.setText('编辑后的验收角色')
            settle()
            check('normal card edit persists', page._term_model.rowCount() == 1 and page._term_model.data_for_row(0)['target'] == '编辑后的验收角色')
            page.search.clear()
            settle()
            page.listing.verticalScrollBar().setValue(page.listing.verticalScrollBar().maximum())
            settle()
            check('scroll reaches final card', page.listing.viewport().rect().intersects(page.listing.visualRect(page._term_model.index(page._term_model.rowCount() - 1, 0))))
            shot('edited-and-scrolled')
            page.add_game_item('参考确认验收', select=True)
            settle()
            game = page.state['game']
            reference = dict(name='单条确认验收', category='角色', aliases=[])
            page._builtin_cache[game] = ([reference['name']], [], [])
            page._builtin_entry_cache[game] = [reference]
            page._term_rows_cache = None
            page.refresh_current_game()
            settle()
            index = page._term_model.index(0, 0)
            check('reference card ready', page._term_model.data_for_row(0)['status'] == 'reference')
            button = page.listing.card_delegate.button_rect(page.listing.visualRect(index), index)
            QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton, pos=button.center())
            settle()
            check('normal painted confirm persists', any(row['to'] == reference['name'] for row in window.legacy.learned_mappings_for_game(page._library_key())))
            from . import blank_project_audit
            check('zero provider requests', blank_project_audit._provider_calls == 0)
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            try:
                shot('failure')
            except Exception:
                pass
        window.result_exit_code = 0 if result['passed'] else 1
        save()
        def stopped():
            result['gui_shutdown'] = True
            save()
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()

    QTimer.singleShot(1000, run)
