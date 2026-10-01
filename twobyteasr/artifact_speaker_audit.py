"""Opt-in isolated GUI acceptance with real local workers and no paid calls."""
import json
import time
import traceback
from dataclasses import asdict
from pathlib import Path


def start(window,out):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QCheckBox,QPushButton,QComboBox
    from .studio_acceptance_audit import require
    from .build_identity import load_build_identity
    result=dict(completed=False,checks=[],events=[],paid_calls=0,build=load_build_identity().to_dict())
    def save():(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value):
        result['checks'].append(dict(name=name,passed=bool(value)));save();require(value,name)
    def pump():QApplication.processEvents();time.sleep(.04)
    def wait(predicate,seconds,name):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:pump()
        check(name,predicate())
    def shot(name):window.grab().save(str(out/(name+'.png')))
    def event(e):
        record=asdict(e);result['events'].append(record);save()
        if 'speaker_progress' in str(record) and 'analyzing' in str(record):shot('04-running')
    def run():
        try:
            page=window.studio_page
            wait(lambda:page.project is not None and page._readiness.ready,90,'startup Studio ready')
            page.video.set_paused(True);page._set_volume(0);source=page.project.media.path
            window._switch_page(0)
            for name,value in [('primary_asr_backend','firered'),('firered_asr_backend','local'),('qwen_asr_backend','off')]:
                combo=getattr(window,name);index=combo.findData(value)
                check('installed choice '+name,index>=0);combo.setCurrentIndex(index)
            window.ai_grouping.setChecked(False);window.unified_glm.setChecked(False)
            check('save local settings',window._save_asr_configuration(show_feedback=False))
            check('save no-cloud grouping',window._save_ai_configuration(show_feedback=False))
            config=window._profile_configuration();config['asr_config']['speaker_source']='single';config['glossary_ids']=[]
            run_id=str(time.time_ns())
            a=window.profile_store.create('说话人验收 A '+run_id,**config);b=window.profile_store.create('说话人验收 B '+run_id,**config)
            check('apply A',window._apply_project_profile(a))
            window._open_model_workshop();workshop=window.workshop_page
            tab=next(x for x in workshop.tab_group.buttons() if x.property('role')=='speaker')
            QTest.mouseClick(tab,Qt.LeftButton);QTest.mouseClick(workshop._cards['nemotron'],Qt.LeftButton)
            model=workshop._cards['nemotron'].model
            wait(lambda:workshop._model_state(model)!='checking',90,'Nemotron readiness resolved')
            wait(lambda:workshop.detail_action.isEnabled(),15,'visible action reflects readiness')
            result['runtime_state']={'model':workshop._model_state(model),'probe':str(workshop._nemotron_probe_result)}
            check('existing runtime ready without reinstall',workshop._model_state(model)=='installed');shot('01-installed')
            QTest.mouseClick(workshop.detail_action,Qt.LeftButton);pump()
            check('A saved enabled',window.profile_store.get(a.id).asr_config['speaker_source']=='nemotron')
            check('B remains disabled',window.profile_store.get(b.id).asr_config['speaker_source']=='single')
            check('card/detail agree',workshop._model_state(model)=='selected')
            check('active model protected','nemotron' in workshop._current_model_keys());shot('02-enabled')
            check('switch B',window._apply_project_profile(window.profile_store.get(b.id)))
            check('B effective single',window.legacy.RUNTIME_SETTINGS['models']['speaker_source']=='single')
            check('switch A',window._apply_project_profile(window.profile_store.get(a.id)))
            window._switch_page(0);window.settings_scroll.verticalScrollBar().setValue(0)
            window.import_media([source],replace=True)
            wait(lambda:window.media_paths==[source] and window.start_button.isEnabled(),30,'normal media intake')
            pump();shot('03-home');window.speaker_tracks.setChecked(True)
            received=[];errors=[];original=window._handle_event
            def observe(e):event(e);original(e)
            window._handle_event=observe
            def reject_unexpected():
                modal=QApplication.activeModalWidget()
                if isinstance(modal,QMessageBox):errors.append(modal.text()+' '+modal.informativeText());modal.reject()
            guard=QTimer(window);guard.timeout.connect(reject_unexpected);guard.start(200)
            window._switch_page(page);page._open_recognition_sheet();pump()
            sheet=window.findChild(QCheckBox,'localSpeakerRecognition').parentWidget()
            local=sheet.findChild(QCheckBox,'localSpeakerRecognition');local.setChecked(True)
            selector=next(c for c in sheet.findChildren(QComboBox) if c.findData('nemotron')>=0)
            check('recognition sheet inherits active choice',selector.currentData()=='nemotron')
            shot('03-recognition-sheet')
            start_button=next(b for b in sheet.findChildren(QPushButton) if b.text()=='识别并替换当前字幕')
            QTest.mouseClick(start_button,Qt.LeftButton);pump()
            confirm=next(b for b in sheet.findChildren(QPushButton) if b.text()=='确认替换')
            QTest.mouseClick(confirm,Qt.LeftButton)
            result['start_diagnostics']=dict(block_reason=window._run_block_reason,errors=errors,
                enabled=window.start_button.isEnabled(),visible=window.start_button.isVisible())
            check('normal Start created worker',window.worker is not None and window.worker.isRunning())
            worker=window.worker;result['task_options']=asdict(worker.options)
            check('worker owns Nemotron selection',worker.options.speaker_source=='nemotron')
            worker.result_ready.connect(received.append);worker.unexpected_error.connect(errors.append)
            window._apply_workshop_backend('speaker','single')
            check('running task snapshot unchanged',worker.options.speaker_source=='nemotron')
            wait(lambda:bool(received) or bool(errors),600,'real local recognition returned')
            guard.stop();require(not errors,str(errors));result['recognition']=asdict(received[0]);save()
            check('recognition delivered project',bool(received[0].successes and received[0].successes[0].project_path))
            wait(lambda:not worker.isRunning(),30,'worker exited')
            encoded=json.dumps(result['events'])
            check('Nemotron process started','NEMOTRON_DIARIZATION' in encoded)
            check('speaker merge completed','speaker_progress' in encoded and 'completed' in encoded);shot('05-complete')
            target=Path(received[0].successes[0].project_path)
            for dialog in QApplication.topLevelWidgets():
                if isinstance(dialog,QDialog) and dialog.isVisible():dialog.close()
            from .studio_project import load_project,save_project
            project=load_project(target);state=project.generation_metadata['speaker_recovery']
            result['speaker_processing']=state.get('processing');result['labels']=[s.id for s in project.speakers]
            check('model did not degrade',state.get('processing',{}).get('status')!='failed')
            check('delivered task model snapshot',project.generation_metadata['models']['speaker_source']=='nemotron')
            status=project.generation_metadata['model_statuses']['NEMOTRON_DIARIZATION']
            result['nemotron_model_status']=status
            check('persisted model lifecycle complete',status['selected'] and status['environment_ready']
                  and status['started'] and status['completed'] and not status['failed'])
            check('anonymous identity pending',all(x=='unconfirmed' for x in state['roles'].values()))
            page.open_project(target,skip_dirty_guard=True);window._switch_page(page)
            wait(lambda:page.project and page.project.project_id==project.project_id and page._readiness.ready,90,'real result in Studio')
            page.video.set_paused(True);page._set_volume(0)
            edited=page.project.cues[0]
            page._timeline_text_edited(edited.id,False,'人工编辑验收：'+edited.text)
            page._push_timing(edited.id,edited.start_ms+10,edited.end_ms)
            pump()
            check('actual cue edit before identity review',page.project.cues[0].text.startswith('人工编辑验收：'))
            from .studio_speaker_manager import SpeakerManagerDialog
            manager=SpeakerManagerDialog(page);manager.show();manager.tabs.setCurrentIndex(0)
            signature=lambda:[(c.id,c.text,c.start_ms,c.end_ms,c.style_id) for c in page.project.cues]
            original_cues=signature();label=next(iter(manager._role_boxes));box=manager._role_boxes[label]
            box.setCurrentIndex(box.findData('main'))
            for _ in range(12):pump()
            manager.grab().save(str(out/'06-speaker-review.png'))
            QTest.mouseClick(manager.rebuild_button,Qt.LeftButton)
            wait(lambda:any(s.id==label and s.is_host for s in page.project.speakers),20,'host selected')
            check('identity preserves edited cue data',signature()==original_cues)
            page.undo_stack.undo();page.undo_stack.redo();check('undo redo lossless',signature()==original_cues)
            manager.close();saved=out/'reviewed.2byteproj';save_project(page.project,saved)
            reloaded=load_project(saved);check('saved host retained',any(s.id==label and s.is_host for s in reloaded.speakers))
            page.open_project(saved,skip_dirty_guard=True)
            wait(lambda:page.project and page._readiness.ready,90,'reviewed project reopened');shot('07-reopened')
            from .studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
            artifacts=export_subtitle_artifacts(reloaded,out/'exports','reviewed',SubtitleExportOptions(frozenset({'srt','ass'}),'both'))
            result['exports']=[asdict(x) for x in artifacts]
            check('combined and separate exports',len(artifacts)==2*(1+len({c.speaker_id for c in reloaded.visible_cues()})))
            # A second real task proves the disabled selection dispatches no
            # speaker worker. ASR caches may be reused and are recorded as such.
            event_offset=len(result['events']);disabled=[]
            page._open_recognition_sheet();pump();sheet=page._recognition_sheet
            selector=next(c for c in sheet.findChildren(QComboBox) if c.findData('nemotron')>=0)
            check('next recognition is disabled',selector.currentData()=='single')
            sheet.findChild(QCheckBox,'localSpeakerRecognition').setChecked(True)
            QTest.mouseClick(page._recognition_controls['start'],Qt.LeftButton);pump()
            QTest.mouseClick(next(b for b in sheet.findChildren(QPushButton) if b.text()=='确认替换'),Qt.LeftButton)
            worker=window.worker;check('disabled task snapshot',worker.options.speaker_source=='single')
            worker.result_ready.connect(disabled.append)
            wait(lambda:bool(disabled),600,'disabled real task returned')
            wait(lambda:not worker.isRunning(),30,'disabled worker exited')
            result['disabled_recognition']=asdict(disabled[0])
            check('disabled task delivered',bool(disabled[0].successes))
            check('disabled task dispatched no Nemotron','NEMOTRON_DIARIZATION' not in json.dumps(result['events'][event_offset:]))
            disabled_project=load_project(disabled[0].successes[0].project_path)
            check('disabled result has no inherited host or empty speaker',
                  not any(s.is_host for s in disabled_project.speakers) and
                  {s.id for s in disabled_project.speakers}=={c.speaker_id for c in disabled_project.cues})
            result['completed']=True
        except BaseException:result['error']=traceback.format_exc()
        finally:
            save()
            if window.worker is not None and window.worker.isRunning():
                window.token.cancel();deadline=time.monotonic()+30
                while window.worker.isRunning() and time.monotonic()<deadline:pump()
            window.studio_page.undo_stack.setClean()
            # The normal close_ready chain drains mpv/render threads before
            # quitting Qt. Forcing quit here races that asynchronous shutdown.
            QTimer.singleShot(150,window.close)
    QTimer.singleShot(700,run)
