"""Normal MainWindow: completion -> candidate review -> reprocess -> Studio."""
from __future__ import annotations
import json,time,traceback,os
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..recognition.service import MediaResult,QueueResult
    from ..recognition.language_recovery_project import project_pending
    from ..projects.studio_project import load_project
    from ..exports.studio_subtitle_export import export_language_layers
    from ..exports.srt_codec import parse_srt
    output=Path(output)
    manual_first=os.environ.get('TWOBYTEASR_MOSS_MANUAL_FIRST')=='1'
    expected_language='en' if manual_first else 'de'
    result=dict(passed=False,checks=[],phase='wait',pid=os.getpid(),gui_shutdown=False,
                synthetic_candidates=True,real_user_click=False,cloud_requests=0)
    from dataclasses import asdict
    from ..diagnostics.build_identity import load_build_identity
    import sys
    result['frozen']=bool(getattr(sys,'frozen',False))
    result['executable']=sys.executable
    identity=load_build_identity()
    result['build_identity']=asdict(identity) if hasattr(identity,'__dataclass_fields__') else identity
    result['module_path']=__file__
    if result['frozen']:result['build']=json.loads((Path(sys.executable).parent/'2byteasr_build.json').read_text('utf8'))
    result['manual_first']=manual_first
    if manual_first:
        from ..providers import ai_connection_record,ai_providers
        ai_connection_record.feature_gate=lambda *a,**kw:'ready'
        class OfflineTranslation:
            provider_id='offline-fixture';model='fixture-no-network'
            def structured_complete(self,messages,schema,**kwargs):
                payload=json.loads(messages[-1]['content'])
                result['translation_calls']=int(result.get('translation_calls',0))+1
                result['translation_sources']=sorted(set(result.get('translation_sources',[])+[str(payload.get('source_language') or '')]))
                return {'items':[{'id':line['id'],'translation':'离线流程测试译文 '+str(line['id'])} for line in payload['lines'] if line['translate']]}
        ai_providers.provider_for_stage=lambda *a,**kw:OfflineTranslation()
    began=time.monotonic()
    timer=QTimer(window);timer.setInterval(100)
    def write():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,ok,detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail));write()
        if not ok:raise AssertionError(name+': '+str(detail))
    def shot(name,target=None):
        (target or window).grab().save(str(output/(name+'.png')))
    def finish():
        timer.stop();write();window.result_exit_code=0 if result['passed'] else 1
        def shutdown():result['gui_shutdown']=True;write()
        QApplication.instance().aboutToQuit.connect(shutdown)
        window.close()
    def step():
        if result.get('_in_step'):
            return
        result['_in_step']=True
        try:
            if time.monotonic()-began>180:raise TimeoutError('candidate recovery UI timeout')
            page=window.built_page('studio')
            if page is None or page.project is None:return
            phase=result['phase']
            if time.monotonic()-result.get('last_progress',0)>1:
                gate=getattr(page,'_readiness',None)
                result['readiness']=dict(ready=bool(gate and gate.ready),enabled=page.isEnabled(),visible=page.isVisible(),
                    completed=list(getattr(gate,'completed',[])),failed=getattr(gate,'error',''),
                    modal=bool(getattr(window,'_modal_host',None) and window._modal_host.isVisible()))
                result['last_progress']=time.monotonic();write()
            if phase=='wait':
                if not getattr(page,'_readiness',None) or not page._readiness.ready:return
                if getattr(window,'_modal_host',None) and window._modal_host.isVisible():return
                if os.environ.get('TWOBYTEASR_MOSS_VERIFY_REOPEN')=='1':
                    saved=load_project(page.project_path)
                    expected=[(c.start_ms,c.end_ms,c.text) for c in saved.cues]
                    check('fresh process reopens usable project',len(page.project.cues)>0 and not project_pending(page.project),len(page.project.cues))
                    check('fresh process language is corrected',page.project.generation_metadata.get('language',{}).get('code')==expected_language)
                    check('fresh process data matches saved project',[(c.start_ms,c.end_ms,c.text) for c in page.project.cues]==expected)
                    artifacts=export_language_layers(page.project,output/'export','reopened',layers=('original',))
                    rows,errors=parse_srt(artifacts.artifacts[0].path.read_text('utf8'))
                    check('fresh process SRT matches project',not errors and [(r.start_ms,r.end_ms,r.text) for r in rows]==expected)
                    shot('reopened-studio');result['cue_count']=len(page.project.cues);result['passed']=True;finish();return
                if manual_first:
                    page._open_recognition_sheet()
                    choice=page._recognition_controls['source_language']
                    choice.setCurrentIndex(choice.findData('en'))
                    check('real recognition sheet explicitly selects English',choice.isEnabled() and choice.currentData()=='en')
                    shot('manual-source-choice')
                    if getattr(window,'_modal_host',None):window._modal_host.hide_content()
                report_path=output/'task-report.json'
                window._tutorial_demo_result=True
                window._handle_result(QueueResult((MediaResult(page.project.media.path,'degraded_success' if manual_first else 'needs_recovery',
                    project_path=str(output/'fixture.2byteproj'),report_json_path=str(report_path)),),1.0))
                result['phase']='completion';result['completion_at']=time.monotonic()
                return
            if phase=='completion':
                if time.monotonic()-result['completion_at']<1.0:return
                if manual_first:
                    check('manual mismatch delivers usable subtitles',len(page.project.cues)>0 and window._recognition_terminal=='degraded_success',window._recognition_terminal)
                    check('completion notice keeps manual language',page.project.generation_metadata['language']['code']=='en')
                else:
                    check('completion says recovery instead of success',window._recognition_terminal=='needs_recovery',window._recognition_terminal)
                    check('completion explains no usable subtitles','尚未生成可用字幕' in window.result_task_summary.text(),window.result_task_summary.text())
                shot('completion-needs-recovery')
                check('completion recovery enabled',window.result_todo.retry_card.action.isEnabled())
                result['phase']='candidate'
                window.result_todo.retry_card.action.click()
                return
            if phase=='candidate':
                dialog=getattr(page,'_language_candidate_dialog',None)
                if dialog is None or not dialog.isVisible():return
                controls=page._language_candidate_controls
                check('all 133 candidates viewable',controls['rows'].count()==133,controls['rows'].count())
                check('original manual source can continue without forced correction',controls['reuse'].isEnabled())
                if not manual_first:
                    controls['language'].setCurrentIndex(controls['language'].findData('de'))
                    check('changing source still requires explicit confirmation',not controls['reuse'].isEnabled())
                    controls['language'].setCurrentIndex(controls['language'].findData('en'))
                check('cloud range action present',controls['cloud'].isEnabled())
                result['listen_generation']=page.video._playback_clock.generation
                controls['listen'].click()
                result['phase']='listening';result['listen_started']=time.monotonic()
                shot('candidate-originals',dialog)
                return
            if phase=='listening':
                if time.monotonic()-result['listen_started']<1.2:return
                check('listening uses current project player',page.video.controller is not None)
                if os.environ.get('TWOBYTEASR_MOSS_AUDIO_ONLY')=='1':
                    audio=page.audio_engine.telemetry_snapshot()
                    clock=page.video._playback_clock.snapshot()
                    result['listening_audio']=audio;result['listening_clock']=dict(source=clock.source,position_ms=clock.presentation_media_ms,generation=clock.playback_generation)
                    check('WAV uses decoded PCM and sink consumption',int(audio.get('decoded_bytes') or 0)>0 and int(audio.get('sink_consumed_bytes') or 0)>0,audio)
                    observed=[t for t in page.video._playback_clock.trace() if t.get('source')=='audio_engine_clock'
                        and t.get('accepted') and t.get('playback_generation')==clock.playback_generation]
                    result['accepted_audio_observations']=len(observed)
                    error_ms=abs(clock.presentation_media_ms-float(audio.get('estimated_source_ms') or 0))
                    result['audio_clock_difference_ms']=error_ms
                    check('WAV clock observes actual audio',bool(observed) and clock.presentation_media_ms>100 and error_ms<250,
                          dict(observations=len(observed),difference_ms=error_ms))

                page.video.set_paused(True)
                controls=page._language_candidate_controls
                controls['language'].setCurrentIndex(controls['language'].findData(expected_language))
                if not manual_first:controls['confirmed'].setChecked(True)
                check('candidate reuse is executable',controls['reuse'].isEnabled())
                controls['reuse'].click()
                result['phase']='sheet'
                return
            if phase=='sheet':
                controls=getattr(page,'_recognition_controls',{})
                if not controls or not controls['start'].isVisible():return
                check('reprocess action names saved candidates','已有候选' in controls['start'].text(),controls['start'].text())
                if manual_first:
                    check('worker sheet preserves English snapshot',controls['source_language'].currentData()=='en')
                    controls['translation'].setCurrentIndex(controls['translation'].findData('bilingual'))
                check('timeline mode remains selected',controls['timeline'].currentData()=='off',controls['timeline'].currentData())
                shot('reprocess-sheet')
                # Freeze only acoustic/VAD boundaries; postprocessing, worker,
                # delivery, range merge and GUI all execute their real code.
                import moss_firered_pipeline as pipeline
                pipeline.detect_lightweight_vad=lambda audio,legacy:[dict(start=0.,end=len(audio)/16000)]
                result['phase']='running';result['clicked_at']=time.monotonic()
                QTest.mouseClick(controls['start'],Qt.MouseButton.LeftButton)
                return
            if phase=='running':
                if getattr(window,'_run_in_progress',False) or getattr(page,'_recognition_running',False):return
                if time.monotonic()-result['clicked_at']<2:return
                if not page.project.generation_metadata.get('range_recognitions'):
                    result['last_status']=getattr(page,'_recognition_status_sticky','')
                    result['block_reason']=getattr(window,'_run_block_reason','')
                    result.setdefault('handoff_wait_at',time.monotonic())
                    if time.monotonic()-result['handoff_wait_at']<60:return
                    raise RuntimeError('recovery not applied: '+str(result.get('last_status'))+' '+str(result.get('block_reason')))
                check('actual Studio has nonzero subtitles',len(page.project.cues)>0,len(page.project.cues))
                check('all pending scope resolved',not project_pending(page.project))
                check('full-range correction changes project language',(page.project.generation_metadata.get('language') or {}).get('code')==expected_language)
                check('German source retained',all('new game' not in c.text for c in page.project.cues))
                events=[]
                for item in getattr(window,'_last_queue_results',[]):
                    if item.report_json_path:
                        r=json.loads(Path(item.report_json_path).read_text('utf8'));events+=r.get('events',[])
                        result['after']=r.get('result',{}).get('transcript_counts');result['after_status']=r.get('status')
                check('reuse receipt and no cloud worker',any(e.get('event')=='asr_candidate_reused' for e in events)
                    and not any(e.get('event')=='cloud_worker_launch' for e in events))
                page.undo_stack.undo()
                check('undo restores original task state',(bool(project_pending(page.project)) and not page.project.cues) if not manual_first else bool(page.project.cues) and page.project.generation_metadata['language']['code']=='en')
                page.undo_stack.redo()
                check('redo restores usable subtitles',not project_pending(page.project) and bool(page.project.cues))
                page.setFocus();QTest.keyClick(page,Qt.Key.Key_S,Qt.KeyboardModifier.ControlModifier)
                result['phase']='save';result['save_at']=time.monotonic();shot('studio-recovered')
                return
            if phase=='save':
                if time.monotonic()-result['save_at']<3:return
                saved=load_project(page.project_path)
                expected=[(c.start_ms,c.end_ms,c.text) for c in page.project.cues]
                check('saved reopen matches workbench',[(c.start_ms,c.end_ms,c.text) for c in saved.cues]==expected)
                artifacts=export_language_layers(saved,output/'export','recovered',layers=('original','translation','bilingual') if manual_first else ('original',))
                source=next(a for a in artifacts.artifacts if a.layer=='original')
                rows,errors=parse_srt(source.path.read_text('utf8'))
                check('exported SRT matches saved project',not errors and [(r.start_ms,r.end_ms,r.text) for r in rows]==expected)
                if manual_first:
                    check('all three SRT layers delivered',{a.layer for a in artifacts.artifacts}>={'original','translation','bilingual'},[a.layer for a in artifacts.artifacts])
                    for artifact in artifacts.artifacts:
                        parsed,errors=parse_srt(artifact.path.read_text('utf8'))
                        check('SRT '+artifact.layer+' count and timing',not errors and [(r.start_ms,r.end_ms) for r in parsed]==[(c.start_ms,c.end_ms) for c in saved.cues])
                    check('saved manual request and mode remain authoritative',saved.generation_metadata['language'].get('requested')=='en' and saved.generation_metadata['language'].get('mode')=='manual')
                    check('source text retained, never translated into English',all('new game' not in c.text for c in saved.cues))
                result['project_path']=str(page.project_path);result['cue_count']=len(saved.cues)
                result['passed']=True;finish()
        except Exception:
            result['error']=traceback.format_exc();shot('failure');finish()
        finally:
            result['_in_step']=False
    write();timer.timeout.connect(step);timer.start()
    window._moss_empty_recovery_audit=(timer,result)
