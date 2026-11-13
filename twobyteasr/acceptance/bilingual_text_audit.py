"""Owned synthetic bilingual projects through the normal Windows application."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import traceback
import sys


def fixture(count=4, media='', glossary_id=''):
    from ..projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
    from ..subtitle_rules import subtitle_translation as st
    p = SubtitleProject(StudioMedia(media, duration_ms=max(12000, count * 1800)),
        cues=[StudioCue(f'source-{i:04d}', i*1800, i*1800+1600,
                       f'SHARED Neuvillette wins round {i}.', speaker_id='S01') for i in range(count)],
        speakers=[StudioSpeaker('S01', 'Alice'), StudioSpeaker('japanese', '日本語・独立訳'),
                  StudioSpeaker('chinese-import', '中文独立译文')], glossary_ids=[glossary_id] if glossary_id else [],
        generation_metadata={'language': {'code':'en','requested':'en'}, 'subtitle_imports': {'version': 1, 'tracks': {
            'japanese': {'language': 'ja', 'role': 'translation'},
            'chinese-import': {'language': 'zh-Hans', 'role': 'translation'}}, 'cues': {}}},
        studio_state={'bilingual': {'mode': 'bilingual'}})
    container = st._empty_container('zh-Hans')
    for cue in p.cues:
        container['records'][cue.id] = st._record('SHARED 那维来特赢了第' + cue.id.rsplit('-', 1)[1] + '局。',
                                                 cue.text, origin=st.ORIGIN_MANUAL, target='zh-Hans')
    p.generation_metadata[st.RECORDS_KEY] = container
    p.cues += [StudioCue('independent-japanese', 0, 5000, 'SHARED ヌヴィレットの勝利。', speaker_id='japanese'),
               StudioCue('independent-zh-split1', 5000, 6000, '那维来特出现了', speaker_id='chinese-import'),
               StudioCue('independent-zh-split2', 6000, 7200, '那维来特赢了', speaker_id='chinese-import')]
    p.validate()
    st._rebuild_view(p)
    return p


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture

    def run():
        from ..diagnostics.build_identity import load_build_identity
        result = {'passed': False, 'checks': [], 'timings_ms': {}, 'scope':
                  'normal source entry, Windows private desktop, synthetic media/projects, offline simulated AI'}
        result.update(identity=load_build_identity().to_dict(),frozen=bool(getattr(sys,'frozen',False)),
                      process_executable=sys.executable,gui_shutdown=False)
        def save():
            (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
        def check(name, condition, detail=None):
            result['checks'].append({'name': name, 'passed': bool(condition), 'detail': detail})
            save()
            if not condition:
                raise AssertionError(name + ': ' + str(detail))
        def pump(seconds=.15):
            deadline = time.perf_counter() + seconds
            while time.perf_counter() < deadline:
                QApplication.processEvents()
                time.sleep(.005)
        def wait(predicate, seconds=35):
            deadline = time.perf_counter() + seconds
            while time.perf_counter() < deadline:
                pump(.035)
                if predicate():
                    return True
            return False
        def timed(name, action):
            before = time.perf_counter()
            value = action()
            if dialog is not None:
                wait(lambda:not getattr(dialog,'_search_pending',False) and not dialog._search_timer.isActive())
            result['timings_ms'][name] = round((time.perf_counter()-before)*1000, 2)
            save()
            return value
        dialog = None
        try:
            from ..studio.studio_find_replace import FindReplaceDialog
            from ..studio.subtitle_text_targets import text_entries
            from ..subtitle_rules import subtitle_translation as st
            from ..projects.studio_project import save_project, load_project
            from ..exports.studio_subtitle_export import export_language_layers
            from ..exports.srt_codec import parse_srt
            page = window.studio_page
            window._switch_page(page)
            page.project_controller.open_project_entry(os.environ['TWOBYTEASR_STARTUP_PROJECT'],
                                                       single_shot_fn=QTimer.singleShot, skip_dirty_guard=True)
            check('startup project ready', wait(lambda: page.project is not None and page._project_view_state == 'open'))
            page.video.set_paused(True)
            for layer in ('original','translation'):
                page.select_cue('source-0000')
                page.timeline.set_subtitle_layer(layer)
                pump(.1)
                index=page.cue_model.index(page.cue_model.row_for_cue_id('source-0000'),3)
                page.cue_table.scrollTo(index)
                pump(.05)
                position=page.cue_table.visualRect(index).center()
                before_index=page.undo_stack.index()
                source_before=page.project.cues[0].text
                translated_before=st.records_of(page.project)['source-0000']['text']
                QTest.mouseClick(page.cue_table.viewport(),Qt.LeftButton,pos=position)
                QTest.mouseDClick(page.cue_table.viewport(),Qt.LeftButton,pos=position)
                pump(.1)
                check('actual '+layer+' double click has one editor',page._caption_draft is not None and
                      page._caption_draft.target.layer==layer and not page.cue_model.flags(index)&Qt.ItemIsEditable)
                page.subtitle_edit_input.setPlainText('')
                QTest.mouseClick(page.caption_cancel_button,Qt.LeftButton)
                pump(.15)
                check('actual '+layer+' double click cancel keeps both texts',page.project.cues[0].text==source_before and
                      st.records_of(page.project)['source-0000']['text']==translated_before and page.undo_stack.index()==before_index)
            page.select_cue('source-0000')
            page.timeline.select_translation('source-0000')
            original = {c.id: c.text for c in page.project.cues}
            japanese = original['independent-japanese']
            page.cue_proofread_action.trigger()
            check('normal AI proofreading entry', wait(lambda: getattr(window, 'glossary_proofread_page', None) is not None))
            review = window.glossary_proofread_page
            # 2026-11-13: the page opens on 原文＋译文 side by side, on the track the entry chose.
            check('translation entry default', review.text_targets.mode_value() == 'both'
                  and review.text_targets.track.currentData() == 'translation-records:zh-Hans' and review.list.paired)
            review.text_targets.mode.setCurrentIndex(review.text_targets.mode.findData('translation'))
            review.text_targets.track.setCurrentIndex(review.text_targets.track.findData('translation-records:zh-Hans'))
            check('initial local checks settle', wait(lambda: not review.checks_running()))
            check('source text is reference', all(row['source_text'].startswith('SHARED Neuvillette') for row in review._rows))
            seen = []
            class OfflineProvider:
                def complete(self, messages, **kwargs):
                    payload = json.loads(messages[1]['content'])
                    seen.append(payload)
                    return {'changes': [{'target_id': row['target_id'], 'original': row['target_text'],
                        'replacement': row['target_text'].replace('那维来特','那维莱特'), 'reason': '离线验收：角色译名'}
                        for row in payload['targets']]}
            import twobyteasr.providers.ai_providers as providers
            previous_provider = providers.provider_for_stage
            providers.provider_for_stage = lambda *args, **kwargs: OfflineProvider()
            from ..glossary.studio_glossary_service import preview_glossary_correction
            review.ai_stand_in = lambda *args, **kwargs: preview_glossary_correction(*args, **kwargs, use_ai=True)
            QTest.mouseClick(review.ai_button, Qt.LeftButton)
            check('AI request uses real language-specific request builder', wait(lambda: bool(seen) and not review.checks_running()))
            check('AI request targets Chinese translation only', all(row['layer']=='translation' and row['language']=='zh-Hans'
                  for payload in seen for row in payload['targets']))
            review.filter_buttons['suggested'].setChecked(True)
            review.search.setText('那维来特')
            review._apply_filter()
            row = next(row for row in review._rows if row['target'].cue_id == 'source-0000')
            key = row['cue_id']
            check('translation proposal exists', bool(row['issues']))
            review.list.ensure_visible(key)
            pump()
            _capture(window, output/'proofread-before.png')
            review._toggle_issue(key, 0)
            pump()
            check('translation suggestion writes translation', '那维莱特' in st.records_of(page.project)['source-0000']['text'])
            check('applied suggestion stays in filtered list', review._row_indexes[key] in review.list.visible and bool(review._by_id[key]['issues']))
            check('English and Japanese unchanged by AI', page.project.cues[0].text == original['source-0000'] and
                  next(c.text for c in page.project.cues if c.id=='independent-japanese') == japanese)
            _capture(window, output/'proofread-applied-retained.png')
            providers.provider_for_stage = previous_provider
            review.ai_stand_in = None
            QTest.mouseClick(review.back_button, Qt.LeftButton)
            pump(.4)
            page.select_cue('source-0001')
            page.timeline.select_translation('source-0001')
            dialog = FindReplaceDialog(page, page)
            dialog.show()
            dialog.text_targets.track.setCurrentIndex(dialog.text_targets.track.findData('translation-records:zh-Hans'))
            dialog.find_edit.setText('那维来特')
            dialog.replace_edit.setText('那维莱特')
            dialog._do_preview()
            wait(lambda:not getattr(dialog,'_search_pending',False) and not dialog._search_timer.isActive())
            check('translation search results visible', dialog.preview.count() == 3)
            check('result identifies layer and language', all('译文' in dialog.preview.item(i).text() and '简体中文' in dialog.preview.item(i).text()
                  for i in range(dialog.preview.count())))
            dialog.grab().save(str(output/'replace-before.png'))
            item = next(dialog.preview.item(i) for i,h in enumerate(dialog._preview_hits) if h.cue_id=='source-0001')
            dialog._preview_item_clicked(item)
            check('result navigation selects translation layer', page.timeline.active_subtitle_layer == 'translation' and
                  page.session.selected_cue_id == 'source-0001')
            check('navigation keeps snapshot applicable', dialog._preview_binding.matches(page.project))
            index_before = page.undo_stack.index()
            QTest.mouseClick(dialog.all_button, Qt.LeftButton)
            pump(.25)
            check('bulk translation replacement is one undo', page.undo_stack.index()==index_before+1)
            check('all selected translations updated', all('那维莱特' in e.text for e in text_entries(page.project, mode='translation', tracks={'translation-records:zh-Hans'})))
            check('selected translation editor updates', '那维莱特' in page.translation_text.toPlainText(), page.translation_text.toPlainText())
            row_index=page.cue_model.index(page.cue_model.row_for_cue_id('source-0001'),3)
            check('workbench subtitle list displays updated translation', '那维莱特' in page.cue_model.data(row_index,Qt.DisplayRole))
            corrected=st.records_of(page.project)['source-0001']['text']
            page.cue_model.setData(row_index,corrected+' · 列表编辑验收')
            check('workbench list editor writes selected translation only', st.records_of(page.project)['source-0001']['text']==corrected+' · 列表编辑验收'
                  and next(c.text for c in page.project.cues if c.id=='source-0001')==original['source-0001'])
            page.undo_stack.undo()
            check('source editor remains English', page.cue_text.toPlainText() == original['source-0001'])
            check('result list refreshes after replacement', dialog.preview.count()==0)
            page.undo_stack.undo()
            check('undo restores translation and editor', '那维来特' in page.translation_text.toPlainText())
            page.undo_stack.redo()
            check('redo restores corrected translation', '那维莱特' in page.translation_text.toPlainText())
            dialog.close()
            dialog = None
            page._seek(2.2)
            page._refresh_ass_preview()
            pump(.8)
            from ..projects.studio_revisions import thaw_json
            check('render revision reflects translation edit', '那维莱特' in
                  thaw_json(page._revision_store.render.generation_metadata)['translations']['source-0001'])
            from ..caption_style.bilingual_layout import companion_id
            check('prepared preview translation cache refreshed', wait(lambda:
                  page._prepared_caption(companion_id('source-0001')) is not None and
                  '那维莱特' in page._prepared_caption(companion_id('source-0001')).snapshot.text))
            scene = page._caption_scene
            check('corrected translation pixels published to video', wait(lambda:
                  scene.published is not None and any(metric.get('posted') and any(
                      row.get('cue_id') == companion_id('source-0001') and row.get('alpha_nonzero', 0)>0
                      for row in metric.get('cue_pixels', ())) for metric in scene.metrics)))
            _capture(window, output/'studio-after.png')
            controller = page.video.controller
            check('native player is running', controller is not None and controller.running)
            controller.screenshot_to_file(str(output/'native-preview-after.png'), mode='window')
            check('native window frame captured', wait(lambda: (output/'native-preview-after.png').is_file()))
            saved = output/'lifecycle.2byteproj'
            save_project(page.project, saved)
            reopened = load_project(saved)
            check('save and reopen records match', st.translation_view(reopened)==st.translation_view(page.project))
            exported = export_language_layers(reopened, output/'export', '双语验收', layers=('translation','bilingual'))
            for artifact in exported.artifacts:
                rows, errors = parse_srt(artifact.path.read_text('utf-8'))
                check('read-back '+artifact.layer, not errors and any('那维莱特' in row.text for row in rows))
            page.project_controller.open_project(saved, single_shot_fn=QTimer.singleShot, skip_dirty_guard=True)
            pump(.4)
            check('actual Studio reopen reads corrected records', '那维莱特' in st.records_of(page.project)['source-0001']['text'])
            # Explicitly enter editing through a translation search result.
            dialog = FindReplaceDialog(page,page)
            dialog.text_targets.mode.setCurrentIndex(1)
            dialog.text_targets.track.setCurrentIndex(dialog.text_targets.track.findData('translation-records:zh-Hans'))
            dialog.find_edit.setText('那维莱特')
            dialog._do_preview()
            wait(lambda:not getattr(dialog,'_search_pending',False) and not dialog._search_timer.isActive())
            dialog._edit_preview_item(dialog.preview.item(0))
            draft=getattr(page,'_caption_draft',None)
            check('search result opens translation text editor', draft is not None and draft.target.layer=='translation'
                  and '那维莱特' in page.subtitle_edit_input.toPlainText())
            page._cancel_canvas_inline_edit()
            dialog.close()
            dialog = None
            # The large project uses the same real workbench/controllers.
            big = fixture(2000)
            big_path = output/'large-2000.2byteproj'
            save_project(big,big_path)
            timed('open_large_project', lambda: page.project_controller.open_project(big_path, single_shot_fn=QTimer.singleShot, skip_dirty_guard=True))
            pump(.5)
            dialog = FindReplaceDialog(page,page)
            dialog.show()
            dialog.find_edit.setText('SHARED')
            dialog.replace_edit.setText('UPDATED')
            timed('search_2000_original', dialog._do_preview)
            check('large original matches', len(dialog._preview_hits)==2000)
            timed('switch_to_translation', lambda: dialog.text_targets.mode.setCurrentIndex(1))
            dialog.text_targets.track.setCurrentIndex(dialog.text_targets.track.findData('translation-records:zh-Hans'))
            timed('search_2000_translation', dialog._do_preview)
            check('large translation matches', len(dialog._preview_hits)==2000)
            dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData('selected'))
            timed('switch_to_selected_scope_and_search',dialog._do_preview)
            check('large selected scope matches one translation', len(dialog._preview_hits)==1)
            dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData('all'))
            dialog.text_targets.mode.setCurrentIndex(2)
            timed('search_4000_both', dialog._do_preview)
            check('large both matches separately', len(dialog._preview_hits)==4000)
            dialog.text_targets.mode.setCurrentIndex(1)
            dialog._do_preview()
            wait(lambda:not getattr(dialog,'_search_pending',False) and not dialog._search_timer.isActive())
            if os.environ.get('TWOBYTEASR_AUDIT_PROFILE'):
                import cProfile
                profiler = cProfile.Profile()
                timed('replace_2000_translation_profiled', lambda: profiler.runcall(dialog._do_apply_preview))
                profiler.dump_stats(str(output/'replace-profile.pstats'))
            else:
                timed('replace_2000_translation_including_result_refresh', dialog._do_apply_preview)
            check('large bulk replacement applied', all('UPDATED' in r['text'] for r in st.records_of(page.project).values()))
            timed('undo_2000_translation', page.undo_stack.undo)
            check('large undo is complete', all('SHARED' in r['text'] for r in st.records_of(page.project).values()))
            timed('redo_2000_translation', page.undo_stack.redo)
            check('large redo is complete', all('UPDATED' in r['text'] for r in st.records_of(page.project).values()))
            dialog.grab().save(str(output/'large-results.png'))
            dialog.close()
            dialog = None
            result['passed'] = all(row['passed'] for row in result['checks'])
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            if dialog is not None:
                dialog.close()
            save()
            review = getattr(window,'glossary_proofread_page',None)
            if review is not None:
                review.shutdown()
            page = window.studio_page
            if page.project is not None:
                save_project(page.project, output/'final-owned.2byteproj')
                page.undo_stack.setClean()
                page.project_dirty = False
            window.close()
            result['gui_shutdown']=True
            save()
            QTimer.singleShot(500, QApplication.instance().quit)
    QTimer.singleShot(1500, run)
