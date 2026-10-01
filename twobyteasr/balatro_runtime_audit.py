"""Opt-in normal-entry Studio audit of three authorized short theme fixtures."""
from pathlib import Path
import json,os,time,traceback
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

def start(window,out):
    page=window.studio_page;result=dict(passed=False,candidates=[],formal_project_applied=False)
    def pump(seconds):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:QApplication.processEvents();time.sleep(.002)
    def run():
        try:
            from .processes import run_hidden_subprocess,popen_hidden_subprocess
            import subprocess
            from .build_identity import load_build_identity
            from .visual_snapshot import build_visual_cue_snapshot
            result['identity']=load_build_identity().to_dict()
            window.raise_();window.activateWindow()
            page.volume_slider.setValue(0);page.video.controller.set_volume(0);page.video.set_paused(True)
            page._set_review_mode(False);page.select_cue('balatro')
            root=Path(os.environ['TWOBYTEASR_BALATRO_THEMES'])
            for ident in 'ABC':
                theme=json.loads((root/ident/'theme.json').read_text('utf8'))
                imported={}
                if os.environ.get('TWOBYTEASR_BALATRO_IMPORT_FLOW')=='1':
                    from unittest.mock import patch
                    from PySide6.QtWidgets import QFileDialog
                    # Only the chooser response is a fixture; parsing, six-frame
                    # validation and application use the real user import flow.
                    with patch.object(QFileDialog,'getOpenFileName',return_value=(str(root/ident/'theme.json'),'')):
                        page._import_ai_theme_archive()
                    drafts=page._theme_drafts();deadline=time.perf_counter()+45
                    while drafts.phase not in {'APPLIED','FAILED','CANCELLED','READY'} and time.perf_counter()<deadline:pump(.04)
                    imported=dict(phase=drafts.phase,detail=drafts.detail,actual_import_flow=True)
                    if drafts.phase!='APPLIED':raise RuntimeError('Import did not apply: '+json.dumps(imported,ensure_ascii=False))
                else:page._apply_web_theme('balatro',theme)
                page._seek(1.5);pump(2.2)
                row=dict(id=ident,theme=theme['name'],paused_truth=page.render_truth_probe(force=True),
                    snapshot=build_visual_cue_snapshot(page.project,'balatro').to_dict(),import_validation=imported)
                window.grab().save(str(out/(ident+'-qt.png')))
                run_hidden_subprocess([Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-y','-f','lavfi','-i',
                    f'gfxcapture=hwnd={int(window.winId())}:max_framerate=30:capture_cursor=0',
                    '-vf','hwdownload,format=bgra','-frames:v','1',out/(ident+'-native.png')],
                    capture_output=True,timeout=10,check=True,purpose='actual paused Studio window pixels')
                page._seek(0);pump(.2);selected=page.selected_cue_id
                previous_worker=getattr(page,'_web_live_worker',None)
                previous_metrics=len(previous_worker.metrics) if previous_worker else 0
                capture=popen_hidden_subprocess([Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-y','-f','lavfi','-i',
                    f'gfxcapture=hwnd={int(window.winId())}:max_framerate=30:capture_cursor=0',
                    '-t','3.5','-c:v','h264_nvenc','-preset','p1','-an',out/(ident+'-studio.mp4')],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,purpose='record actual three-second Studio motion')
                pump(.25)
                started=time.perf_counter();page.video.set_paused(False);pump(3.15);page.video.set_paused(True)
                row['playback_seconds']=time.perf_counter()-started;row['selected_unchanged']=page.selected_cue_id==selected
                _,capture_error=capture.communicate(timeout=8)
                row['native_recording_ok']=capture.returncode==0
                if capture_error:row['capture_diagnostic']=capture_error.decode('utf8',errors='replace')[:1000]
                row['playing_truth_after']=page.render_truth_probe(force=True)
                worker=getattr(page,'_web_live_worker',None)
                row['web_metrics']=list(worker.metrics)[previous_metrics if worker is previous_worker else 0:] if worker else []
                row['web_worker_alive']=bool(worker and worker.running)
                durations=[m['duration_ms'] for m in row['web_metrics'] if m.get('phase') in {'frame_transport','motion_clock_frame'}]
                row['frames_published']=len(durations)
                row['live_frame_ms']=dict(mean=sum(durations)/len(durations),maximum=max(durations)) if durations else {}
                row['passed']=(row['selected_unchanged'] and row['playback_seconds']<=8
                    and row['frames_published']>0 and row['native_recording_ok'] and (out/(ident+'-native.png')).is_file())
                result['candidates'].append(row)
                page._seek(1.5);pump(.3)
            result['passed']=all(c['passed'] for c in result['candidates']) and len(result['candidates'])==3
        except Exception:result['error']=traceback.format_exc()
        finally:
            page.video.set_paused(True);page.undo_stack.setClean()
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            QTimer.singleShot(150,window.close)
    QTimer.singleShot(400,run)
