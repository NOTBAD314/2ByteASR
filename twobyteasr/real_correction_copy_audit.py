"""Opt-in view/save/export verification of already measured real AI results.

No request replay or new model call: production correction was measured before
this GUI phase. Its expected texts and copied project live in the audit root.
"""
import json, os, sys, time, traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QObject, QTimer
    from PySide6.QtWidgets import QApplication
    from .build_identity import load_build_identity
    from .blank_project_audit import _capture
    from .studio_project import load_project, save_project
    from .studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions, verify_subtitle_artifact

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.result=dict(passed=False,checks=[],screenshots=[],pid=os.getpid(),executable=sys.executable,
                identity=load_build_identity().to_dict(),scope='real 13-cue correction results; saved copy, no new ASR/model request')
            self.expected=json.loads((output/'expected.json').read_text('utf8'))
            self.steps=self.run();self.waiting=0;self.busy=False;self.deadline=time.monotonic()+80
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)
        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
            if not value:raise AssertionError(name+': '+str(detail))
        def tick(self):
            if self.busy:return
            self.busy=True
            try:
                now=time.monotonic()
                if now>self.deadline:raise TimeoutError('real copy GUI phase timeout')
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<float(self.waiting):return
                wait=next(self.steps);self.waiting=wait if callable(wait) else now+float(wait);self.deadline=now+80
            except StopIteration:self.result['passed']=True;self.finish()
            except BaseException:self.result['error']=traceback.format_exc();self.finish()
            finally:self.busy=False
        def ready(self):
            return self.page.project is not None and self.page._readiness.ready and not self.page._readiness.active
        def run(self):
            window.open_studio_project(output/'real-copy.2byteproj',mode='edit',source='real_correction_copy_audit')
            yield self.ready
            yield .3
            p=self.page;actual={c.id:c for c in p.project.cues}
            self.check('13 real measured results loaded',len(actual)==13,len(actual))
            for row in self.expected['cues']:
                cue=actual[row['id']]
                self.check('final text '+row['id'],cue.text==row['text'],cue.text)
                self.check('original timing and speaker '+row['id'],[cue.start_ms,cue.end_ms,cue.speaker_id]==row['timing_speaker'])
            self.check('table and timeline share final project',p.cue_model.project is p.project and p.timeline.project is p.project)
            first=next(row for row in self.expected['cues'] if '炽心勇狮' in row['text'])
            p.video.seek((first['timing_speaker'][0]+200)/1000);yield 1.2
            _capture(window,output/'real-correction-preview.png');self.result['screenshots'].append('real-correction-preview.png')
            save_project(p.project,p.project_path)
            reopened=load_project(p.project_path)
            self.check('save reopen keeps measured final texts',[(c.id,c.text) for c in reopened.cues]==[(c.id,c.text) for c in p.project.cues])
            artifacts=export_subtitle_artifacts(reopened,output/'exports','洛克真实13条校对',SubtitleExportOptions(frozenset({'srt','ass','json','txt'}),'combined'))
            for artifact in artifacts:
                self.check('production export '+artifact.format,verify_subtitle_artifact(artifact,reopened).valid,artifact.path.name)
            self.check('oral small numbers retained',any(c.text=='再来一发水刃' for c in reopened.cues) and any(c.text=='我两发水刃把你带走' for c in reopened.cues))
        def finish(self):
            self.timer.stop();window.result_exit_code=0 if self.result['passed'] else 1
            def write():(output/'real-copy-result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
            write()
            def stopped():self.result['gui_shutdown']=True;write()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.close()
    window._real_correction_copy_audit=Audit()
