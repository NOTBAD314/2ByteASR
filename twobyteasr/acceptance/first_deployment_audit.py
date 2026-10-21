"""Opt-in real first-use GUI deployment, then actual Home ASR and timeline.

All data and configuration are guarded by studio_acceptance_audit. This audit
does not install packages, fabricate readiness, or substitute model outputs.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QProcess, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ..app.quick_setup import QuickSetupDialog
    from ..diagnostics.build_identity import load_build_identity
    from ..local_models.download_diagnostics import redact
    from ..runtime_paths import get_runtime_paths, user_data_root
    from .studio_acceptance_audit import require

    config=json.loads((output/'first-deployment.json').read_text('utf8'))
    label=str(config.get('label','fresh'))
    evidence=output/'evidence'/label
    evidence.mkdir(parents=True,exist_ok=True)
    begun=time.monotonic()
    result=dict(passed=False,identity=load_build_identity().to_dict(),events=[],phases=[],processes={},
                entry='GUI first-use QuickSetupDialog',source=config['source'],label=label,
                elevated=None,host_condition='existing development host; isolated profile/runtime/models/caches')
    if os.name=='nt':
        import ctypes
        result['elevated']=bool(ctypes.windll.shell32.IsUserAnAdmin())
    state=dict(mode='chooser',dialog=None,finished=False,last_phase=None,last_shot=0,
               started_job=False,addon=False,received=[],errors=[],observed=set(),paused=False)
    mode=config.get('mode','fresh')
    if mode=='restart':state['mode']='restart'
    if mode in {'resume','repair','diagnostic'}:state['mode']='open_existing'

    def event(name,**values):
        result['events'].append(dict(t=round(time.monotonic()-begun,2),event=name,**values))

    def save():
        (evidence/'result.json').write_text(json.dumps(redact(result),ensure_ascii=False,indent=2,default=str),'utf8')

    def shot(widget,name):
        require(widget.grab().save(str(evidence/(name+'.png'))),'screenshot failed: '+name)

    def finish(error=None):
        if state['finished']:return
        state['finished']=True
        timer.stop()
        result.update(passed=error is None,elapsed_s=round(time.monotonic()-begun,2),
                      interrupted=bool(state.get('interrupted')))
        if error:result['error']=error
        dialog=state['dialog']
        if dialog:
            (evidence/'last-dialog.log').write_text(dialog.log.toPlainText(),'utf8')
            dialog.export_deployment_diagnostic(evidence/'deployment-diagnostic.zip')
            if dialog.process.state()!=QProcess.ProcessState.NotRunning: dialog._request_pause()
            dialog.hide()
        save()
        # A nested first-use exec() must unwind before the main window closes.
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget,QuickSetupDialog):widget.reject()
        window.result_exit_code=1 if error else 0
        QTimer.singleShot(250,window.close)

    def processes():
        import psutil
        owner=psutil.Process()
        for proc in [owner,*owner.children(recursive=True)]:
            try:
                key=str(proc.pid)
                if key not in result['processes']:
                    result['processes'][key]=dict(pid=proc.pid,parent=proc.ppid(),exe=proc.exe(),
                                                   args=proc.cmdline(),created=proc.create_time())
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass

    def observe_dialog(dialog):
        state['dialog']=dialog
        job=getattr(dialog,'_journal',None)
        if job and job.job_id not in state['observed']:
            state['observed'].add(job.job_id)
            event('deployment_job',job_id=job.job_id,keys=list(dialog.download_keys),
                  source=dialog.source_combo.currentData(),pid=int(dialog.process.processId()))
            first=int(dialog.process.processId())
            QTest.mouseClick(dialog.start_button,Qt.MouseButton.LeftButton)
            require(int(dialog.process.processId())==first,'duplicate click started a second process')
            require(dialog._journal.job_id==job.job_id,'duplicate click changed job identity')
            event('duplicate_click_preserved_job',pid=first)
        phase=(getattr(dialog,'_phase',''),dialog.progress_status.text())
        if phase!=state['last_phase']:
            result['phases'].append(dict(t=round(time.monotonic()-begun,2),phase=phase[0],text=phase[1],
                indeterminate=dialog.progress.maximum()==0,bytes=getattr(dialog,'_last_bytes',0)))
            state['last_phase']=phase
        if time.monotonic()-state['last_shot']>30:
            shot(dialog,f'deploy-{len(result["phases"]):04d}')
            state['last_shot']=time.monotonic()

    def start_recognition():
        window._return_to_settings()
        index=window.recognition_language.findData('en')
        require(index>=0,'English speech-language control missing')
        window.recognition_language.setCurrentIndex(index)
        window.subtitle_output.setCurrentIndex(window.subtitle_output.findData('original'))
        window.ai_polish.setChecked(False)
        window.ai_grouping.setChecked(False)
        window.unified_glm.setChecked(False)
        window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids']=[]
        window.legacy.RUNTIME_SETTINGS['models']['speaker_source']='moss'
        require(window._save_asr_configuration(show_feedback=False),'save ASR selection')
        require(window._save_ai_configuration(show_feedback=False),'save local AI selection')
        window.import_media([str(output/'sample.wav')],replace=True)
        state['mode']='media'
        event('home_media_import',path=str(output/'sample.wav'))

    def prepared():
        dialog=state['dialog']
        require(dialog._finished_ok,'deployment did not finish successfully: '+dialog.progress_status.text())
        (evidence/('aligner' if state['addon'] else 'first-combination')).mkdir(exist_ok=True)
        dialog.export_deployment_diagnostic(evidence/('aligner-diagnostic.zip' if state['addon'] else 'first-diagnostic.zip'))
        dialog.hide()
        if not state['addon'] and mode not in {'repair'}:
            # English smoke needs the product's English alignment model.
            # The first-use local preset remains unchanged.
            page=window.workshop_page
            page._view_model('qwen_aligner')
            action=page.detail_repair if page.detail_repair.isVisible() and page.detail_repair.isEnabled() else page.detail_action
            require(action.isEnabled(),'aligner action unavailable')
            QTest.mouseClick(action,Qt.MouseButton.LeftButton)
            state['addon']=True
            state['mode']='aligner'
            event('click_additional_english_alignment_model',text=action.text())
            return
        receipts={}
        for key in ('moss','firered_vad','firered_aed','qwen_asr','qwen_aligner'):
            path=user_data_root()/'model-readiness'/(key+'.json')
            require(path.is_file(),'missing model load receipt: '+key)
            receipts[key]=json.loads(path.read_text('utf8'))
        result['readiness']=receipts
        start_recognition()

    def tick():
        if state['finished']:return
        try:
            require(time.monotonic()-begun<float(config.get('timeout_s',10800)),'GUI deployment deadline')
            processes()
            modal=QApplication.activeModalWidget()
            if isinstance(modal,QMessageBox):
                # Only the documented VRAM advisory has an explicitly local choice.
                keep=next((button for button in modal.buttons() if '仍然' in button.text() and '本机' in button.text()),None)
                if keep:
                    event('vram_advisory',text=modal.text());QTest.mouseClick(keep,Qt.MouseButton.LeftButton);return
                raise RuntimeError('unexpected modal: '+modal.windowTitle()+' '+modal.text())
            if state['mode']=='restart':
                require(not isinstance(modal,QuickSetupDialog),'healthy restart offered deployment again')
                if time.monotonic()-begun<15:return
                forbidden=[p for p in result['processes'].values() if Path(p['exe']).name.lower() in {'uv.exe','curl.exe','powershell.exe'}]
                require(not forbidden,'healthy restart launched installer/downloader')
                event('healthy_restart_without_install_or_full_validation')
                start_recognition()
            elif state['mode']=='open_existing':
                if mode=='resume':
                    state['mode']='chooser'
                    # Same ordinary Home action used by “选择识别方式…”.
                    QTimer.singleShot(0,lambda:window._next_step_action('choose_plan'))
                else:
                    window._open_model_workshop()
                    window.workshop_page._view_model('moss')
                    action=window.workshop_page.detail_repair if window.workshop_page.detail_repair.isVisible() else window.workshop_page.detail_action
                    QTest.mouseClick(action,Qt.MouseButton.LeftButton)
                    state['mode']='existing_dialog'
            elif state['mode']=='existing_dialog':
                dialogs=window.workshop_page._download_dialogs
                if not dialogs:return
                dialog=state['dialog']=dialogs[-1]
                dialog.source_combo.setCurrentIndex(dialog.source_combo.findData(config['source']))
                if mode=='diagnostic':
                    QTest.mouseClick(dialog.check_download_button,Qt.MouseButton.LeftButton)
                    state['mode']='diagnostic'
                    event('click_download_diagnostic')
                else:
                    QTest.mouseClick(dialog.rebuild_runtime_button,Qt.MouseButton.LeftButton)
                    state['mode']='deployment'
                    event('click_rebuild_managed_python')
            elif state['mode']=='diagnostic':
                dialog=state['dialog']
                if dialog._diagnostic_report is None:return
                result['diagnostic']=dialog._diagnostic_report
                shot(dialog,'download-diagnostic')
                finish()
            elif state['mode']=='chooser':
                dialogs=[widget for widget in QApplication.topLevelWidgets()
                         if isinstance(widget,QuickSetupDialog) and widget.isVisible()]
                if not dialogs:
                    require(time.monotonic()-begun<45,'first-use GUI did not appear')
                    return
                chooser=dialogs[0]
                require('local' in chooser.cards and chooser.cards['local'].isEnabled(),'local card unavailable')
                QTest.mouseClick(chooser.cards['local'],Qt.MouseButton.LeftButton)
                index=chooser.source_combo.findData(config['source'])
                require(index>=0,'source not offered on first-use GUI')
                chooser.source_combo.setCurrentIndex(index)
                shot(chooser,'01-first-use')
                result['first_choice']=dict(plan=chooser.choice,source=chooser.source_combo.currentData(),button=chooser.go_button.text())
                if config.get('ui_only'):
                    finish();return
                state['mode']='deployment'
                event('click_first_use_deploy',**result['first_choice'])
                QTest.mouseClick(chooser.go_button,Qt.MouseButton.LeftButton)
            elif state['mode'] in {'deployment','aligner'}:
                page=getattr(window,'workshop_page',None)
                dialogs=list(getattr(page,'_download_dialogs',[]))
                wanted=('qwen_aligner',) if state['addon'] else None
                dialog=next((d for d in reversed(dialogs) if wanted is None or d.download_keys==wanted),None)
                if dialog is None:return
                if state['mode']=='aligner':
                    index=dialog.source_combo.findData(config['source'])
                    dialog.source_combo.setCurrentIndex(index)
                    QTest.mouseClick(dialog.start_button,Qt.MouseButton.LeftButton)
                    state['mode']='deployment'
                observe_dialog(dialog)
                if getattr(dialog,'_journal',None) is None:return
                if config.get('interrupt_at_bytes') and not state['paused'] and dialog._last_bytes>=int(config['interrupt_at_bytes']):
                    state['paused']=True
                    state['interrupted']=True
                    event('click_pause',bytes=dialog._last_bytes,job_id=dialog._journal.job_id)
                    QTest.mouseClick(dialog.pause_button,Qt.MouseButton.LeftButton)
                if dialog.process.state()==QProcess.ProcessState.NotRunning:
                    if state.get('interrupted'):
                        require(dialog._paused and not dialog._finished_ok,'pause was reported as success')
                        event('paused_process_exited')
                        finish()
                    else:prepared()
            elif state['mode']=='media':
                if not window.start_button.isEnabled():return
                shot(window,'home-ready')
                QTest.mouseClick(window.start_button,Qt.MouseButton.LeftButton)
                require(window.worker is not None,'Home Start did not create actual worker')
                worker=window.worker
                worker.result_ready.connect(state['received'].append)
                worker.unexpected_error.connect(state['errors'].append)
                result['task_options']=asdict(worker.options)
                event('click_home_start')
                state['mode']='recognition'
            elif state['mode']=='recognition':
                require(not state['errors'],'recognition error: '+str(state['errors']))
                if not state['received']:return
                outcome=state['received'][0]
                result['recognition']=asdict(outcome)
                require(bool(outcome.successes),'actual ASR returned no successful task')
                target=Path(outcome.successes[0].project_path)
                require(target.is_file(),'ASR did not create project')
                from ..projects.studio_project import load_project
                project=load_project(target)
                require(bool(project.cues),'ASR timeline is empty')
                result['timeline']=[asdict(cue) for cue in project.cues]
                require(all(cue.end_ms>cue.start_ms>=0 for cue in project.cues),'invalid timeline bounds')
                require(any(cue.text.strip() for cue in project.cues),'ASR transcript is empty')
                transcript=' '.join(cue.text for cue in project.cues).lower()
                result['sample_keyword_matches']=[word for word in
                    ('hello','local','speech','recognition','test','weather','sunny') if word in transcript]
                require(len(result['sample_keyword_matches'])>=3,'transcript does not match the spoken sample')
                result['word_timing_count']=sum(len(row.get('words',[])) for row in project.asr_evidence.values() if isinstance(row,dict))
                require(result['word_timing_count']>=3,'no actual word-timing evidence in project')
                report_path=Path(outcome.successes[0].report_json_path)
                require(report_path.is_file() and report_path.resolve().is_relative_to(output.resolve()),
                        'missing or nonisolated Home task report')
                from .first_deployment_contract import verify_home_evidence
                result['home_report_path']=str(report_path)
                result['home_evidence']=verify_home_evidence(
                    json.loads(report_path.read_text('utf8')),project.asr_evidence,
                    job_id=outcome.successes[0].job_id)
                event('actual_recognition_and_timeline',project=str(target),cues=len(project.cues))
                shot(window,'recognition-completed')
                finish()
            save()
        except Exception:
            finish(traceback.format_exc())

    timer=QTimer(window)
    timer.setInterval(1000)
    timer.timeout.connect(tick)
    window._first_deployment_audit_timer=timer
    timer.start()
    tick()
