"""Normal source/frozen Ultra selection and real background inference audit."""
from __future__ import annotations
import copy,json,os,sys,threading,time,traceback,wave
from pathlib import Path


def start(window,output):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..local_models import model_workshop as workshop
    from ..runtime_paths import user_data_root
    from .blank_project_audit import _capture
    result=dict(passed=False,checks=[],real_user_click=False,readiness='actual offline worker',
                identity=load_build_identity().to_dict(),pid=os.getpid(),worker_results=[])
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value):
        result['checks'].append(dict(name=name,passed=bool(value)))
        if not value:raise AssertionError(name)
    def pump_until(predicate,timeout=12):
        stop=time.monotonic()+timeout
        while not predicate() and time.monotonic()<stop:
            QApplication.processEvents();time.sleep(.02)
        check('condition completed before timeout',predicate())
    studio_poll = QTimer(window)
    studio_state = {}
    def shutdown(error=None):
        if error:result['error']=error
        timer.stop();poll.stop();studio_poll.stop()
        if ticks:
            result['ui_timer_p95_ms']=sorted(ticks)[min(len(ticks)-1,int(len(ticks)*.95))]
            result['ui_timer_max_ms']=max(ticks)
        save()
        try:
            window.studio_page.undo_stack.setClean()
            window.studio_page._subtitle_task_panel().hide()
        except Exception:
            pass
        window.close();QTimer.singleShot(400,QApplication.instance().quit)
    def finish():
        poll.stop()
        try:
            if shared.get('error'):raise RuntimeError(shared['error'])
            check('GUI never imported torch','torch' not in sys.modules)
            result['ui_timer_intervals_ms']=ticks
            if ticks:
                result['ui_timer_p95_ms']=sorted(ticks)[min(len(ticks)-1,int(len(ticks)*.95))]
                result['ui_timer_max_ms']=max(ticks)
            from ..recognition.qwen_upgrade import activate_if_ready
            check('real inference activates existing Qwen profile',activate_if_ready(window.legacy.RUNTIME_SETTINGS))
            check('new task profile is Ultra base',window.legacy.RUNTIME_SETTINGS['models']['qwen_alignment_profile']=='ultra-v5')
            page=window.workshop_page
            page.refresh(check_status=False)
            models={model.key:model for model in workshop.MODELS}
            for key in ('qwen_aligner','qwen_ultra_head'):
                state=page._model_state(models[key],'timeline')
                check(key+' actual inference enables selection',state in {'installed','selected'})
                if window.firered_asr_backend.currentData()!=key:page._perform_action(key,role='timeline')
                QTest.qWait(250)
                check(key+' saved backend',window.firered_asr_backend.currentData()==key)
                check(key+' settings identity',window.legacy.RUNTIME_SETTINGS['models']['firered_asr_backend']==key)
                check('default CTC is retired',window.legacy.RUNTIME_SETTINGS['switches'].get('use_ja_ctc_aligner') is False)
            window._open_model_picker('timeline');QTest.qWait(400)
            panel=window._model_picker_timeline_panel
            check('one existing base Qwen choice',{'qwen_aligner','qwen_ultra_head'}<=panel.cards.keys() and 'qwen_ultra_aligner' not in panel.cards)
            check('no dedicated CTC choice','ja_ctc_aligner' not in panel.cards)
            for width,height in ((1600,960),(1180,820)):
                window.resize(width,height);QTest.qWait(200)
                panel.scroll.ensureWidgetVisible(panel.cards['qwen_ultra_head'].action);QTest.qWait(100)
                check('Ultra action visible at '+str(width),panel.cards['qwen_ultra_head'].action.isVisible())
                _capture(window,output/f'ultra-picker-{width}.png')
            window._modal_host._request_close()
            QTest.qWait(250)
            page._perform_action('qwen_aligner',role='timeline')
            check('Head is off for the actual Studio task',window.firered_asr_backend.currentData()=='qwen_aligner')
            fixture=Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            window.open_studio_project(str(fixture),mode='edit',source='ultra_alignment_audit')
            pump_until(lambda:window.built_page('studio') is not None,30)
            page=window.built_page('studio')
            pump_until(lambda:page.project is not None and page.project.cues and page._readiness.ready,30)
            page.runtime_settings=copy.deepcopy(window.legacy.RUNTIME_SETTINGS)
            if page.video.controller is not None:
                page.video.controller.set_volume(0)
            page.volume_slider.setValue(0)
            cue=page.project.cues[0]
            studio_state.update(stage='cancel-first',cue_id=cue.id,
                before=(cue.text,cue.start_ms,cue.end_ms),deadline=time.monotonic()+150)
            from ..studio.studio_realign import start_realign
            start_realign(page,[cue.id])
            page.show_subtitle_tasks()
            studio_state['task']=max(page._subtitle_tasks.values(),key=lambda item:item.started)
            studio_poll.setInterval(50);studio_poll.timeout.connect(studio_step);studio_poll.start()
        except Exception:
            shutdown(traceback.format_exc())
    def studio_step():
        try:
            page=window.studio_page;task=studio_state['task'];panel=page._subtitle_task_panel()
            if time.monotonic()>studio_state['deadline']:raise TimeoutError('Studio task acceptance timeout')
            if studio_state['stage']=='cancel-first':
                if task.ended is not None:raise AssertionError('Expected an active task before cancelling')
                if '加载模型' in task.phase or '词级对齐' in task.phase:
                    panel.grab().save(str(output/'studio-alignment-progress.png'))
                    check('existing task cancel button enabled',panel.cancel_button.isEnabled())
                    QTest.mouseClick(panel.cancel_button,Qt.MouseButton.LeftButton)
                    studio_state['stage']='wait-cancel'
            elif studio_state['stage']=='wait-cancel' and task.ended is not None:
                check('Studio cancel is terminal',task.cancelled)
                cue=page.project.cues[0]
                check('cancel keeps original text and cue interval',(cue.text,cue.start_ms,cue.end_ms)==studio_state['before'])
                page._retry_subtitle_task_range(dict(task_id=task.task_id,record=dict(cue_ids=[cue.id])))
                studio_state['task']=max(page._subtitle_tasks.values(),key=lambda item:item.started)
                studio_state['stage']='wait-success';page.show_subtitle_tasks()
            elif studio_state['stage']=='wait-success' and task.ended is not None:
                check('retried local task applied',task.counts()['applied']==1)
                from ..timeline.studio_caption_timeline import KEY
                row=page.project.studio_state[KEY]['instances'][studio_state['cue_id']]
                check('current selected Ultra identity stored',row['forced_alignment']['model']=='17slever17/Qwen3-ForcedAligner-Ultra')
                check('real word times stored',bool(row.get('words')))
                from ..projects.studio_project import save_project,load_project
                path=output/'roundtrip.2byteproj';save_project(page.project,path)
                loaded=load_project(path)
                check('new acoustic evidence roundtrips',loaded.studio_state[KEY]['instances'][studio_state['cue_id']]['words']==row['words'])
                before_words=copy.deepcopy(row['words'])
                page.undo_stack.undo();page.undo_stack.redo()
                check('word realignment is one undoable command',page.project.studio_state[KEY]['instances'][studio_state['cue_id']]['words']==before_words)
                from ..studio.studio_realign import start_realign
                start_realign(page,[studio_state['cue_id']])
                studio_state['task']=max(page._subtitle_tasks.values(),key=lambda item:item.started)
                studio_state['stage']='wait-cache';page.show_subtitle_tasks()
            elif studio_state['stage']=='wait-cache' and task.ended is not None:
                check('repeat local window hits checkpoint',task.alignment_progress['cached']>=1)
                check('cached local task remains applied',task.counts()['applied']==1)
                panel.refresh();panel.grab().save(str(output/'studio-alignment-cached.png'))
                check('task ranges use actual project time',task.rows[studio_state['cue_id']]['start_ms']==studio_state['before'][1]
                      and task.rows[studio_state['cue_id']]['end_ms']==studio_state['before'][2])
                check('task labels its timebase',task.time_label=='工程时间')
                result['studio_task_elapsed_s']=task.elapsed
                result['studio_task_counts']=task.counts()
                result['studio_alignment_progress']=task.alignment_progress
                check('Studio kept torch out of GUI','torch' not in sys.modules)
                result['passed']=True;shutdown()
        except Exception:
            shutdown(traceback.format_exc())
    def tick():
        now=time.perf_counter()
        if ticks_at[0]:ticks.append((now-ticks_at[0])*1000)
        ticks_at[0]=now
    shared={};ticks=[];ticks_at=[None];started=[0.];ctc_before=True
    timer=QTimer(window);timer.setInterval(16);timer.timeout.connect(tick)
    poll=QTimer(window);poll.setInterval(50)
    def poll_done():
        if shared.get('done'):finish()
        elif time.monotonic()-started[0]>180:
            shared['error']='background inference timeout';finish()
    poll.timeout.connect(poll_done)
    def launch():
        nonlocal ctc_before
        try:
            window.showNormal();window.resize(1600,960)
            page=window.workshop_page;page.ensure_ui()
            pump_until(lambda:page._registry is not None and not page.background_busy(),30)
            check('real model files discovered',{'qwen_ultra_aligner','qwen_ultra_head'}<=page._installed)
            models={model.key:model for model in workshop.MODELS}
            check('official files are not Ultra readiness',page._model_state(models['qwen_aligner'],'timeline') not in {'installed','selected'})
            ctc_before=window.legacy.RUNTIME_SETTINGS.get('switches',{}).get('use_ja_ctc_aligner',True)
            window._switch_page(window.settings_scroll)
            from ..recognition.run_context import RuntimeContext,activate_runtime_context
            from ..recognition import asr
            settings=copy.deepcopy(window.legacy.RUNTIME_SETTINGS)
            def work():
                context=RuntimeContext(alignment_checkpoint_dir=str(output/'checkpoints'))
                try:
                    import numpy as np
                    root=Path(workshop.__file__).resolve().parents[2]
                    # External sources are beside the frozen archive as required by the spec.
                    if getattr(sys,'frozen',False):root=Path(sys._MEIPASS)
                    with wave.open(str(root/'assets/diagnostics/speech_en.wav'),'rb') as stream:
                        audio=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
                    jobs=[dict(id='audit',text='Hello this is a local speech recognition test the weather is sunny today',
                               language='English',window_start_ms=0,window_end_ms=round(len(audio)/16))]
                    with activate_runtime_context(context):
                        for key in ('qwen_ultra_aligner','qwen_ultra_head'):
                            context.asr_settings_snapshot=copy.deepcopy(settings)
                            context.asr_settings_snapshot.setdefault('models',{})['firered_asr_backend']=key
                            payload=asr.run_qwen_aligner_worker(audio,jobs)
                            if not any(row.get('segments') for row in payload['results']):raise RuntimeError('empty inference result')
                            if key=='qwen_ultra_aligner':
                                from ..recognition.qwen_upgrade import receipt_from_payload
                                receipt=receipt_from_payload(payload)
                            else:
                                receipt=dict(status='PASS',inference_verified=True,alignment_receipt={
                                    name:payload.get(name) for name in ('model','model_revision','code','unit_policy','alignment_identity','execution_identity')})
                            target=user_data_root()/'model-readiness'/(key+'.json')
                            target.parent.mkdir(parents=True,exist_ok=True)
                            target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
                            result['worker_results'].append(dict(profile=key,pid=payload.get('pid'),identity=payload.get('alignment_identity'),
                                load_ms=payload.get('load_ms'),inference_ms=payload.get('inference_ms'),base_forward_attempts=payload.get('base_forward_attempts')))
                except Exception:shared['error']=traceback.format_exc()
                finally:context.close_resources();shared['done']=True
            started[0]=time.monotonic();timer.start();poll.start()
            threading.Thread(target=work,name='ultra-audit-worker',daemon=True).start()
        except Exception:
            shared['error']=traceback.format_exc();finish()
    QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),save()))
    QTimer.singleShot(2000,launch)
