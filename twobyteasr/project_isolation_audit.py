"""Normal-window project switches, including unregistered native caption pixels."""
import json,os,time,traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QObject,QTimer
    from PySide6.QtGui import QImage,QPainter,QColor,QFont,QPixmap
    from .build_identity import load_build_identity
    from .studio_mpv import ADVANCED_OVERLAY_ID
    from .caption_boundary_publisher import CaptionBoundaryPublisher,BoundaryPixels
    from types import SimpleNamespace

    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.page=window.studio_page
            self.result=dict(passed=False,checks={},identity=vars(load_build_identity()),
                scope='isolated normal Qt/mpv windows; direct-publisher regression fixture and ordinary project switching',
                transitions=[],provider_calls=0)
            self.started=time.monotonic();self.deadline=self.started+90;self.waiting=0
            self.steps=self.run();self.timer=QTimer(self);self.timer.setInterval(30)
            self.timer.timeout.connect(self.tick);self.timer.start()

        def check(self,name,value):
            self.result['checks'][name]=bool(value)
            if not value:raise AssertionError(name)

        def tick(self):
            try:
                now=time.monotonic()
                if now>self.deadline:raise TimeoutError('project isolation step timed out')
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                item=next(self.steps);self.waiting=item if callable(item) else now+float(item)
                self.deadline=now+60
                (output/'progress.json').write_text(json.dumps({'checks':len(self.result['checks']),'line':self.steps.gi_frame.f_lineno}),'utf8')
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()

        def ready(self):
            p=self.page;c=p.video.controller
            return bool(p.project and c and c.running and c._subtitle_media_ready and
                c._studio_subtitle_path and c._studio_subtitle_path==p.video._ass_path)

        def open(self,name):
            self.opened=False
            window.open_studio_project(output/'projects'/(name+'.2byteproj'),on_ready=lambda *_:setattr(self,'opened',True))

        def run(self):
            p=self.page
            yield self.ready
            if os.environ.get('TWOBYTEASR_ISOLATION_BASELINE'):
                # Replay only the entry versions of the two lifecycle methods.
                import importlib.util
                root=Path(os.environ['TWOBYTEASR_ISOLATION_BASELINE'])
                for filename,cls,methods in [('studio_video_canvas','MpvCanvas',['enter_empty_playback_state','remove_compositor_overlay']),
                                              ('studio_project_flow','StudioProjectFlowMixin',['_close_project_session'])]:
                    spec=importlib.util.spec_from_file_location('twobyteasr._isolation_baseline_'+filename,root/(filename+'.py'))
                    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
                    current=__import__('twobyteasr.'+filename,fromlist=[cls])
                    for method in methods:setattr(getattr(current,cls),method,getattr(getattr(mod,cls),method))
                self.result['baseline_replay']=str(root)
            # Make the exact logged failure state: native slot 1 has pixels
            # from the direct publisher, while the QWidget registry is empty.
            c=p.video.controller
            image=QImage(480,96,QImage.Format_ARGB32_Premultiplied);image.fill(QColor('#fd00db'))
            painter=QPainter(image);painter.setPen(QColor('white'));painter.setFont(QFont('Arial',24,QFont.Bold))
            painter.drawText(10,60,'OLD PROJECT A');painter.end()
            raw=output/'old-project-pixels.bgra';raw.write_bytes(bytes(image.constBits()))
            from .visual_snapshot import build_visual_cue_snapshot
            snapshot=build_visual_cue_snapshot(p.project,'same-cue',width=640,height=360)
            # QLabel.clear used to leave this retained source/snapshot alive.
            # A later compositor promotion could re-publish A for B's same id.
            p.advanced_cue_overlay.set_visual(QPixmap.fromImage(image),snapshot,
                animate_graph=False,prepared_scene=None)
            p.video.clear_caption_boundaries()
            boundary=CaptionBoundaryPublisher(c,ADVANCED_OVERLAY_ID)
            c._caption_boundary_publisher=boundary
            pixels=SimpleNamespace(raw_path=raw,raw_geometry={'alpha_nonzero':480*96})
            boundary.register('old-project',BoundaryPixels('old',0,10000,pixels,dict(x=40,y=80,width=480,height=96,stride=1920)))
            boundary.observe(dict(position=.5,paused=False,seeking=False))
            # Pending upload completion and its validity are tested separately;
            # leave the same raw native pixels deterministically while paused.
            c.set_raw_overlay(ADVANCED_OVERLAY_ID,raw,x=40,y=80,width=480,height=96,stride=1920)
            p.video._active_compositor_overlays.discard(ADVANCED_OVERLAY_ID)
            c.screenshot_to_file(output/'A-unregistered-native.png')
            self.check('native-only caption exists before close',c.applied_visual_state()['overlays'][ADVANCED_OVERLAY_ID]['visible'])
            p.show_project_hub(skip_dirty_guard=True)
            yield .2
            self.check('hub drops retained caption source',p.advanced_cue_overlay._snapshot is None
                and p.advanced_cue_overlay._source.isNull())
            self.check('hub retires native-only pixels',not c.applied_visual_state()['overlays'].get(ADVANCED_OVERLAY_ID,{}).get('visible',False))
            self.open('B')
            yield lambda:self.opened and self.ready()
            yield .2
            c=p.video.controller
            c.screenshot_to_file(output/'B-after-native.png')
            self.check('old publisher revoked at project close',boundary.closed)
            from PIL import Image
            import numpy as np
            colors=np.asarray(Image.open(output/'B-after-native.png').convert('RGB'))
            self.check('native-only caption retired after B opens',not ((colors[:,:,0]>245)&(colors[:,:,1]<10)&(colors[:,:,2]>200)).any())
            retained=p.advanced_cue_overlay._snapshot
            self.check('B never reuses A canvas',retained is None or retained.text=='PROJECT B OWN')
            for turn,name in enumerate(['empty','A','same-id','B','A','empty','B','same-id','A','B']):
                p.show_project_hub(skip_dirty_guard=True);self.open(name)
                yield lambda:self.opened and self.ready()
                p._seek(.5);yield .15
                c=p.video.controller;text=Path(c._studio_subtitle_path).read_text('utf8')
                expected={'A':'PROJECT A OWN','B':'PROJECT B OWN','same-id':'COPIED PROJECT OWN','empty':''}[name]
                retained=p.advanced_cue_overlay._snapshot
                self.check(f'{turn}-{name}-canvas-owner',retained is None or retained.text==expected)
                self.check(f'{turn}-{name}-own-ass',expected in text if expected else 'Dialogue:' not in text)
                for foreign in {'PROJECT A OWN','PROJECT B OWN','COPIED PROJECT OWN'}-{expected}:
                    self.check(f'{turn}-{name}-reject-{foreign}',foreign not in text)
                self.check(f'{turn}-{name}-one-native-track',sum(t.get('type')=='sub' and t.get('external',False)
                    for t in c.get_property('track-list',[]))==1)
                self.result['transitions'].append({'name':name,'ass':c._studio_subtitle_path,
                    'overlay_state':c.applied_visual_state(),'project_id':p.project.project_id})
                c.screenshot_to_file(output/f'{turn:02}-{name}-native.png')
            p.video.set_paused(False);yield .35;p.video.set_paused(True)
            self.check('play after switches retains current media',Path(c.get_property('path')).resolve()==Path(p.video._media_path).resolve())
            window.grab().save(str(output/'final-window.png'))
            # Optional original project copies, read-only source media. All
            # autosaves and migrations affect only the copies under output.
            for name in ['user-A','user-B','user-A','user-B']:
                if not (output/'projects'/(name+'.2byteproj')).exists():continue
                p.show_project_hub(skip_dirty_guard=True);self.open(name)
                yield lambda:self.opened and self.ready()
                p._seek(187.5 if name=='user-A' else 38.133);yield .6
                if name=='user-A':
                    p.video.set_paused(False);yield .5;p.video.set_paused(True)
                else:
                    c=p.video.controller
                    self.check('actual B gap has no old raster',not c.applied_visual_state()['overlays'].get(ADVANCED_OVERLAY_ID,{}).get('visible',False))
                    self.check('actual B owns its ASS','利用格挡对敌人进行反牵制' not in Path(c._studio_subtitle_path).read_text('utf8'))
                    c.screenshot_to_file(output/'actual-B-native.png');window.grab().save(str(output/'actual-B-window.png'))

        def finish(self):
            self.timer.stop();self.result['passed']='error' not in self.result
            self.result['elapsed_seconds']=round(time.monotonic()-self.started,3)
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
            p=self.page;p.undo_stack.setClean();p._recovered_autosave_pending=False
            QTimer.singleShot(150,window.close)
    window._project_isolation_audit=Audit()
