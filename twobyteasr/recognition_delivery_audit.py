"""Opt-in, local-only acceptance on the user's copied completed project."""
import hashlib,json,os,time,traceback,shutil
from pathlib import Path
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

def start(window,out):
    def run():
        result={'passed':False,'checks':[],'phase':os.environ.get('TWOBYTEASR_RECOVERY_PHASE','recover')}
        page=window.studio_page;phase=result['phase'];cfg=json.loads((out/'run-config.json').read_text('utf8'))
        def pump(seconds):
            until=time.monotonic()+seconds
            while time.monotonic()<until:QApplication.processEvents();time.sleep(.01)
        def wait(predicate,seconds,label):
            until=time.monotonic()+seconds
            while time.monotonic()<until and not predicate():pump(.05)
            check(label,predicate())
        def check(label,passed):
            result['checks'].append({'name':label,'passed':bool(passed)})
            if not passed:raise AssertionError(label)
        def capture(label):
            from .processes import run_hidden_subprocess
            from .runtime_paths import detect_install_root
            window.grab().save(str(out/(label+'-qt.png')))
            run_hidden_subprocess([detect_install_root()/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
                f'gfxcapture=hwnd={int(window.winId())}:max_framerate=10:capture_cursor=0','-vf','hwdownload,format=bgra',
                '-frames:v','1','-y',out/(label+'-native.png')],timeout=15,purpose='recovered Studio actual pixels')
        try:
            from .build_identity import load_build_identity
            result['identity']=load_build_identity().to_dict()
            original=Path(cfg['original']);before=hashlib.sha256(original.read_bytes()).hexdigest()
            target=out/'fixture.2byteproj'
            wait(lambda:page.project is not None and getattr(page,'_readiness',None) and page._readiness.ready,60,'Studio ready with copied project')
            if phase=='recover':
                check('same-path in-memory project starts empty',len(page.project.cues)==0)
                shutil.copy2(original,target)
                from .service import PipelineEvent,MediaResult,QueueResult
                report=json.loads(Path(cfg['report']).read_text('utf8'))
                window._studio_recognition_context={'media_path':report['media']['path'],'project_path':str(target),'project_id':page.project.project_id}
                window.started_at=time.perf_counter();window._run_in_progress=True
                window._show_task_notification=lambda *_args,**_kw:None
                for e in report['events']:
                    if e['event'] in ('stage_started','stage_completed'):
                        window._handle_event(PipelineEvent(kind=e['event'],timestamp=e['time'],media_path=report['media']['path'],media_index=1,media_total=1,
                            stage_index=e.get('index',0),stage_total=e.get('total',11),label=e.get('label',''),resource=e.get('resource',''),payload=e))
                window._handle_result(QueueResult((MediaResult(report['media']['path'],'degraded_success',project_path=str(target),report_json_path=cfg['report']),),637.847))
                wait(lambda:len(page.project.cues)==1127 and not window._studio_recognition_context and page._readiness.ready,60,'completion loads all 1127 saved cues')
                check('degraded completion has terminal label','完成' in window.result_title.text() and '复核' in window.result_title.text())
                check('task progress finalized',window.progress_percent.text()=='100%')
            else:check('fresh process retains 1127 cues',len(page.project.cues)==1127)
            cue=page.project.cues[139];page._seek(cue.start_ms/1000+.2);pump(3);page.select_cue(cue.id);pump(.2)
            check('requested cue selected',page.selected_cue_id==cue.id)
            if phase=='recover':
                page._begin_canvas_inline_edit();pump(.2)
                editor=page.subtitle_edit_input;check('real subtitle editor visible',editor.isVisible())
                result['edit_before']={'id':cue.id,'selected':page.selected_cue_id,'text':editor.toPlainText()}
                editor.setFocus();QTest.keyClick(editor,Qt.Key_End,Qt.ControlModifier);QTest.keyClicks(editor,' [acceptance]');pump(.1)
                result['typed_text']=editor.toPlainText()
                QTest.keyClick(editor,Qt.Key_Return);pump(.5)
                result['edit_after']={'selected':page.selected_cue_id,'text':page._cue_lookup[cue.id].text}
                check('normal editor committed text','[acceptance]' in page._cue_lookup[cue.id].text)
                QTest.mouseClick(page.save_button,Qt.LeftButton)
                wait(lambda:page.undo_stack.isClean(),20,'normal save completed')
                (out/'expected.json').write_text(json.dumps({'cue_id':cue.id,'text':page._cue_lookup[cue.id].text,'count':1127},ensure_ascii=False),'utf8')
            else:
                expected=json.loads((out/'expected.json').read_text('utf8'))
                check('fresh process retains edited subtitle',page._cue_lookup[expected['cue_id']].text==expected['text'])
            wait(lambda:page.video.controller is not None,20,'native video controller ready')
            initial=page.video._playback_clock.presentation_position_ms()
            QTest.mouseClick(page.play_button,Qt.LeftButton);pump(1.3)
            final=page.video._playback_clock.presentation_position_ms();result['playback_advance_ms']=final-initial
            check('actual playback clock advances',final-initial>500)
            capture(phase+'-playing');QTest.mouseClick(page.play_button,Qt.LeftButton);pump(.15)
            from .recognition_recovery import recover_report
            recovered=recover_report(cfg['report'],recovery_root=out/'idempotent')
            from .studio_project import load_project,save_project
            item=load_project(recovered);item.cues[0].text='保留用户后续修改';save_project(item,recovered);saved=recovered.read_bytes()
            check('recovery preserves subsequent edits',recover_report(cfg['report'],recovery_root=out/'idempotent')==recovered and recovered.read_bytes()==saved)
            check('original project remains unchanged',hashlib.sha256(original.read_bytes()).hexdigest()==before)
            result['passed']=True
        except Exception:result['error']=traceback.format_exc()
        finally:
            (out/(phase+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
            if page.video.controller:page.video.set_paused(True)
            page.undo_stack.setClean();window.close()
    QTimer.singleShot(2000,run)
