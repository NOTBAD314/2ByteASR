"""Normal GUI roundtrip of a protected copy of an existing user project."""
import json,os,time,traceback
from pathlib import Path


def start(window,output):
    from PySide6.QtCore import QObject,QTimer
    from .studio_project import load_project
    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.p=window.studio_page;self.result={'passed':False,'checks':{}}
            self.steps=self.run();self.waiting=0;self.deadline=time.monotonic()+90
            self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.tick);self.timer.start()
        def check(self,key,value):
            self.result['checks'][key]=bool(value)
            if not value:raise AssertionError(key)
        def ready(self):
            p=self.p;c=p.video.controller
            return bool(p.project and p._readiness.ready and c and c.running and c._subtitle_media_ready)
        def tick(self):
            try:
                now=time.monotonic()
                if now>self.deadline:raise TimeoutError('data roots GUI timeout')
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                item=next(self.steps);self.waiting=item if callable(item) else now+float(item);self.deadline=now+90
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
        def run(self):
            p=self.p;expected=json.loads((output/'expected.json').read_text('utf8'))
            yield self.ready
            yield 1.0
            import sys
            from .runtime_paths import get_runtime_paths
            paths=get_runtime_paths()
            self.result['runtime']={'executable':sys.executable,'data_root':str(paths.user_data_root),
                                    'model_root':str(paths.model_root),'project_root':str(paths.project_root)}
            self.check('QA visibly labelled','隔离测试' in window.windowTitle())
            self.check('original cue count',len(p.project.cues)==expected['cues'])
            self.check('original subtitle text',[c.text for c in p.project.cues]==expected['texts'])
            self.check('video exists',Path(p.project.media.path).is_file())
            self.check('video and subtitle tracks',bool(p.project.video_tracks) and bool(p.project.cues))
            p.video.controller.set_volume(0);p._seek(expected['seek_seconds']);yield 1.0
            p.video.controller.screenshot_to_file(output/'original-copy-video.png')
            window.grab().save(str(output/'original-copy-window.png'))
            path=p.project_path;p.project_controller.save();yield .2
            saved=load_project(path)
            self.check('saved copy preserves text',[c.text for c in saved.cues]==expected['texts'])
            p.show_project_hub(skip_dirty_guard=True);yield .2
            records=p._project_library_records()
            self.result['library_count']=len(records)
            self.check('library retains original copies',len(records)>=expected['minimum_library'])
            window.grab().save(str(output/'copied-library.png'))
            window.open_studio_project(path);yield self.ready;yield .5
            self.check('reopen preserves text',[c.text for c in p.project.cues]==expected['texts'])
        def finish(self):
            self.timer.stop();self.result['passed']='error' not in self.result
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
            self.p.undo_stack.setClean();self.p._recovered_autosave_pending=False
            QTimer.singleShot(100,window.close)
    window._data_roots_audit=Audit()
