"""Real user audio, normal Studio review and real-English saved result; no ASR mocks."""
from __future__ import annotations
import json,os,time,traceback
from pathlib import Path


def start(window,output):
    from PySide6.QtCore import QTimer,Qt,QPoint
    from PySide6.QtWidgets import QApplication,QMenu
    from PySide6.QtTest import QTest
    from dataclasses import asdict
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project
    from ..exports.studio_subtitle_export import export_language_layers
    from ..exports.srt_codec import parse_srt
    import sys
    output=Path(output);mode=os.environ.get('TWOBYTEASR_REAL_LANGUAGE_MODE','review')
    result=dict(passed=False,checks=[],phase='wait',mode=mode,pid=os.getpid(),frozen=bool(getattr(sys,'frozen',False)),
        executable=sys.executable,build_identity=asdict(load_build_identity()),gui_shutdown=False,
        real_user_audio=True,synthetic_asr=False,human_listen_verified=False,cloud_requests=0)
    timer=QTimer(window);timer.setInterval(100);began=time.monotonic()
    def write():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));write()
        if not value:raise AssertionError(name+': '+str(detail))
    def shot(name,target=None):(target or window).grab().save(str(output/(name+'.png')))
    def finish():
        timer.stop();write();window.result_exit_code=0 if result['passed'] else 1
        def done():result['gui_shutdown']=True;write()
        QApplication.instance().aboutToQuit.connect(done);window.close()
    def choose_menu():
        try:
            menu=QApplication.activePopupWidget()
            check('actual timeline menu opened',isinstance(menu,QMenu))
            action=next((a for a in menu.actions() if a.objectName()=='languageReviewAction'),None)
            check('unflagged auto project has review action',action is not None and action.isEnabled())
            shot('review-menu',menu);menu.close();action.trigger()
        except Exception:
            result['error']=traceback.format_exc();finish()
    def step():
        if result.get('_busy'):return
        result['_busy']=True
        try:
            if time.monotonic()-began>150:raise TimeoutError('real-language UI validation timeout')
            page=window.built_page('studio')
            if page is None or page.project is None:return
            phase=result['phase']
            if phase=='wait':
                if not getattr(page,'_readiness',None) or not page._readiness.ready:return
                if getattr(window,'_modal_host',None) and window._modal_host.isVisible():return
                if mode=='review':
                    check('old German project loaded with auto source',page.project.generation_metadata['language']['requested']=='auto')
                    check('saved project captions remain available',len(page.project.cues)>0,len(page.project.cues))
                    result['phase']='candidate';QTimer.singleShot(150,choose_menu)
                    page._show_timeline_menu(page.project.cues[0].id,page.timeline.mapToGlobal(QPoint(80,50)))
                else:
                    check('real English captions loaded',len(page.project.cues)==120,len(page.project.cues))
                    check('manual English metadata persists',page.project.generation_metadata['language']['code']=='en' and page.project.generation_metadata['language']['requested']=='en')
                    check('old German translations not attached',not page.project.generation_metadata.get('translations'))
                    archive=page.project.generation_metadata['timeline_recognition'].get('original_caption_metadata') or {}
                    check('old translations retained in source archive',bool(archive.get('translations')))
                    result['phase']='playback';page._seek(8.0);page.video.set_paused(False);result['play_at']=time.monotonic()
                return
            if phase=='candidate':
                dialog=getattr(page,'_language_candidate_dialog',None)
                if dialog is None or not dialog.isVisible():return
                c=page._language_candidate_controls
                check('reference captions viewable',c['rows'].count()==len(page.project.cues))
                check('processed project text cannot masquerade as raw candidates',not c['reuse'].isEnabled())
                c['listen'].click();result['phase']='listen';result['listen_at']=time.monotonic();shot('review-original-text',dialog);return
            if phase=='listen':
                if time.monotonic()-result['listen_at']<1.3:return
                audio=page.audio_engine.telemetry_snapshot()
                consumed=int(audio.get('decoded_bytes') or 0)>0 and int(audio.get('sink_consumed_bytes') or 0)>0
                samples=result.setdefault('listen_states',[])
                state=audio.get('state')
                if not samples or samples[-1]['state']!=state:
                    samples.append(dict(state=state,elapsed=round(time.monotonic()-result['listen_at'],3)))
                # Cold WASAPI startup/recovery is asynchronous. Keep the PCM
                # requirement, wait for its receipt rather than assuming 1.3 s.
                if not consumed and time.monotonic()-result['listen_at']<25:return
                check('real input audition consumes audio',consumed,audio)
                page.video.set_paused(True);c=page._language_candidate_controls
                c['language'].setCurrentIndex(c['language'].findData('en'));QTest.mouseClick(c['source_confirmed'],Qt.MouseButton.LeftButton)
                check('only English source confirmation is checked',c['source_confirmed'].isChecked() and not c['confirmed'].isChecked())
                check('reuse is still guarded',not c['reuse'].isEnabled())
                result['phase']='sheet';QTest.mouseClick(c['local'],Qt.MouseButton.LeftButton);return
            if phase=='sheet':
                c=getattr(page,'_recognition_controls',{})
                if not c or not c['start'].isVisible():return
                check('normal local recovery sheet opens',c['primary'].currentData()=='qwen_local',c['primary'].currentData())
                check('English selection reaches recovery sheet',c['source_language'].currentData()=='en')
                check('opening recovery did not change old project language',page.project.generation_metadata['language']['requested']=='auto')
                check('no recognition or cloud request started',not getattr(window,'_run_in_progress',False) and not getattr(page,'_recognition_running',False))
                shot('English-local-recovery-sheet');window._modal_host.hide_content();result['passed']=True;finish();return
            if phase=='playback':
                clock=page.video._playback_clock.snapshot()
                if time.monotonic()-result['play_at']<1.5 or clock.presentation_media_ms<8200:return
                check('recovered project seeks and plays original media',clock.presentation_media_ms>8200,clock.presentation_media_ms)
                audio=page.audio_engine.telemetry_snapshot();check('recovered media actual PCM consumption',int(audio.get('sink_consumed_bytes') or 0)>0,audio)
                page.video.set_paused(True);result['phase']='capture';result['capture_at']=time.monotonic();return
            if phase=='capture':
                if time.monotonic()-result['capture_at']<.6:return
                target=output/'native-English-preview.png';page.video.controller.screenshot_to_file(target)
                check('native video and subtitle plane captured',target.is_file() and target.stat().st_size>1024)
                shot('English-workbench');page.setFocus();QTest.keyClick(page,Qt.Key.Key_S,Qt.KeyboardModifier.ControlModifier)
                result['phase']='save';result['save_at']=time.monotonic();return
            if phase=='save':
                if time.monotonic()-result['save_at']<2:return
                saved=load_project(page.project_path);expected=[(c.start_ms,c.end_ms,c.text) for c in page.project.cues]
                check('real English save and reopen match',[(c.start_ms,c.end_ms,c.text) for c in saved.cues]==expected)
                export=export_language_layers(saved,output/'export','English-recovered',layers=('original',))
                rows,errors=parse_srt(export.artifacts[0].path.read_text('utf8'))
                from ..subtitle_rules.punctuation_style import style_cues,project_mode
                styled=style_cues(saved,saved.cues)
                presentation=[(c.start_ms,c.end_ms,c.text) for c in styled]
                result['punctuation_mode']=project_mode(saved)
                check('real English SRT matches saved presentation policy',not errors and [(c.start_ms,c.end_ms,c.text) for c in rows]==presentation)
                check('display punctuation does not rewrite recognized source',[(c.start_ms,c.end_ms,c.text) for c in saved.cues]==expected)
                check('English original is not stale German','ich bin' not in rows[0].text and 'Hi' in rows[0].text,rows[0].text)
                result['project_path']=str(page.project_path);result['srt_path']=str(export.artifacts[0].path);result['passed']=True;finish()
        except Exception:
            result['error']=traceback.format_exc();shot('failure');finish()
        finally:result['_busy']=False
    write();timer.timeout.connect(step);timer.start();window._real_language_audit=(timer,result)
