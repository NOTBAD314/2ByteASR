"""Real windows, screen pixels, immutable requests and production export."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject,QTimer,Qt,QPoint
    from PySide6.QtGui import QGuiApplication,QColor,QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialogButtonBox,QScrollArea,QTableWidgetItem
    from ..projects.studio_project import load_project,save_project
    from ..caption_style.bilingual_layout import project_display_cues
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..subtitle_rules import subtitle_translation as st
    from .blank_project_audit import _capture
    output=Path(output); app=QApplication.instance()

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result={'passed':False,'pid':os.getpid(),'executable':sys.executable,'checks':[],
                'screenshots':[],'requests':[],'real_user_click':False,'provider':'explicit offline replay'}
            self.steps=self.run();self.until=0
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(25)

        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
            self.save()
            if not value: raise AssertionError(name+': '+str(detail))

        def save(self):
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')

        def tick(self):
            if time.monotonic()<self.until:return
            try:self.until=time.monotonic()+next(self.steps)
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()

        def wait(self,predicate,name,seconds=25):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline and not predicate():yield .1
            self.check(name,predicate())

        def shot(self,name,widget=None):
            path=output/(name+'.png')
            if widget is None:_capture(window,path)
            else:widget.grab().save(str(path))
            self.result['screenshots'].append(str(path));self.save()

        def click(self,control):
            parent=control.parentWidget()
            while parent is not None and not isinstance(parent,QScrollArea):parent=parent.parentWidget()
            if parent is not None:parent.ensureWidgetVisible(control,0,30)
            QTest.mouseClick(control,Qt.LeftButton)

        def snapshot(self,page):
            result={}
            for cue in project_display_cues(page.project):
                result[cue.id]=build_visual_cue_snapshot(page.project,cue.id,width=1280,height=720,resolved_cue=cue).to_dict()
            return result

        def screen_pixel(self,point):
            screen=QGuiApplication.screenAt(point)
            image=screen.grabWindow(0).toImage();local=point-screen.geometry().topLeft();ratio=image.devicePixelRatio()
            return image.pixelColor(int(local.x()*ratio),int(local.y()*ratio))

        def foreground(self):
            import ctypes
            user=ctypes.windll.user32
            user.GetForegroundWindow.restype=ctypes.c_void_p
            return user.GetForegroundWindow()==int(window.winId())

        def sample_point(self,page,green=False):
            # Search only this owned video widget for the fixture's colored
            # patch; do not inspect or save any other desktop application.
            video=page.video
            start=video.mapToGlobal(QPoint(0,0))
            screen=QGuiApplication.screenAt(start);image=screen.grabWindow(0).toImage();ratio=image.devicePixelRatio()
            offset=start-screen.geometry().topLeft()
            self.check('sampling_owned_foreground_window',self.foreground())
            self.result.setdefault('screen_sampling',[]).append(dict(video=[start.x(),start.y(),video.width(),video.height()],
                screen=screen.geometry().getRect(),image=[image.width(),image.height()],dpr=ratio))
            for y in range(20,max(21,int(video.height()*.50)),12):
                for x in range(20,max(21,video.width()-20),12):
                    color=image.pixelColor(int((offset.x()+x)*ratio),int((offset.y()+y)*ratio))
                    found=(color.green()>130 and color.red()<100 and 70<color.blue()<160) if green else (color.red()>190 and 30<color.green()<120 and 65<color.blue()<160)
                    if found:return start+QPoint(x,y),color
            raise RuntimeError('Could not find the displayed video color patch on the current desktop')

        def pick(self,page,*,green=False,cancel=False):
            point,expected=self.sample_point(page,green)
            count=page.undo_stack.count();index=page.undo_stack.index();errors=[];sample=[]
            def dialog_step():
                try:
                    dialog=QApplication.activeModalWidget()
                    if dialog is None or not hasattr(dialog,'picker'):raise RuntimeError('Real fill dialog did not open')
                    self.click(dialog.picker.eyedropper)
                    def overlay_step():
                        try:
                            overlay=dialog.picker._dropper
                            if overlay is None:raise RuntimeError('Real eyedropper overlay did not open')
                            QTest.mouseClick(overlay,Qt.RightButton if cancel else Qt.LeftButton,pos=overlay.mapFromGlobal(point))
                            sample.append(dialog.picker.color().name())
                            box=dialog.findChild(QDialogButtonBox)
                            self.click(box.button(QDialogButtonBox.Cancel if cancel else QDialogButtonBox.Ok))
                        except Exception:errors.append(traceback.format_exc());dialog.reject()
                    QTimer.singleShot(200,overlay_step)
                except Exception:errors.append(traceback.format_exc())
            QTimer.singleShot(180,dialog_step)
            self.click(page.style_fill_button)
            self.check('eyedropper_modal_session_completed',not errors,errors)
            if cancel:self.check('cancel_has_no_command',page.undo_stack.index()==index)
            else:
                self.check('sample_matches_actual_video_pixel',sample and sample[0].lower()==expected.name().lower(),dict(sample=sample,expected=expected.name()))
                self.check('confirmed_color_is_one_undo_step',page.undo_stack.index()==index+1)
            return expected.name()

        def run(self):
            window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            yield from self.wait(lambda:window.built_page('studio') and window.built_page('studio').project is not None
                and window.built_page('studio').video._startup_state=='READY'
                and window.built_page('studio')._readiness.ready and not window.built_page('studio')._readiness.active,
                'normal_window_media_and_controls_ready',70)
            page=window.studio_page;self.page=page
            window.showMaximized();window.raise_();window.activateWindow()
            yield from self.wait(self.foreground,'owned_test_window_is_foreground',60)
            page.volume_slider.setValue(0);page.video.set_paused(True);page._seek(.9);page.select_cue('source-1')
            page.context_drawer.setCurrentIndex(1)
            yield 1.5
            self.result['dpr']=window.devicePixelRatioF();self.shot('01-initial')
            if os.environ.get('TWOBYTEASR_TERMS_REOPEN')=='1':
                expected=json.loads((output/'expected-colors.json').read_text('utf8'))
                state=self.snapshot(page)
                self.check('fresh_process_saved_colors',all(state[key]['fill']==value for key,value in expected.items()),{k:v['fill'] for k,v in state.items()})
                self.check('fresh_process_source_and_translation',page.project.cues[0].text=='アリスが来た' and st.records_of(page.project)['source-1']['text']=='爱丽丝来了')
                expected_project=json.loads((output/'restart-expected.json').read_text('utf8'))
                self.check('fresh_process_independent_library_selections',
                    page.project.glossary_ids==expected_project['glossary_ids'] and
                    page.project.generation_metadata.get('translation_terminology')==expected_project['generation_metadata'].get('translation_terminology'))
                yield from self.wait(lambda:any(r.get('alpha_nonzero',0)>10 for r in page.subtitle_visibility_trace(reason='terms_restart').get('cue_pixels',[])),
                    'fresh_process_actual_subtitle_pixels',20)
                self.shot('02-reopened-subtitles');return

            # Defaults configured from Home must cross the real settings
            # validator and survive a reload, independently of source IDs.
            import subtitle_core as legacy
            from ..storage.settings import load_runtime_settings
            old_home_ids=list(legacy.RUNTIME_SETTINGS.get('glossary',{}).get('enabled_glossary_ids',[]))
            window._switch_page(0)
            yield .5
            home_terms=window.translation_term_libraries
            errors=[]
            def configure_home_terms():
                try:
                    manager=QApplication.activeModalWidget()
                    manager.name.setText('主页日→中术语库')
                    manager.source.setCurrentIndex(manager.source.findData('ja'))
                    manager.target.setCurrentIndex(manager.target.findData('zh-Hans'))
                    manager.enabled.setChecked(True)
                    manager.table.setRowCount(1)
                    for column,value in enumerate(('アリス','爱丽丝','アリヌ','')):
                        manager.table.setItem(0,column,QTableWidgetItem(value))
                    self.shot('01b-home-translation-library',manager)
                    self.click(manager.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok))
                except Exception:
                    errors.append(traceback.format_exc())
                    modal=QApplication.activeModalWidget()
                    if modal is not None:modal.reject()
            QTimer.singleShot(180,configure_home_terms)
            self.click(home_terms.manage)
            self.check('home_library_editor_confirmed',not errors,errors)
            saved_settings,_,_=load_runtime_settings()
            home_policy=saved_settings['glossary'].get('translation_terminology',{})
            self.check('home_directional_defaults_survive_settings_reload',home_policy.get('enabled')
                and home_policy['libraries'][0]['terms'][0]['target']=='爱丽丝')
            self.check('home_defaults_do_not_replace_source_library_ids',saved_settings['glossary']['enabled_glossary_ids']==old_home_ids)
            window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            yield from self.wait(lambda:page.isVisible() and page._readiness.ready and not page._readiness.active,'return_to_owned_project')
            page.video.set_paused(True);page.select_cue('source-1');page._seek(.9);page.context_drawer.setCurrentIndex(1)
            yield .5

            # Real proofreading entry, local original correction, one user action.
            yield from self.wait(lambda:page.cue_proofread_action.isEnabled() and page.cue_ai_button.isVisible(),
                                 'original_proofread_button_ready')
            page.cue_proofread_action.trigger()
            yield from self.wait(lambda:getattr(window,'glossary_proofread_page',None) is not None,'original_proofread_open')
            review=window.glossary_proofread_page
            yield from self.wait(lambda:review._worker is None and any(row['issues'] for row in review._rows),'original_alias_suggestion')
            self.shot('02-original-proofreading')
            source_libraries=list(page.project.glossary_ids)
            manager_errors=[]
            def edit_translation_library():
                try:
                    manager=QApplication.activeModalWidget()
                    self.check('directional_library_editor_has_ja_zh_controls',
                               manager.source.currentData()=='ja' and manager.target.currentData()=='zh-Hans')
                    manager.name.setText(manager.name.text()+'（本工程）')
                    self.shot('02b-directional-library-editor',manager)
                    self.click(manager.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok))
                except Exception:
                    manager_errors.append(traceback.format_exc())
                    modal=QApplication.activeModalWidget()
                    if modal is not None:modal.reject()
            QTimer.singleShot(180,edit_translation_library)
            self.click(review.translation_term_libraries.manage)
            self.check('translation_library_editor_confirmed',not manager_errors,manager_errors)
            self.check('translation_library_change_keeps_source_selection',page.project.glossary_ids==source_libraries)
            self.check('translation_library_change_keeps_source_proposals',any(row['issues'] for row in review._rows))
            self.click(review.select_all)
            yield .4
            self.check('applied_original_is_committed',page.project.cues[0].text=='アリスが来た')
            self.click(review.back_button)
            yield .7

            # A recording provider enters at the normal provider boundary.
            from ..providers import ai_providers,llm_config
            audit=self
            class RecordingProvider:
                model='offline-replay';provider_id='offline-replay'
                def structured_complete(self,messages,schema,**kwargs):
                    body=json.loads(messages[-1]['content']);audit.result['requests'].append(body);audit.save()
                    if len(audit.result['requests'])==1:
                        return {'items':[dict(id=row['id'],translation='阿莉丝来了') for row in body['lines'] if row['translate']]}
                    return {'items':[{'id':row['id'],'translation':'爱丽丝来了' if row['id']=='source-1' else '我看见爱丽丝了'}
                                     for row in body['lines'] if row['translate']]}
                def complete(self,messages,**kwargs):
                    body=json.loads(messages[-1]['content']);audit.result.setdefault('review_requests',[]).append(body)
                    return {'changes':[dict(target_id=row['target_id'],original=row['target_text'],
                        replacement=row['target_text'].replace('阿莉丝','爱丽丝') if '阿莉丝' in row['target_text'] else row['target_text'].replace('爱丽丝','阿莉丝'),
                        reason='按用户日→中术语库校对／其他候选译法') for row in body['targets']]}
            ai_providers.provider_for_stage=lambda *a,**kw:RecordingProvider()
            llm_config.text_ai_key_missing=lambda *a,**kw:False
            page._open_translation_dialog(scope='all')
            dialog=page._translation_dialog;dialog.start_button.setEnabled(True);dialog.service.setText('本机离线回放模型 · 实际请求记录，不联网')
            self.shot('03-translation-settings',dialog)
            self.click(dialog.start_button)
            yield from self.wait(lambda:dialog._thread is None and bool(st.records_of(page.project).get('source-1')),'translation_finished')
            bodies=self.result['requests'];first=bodies[0]
            self.check('actual_model_request_uses_applied_source',any(row['id']=='source-1' and row['text']=='アリスが来た' for row in first['lines']))
            self.check('actual_model_request_contains_japanese_chinese_map',first['translation_terminology'][0]['source']=='アリス' and first['translation_terminology'][0]['target']=='爱丽丝')
            self.check('generated_translation_uses_requested_name',st.records_of(page.project)['source-1']['text']=='爱丽丝来了')
            self.check('generation_term_conflict_is_explained', '术语冲突' in dialog.request_log.toPlainText())
            self.shot('03a-generation-conflict-and-retry',dialog)
            dialog.close();yield .4
            from ..studio.studio_bilingual import set_manual_translation
            set_manual_translation(page,'source-1','阿莉丝来了',page._changed)
            source_before=[(cue.id,cue.text) for cue in page.project.cues]
            page.cue_proofread_action.trigger()
            yield .4
            review=window.glossary_proofread_page
            review.text_targets.mode.setCurrentIndex(review.text_targets.mode.findData('translation'))
            yield from self.wait(lambda:review._worker is None,'translation_review_local_ready')
            self.click(review.ai_button)
            yield from self.wait(lambda:review._worker is None and any(row['issues'] for row in review._rows),'translation_review_has_mapping_proposal')
            self.shot('03b-translation-proofreading')
            self.check('review_conflict_keeps_the_valid_translation',bool(review._term_conflicts)
                and st.records_of(page.project)['source-3']['text']=='我看见爱丽丝了')
            conflict_errors=[]
            def close_conflicts():
                try:
                    modal=QApplication.activeModalWidget()
                    from PySide6.QtWidgets import QPlainTextEdit
                    detail=modal.findChild(QPlainTextEdit).toPlainText()
                    self.check('review_conflict_dialog_shows_reference_and_alternative','阿莉丝' in detail and '爱丽丝' in detail and '对应原文' in detail)
                    self.shot('03c-review-terminology-conflicts',modal)
                    self.click(modal.findChild(QDialogButtonBox).button(QDialogButtonBox.Close))
                except Exception:
                    conflict_errors.append(traceback.format_exc())
                    modal=QApplication.activeModalWidget()
                    if modal is not None:modal.reject()
            QTimer.singleShot(180,close_conflicts)
            self.click(review.term_conflicts_button)
            self.check('review_conflict_dialog_is_read_only',not conflict_errors,conflict_errors)
            self.click(review.select_all);yield .3
            self.check('translation_review_applies_only_translation',st.records_of(page.project)['source-1']['text']=='爱丽丝来了'
                and source_before==[(cue.id,cue.text) for cue in page.project.cues])
            self.click(review.undo_button);yield .2
            self.check('translation_review_undo',st.records_of(page.project)['source-1']['text']=='阿莉丝来了')
            self.click(review.redo_button);yield .2
            self.check('translation_review_redo',st.records_of(page.project)['source-1']['text']=='爱丽丝来了')
            self.click(review.back_button);yield .5
            page.select_cue('source-1');page._seek(.9);page.context_drawer.setCurrentIndex(1)
            page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
            page.style_layer.setCurrentIndex(page.style_layer.findData('original'))
            yield 1
            before=self.snapshot(page)
            original_color=self.pick(page)
            yield 1
            original=self.snapshot(page)
            self.check('source_fill_changes_actual_caption',original['source-1']['fill']['color'].lower().endswith(original_color[1:]))
            self.check('source_pick_preserves_translation',original['source-1#tr']['fill']==before['source-1#tr']['fill'])
            for field in ('font_family','font_size','position_x','position_y','scale_x','scale_y','rotation','strokes','motion_recipe'):
                self.check('fill_preserves_'+field,original['source-1'].get(field)==before['source-1'].get(field))
            self.shot('04-picked-source-caption')
            page.undo_stack.undo();yield .3
            self.check('color_undo_restores_fill',self.snapshot(page)['source-1']['fill']==before['source-1']['fill'])
            page.undo_stack.redo();yield .4
            self.check('color_redo_restores_pick',self.snapshot(page)['source-1']['fill']==original['source-1']['fill'])
            self.pick(page,cancel=True)
            yield .3
            self.check('color_cancel_keeps_fill',self.snapshot(page)['source-1']['fill']==original['source-1']['fill'])
            page.style_layer.setCurrentIndex(page.style_layer.findData('translation'))
            yield .3
            translated_color=self.pick(page,green=True)
            yield 1
            both=self.snapshot(page)
            self.check('translation_fill_changes_own_caption',both['source-1#tr']['fill']['color'].lower().endswith(translated_color[1:]))
            self.check('translation_pick_preserves_source',both['source-1']['fill']==original['source-1']['fill'])
            yield from self.wait(lambda:len([row for row in page.subtitle_visibility_trace(reason='actual_eyedrop').get('cue_pixels',[]) if row.get('alpha_nonzero',0)>10])>=2,
                'two_language_actual_visible_caption_pixels',20)
            self.shot('05-source-and-translation-color')

            # Same screen-sampling action under each existing scope, with
            # independent language colors and one-step undo for each.
            from dataclasses import asdict
            from ..caption_style.scoped_style import effective_layer_style
            from ..timeline.selection_scope import SelectionScope
            for scope in ('speaker','selected','all'):
                for layer in ('original','translation'):
                    page.cue_controller.apply_selection_scope(SelectionScope.explicit(['source-1','source-3'],'source-1'))
                    page.style_scope.setCurrentIndex(page.style_scope.findData(scope))
                    page.style_layer.setCurrentIndex(page.style_layer.findData(layer))
                    yield .3
                    targets=set(page._style_target_ids())
                    before_styles={cue.id:asdict(effective_layer_style(page.project,cue,layer)) for cue in page.project.cues}
                    color=self.pick(page,green=layer=='original')
                    yield .3
                    after_styles={cue.id:asdict(effective_layer_style(page.project,cue,layer)) for cue in page.project.cues}
                    self.check(scope+'_'+layer+'_color_scope',all(
                        after_styles[key]['primary_color'].lower().endswith(color[1:]) if key in targets
                        else after_styles[key]==before_styles[key] for key in before_styles))
                    self.check(scope+'_'+layer+'_keeps_geometry_and_font',all(
                        all(after_styles[key][field]==before_styles[key][field] for field in ('font_family','font_size','position_x','position_y','scale_x','scale_y'))
                        for key in before_styles))
                    page.undo_stack.undo();yield .3
                    self.check(scope+'_'+layer+'_undo',all(asdict(effective_layer_style(page.project,cue,layer))==before_styles[cue.id] for cue in page.project.cues))
            page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
            page.select_cue('source-1')

            # The export entry must provide diagnostics before workspace creation.
            self.click(page.studio_render_button)
            yield .4
            issues=page._export_issues_dialog
            self.check('diagnostics_open_without_export_workspace',issues.isVisible() and page.export_workspace is None)
            self.check('empty_issue_owner',issues.current().cue_id=='range-4e4aaa9b-236')
            self.shot('06-empty-source-diagnostics',issues)
            page.cue_search.setText('does not match');page._activate_filter('done')
            self.click(issues.locate)
            yield .5
            self.check('location_clears_filters_and_selects_owner',page.selected_cue_id=='range-4e4aaa9b-236' and page.cue_model.row_for_cue_id(page.selected_cue_id)>=0)
            self.shot('07-located-empty-source')
            self.click(issues.restore);yield .4
            self.check('restore_rechecks_and_unblocks',not issues.issues and page.project.cues[1].text=='アリスが待っている')
            page.undo_stack.undo();issues.refresh();self.check('restore_is_undoable',bool(issues.issues))
            self.click(issues.confirm);self.check('intentional_empty_is_confirmable',not issues.issues and page.project.cues[1].text=='')
            page.undo_stack.undo();issues.refresh();self.click(issues.restore)
            issues.close();yield .4

            saved=output/'saved-result.2byteproj';save_project(page.project,saved)
            expected={key:value['fill'] for key,value in self.snapshot(page).items()}
            (output/'expected-colors.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2),'utf8')
            reopened=load_project(saved)
            self.check('save_reopen_keeps_separate_term_libraries',reopened.glossary_ids==page.project.glossary_ids and reopened.generation_metadata['translation_terminology']==page.project.generation_metadata['translation_terminology'])
            page._open_render_dialog();yield .8
            ui=page.export_workspace
            self.check('repaired_project_opens_export',ui is not None)
            ui.directory.setText(str(output));ui.filename_prefix.setText('');ui.filename_suffix.setText('');ui.filename.setText('verified')
            ui.audio.setCurrentIndex(ui.audio.findData('none'))
            index=ui.encoder.findData('libx264')
            if index>=0:ui.encoder.setCurrentIndex(index)
            self.destination=ui.export_target().full_path
            self.click(ui.export_button)
            yield from self.wait(lambda:not ui._running,'production_export_finished',110)
            self.check('production_video_published',self.destination.is_file() and self.destination.stat().st_size>1000,
                dict(path=str(self.destination),failure=ui._last_failure))
            self.result['video']=str(self.destination)
            self.shot('08-production-export-complete')

        def finish(self):
            self.timer.stop()
            self.result['passed']=bool(self.result['checks']) and all(c['passed'] for c in self.result['checks']) and 'error' not in self.result
            self.save()
            def closed():self.result['gui_shutdown']=True;self.save()
            app.aboutToQuit.connect(closed)
            page=getattr(self,'page',None)
            if page is not None:
                if page.export_workspace is not None:page._close_export_workspace()
                page.undo_stack.setClean();page.project_dirty=False
            review=getattr(window,'glossary_proofread_page',None)
            if review is not None:review.shutdown()
            window.close();QTimer.singleShot(1200,app.quit)

    window._terms_color_export_audit=Audit()
