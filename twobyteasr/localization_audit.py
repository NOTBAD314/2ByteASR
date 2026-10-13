"""Opt-in real-window localization audit; fixtures and output remain isolated."""
import json
import time
import traceback
import os
from copy import deepcopy
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtWidgets import QApplication,QWidget,QLabel,QAbstractButton,QComboBox,QTabBar,QLineEdit,QDialog,QTableWidget,QListWidget,QMenu,QScrollArea
    from .i18n import current_language,save_language,tr
    from .build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            (output/'audit-started.txt').write_text('started','utf8')
            self.result={'passed':False,'checks':[],'identity':load_build_identity().to_dict(),'surfaces':{}}
            self.steps=self.run();self.wait_until=0
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(100)

        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
            if not value:raise AssertionError(name)

        def tick(self):
            if time.monotonic()<self.wait_until:return
            try:self.wait_until=time.monotonic()+next(self.steps)
            except StopIteration:self.result['passed']=True;self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()

        def capture(self,name,root):
            root.grab().save(str(output/(name+'.png')))
            rows=[]
            for w in [root,*root.findChildren(QWidget)]:
                texts=[]
                if isinstance(w,(QLabel,QAbstractButton)):texts.append(('text',w.text()))
                if isinstance(w,QLineEdit):texts.append(('placeholder',w.placeholderText()))
                if isinstance(w,QComboBox):texts.extend(('item',w.itemText(i)) for i in range(w.count()))
                if isinstance(w,QTabBar):texts.extend(('tab',w.tabText(i)) for i in range(w.count()))
                if isinstance(w,QTableWidget):
                    texts.extend(('header',w.horizontalHeaderItem(i).text()) for i in range(w.columnCount()) if w.horizontalHeaderItem(i))
                    texts.extend(('cell',w.item(r,c).text()) for r in range(w.rowCount()) for c in range(w.columnCount()) if w.item(r,c))
                if isinstance(w,QListWidget):texts.extend(('list',w.item(i).text()) for i in range(w.count()))
                if w.toolTip():texts.append(('tip',w.toolTip()))
                for a in w.actions():texts.append(('action',a.text()))
                for prop,text in texts:
                    if text:rows.append(dict(type=type(w).__name__,name=w.objectName(),property=prop,text=text,
                        visible=w.isVisible(),width=w.width(),height=w.height(),user=bool(w.property('i18nUserText'))))
            self.result['surfaces'][name]=rows
            (output/(name+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),'utf8')

        def modal(self, name, opener):
            self.timer.stop()
            def take():
                dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]
                try:
                    self.check(name + ' opened', bool(dialogs))
                    for i, dialog in enumerate(dialogs):
                        self.capture(name + (str(i) if i else ''), dialog)
                        dialog.reject()
                except Exception:
                    self.result['error'] = traceback.format_exc()
                    for dialog in dialogs: dialog.reject()
            QTimer.singleShot(750, take)
            opener()
            self.timer.start(100)

        def menu(self, name, opener):
            self.timer.stop()
            def take():
                menus=[w for w in QApplication.topLevelWidgets() if isinstance(w,QMenu) and w.isVisible()]
                self.check(name+' opened', bool(menus))
                for menu in menus:
                    self.capture(name,menu)
                    menu.close()
            QTimer.singleShot(450,take)
            opener()
            self.timer.start(100)

        def state(self, page):
            project=deepcopy(page.project.to_dict())
            # Localized controls may change splitter pixel sizes. Those view
            # measurements are not caption/project content. Keep all other
            # persisted state, including selection, zoom and scroll, in scope.
            project.get('studio_state', {}).pop('layout', None)
            return dict(project=project,
                selected=list(page.timeline.selected_ids),
                playhead=page.timeline.playhead_ms,
                undo=(page.undo_stack.index(), page.undo_stack.isClean()),
                recognition=deepcopy(window._asr_values()))

        def run(self):
            from .studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,save_project,project_library_root
            from .processes import run_hidden_subprocess
            from .audio_engine import studio_ffmpeg_path
            from .project_display_name import display_project_name
            window.showNormal();window.resize(1600,950)
            QApplication.instance().setProperty('reduceMotion', True)
            yield .8
            if os.environ.get('TWOBYTEASR_LOCALIZATION_RESTART'):
                self.check('restart restored Japanese', current_language() == 'ja')
                self.capture('ja-restarted-home', window)
                window._open_subtitle_studio(mode='hub')
                yield 1.2
                self.capture('ja-restarted-library', window)
                paths=json.loads((output/'fixture-paths.json').read_text('utf8'))
                window.studio_page.open_project(Path(paths[0]),skip_dirty_guard=True)
                deadline=time.monotonic()+25
                while time.monotonic()<deadline and not window.studio_page._readiness.ready:yield .2
                self.check('restart opened existing project', window.studio_page._readiness.ready)
                self.capture('ja-restarted-studio', window)
                window.studio_page.show_project_hub(skip_dirty_guard=True)
                return
            # Create real saved fixtures, including a legacy automatic title and
            # a deliberate Chinese user title. No user project is opened/written.
            library=project_library_root();self.paths=[]
            media=output/'中文测试视频.mp4'
            result=run_hidden_subprocess([str(studio_ffmpeg_path()),'-y','-f','lavfi','-i','color=c=0x342b40:s=960x540:r=25:d=4',
                '-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(media)],
                purpose='localization fixture',capture_output=True,timeout=30)
            self.check('short media created',result.returncode==0)
            for filename,custom in [('未命名工程 30',''),('新默认工程',''),('用户工程','游戏剪辑第一版')]:
                folder=library/filename;folder.mkdir(parents=True,exist_ok=True)
                p=SubtitleProject(media=StudioMedia(path=str(media),display_name=media.name,duration_ms=4000,width=960,height=540),
                    cues=[StudioCue('one',0,1800,'用户字幕保持中文'),StudioCue('two',2000,3800,'游戏剪辑第一版')],
                    speakers=[StudioSpeaker('S00','主播自定义名字')])
                if custom:p.studio_state['project_name']=custom
                if filename=='新默认工程':p.studio_state['project_name_origin']={'kind':'unnamed','number':35}
                target=save_project(p,folder/(filename+'.2byteproj'));self.paths.append(target)
            (output/'fixture-paths.json').write_text(json.dumps([str(p) for p in self.paths],ensure_ascii=False),'utf8')
            for language in ('zh','en','ja','zh'):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                window.ai_panel.set_expanded(False,animate=False)
                window.settings_scroll.verticalScrollBar().setValue(0)
                yield .6
                self.check('language '+language,current_language()==language)
                if language in ('en','ja'):self.capture(language+'-home',window)
            window._open_subtitle_studio(mode='hub')
            yield .5
            window.studio_page.project_controller.create_blank_project()
            yield 1.5
            blank=window.studio_page
            self.check('real new-project action records automatic origin',
                blank.project.studio_state.get('project_name_origin',{}).get('kind')=='unnamed')
            self.result['new_project_path']=str(blank.project_path)
            blank.show_project_hub(skip_dirty_guard=True)
            yield .5
            for language in ('en','ja'):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                yield .4
                window._open_subtitle_studio(mode='hub')
                yield 1.5
                page=window.studio_page
                self.capture(language+'-library',page.window())
                titles=[w.text() for w in page.findChildren(QLabel) if w.objectName()=='projectCardTitle']
                self.check(language+' rendered default titles',str(tr('未命名工程 {number}',number=30)) in titles and str(tr('未命名工程 {number}',number=35)) in titles,titles)
                self.check(language+' rendered custom title','游戏剪辑第一版' in titles)
                page.project_search.setText('no-matching-project-93993')
                yield .3
                self.capture(language+'-library-empty-search',page.window())
                page.project_search.clear()
                yield .3
                page._library_selected_paths={str(self.paths[0])}
                self.modal(language+'-delete-confirmation',page._delete_selected_library_projects)
                page._library_selected_paths=set()
                self.check(language+' cancelled deletion preserves file',self.paths[0].is_file())
                self.modal(language+'-missing-project',lambda:page._open_recent_project_card(str(output/'missing.2byteproj')))
                offline=dict(path=str(self.paths[0]),name='Offline fixture',source_media=str(output/'missing.mp4'))
                card=page._build_project_card(offline,340)
                card.show()
                yield .3
                self.capture(language+'-offline-project-card',card)
                self.check(language+' offline card status',any(w.text()==str(tr('素材离线')) for w in card.findChildren(QLabel)))
                card.close();card.deleteLater()
                page._set_project_library_view('list')
                yield .6
                self.capture(language+'-library-list',page.window())
                self.menu(language+'-library-context-menu',lambda:page._recent_project_menu(str(self.paths[0])))
                self.modal(language+'-project-details',lambda:page._show_recent_project_details(str(self.paths[0])))
                page._set_project_library_view('card')
                page.open_project(self.paths[0],skip_dirty_guard=True)
                deadline=time.monotonic()+25
                while time.monotonic()<deadline and not getattr(getattr(page,'_readiness',None),'ready',False):yield .2
                self.check(language+' studio actually ready',bool(page._readiness.ready))
                page.video.set_paused(True)
                yield .6
                self.capture(language+'-studio',page.window())
                page.select_cue('two')
                page.cue_controller.set_text('two','未保存的中文字幕：全部 / 说话人管理')
                page._seek(1.2)
                page.video.set_paused(True)
                yield .6
                page._capture_studio_state()  # Prime normal view-state serialization before comparison.
                before = self.state(page)
                for target in ('zh','en','ja',language):
                    save_language(target)
                    yield .25
                    after = self.state(page)
                    if before != after:
                        (output / ('state-diff-'+language+'-'+target+'.json')).write_text(json.dumps({'before':before,'after':after},ensure_ascii=False,indent=2),'utf8')
                    for field in before:
                        self.check(language + ' hot switch ' + target + ' preserves ' + field, after[field] == before[field])
                self.modal(language+'-speaker-dialog', page._open_speaker_manager)
                yield .2
                self.modal(language+'-replace-dialog', page._open_find_replace)
                yield .2
                self.menu(language+'-caption-menu',page._show_cue_more_menu)
                page._show_shortcut_settings()
                yield .6
                self.capture(language+'-shortcut-panel',page.window())
                page._shortcut_settings_panel.rejected.emit()
                yield .2
                for index,label in enumerate(('ai','style','video','clips','media')):
                    page.context_drawer.setCurrentIndex(index)
                    yield .4
                    self.check(language+' '+label+' panel selected',page.context_drawer.currentIndex()==index)
                    self.capture(language+'-panel-'+label,page.window())
                page.context_drawer.setCurrentIndex(1)
                # Undo only the audit's unsaved edit before testing a real export.
                page.undo_stack.undo()
                page._open_render_dialog()
                yield .8
                export=page.export_workspace
                self.check(language+' export opened',export is not None)
                self.capture(language+'-export',page.window())
                if language == 'en':
                    destination=output/'exports';destination.mkdir(exist_ok=True)
                    export.directory.setText(str(destination))
                    export.filename.setText('localization-real-export')
                    export._start()
                    yield .15
                    self.capture('en-export-running',page.window())
                    save_language('ja')
                    deadline=time.monotonic()+45
                    while export._running and time.monotonic()<deadline:yield .2
                    self.check('real short export completed',export.pages.currentWidget() is export.success_page,
                        getattr(export,'_last_failure',None))
                    self.capture('ja-export-success',page.window())
                    self.result['real_export'] = str(export._success_output)
                    save_language(language)
                # Controlled failure reaches the actual error surface; no fake ASR success.
                export._show_failure('Permission denied (controlled localization test)')
                self.capture(language+'-export-controlled-failure',page.window())
                page._close_export_workspace()
                yield .4
                self.check(language+' legacy default display',display_project_name(path=self.paths[0])==('Unnamed Project 30' if language=='en' else '無題のプロジェクト 30'))
                self.check(language+' custom name preserved',display_project_name(path=self.paths[2])=='游戏剪辑第一版')
                page.save()  # Persist only the audit fixture after the unsaved-state test.
                page.show_project_hub(skip_dirty_guard=True)
                yield .3
                self.modal(language+'-settings-dialog',window._open_application_settings)
                yield .2
                window._open_model_workshop()
                yield .8
                self.capture(language+'-workshop',window)
                window.workshop_page._select_model('moss')
                window.workshop_page._show_technical_details()
                yield .6
                self.capture(language+'-model-details',window)
                technical=next(iter(window.workshop_page._technical_cache.values()))
                for scroll in technical.findChildren(QScrollArea):scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                yield .3
                self.capture(language+'-model-details-bottom',window)
                technical._close_self()
                yield .3
                window._manage_terms()
                yield .8
                self.capture(language+'-terms',window)
                window._return_to_settings()
                yield .3
                self.capture(language+'-home-returned',window)
            # Controlled structured callbacks exercise the real progress page.
            # This is explicitly not a model inference run.
            from .service import PipelineEvent
            window.started_at=time.perf_counter()
            window._switch_page(1)
            for language in ('en','ja'):
                save_language(language)
                window._recognition_terminal=''
                window._handle_event(PipelineEvent(kind='stage_started',timestamp='',stage_index=8,stage_total=11,
                    media_index=1,media_total=1,label='主力转写',resource='MOSS'))
                window._handle_event(PipelineEvent(kind='asr_progress',timestamp='',payload=dict(
                    backend='api',completed_batches=1,total_batches=2,cue_count=2,processed_ranges_ms=[[0,4000]])))
                window._handle_event(PipelineEvent(kind='speaker_progress',timestamp='',payload=dict(
                    state='analyzing',processed_start=0,processed_end=4)))
                yield .3
                self.capture(language+'-recognition-controlled-running',window)
                window._recognition_terminal='success';window._refresh_progress_cards()
                self.capture(language+'-recognition-controlled-complete',window)
                window._recognition_terminal='failed';window._refresh_progress_cards()
                self.capture(language+'-recognition-controlled-failed',window)
            window.started_at=0
            window._recognition_live_work={}
            window._return_to_settings()
            save_language('ja')
            self.check('saved language before restart',current_language()=='ja')

        def finish(self):
            self.timer.stop()
            receipt = 'restart-result.json' if os.environ.get('TWOBYTEASR_LOCALIZATION_RESTART') else 'result.json'
            (output/receipt).write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
            if hasattr(window, "studio_page"):
                window.studio_page.show_project_hub(skip_dirty_guard=True)
            window.close()
            QTimer.singleShot(300,lambda:QApplication.instance().exit(0 if self.result['passed'] else 1))

    window._localization_audit=Audit()
