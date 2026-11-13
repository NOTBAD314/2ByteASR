"""Normal MainWindow acceptance using owned storage and deterministic AI replies."""
from __future__ import annotations
import json
import os
import threading
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from PySide6.QtTest import QTest
    from ..glossary import multilingual_terms as m
    from ..glossary.multilingual_terms_ui import CompletionJob, NamesEditor, CandidateDialog
    from ..glossary.translation_name_candidates import complete_names
    from ..recognition.service import CancellationToken
    from .blank_project_audit import _capture
    output = Path(output)
    result = dict(passed=False, checks=[], timings={}, screenshots=[], provider='deterministic fixture; no cloud requests')

    def check(label, condition, detail=None):
        result['checks'].append(dict(name=label, passed=bool(condition), detail=__import__('copy').deepcopy(detail)))
        if not condition: raise AssertionError(label + ': ' + str(detail))

    def wait(predicate, timeout=8000):
        until = time.monotonic() + timeout / 1000
        while not predicate() and time.monotonic() < until:
            QApplication.processEvents()
            # Match the existing proofread audit: explicitly yield Python's
            # GIL so a QThread can finish while this nested driver runs.
            time.sleep(.005)
        check('wait for UI state', predicate())

    def shot(label, widget=None):
        _capture(widget or window, output / (label + '.png')); result['screenshots'].append(label + '.png')

    def run():
        try:
            legacy = window.legacy
            check('owned glossary storage', Path(legacy.LEARNED_TERMS_PATH).resolve().is_relative_to(output))
            library_id = legacy.create_learned_content('多语言验收库', create_new=True)
            rows = []
            for i in range(1200):
                c = m.concept('艾莉娅' if i == 0 else f'概念{i:04}', 'zh-Hans', category='角色')
                c['names']['en'] = m.name_record('Aria' if i == 0 else f'Concept{i:04}', mistranslations=['Alyria'] if i == 0 else [])
                c['names']['ja'] = m.name_record('アリア' if i == 0 else f'テスト{i:04}')
                rows.append(c)
            m.mutate(legacy, library_id, lambda dest, entry: dest.extend(rows))
            window.resize(1440, 960); window._manage_terms(); QTest.qWait(250)
            page = window.term_library_page._ensure_library()
            started = time.perf_counter(); page.add_game_item('多语言验收库', select=True, library_id=library_id)
            wait(lambda: page._library_key() == library_id and page._term_model.rowCount() == 1200)
            result['timings']['open_1200_ms'] = (time.perf_counter()-started)*1000
            shot('01-concept-cards')
            page.term_input_language.setCurrentIndex(page.term_input_language.findData('en'))
            page.term_editor.setText('Independent'); page.add_term_button.click()
            wait(lambda: page._term_model.rowCount() == 1201)
            stored = m.read_concepts(legacy, library_id)
            check('English only quick add', any(list(c['names']) == ['en'] and c['names']['en']['name'] == 'Independent' for c in stored))
            page.listing.verticalScrollBar().setValue(600); QTest.qWait(150)
            scroll = page.listing.verticalScrollBar().value()
            resets = []; page._term_model.modelReset.connect(lambda: resets.append(True))
            record = next(c for c in stored if c['id'] == rows[0]['id'])
            from ..glossary.multilingual_terms_ui import open_editor
            open_editor(page, record['id']); editor = page._names_editor
            QTest.qWait(200)
            check('normal card opens the embedded names drawer', editor.embedded and page.names_drawer.isVisible())
            from PySide6.QtCore import QPoint
            for control in (page.search, page.filter_category, *page.status_buttons.values(), page.use_game,
                            page.term_editor, page.term_alias_editor,
                            page.ai_menu_button, page.import_terms, page.more_button, page.add_term_button):
                if control.isHidden(): continue
                left=control.mapTo(page.library_content,QPoint()).x()
                check('drawer keeps library command reachable '+control.objectName(),
                      left>=0 and left+control.width()<=page.library_content.width(),
                      dict(left=left,width=control.width(),available=page.library_content.width()))
            check('drawer retains readable quick-add text fields',page.term_editor.width()>=150 and page.term_alias_editor.width()>=150)
            editor.names.setCurrentRow(list(record['names']).index('en')); editor.standard.setText('Aria Renewed')
            shot('02-name-editor', editor)
            editor.advanced.show(); editor.adjustSize(); QTest.qWait(100); shot('02-name-editor-advanced', editor)
            editor.save_button.click()
            QTest.qWait(700)
            check('only edited language saved', next(c for c in m.read_concepts(legacy, library_id) if c['id'] == record['id'])['names']['en']['name'] == 'Aria Renewed')
            check('single name edit does not reset card model', not resets, resets)
            check('single edit retains scroll', abs(page.listing.verticalScrollBar().value()-scroll) < 3)
            check('saving keeps the names drawer open', editor.isVisible() and page._names_editor is editor)
            from ..design.theme_manager import apply_theme
            for theme in ('grape', 'warm'):
                apply_theme(theme, QApplication.instance()); QTest.qWait(200)
                shot('02-drawer-' + theme)
            import shiboken6
            for _ in range(12):
                open_editor(page, record['id']); QApplication.processEvents()
                active_editor = page._names_editor
                active_editor.close()
                wait(lambda: not shiboken6.isValid(active_editor))
            check('repeated normal editor lifetimes', True)
            timings = []
            for query in ('Concept0987', 'テスト0555', '没有这个词'):
                started = time.perf_counter(); page.search.setText(query)
                wait(lambda: page._term_model.rowCount() == (0 if query == '没有这个词' else 1))
                timings.append((time.perf_counter()-started)*1000)
            result['timings']['search_ms'] = timings
            page.search.clear(); wait(lambda: page._term_model.rowCount() == 1201)
            started = time.perf_counter()
            page.term_display_language.setCurrentIndex(page.term_display_language.findData('ja'))
            wait(lambda: page._term_model.data_for_row(0).get('translation') == 'アリア')
            check('display language retains the canonical card name',
                  page._term_model.data_for_row(0)['target'] == record['names'][next(iter(record['names']))]['name'])
            result['timings']['display_language_ms'] = (time.perf_counter()-started)*1000
            page.term_language_filter.setCurrentIndex(page.term_language_filter.findData('missing'))
            wait(lambda: page._term_model.rowCount() == 1)
            check('missing language is normal state', page._term_model.data_for_row(0).get('language_note') == '尚无 日本語')
            shot('03-missing-language')
            page.term_language_filter.setCurrentIndex(0); page.search.clear()
            token = CancellationToken(); job = CompletionJob(page); finished = []; progress = []
            job.finished.connect(finished.append); job.progress.connect(progress.append)
            class Provider:
                def complete(self, messages, **kwargs):
                    # An owned slow reply gives UI interactions time to overlap.
                    time.sleep(.15)
                    return json.dumps({'name': '測試譯名', 'sources': ['fixture, not official']})
            def work():
                try: job.finished.emit(complete_names(legacy, library_id, [r['id'] for r in rows[:5]], ['zh-Hant'], Provider(), token=token, progress=job.progress.emit))
                except Exception as exc: job.finished.emit({'error': str(exc)})
            threading.Thread(target=work, daemon=True).start()
            page.search.setText('Concept0123'); wait(lambda: page._term_model.rowCount() == 1)
            page.term_display_language.setCurrentIndex(page.term_display_language.findData('en'))
            page.listing.verticalScrollBar().setValue(0); QTest.qWait(250); token.cancel()
            wait(lambda: bool(finished))
            check('background completion remained interactive', page.search.text() == 'Concept0123' and 'error' not in finished[0], finished[0])
            check('cancel retains generated candidates', sum(len(c.get('candidates', {}).get('zh-Hant', [])) for c in m.read_concepts(legacy, library_id)) > 0)
            page.search.clear(); QTest.qWait(200)
            candidates = CandidateDialog(page, library_id); candidates.show(); QTest.qWait(100); shot('04-candidates', candidates)
            candidates.select_all(); check('batch confirmation names language and count', 'zh-Hant' in candidates.accept_button.text())
            candidates.review(True); candidates.close()
            check('per-language acceptance persisted', any('zh-Hant' in c['names'] for c in m.read_concepts(legacy, library_id)))
            from ..glossary.translation_terms_ui import TranslationTermsDialog
            settings = TranslationTermsDialog({'enabled': True, 'concept_library_ids': [library_id]}, page)
            settings.show(); QTest.qWait(150); shot('05-existing-translation-settings', settings)
            check('existing settings selects shared concepts', settings.value()['concept_library_ids'] == [library_id]); settings.close()
            # Exercise the real review page, QThread callback, proposal guards,
            # application command and undo stack, rather than only its service.
            from ..projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project
            from ..subtitle_rules import subtitle_translation as st
            project = SubtitleProject(media=StudioMedia(path='', duration_ms=3000),
                cues=[StudioCue('review-identity', 100, 1800, '艾莉娅小姐来了')], glossary_ids=[library_id],
                generation_metadata={'language': {'code': 'zh'}, 'translation_terminology': {'enabled': True,
                    'concept_library_ids': [library_id]}})
            project.generation_metadata['translation_records'] = st._empty_container('en')
            st.set_manual(project, 'review-identity', 'Miss Alyria has arrived.', target='en')
            path = output / 'review.2byteproj'; save_project(project, path)
            window._show_glossary_proofread(str(path), project)
            review = window.glossary_proofread_page
            import faulthandler
            trace_stream = (output / 'review-threads.txt').open('w', encoding='utf8')
            faulthandler.dump_traceback_later(15, file=trace_stream)
            QTest.qWait(500)
            review.recheck_translation_button.click()
            wait(lambda: review._worker is None and any(
                issue.get('replacement') == 'Aria Renewed' for row in review._rows for issue in row['issues']), timeout=60000)
            # The real page batches list painting/counts on short Qt timers.
            # Capture their visible result, not just the ready callback's data.
            settle_until = time.monotonic() + .7
            while time.monotonic() < settle_until:
                QApplication.processEvents(); time.sleep(.005)
            shot('07-current-translation-review')
            row = next(row for row in review._rows if any(i.get('replacement') == 'Aria Renewed' for i in row['issues']))
            index = next(i for i, issue in enumerate(row['issues']) if issue.get('replacement') == 'Aria Renewed')
            review._toggle_issue(row['cue_id'], index)
            live, _ = review._live_project()
            check('normal review page applies target rule', st.records_of(live)['review-identity']['text'] == 'Miss Aria Renewed has arrived.')
            check('normal review preserves identity and timing', live.cues[0].id == 'review-identity' and
                  (live.cues[0].start_ms, live.cues[0].end_ms, live.cues[0].text) == (100, 1800, '艾莉娅小姐来了'))
            review._undo()
            check('normal review page undo', st.records_of(live)['review-identity']['text'] == 'Miss Alyria has arrived.')
            faulthandler.cancel_dump_traceback_later(); trace_stream.close()
            from ..design.theme_manager import apply_theme
            for theme in ('warm', 'grape'):
                apply_theme(theme); QTest.qWait(250); shot('06-' + theme)
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            if 'review' in locals():
                result['review_debug'] = dict(status=review.status_label.text(), visible=review.isVisible(),
                    page_left=getattr(review, '_page_left', None), checks_pending=getattr(review, '_checks_pending', None),
                    queued=str(review._queued), worker=str(review._worker),
                    rows=len(review._rows), issues=[str(row.get('issues')) for row in review._rows])
        finally:
            if 'trace_stream' in locals() and not trace_stream.closed:
                faulthandler.cancel_dump_traceback_later(); trace_stream.close()
            (output / 'multilingual-terms.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
            window._allow_exit_without_prompt = True
            QApplication.instance().quit()
    QTimer.singleShot(450, run)
