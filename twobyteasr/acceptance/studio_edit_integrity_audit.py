"""Actual window evidence for caption transactions and terminology drafts."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QDialog, QRadioButton, QComboBox, QTableWidgetItem
    from ..projects.studio_project import save_project, load_project
    from ..projects.studio_runtime_state import state_for
    from ..timeline.studio_selection import ClipSelection
    from ..timeline.studio_commands import SetCueFieldsCommand
    from ..subtitle_rules import subtitle_translation as st
    from ..glossary.translation_terms import KEY, policy_of, relevant
    from ..glossary.translation_terms_ui import TranslationTermsDialog, project_widget
    from ..glossary.translation_terms_import import parse_libraries

    def run():
        result = dict(passed=False, checks=[], timings_ms={}, gui_shutdown=False, frozen=bool(getattr(sys, 'frozen', False)),
                      scope='normal MainWindow, private Windows desktop, isolated synthetic original+translation project, offline')
        dialogs = []
        def save(): (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        def check(name, ok, detail=None):
            result['checks'].append(dict(name=name, passed=bool(ok), detail=detail)); save()
            if not ok: raise AssertionError(name + ': ' + str(detail))
        def pump(seconds=.08):
            end = time.perf_counter()+seconds
            while time.perf_counter() < end:
                QApplication.processEvents(); time.sleep(.005)
        def wait(predicate, seconds=60):
            end=time.perf_counter()+seconds
            while time.perf_counter()<end:
                pump(.04)
                if predicate(): return True
            return False
        def timed(name, fn):
            begin=time.perf_counter(); value=fn()
            result['timings_ms'].setdefault(name, []).append(round((time.perf_counter()-begin)*1000, 3)); save()
            return value
        def shot(widget, name):
            pump(.12)
            pix=widget.grab(); check(name+' actual pixels', not pix.isNull() and pix.width()>100 and pix.height()>30)
            check(name+' saved', pix.save(str(output/(name+'.png'))))
        page = window.studio_page
        try:
            window._switch_page(page)
            page.project_controller.open_project_entry(os.environ['TWOBYTEASR_STARTUP_PROJECT'],
                single_shot_fn=QTimer.singleShot, skip_dirty_guard=True)
            check('normal project ready', wait(lambda: page.project is not None and page._project_view_state=='open'))
            check('page visible', page.isVisible())
            p=page.project; t=page.timeline
            result.update(cue_count=len(p.cues), translation_count=len(p.generation_metadata.get('translations', {})),
                          dpr=window.devicePixelRatioF())
            if os.environ.get('TWOBYTEASR_EDIT_INTEGRITY_RESTART')=='1':
                expected=json.loads((output/'expected.json').read_text('utf8'))
                check('fresh process caption state', [c.id for c in p.cues]==expected['ids'])
                check('fresh process terminology state', policy_of(p)==expected['policy'])
                check('fresh process translations', p.generation_metadata.get('translations')==expected['translations'])
                check('fresh process global terminology',window.translation_term_libraries.read()==expected['global_terms'])
                shot(window,'fresh-process')
                result['passed']=True
                return
            t.set_visible_window(0, 20000)
            QApplication.setActiveWindow(window); t.setFocus(); pump(.2)
            original_ids={c.id for c in p.cues}
            initial_count=len(p.cues)
            thumbs=t._thumbnails
            source_before={c.id:c.text for c in p.cues[:2]}
            t.select_translation('cue-00000');t.select_translation('cue-00001',extend=True);t.setFocus();pump()
            commit_before=state_for(p).commit_count
            timed('translation_delete',lambda:QTest.keyClick(t,Qt.Key_Delete))
            check('generated translation delete keeps source objects',all(
                next(c for c in p.cues if c.id==key).text==text for key,text in source_before.items()))
            check('generated multi translation delete commits once',state_for(p).commit_count==commit_before+1
                  and all(key not in p.generation_metadata['translations'] for key in source_before))
            page.undo_stack.undo();check('generated translation delete undo restores associations',all(
                key in p.generation_metadata['translations'] for key in source_before))
            page.undo_stack.redo();check('generated translation delete redo clears only selected',all(
                key not in p.generation_metadata['translations'] for key in source_before) and 'cue-00002' in p.generation_metadata['translations'])
            page.undo_stack.undo()
            def choose(ids):
                t.set_subtitle_layer('original'); t._publish_clip_selection(ClipSelection(cue_ids=set(ids)))
                t.setFocus(); pump(.05)
            def consistent(deleted):
                check('deleted canonical data', not set(deleted)&{c.id for c in p.cues})
                check('deleted runtime index', not set(deleted)&set(state_for(p).cue_by_id))
                check('deleted timeline paint/hit index', not set(deleted)&set(t._timeline_cue_by_id))
                check('deleted visible window', not set(deleted)&{c.id for c in t.visible_cues()})
                check('deleted table rows', all(page.cue_model.row_for_cue_id(key)<0 for key in deleted))
                check('deleted linked translation', not set(deleted)&set(p.generation_metadata.get('translations',{}))
                      and not set(deleted)&set(st.records_of(p)))
            for ids in (['cue-00000'], ['cue-00001','cue-00003'], ['cue-00002']):
                choose(ids)
                timed('delete_key', lambda: QTest.keyClick(t, Qt.Key_Delete))
                consistent(ids)
                timed('delete_undo', page.undo_stack.undo)
                check('undo restores captions and associations', set(ids)<={c.id for c in p.cues}
                      and set(ids)<=set(p.generation_metadata['translations']))
                timed('delete_redo', page.undo_stack.redo); consistent(ids)
            check('caption edits retain media workers', thumbs is t._thumbnails)
            shot(t,'deleted-timeline')
            deleted_ids=original_ids-{c.id for c in p.cues}
            retained=[c for c in p.cues if c.start_ms<20000][:2]
            check('multi-copy fixture', len(retained)==2)
            choose([c.id for c in retained])
            source_text={c.id:c.text for c in retained}
            QTest.keyClick(t, Qt.Key_C, Qt.ControlModifier)
            t.playhead_ms=10000
            before={c.id for c in p.cues}; before_stack=page.undo_stack.count()
            timed('paste_key', lambda: QTest.keyClick(t, Qt.Key_V, Qt.ControlModifier))
            copies=[c for c in p.cues if c.id not in before]
            check('Ctrl C/V copies actual objects', len(copies)==2 and page.undo_stack.count()==before_stack+1)
            copies.sort(key=lambda c:c.start_ms)
            check('playhead relative times', copies[0].start_ms==10000 and
                  copies[1].start_ms-copies[0].start_ms==retained[1].start_ms-retained[0].start_ms)
            check('copied linked translations', all(c.id in p.generation_metadata['translations'] for c in copies))
            timed('copy_undo', page.undo_stack.undo)
            check('copy undo removes only copies', {c.id for c in p.cues}==before)
            timed('copy_redo', page.undo_stack.redo)
            copy_id=copies[0].id
            page.undo_stack.push(SetCueFieldsCommand(p, copy_id, {'text':'副本独立编辑'}, '编辑副本'))
            check('copy edit cannot change source', all(next(c for c in p.cues if c.id==key).text==text for key,text in source_text.items()))
            # Real Qt input on the timeline: no model mutations during the gesture.
            choose([c.id for c in retained]); t.set_visible_window(5000, 20000); pump()
            rect=t._track_layout()[0][retained[0].speaker_id]
            point=QPoint(round(t._time_to_x(retained[0].start_ms+500)), round(rect.center().y()))
            before={c.id for c in p.cues}; count=page.undo_stack.count()
            QTest.mousePress(t,Qt.LeftButton,Qt.AltModifier,point)
            QTest.mouseMove(t,point+QPoint(95,0)); pump()
            check('Alt preview has frozen copy payload', bool(t._group_drag and t._group_drag.get('copy')
                  and getattr(t._group_drag['selection'],'caption_payload',None)))
            check('Alt move creates no data or undo', {c.id for c in p.cues}==before and page.undo_stack.count()==count)
            shot(t,'alt-copy-preview')
            QTest.keyClick(t,Qt.Key_Escape); QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,point+QPoint(95,0))
            check('Alt cancel leaves no copies', {c.id for c in p.cues}==before and page.undo_stack.count()==count)
            choose([c.id for c in retained])
            QTest.mousePress(t,Qt.LeftButton,Qt.AltModifier,point); QTest.mouseMove(t,point+QPoint(95,0))
            timed('alt_release',lambda:QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,point+QPoint(95,0)))
            check('Alt release one group copy', len(p.cues)==len(before)+2 and page.undo_stack.count()==count+1)
            timed('alt_undo',page.undo_stack.undo); check('Alt undo whole group', {c.id for c in p.cues}==before)
            timed('alt_redo',page.undo_stack.redo)
            # Generated translation becomes an independent editable translation track.
            source=retained[0]; original=copy.deepcopy(next(c for c in p.cues if c.id==source.id))
            t.select_translation(source.id); t.setFocus(); QTest.keyClick(t,Qt.Key_C,Qt.ControlModifier)
            t.playhead_ms=15000; before={c.id for c in p.cues}
            timed('translation_paste',lambda:QTest.keyClick(t,Qt.Key_V,Qt.ControlModifier))
            new=[c for c in p.cues if c.id not in before]
            check('translation copy creates only one independent caption', len(new)==1 and new[0].text==p.generation_metadata['translations'][source.id])
            check('translation copy retains original', next(c for c in p.cues if c.id==source.id)==original)
            check('translation copy track metadata', p.generation_metadata['subtitle_imports']['tracks'][new[0].speaker_id]['role']=='translation')
            page.undo_stack.undo(); check('translation undo keeps original', {c.id for c in p.cues}==before)
            page.undo_stack.redo()
            # Translated Alt-drag is a frozen translation copy, never a source move.
            t.select_translation(source.id);t.setFocus();t.set_visible_window(5000,20000)
            t.vertical_scrollbar.setValue(t.vertical_scrollbar.maximum());pump()
            tr_rect=t._track_layout()[1]
            check('translation lane exists for Alt copy',tr_rect is not None)
            tr_point=QPoint(round(t._time_to_x(source.start_ms+500)),round(tr_rect.center().y()))
            check('translation Alt pointer is in visible subtitle viewport',t._track_viewport().contains(tr_point))
            before_tr={c.id for c in p.cues};undo_tr=page.undo_stack.count()
            QTest.mousePress(t,Qt.LeftButton,Qt.AltModifier,tr_point);QTest.mouseMove(t,tr_point+QPoint(80,0))
            check('translation Alt copy is a preview',t._group_drag is not None and len(p.cues)==len(before_tr),
                dict(selection_ids=list(t._group_drag['selection'].cue_ids) if t._group_drag else [],
                     layer=getattr(t._group_drag['selection'],'subtitle_layer','') if t._group_drag else '',
                     delta=t._group_drag.get('delta') if t._group_drag else None,
                     copy=t._group_drag.get('copy') if t._group_drag else None))
            QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,tr_point+QPoint(80,0))
            tr_copies=[c for c in p.cues if c.id not in before_tr]
            check('translation Alt release copies translated text once',len(tr_copies)==1
                  and tr_copies[0].text==p.generation_metadata['translations'][source.id] and page.undo_stack.count()==undo_tr+1,
                  dict(copies=[dict(id=c.id,text=c.text) for c in tr_copies], expected=p.generation_metadata['translations'][source.id],
                       undo_before=undo_tr,undo_after=page.undo_stack.count(),hint=page.save_state.text()))
            check('translation Alt never moves original',next(c for c in p.cues if c.id==source.id)==original)
            page.undo_stack.undo();check('translation Alt undo whole copy',{c.id for c in p.cues}==before_tr)
            page.undo_stack.redo()
            editor=QLineEdit('文本框正常复制',page);editor.setGeometry(20,80,320,40);editor.show();editor.setFocus();editor.selectAll();pump()
            count=len(p.cues); QTest.keyClick(editor,Qt.Key_C,Qt.ControlModifier); editor.clear(); QTest.keyClick(editor,Qt.Key_V,Qt.ControlModifier)
            check('text input owns copy/paste', editor.text()=='文本框正常复制' and len(p.cues)==count)
            editor.setReadOnly(True);editor.setFocus();editor.selectAll();pump(.08)
            QTest.keyClick(editor,Qt.Key_C,Qt.ControlModifier);pump(.08)
            check('read-only text copy also owns clipboard',QApplication.clipboard().text()=='文本框正常复制' and len(p.cues)==count,
                  dict(text=editor.text(),selected=editor.selectedText(),clipboard=QApplication.clipboard().text(),
                       focus=type(QApplication.focusWidget()).__name__,count_before=count,count_after=len(p.cues)))
            editor.close(); editor.deleteLater();t.setFocus()
            # Main project terminology widget: the caller commits only Accepted.
            widget=project_widget(page); dialogs.append(widget)
            original_policy=policy_of(p)
            def edit_terms(accept):
                def act():
                    d=QApplication.activeModalWidget()
                    if not isinstance(d,TranslationTermsDialog):
                        QTimer.singleShot(30,act);return
                    try:
                        d.list.setCurrentRow(0)
                        # Exercise the real choice dialog and its default target.
                        def mode():
                            modal=QApplication.activeModalWidget()
                            radios=modal.findChildren(QRadioButton)
                            check('append defaults to highlighted library', any(r.isChecked() and '鸣潮' in r.text() for r in radios))
                            shot(modal,'append-choice'); modal.accept()
                        QTimer.singleShot(50,mode)
                        check('append mode choice', d.choose_import_mode()=='append')
                        libs=parse_libraries('新語\t新译名',is_json=False,name='追加',source_language='ja',target_language='zh-Hans')
                        check('append new term count',d.apply_import(libs,mode='append')['added']==1)
                        check('repeat import duplicate count',d.apply_import(libs,mode='append')['duplicates']==1)
                        d.add_term_button.click(); row=d.table.rowCount()-1
                        d.table.setItem(row,0,QTableWidgetItem('手動'));d.table.setItem(row,1,QTableWidgetItem('手动'))
                        incoming=copy.deepcopy(d.value()['libraries'][0]);incoming['terms']=[dict(source='アリス',target='艾丽丝',aliases=[],context='人物')]
                        from ..glossary.translation_terms_import import merge_library
                        conflicts=merge_library(d.value()['libraries'][0],incoming)[2]
                        def resolve():
                            modal=QApplication.activeModalWidget();boxes=modal.findChildren(QComboBox)
                            check('conflict defaults keep existing',all(b.currentData()=='keep' for b in boxes))
                            boxes[0].setCurrentIndex(1);shot(modal,'term-conflict');modal.accept()
                        QTimer.singleShot(50,resolve)
                        decisions=d.choose_conflicts(conflicts)
                        d.apply_import([incoming],mode='append',decisions=decisions)
                        shot(d,'terms-appended')
                        if accept:d.accept()
                        else:d.reject()
                    except Exception:
                        result['modal_error']=traceback.format_exc();d.reject()
                QTimer.singleShot(100,act); widget.manage.click(); pump()
                check('term modal completed',not result.get('modal_error'),result.get('modal_error'))
            edit_terms(False);check('Cancel never commits terminology',policy_of(p)==original_policy)
            edit_terms(True)
            check('Accept retains current library identity', [l['id'] for l in policy_of(p)['libraries']]==['a','b'])
            check('manual term survives committed policy', any(r['source']=='手動' for r in policy_of(p)['libraries'][0]['terms']))
            # Entire-library delete targets the highlight, not checked libraries.
            def confirm_delete(d, expected_name, expected_count, screenshot):
                def confirm():
                    modal=QApplication.activeModalWidget()
                    if not isinstance(modal,QMessageBox):QTimer.singleShot(20,confirm);return
                    try:
                        check('delete confirmation names whole selected library',expected_name in modal.text()
                              and str(expected_count) in modal.text() and '整份' in modal.text())
                        shot(modal,screenshot);modal.button(QMessageBox.Yes).click()
                    except Exception:
                        result['modal_error']=traceback.format_exc();modal.reject()
                QTimer.singleShot(50,confirm);d.delete_button.click()
            def delete_terms():
                d=QApplication.activeModalWidget()
                if not isinstance(d,TranslationTermsDialog):QTimer.singleShot(30,delete_terms);return
                try:
                    d.list.setCurrentRow(1)
                    confirm_delete(d,'废案',1,'delete-confirmation')
                    check('delete keeps other checked library', [l['id'] for l in d.value()['libraries']]==['a'])
                    shot(d,'library-deleted');d.accept()
                except Exception:result['modal_error']=traceback.format_exc();d.reject()
            QTimer.singleShot(80,delete_terms);widget.manage.click();pump()
            check('delete modal completed',not result.get('modal_error'),result.get('modal_error'))
            check('deleted library absent from runtime lookup',not relevant(policy_of(p),'ja','zh-Hans','石'))
            page.undo_stack.undo();check('library delete undo restores lookup',bool(relevant(policy_of(p),'ja','zh-Hans','石')))
            page.undo_stack.redo()
            before_empty=policy_of(p)
            def empty_terms():
                d=QApplication.activeModalWidget()
                if not isinstance(d,TranslationTermsDialog):QTimer.singleShot(25,empty_terms);return
                try:
                    count=len(d.value()['libraries'][0]['terms'])
                    confirm_delete(d,'鸣潮',count,'delete-last-confirmation')
                    check('last deleted library has normal empty editor',d.list.count()==d.table.rowCount()==0
                          and not d.delete_button.isEnabled() and not d.add_term_button.isEnabled())
                    shot(d,'empty-library');d.reject()
                except Exception:result['modal_error']=traceback.format_exc();d.reject()
            QTimer.singleShot(60,empty_terms);widget.manage.click();pump()
            check('cancel last-library deletion preserves saved library',policy_of(p)==before_empty and not result.get('modal_error'))
            # The same dialog also owns application defaults; read the saved
            # isolated settings again, rather than relying on its UI draft.
            home_widget=window.translation_term_libraries
            global_before=copy.deepcopy(home_widget.read())
            def global_terms(accepted):
                def act():
                    d=QApplication.activeModalWidget()
                    if not isinstance(d,TranslationTermsDialog):QTimer.singleShot(25,act);return
                    d.add_library();d.name.setText('默认译文库')
                    d.add_term_button.click();row=d.table.rowCount()-1
                    d.table.setItem(row,0,QTableWidgetItem('追加語'));d.table.setItem(row,1,QTableWidgetItem('追加词'))
                    if accepted:d.accept()
                    else:d.reject()
                QTimer.singleShot(60,act);home_widget.manage.click();pump()
            global_terms(False);check('global library Cancel leaves settings intact',home_widget.read()==global_before)
            global_terms(True)
            from ..storage.settings import load_runtime_settings
            stored=load_runtime_settings()[0].get('glossary',{}).get(KEY,{})
            check('global accepted terminology actually saved',stored==home_widget.read()
                  and any(lib['name']=='默认译文库' for lib in stored['libraries']))
            # Exercise the real queue boundary and Chinese self-test under Japanese task state.
            import subtitle_core as core
            from ..subtitle_rules.language_rules import language_scope, active_task_language
            with language_scope('ja'):
                check('startup guard succeeds in Japanese task',core.run_startup_self_test()['checks']>=10)
                check('startup guard restores caller language',active_task_language()=='ja')
            from ..app.completion_dialog import CompletionDialog,delivery_hint
            failure=CompletionDialog('字幕任务异常中止','没有可用结果',QMessageBox.Critical,'自检故障注入',window,
                result_hint=delivery_hint([]));dialogs.append(failure);failure.show();pump()
            check('failure footer never claims synchronization','已同步' not in failure.delivery_hint.text())
            shot(failure,'failure-no-results');failure.close()
            from types import SimpleNamespace
            partial_hint=delivery_hint([(SimpleNamespace(status='success'),p),(SimpleNamespace(status='failed'),None)],page)
            check('partial synchronized footer states partial result',partial_hint=='部分结果已同步到工作台')
            previous_ids=[c.id for c in p.cues]
            page.fail_recognition_runtime('隔离故障注入：没有可用结果')
            check('failed recognition preserves current authored captions',[c.id for c in p.cues]==previous_ids
                  and next(c for c in p.cues if c.id==copy_id).text=='副本独立编辑')
            page._seek(15.5);page._refresh_ass_preview();pump(1.)
            check('render snapshot omits deleted captions',not deleted_ids&{c.id for c in page._revision_store.render.cues})
            check('prepared cache cannot return deleted captions',all(page._prepared_caption(key) is None for key in deleted_ids))
            controller=page.video.controller
            check('preview controller running',controller is not None and controller.running)
            controller.screenshot_to_file(output/'native-preview.png',mode='window')
            check('composed preview captured',wait(lambda:(output/'native-preview.png').is_file(),10))
            from PIL import Image
            extrema=Image.open(output/'native-preview.png').convert('RGB').getextrema()
            check('preview contains visible subtitle pixels',any(high-low>50 for low,high in extrema),extrema)
            from .blank_project_audit import _capture
            _capture(window,output/'native-window.png')
            # Persist and independently parse the same canonical model used by export.
            from ..exports.studio_subtitle_export import export_language_layers
            exported=export_language_layers(p,output/'exports','edited',layers=['original','translation'])
            check('exports exist',bool(exported.artifacts) and all(a.path.is_file() for a in exported.artifacts))
            check('exports contain no deleted originals',all(f'原文字幕第{int(key.split("-")[-1]):05d}条' not in
                a.path.read_text('utf-8-sig') for key in deleted_ids for a in exported.artifacts if a.layer=='original'))
            save_project(p,output/'saved-result.2byteproj')
            reloaded=load_project(output/'saved-result.2byteproj')
            check('saved reload has exact IDs', [c.id for c in reloaded.cues]==[c.id for c in p.cues])
            check('saved reload has no deleted captions', not deleted_ids&{c.id for c in reloaded.cues})
            check('saved reload retains library additions/deletion',policy_of(reloaded)==policy_of(p))
            (output/'expected.json').write_text(json.dumps(dict(ids=[c.id for c in p.cues], policy=policy_of(p),
                translations=p.generation_metadata.get('translations',{}),global_terms=home_widget.read()),ensure_ascii=False),'utf8')
            t.set_visible_window(0,20000);shot(window,'final-workbench')
            result['passed']=all(c['passed'] for c in result['checks'])
        except Exception:
            result['error']=traceback.format_exc()
        finally:
            for dialog in dialogs:dialog.close()
            save()
            if page.project:
                page.undo_stack.setClean();page.project_dirty=False
            window.close();result['gui_shutdown']=True;save()
            QTimer.singleShot(500,QApplication.instance().quit)
    QTimer.singleShot(1500,run)
