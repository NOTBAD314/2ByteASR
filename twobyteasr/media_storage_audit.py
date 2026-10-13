"""Opt-in normal Studio media import and native consumer lifetime acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback


def install_offline_guards():
    from .blank_project_audit import install_offline_guards as guards
    guards()


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt, QRect, QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from .blank_project_audit import _capture
    from . import blank_project_audit
    from .indexed_media import GLOBAL_INDEXED_MEDIA
    from .build_identity import load_build_identity
    from .studio_mpv import find_mpv_executable
    from .processes import run_hidden_subprocess
    from .studio_project import load_project

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page;self.started=time.monotonic()
            self.result=dict(passed=False,checks=[],screenshots=[],samples=[],
                pid=os.getpid(),executable=sys.executable,
                entry='frozen' if getattr(sys,'frozen',False) else 'quick_start.main',
                identity=load_build_identity().to_dict(),dpr=window.devicePixelRatioF(),
                scope='Normal Home→Studio import, actual timecode/play/save/style controls; controlled raster publisher inputs; no ASR/provider')
            self.steps=self.run();self.waiting=0;self.deadline=self.started+45
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(20)

        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
            if not value:raise AssertionError(name+': '+str(detail))

        def tick(self):
            try:
                modal=QApplication.activeModalWidget()
                if isinstance(modal,QMessageBox):
                    raise RuntimeError(modal.text()+' '+modal.informativeText())
                now=time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now>self.deadline:raise TimeoutError('media storage audit condition timed out')
                        return
                elif now<self.waiting:return
                step=next(self.steps)
                self.waiting=step if callable(step) else time.monotonic()+float(step)
                self.deadline=time.monotonic()+45
            except StopIteration:
                self.result['passed']=True;self.finish()
            except Exception:
                self.result['error']=traceback.format_exc()
                try:self.shot('failure')
                except Exception:pass
                self.finish()

        def click(self,button):
            self.check('visible enabled: '+button.objectName(),button.isVisible() and button.isEnabled(),button.text())
            QTest.mouseClick(button,Qt.LeftButton)

        def shot(self,name):
            _capture(window,output/(name+'.png'));self.result['screenshots'].append(name+'.png')
            controller=self.page.video.controller
            if controller and controller.running and self.page.video._media_attached:
                controller.screenshot_to_file(output/(name+'-mpv.png'))
                self.result['screenshots'].append(name+'-mpv.png')

        def sample(self,phase):
            folder=self.page.video._compositor_overlay_dir
            paths=[path for directory in (folder,folder/'caption-prepared',folder/'caption-scenes')
                for path in directory.glob('*.rgba')]
            sample=dict(phase=phase,files=len(paths),bytes=sum(p.stat().st_size for p in paths if p.is_file()),
                paths=[str(p.relative_to(folder)) for p in paths],
                transport=dict(paused=self.page.video._paused,buffered_play_pending=self.page.video._buffered_play_pending,
                    observed=self.page.video.controller.observed_properties() if self.page.video.controller else {}))
            self.result['samples'].append(sample)
            self.check(phase+': bounded disposable file count',sample['files']<=16,sample)
            self.check(phase+': bounded disposable bytes',sample['bytes']<=40*1024**2,sample['bytes'])

        def timecode(self,milliseconds):
            editor=self.page.timecode_input
            QTest.mouseClick(editor,Qt.LeftButton);QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(editor,f'00:00:{milliseconds//1000:02d}.{milliseconds%1000:03d}')
            QTest.keyClick(editor,Qt.Key_Return)

        def run(self):
            p=self.page;media=output/'short-source.flv';subtitle=output/'short-source.srt'
            window.showNormal();window.resize(1440,900);yield .3
            self.click(window.subtitle_studio_button);yield .3
            self.check('Home opens actual Studio library',window.pages.currentWidget() is p and p.project is None)
            self.click(p.project_new_button)
            yield lambda:p.project is not None and p._readiness.ready
            self.shot('01-empty')
            chooser=QFileDialog.getOpenFileName
            QFileDialog.getOpenFileName=lambda *a,**k:(str(media),'')
            try:self.click(p.studio_import_media_button)
            finally:QFileDialog.getOpenFileName=chooser
            yield lambda:p.project is not None and p.project.media.path==str(media) and p.video._startup_state=='READY'
            self.check('canonical project source remains FLV',Path(p.project.media.path)==media)
            self.check('mpv reads original FLV',Path(p.video.controller.get_property('path'))==media)
            self.check('no suffix-triggered full remux',not GLOBAL_INDEXED_MEDIA._requested,sorted(GLOBAL_INDEXED_MEDIA._requested))
            self.check('no full MP4/MKV before compatibility need',not list(GLOBAL_INDEXED_MEDIA.root.glob('v2/*/optimized.*')))
            QFileDialog.getOpenFileName=lambda *a,**k:(str(subtitle),'')
            try:self.click(p.cue_import_subtitles_button)
            finally:QFileDialog.getOpenFileName=chooser
            yield lambda:len(p.project.cues)==3
            self.click(p.save_button);yield .2
            # Ingest intentionally auto-plays once MEDIA_OPENING is ready.
            # Establish pause via its real button and observed native ACK;
            # otherwise the first supposed "play" click actually pauses.
            self.result['post_import_transport']=dict(paused=p.video._paused,
                snapshot_paused=p.video.playback_position_snapshot().paused,
                observed=p.video.controller.observed_properties(),buffered_play_pending=p.video._buffered_play_pending)
            if not p.video.playback_position_snapshot().paused or p.video._buffered_play_pending:
                self.click(p.play_button)
            yield lambda:p.video._paused and p.video.controller.observed_properties().get('pause') is True and not p.video._buffered_play_pending
            self.check('paused before playback trial',p.video.playback_position_snapshot().paused)
            self.timecode(500);yield .3;self.sample('02-original-paused');self.shot('02-original-paused')
            initial=p.video.visual_position();self.click(p.play_button)
            yield lambda:not p.video._paused and p.video.controller.observed_properties().get('pause') is False
            yield .8
            self.check('direct FLV playback moves actual video',p.video.visual_position()>initial+.2,
                dict(before=initial,after=p.video.visual_position()))
            self.sample('03-playing');self.shot('03-playing')
            self.click(p.play_button)
            yield lambda:p.video._paused and p.video.controller.observed_properties().get('pause') is True
            for index,target in enumerate((2500,500,4500,1500,3500,500)):
                self.timecode(target);yield .2
                self.check('seek '+str(index)+' preserves original backend source',Path(p.video.controller.get_property('path'))==media)
                self.check('seek '+str(index)+' actual position',abs(p.video.visual_position()*1000-target)<100,
                    dict(target=target,actual=p.video.visual_position()*1000))
                self.sample('seek-'+str(index))
            # Real paused repaints with immutable sync slots and actual mpv ACK.
            image=QImage(40,24,QImage.Format_ARGB32_Premultiplied);image.fill(0xffe1b5ce)
            rect=QRect(20,20,40,24)
            for index in range(30):
                p.video.publish_compositor_overlay(p.video.TRANSFORM_OVERLAY_ID,image,rect,context={'caller':'storage-media-audit'})
                yield .02
                self.sample('repaint-'+str(index))
            self.check('sync uploads drained',not p.video._sync_overlay_busy)
            p.video.remove_compositor_overlay(p.video.TRANSFORM_OVERLAY_ID,force=True)
            # Controlled PNG frames feed the existing web bitmap consumer,
            # exercising mmap/ACK/close without a browser or remote template.
            encoded=QByteArray();buffer=QBuffer(encoded);buffer.open(QIODevice.WriteOnly);image.save(buffer,'PNG');buffer.close()
            p.video.begin_web_live_overlays()
            for index in range(30):
                p.video.publish_web_live_overlay(p.video.TRANSFORM_OVERLAY_ID,bytes(encoded),rect,context={'caller':'storage-media-audit'})
                yield .02
                self.sample('web-frame-'+str(index))
            p.video.stop_web_live_overlays();p.video.remove_compositor_overlay(p.video.TRANSFORM_OVERLAY_ID,force=True)
            p.select_cue(p.project.cues[0].id);yield .1
            # User key entry to the existing font-size editor runs the real
            # style/undo/revision/render path.
            control=p.style_font_size
            QTest.mouseClick(control,Qt.LeftButton);QTest.keyClick(control,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(control,'76');QTest.keyClick(control,Qt.Key_Return);yield .4
            self.sample('04-style');self.shot('04-style')
            self.click(p.save_button);yield .2
            saved=load_project(p.project_path)
            self.check('save keeps original reference and all cues',saved.media.path==str(media) and len(saved.cues)==3)
            executable=find_mpv_executable()
            version=run_hidden_subprocess([str(executable),'--version'],capture_output=True,purpose='read acceptance mpv version',timeout=10)
            self.result['mpv']=dict(executable=str(executable),version=version.stdout.decode('utf8','replace') if isinstance(version.stdout,bytes) else version.stdout)
            self.click(p.studio_back_button);yield .3
            self.check('normal close returns to project library',p.project is None)
            self.sample('05-project-closed');self.shot('05-project-closed')
            self.check('no provider or external network',blank_project_audit._provider_calls==0 and not blank_project_audit._blocked_external_connections)

        def finish(self):
            self.timer.stop();self.result['provider_calls']=blank_project_audit._provider_calls
            self.result['elapsed_seconds']=round(time.monotonic()-self.started,3)
            self.result['overlay_folder']=str(self.page.video._compositor_overlay_dir)
            window.result_exit_code=0 if self.result['passed'] else 1
            self.write()
            QApplication.instance().aboutToQuit.connect(lambda:self.stopped())
            window.close()

        def stopped(self):
            self.result['gui_shutdown']=True;self.write()

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')

    window._media_storage_audit=Audit()
