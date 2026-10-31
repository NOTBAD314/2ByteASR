"""Normal application entry: real recovery UI, local worker, save and export."""
from __future__ import annotations
import copy,json,os,sys,time,traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..recognition.language_recovery_project import project_pending
    from ..projects.studio_project import load_project
    from ..exports.studio_subtitle_export import export_language_layers
    from ..exports.srt_codec import parse_srt
    from ..runtime_paths import get_runtime_paths
    output=Path(output)
    config=json.loads((output/'audit-config.json').read_text('utf8'))
    os.environ['2BYTEASR_MODEL_ROOT']=config['model_root']
    os.environ['2BYTEASR_QWEN3_ASR_DIR']=str(Path(config['model_root'])/'Qwen3-ASR-1.7B')
    os.environ['2BYTEASR_QWEN_ALIGNER_DIR']=str(Path(config['model_root'])/'Qwen3-ForcedAligner-0.6B')
    os.environ['TWOBYTEASR_MAIN_PYTHON']=config['python']
    os.environ['TWOBYTEASR_DEVELOPER_RUNTIMES']='1'
    os.environ['TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY']='1'
    get_runtime_paths(refresh=True)
    result=dict(passed=False,checks=[],phase='wait',pid=os.getpid(),frozen=bool(getattr(sys,'frozen',False)),
                executable=sys.executable,module_path=__file__,identity=load_build_identity().to_dict(),gui_shutdown=False)
    before=load_project(config['project']).to_dict()
    started=time.monotonic()
    timer=QTimer(window);timer.setInterval(150)
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
        if not value:raise AssertionError(name+': '+str(detail))
    def write():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    def stop():
        timer.stop();write();window.result_exit_code=0 if result['passed'] else 1
        def shutdown():result['gui_shutdown']=True;write()
        QApplication.instance().aboutToQuit.connect(shutdown)
        window.close()
    def shot(name):
        window.grab().save(str(output/(name+'.png')))
    def verify_project(page):
        project=page.project
        ranges=project.generation_metadata.get('range_recognitions') or []
        ids=ranges[-1]['cue_ids'] if ranges else (project.generation_metadata.get('timeline_recognition') or {}).get('range',{}).get('cue_ids',[])
        new=[c for c in project.cues if c.id in set(ids)]
        check('accepted recovered range persisted',bool(ids) and not project_pending(project),len(new))
        check('no Italian used in recovered original',all('quindi' not in c.text.lower() for c in new))
        check('saturation sentence is English',any('double' in c.text.lower() and 'saturation' in c.text.lower() for c in new))
        outside={c['id']:c for c in before['cues'] if c['start_ms']>=1159891}
        current={c.id:c for c in project.cues}
        from dataclasses import asdict
        check('outside captions exact',all(cid in current and asdict(current[cid])==row for cid,row in outside.items()))
        old_trans=before['generation_metadata'].get('translations',{})
        check('outside translations exact',all(project.generation_metadata.get('translations',{}).get(cid)==old_trans.get(cid) for cid in outside))
        check('speaker roster and styles retained',project.to_dict()['speakers']==before['speakers'] and project.to_dict()['styles']==before['styles'])
        check('user outline retained in recovered scope',any(c.appearance_override.get('outline_width')==2.5 for c in new))
        if config.get('require_translation'):
            from ..subtitle_rules.subtitle_translation import cue_status,records_of
            check('new Chinese translations are current',all(cue_status(project,c,target='zh-Hans')=='done' for c in new))
            selected_record=next(records_of(project)[c.id] for c in new if 'saturation' in c.text.lower() and 'double' in c.text.lower())
            check('saturation Chinese is associated',all(word in selected_record['text'] for word in ('双击','饱和度')))
        # Same production exporter used by the UI; no synthetic translation is added.
        exported=export_language_layers(project,output/'export','recovered')
        check('source SRT export exists',any(a.layer=='original' for a in exported.artifacts))
        for artifact in exported.artifacts:
            cues,errors=parse_srt(artifact.path.read_text('utf8'))
            check('SRT readback '+artifact.layer,not errors and bool(cues))
        selected=next(c for c in new if 'saturation' in c.text.lower() and 'double' in c.text.lower())
        page.select_cue(selected.id);page._seek(selected.start_ms/1000+.5)
        QTest.qWait(350);shot('recovered-saturation')
        page.video.set_paused(True)
        until=time.monotonic()+15
        trace={}
        while time.monotonic()<until:
            trace=page.subtitle_visibility_trace(reason='language_recovery_audit')
            if selected.id in trace.get('rendered_cue_ids',[]) and trace.get('visible'):break
            QTest.qWait(50)
        result['caption_visibility']=trace
        check('recovered caption really presented',selected.id in trace.get('rendered_cue_ids',[]) and trace.get('visible'),trace)
        native=output/'recovered-saturation-mpv.png'
        page.video.controller.screenshot_to_file(native)
        from PySide6.QtGui import QImage
        pixels=QImage(str(native))
        check('actual mpv window frame captured',not pixels.isNull())
        levels=[pixels.pixelColor(x,y).lightness() for x in range(0,pixels.width(),max(1,pixels.width()//32))
                for y in range(0,pixels.height(),max(1,pixels.height()//24))]
        check('native frame contains real video',max(levels)-min(levels)>40)
        if config.get('frame_export'):
            frames=output/'saved-frames';frames.mkdir(exist_ok=True)
            page.frame_capture.settings.setValue('frame_export/directory',str(frames))
            page.frame_capture.settings.setValue('frame_export/subtitles',True)
            page.frame_capture.failed.connect(lambda message:result.update(frame_error=message))
            page.frame_capture.last=None;page.frame_capture.save()
            until=time.monotonic()+90
            while page.frame_capture.busy and time.monotonic()<until:QTest.qWait(50)
            result['saved_frame']=page.frame_capture.last
            check('production frame with captions exported',page.frame_capture.last is not None,
                  dict(receipt=result['saved_frame'],busy=page.frame_capture.busy,error=result.get('frame_error'),status=page.save_state.text()))
        result['recovered_cues']=len(new);result['total_cues']=len(project.cues)
        result['project_path']=str(page.project_path)
    def step():
        try:
            if time.monotonic()-started>config.get('timeout',700):raise TimeoutError('recovery audit timeout')
            page=window.built_page('studio')
            if page is None or page.project is None:return
            phase=result['phase']
            if phase=='wait':
                if not page.isVisible() or not page.isEnabled():return
                modal=getattr(window,'_modal_host',None)
                if modal is not None and modal.isVisible():return
                if not getattr(page,'_readiness',None) or not page._readiness.ready:return
                if config.get('mode')=='verify':
                    result['phase']='verifying'
                    verify_project(page);result['passed']=True;stop();return
                page._sync_recognition_zero_state()
                check('one pending language range',len(project_pending(page.project))==1)
                button=getattr(page,'_language_recovery_button',None)
                if button is not None and not button.isEnabled():return
                if not getattr(page,'_readiness',None) or not page._readiness.ready:return
                check('recovery action visible',button is not None and button.isVisible())
                shot('pending-range')
                result['before_action']=dict(running=bool(getattr(page,'_recognition_running',False)),
                    media=page.project.media.path,media_exists=Path(page.project.media.path).is_file(),
                    project_path=str(page.project_path),ready=bool(page._readiness.ready))
                button.clicked.connect(lambda _checked=False:result.update(clicked_signal_seen=True))
                result['phase']='opening'
                button.click()
                result['action_status']=getattr(page,'_language_recovery_request_status',None)
                result['action_at']=time.monotonic()
                result['phase']='sheet';write();return
            if phase=='sheet':
                controls=getattr(page,'_recognition_controls',{})
                if not controls:
                    if time.monotonic()-result['action_at']>3:
                        shot('missing-sheet');raise RuntimeError('sheet not opened: '+str(result.get('action_status'))+' clicked='+str(result.get('clicked_signal_seen')))
                    return
                shot('recovery-model-sheet')
                check('local Qwen ASR selected',controls['primary'].currentData()=='qwen_local',controls['primary'].currentData())
                check('English timeline model selected',controls['timeline'].currentData()=='qwen_aligner')
                check('no paid translation selected',controls['translation'].currentData()=='original')
                shot('recovery-model-sheet')
                result['phase']='starting';result['started_click_at']=time.monotonic()
                QTest.mouseClick(controls['start'],Qt.MouseButton.LeftButton)
                result['phase']='running';write();return
            if phase=='running':
                if getattr(window,'_run_in_progress',False) or getattr(page,'_recognition_running',False):return
                if time.monotonic()-result['started_click_at']<2:return
                if not page.project.generation_metadata.get('range_recognitions'):
                    result.setdefault('delivery_wait_at',time.monotonic())
                    result['last_status']=str(getattr(page,'_recognition_status_sticky',''))
                    if time.monotonic()-result['delivery_wait_at']<60:return
                    raise RuntimeError('range result not applied: '+result['last_status'])
                result['phase']='verifying'
                verify_project(page)
                page.undo_stack.undo()
                check('undo restores pending range',bool(project_pending(page.project)))
                page.undo_stack.redo()
                check('redo restores English selection',not project_pending(page.project))
                page.setFocus();QTest.keyClick(page,Qt.Key.Key_S,Qt.KeyboardModifier.ControlModifier)
                result['phase']='save';result['save_wait_at']=time.monotonic();write();return
            if phase=='save':
                if time.monotonic()-result['save_wait_at']<2:return
                reopened=load_project(page.project_path)
                check('saved reopen is English',not project_pending(reopened) and any('double-click' in c.text for c in reopened.cues))
                result['saved_project']=str(page.project_path)
                result['passed']=True;stop()
        except Exception:
            result['error']=traceback.format_exc();stop()
    timer.timeout.connect(step);timer.start()
    window._language_range_audit=(timer,result)
