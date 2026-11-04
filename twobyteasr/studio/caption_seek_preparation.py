"""Latest-request seek presentation with an owned copy of the last complete frame.

The existing mpv clock remains authoritative. The cover is a separate mpv
overlay; timeline input stays live while caption and decoder work completes.
"""
from __future__ import annotations

import threading
import time
import uuid
import weakref

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from ..rendering.caption_scene import active_cues, animated_caption, complete_scene_for_seek
from ..playback.studio_mpv import SEEK_COVER_OVERLAY_ID as COVER_ID



class CaptionSeekPreparation(QObject):
    capture_ready = Signal(int, object, str)

    def __init__(self, page):
        super().__init__(page)
        self.page=page;self.pending=None;self.serial=0;self.closed=False
        self.cover=None;self.cover_epoch=0;self.cover_scope=None;self.cover_posted=0.;self.cover_ready=False
        self.capture_running=False;self.capture_error='';self.status_owned=None;self.status_before=''
        self.lock=threading.RLock();self.samples=[]
        self.timer=QTimer(self);self.timer.setInterval(16);self.timer.timeout.connect(self.tick)
        self.capture_ready.connect(self._captured)
        reference=weakref.ref(self)
        def retire(*_):
            owner=reference()
            if owner is not None:owner.cancel(closing=True)
        page.destroyed.connect(retire)

    def _scope(self):
        page=self.page
        controller=page.video.controller
        return (id(page.project),getattr(getattr(page,'_readiness',None),'generation',0),
                id(controller),getattr(controller,'instance_id',None),getattr(controller,'_subtitle_binding_epoch',None))

    def request(self, seconds, accurate):
        page=self.page;video=page.video;scene=getattr(page,'_caption_scene',None)
        if (self.closed or page.project is None or not page.project.cues
                or getattr(video,'_startup_state','')!='READY' or not getattr(scene,'active',False)
                or not getattr(video,'_media_has_video',True) or getattr(video,'_clock_only',False)
                or not callable(getattr(video.controller,'screenshot_to_file',None))
                or not callable(getattr(video.controller,'post_raw_overlay',None))):
            if self.pending is not None:self.cancel()
            return False
        target=max(0,round(float(seconds)*1000))
        if self.pending is None and self.cover is None and abs(video.visual_position()*1000-target)<=1:
            return False  # Same presented frame; the existing no-op path owns it.
        if self.cover_scope is not None and self.cover_scope!=self._scope():self.cancel()
        if self.pending is not None and self.pending.get('phase')=='reveal':
            if self._removal_applied(self.pending):self._finish(self.pending,resume=False)
            else:self.cover_posted=0.;self.cover_ready=False
        self.serial+=1
        held=round(video.visual_position()*1000)
        if getattr(page,'_playback_mode','source')=='mapped':
            from ..timeline.studio_edit_sequence import sequence_of
            from ..timeline.studio_sequence_mapper import source_to_timeline
            mapped=source_to_timeline(sequence_of(page.project),held,segment=page._mapped_sequence_segment())
            if mapped is not None:held=mapped.timeline_ms
        record=dict(serial=self.serial,scope=self._scope(),target=target,accurate=bool(accurate),
                    started=time.perf_counter(),phase='prepare',held_sample_ms=held,
                    initial_generation=video._playback_clock.generation)
        self.pending=record
        video.begin_caption_seek_hold()
        page.timeline.set_playhead(target)
        record['optimistic_at']=time.perf_counter()
        page._studio_trace('CAPTION_SEEK_REQUEST',request_sequence=self.serial,target_ms=target,
                           playback_generation=record['initial_generation'])
        if self.cover_scope is None:
            self.cover_scope=record['scope'];self._capture()
        self.timer.start()
        self.tick()
        return True

    def _capture(self):
        page=self.page;video=page.video;controller=video.controller
        self.cover_epoch+=1;epoch=self.cover_epoch;self.capture_running=True;self.capture_error=''
        folder=video._compositor_overlay_dir/'seek-cover';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(uuid.uuid4().hex+'.png')
        def work():
            pixels=None;error=''
            try:
                began=time.perf_counter()
                controller.screenshot_to_file(path,mode='window',fast=True)
                picture=QImage(str(path))
                if picture.isNull():raise RuntimeError('播放器未返回完整画面')
                from ..rendering.caption_pixel_cache import prepared_pixels
                pixels=prepared_pixels(picture,None,began,folder)
            except Exception as exc:error=f'{type(exc).__name__}: {exc}'
            finally:
                try:path.unlink(missing_ok=True)
                except OSError:pass
            with self.lock:
                if self.closed or epoch!=self.cover_epoch:return
                try:self.capture_ready.emit(epoch,pixels,error)
                except RuntimeError:pass
        worker=threading.Thread(target=work,name='seek-complete-frame',daemon=True)
        from ..rendering.overlay_session import register_overlay_worker
        register_overlay_worker(video._compositor_overlay_dir,worker)
        worker.start()

    def _captured(self, epoch, pixels, error):
        if self.closed or epoch!=self.cover_epoch or self.pending is None:return
        self.capture_running=False
        if self.cover_scope!=self._scope():self.cancel();return
        self.cover=pixels;self.capture_error=str(error or '')
        if error:
            self.page._studio_trace('CAPTION_SEEK_COVER_FAILED',error=error,request_sequence=self.serial)
        self.tick()

    def _publish_cover(self):
        if self.cover is None:return bool(self.capture_error)
        video=self.page.video;rect=video.rect()
        geometry=tuple(rect.getRect())
        if self.cover_posted and geometry==getattr(self,'cover_geometry',None):
            rows=getattr(video,'_prepared_caption_publications',())
            matches=[row for row in rows if row.get('cue_id')==self.cover_key and row.get('posted_at',0)>=self.cover_posted]
            if matches:
                if matches[-1].get('applied'):self.cover_ready=True;return True
                self.cover_posted=0.
            else:return False
        self.cover_key=f'seek-cover:{self.cover_epoch}'
        self.cover_posted=time.perf_counter();self.cover_geometry=geometry;self.cover_ready=False
        if not video.publish_compositor_overlay(COVER_ID,self.cover.image,rect,prepared_pixels=self.cover,
                context=dict(caller='CaptionSeekCover',cue_id=self.cover_key)):
            self.cover_posted=0.
        return False

    def _prepare_caption(self, request):
        page=self.page;scene=page._caption_scene;target=request['target']
        cues=active_cues(page,target)
        if not cues:return True
        page._prepare_caption_window(target,prepare_pixels=False)
        prepared=scene.scene_items(cues)
        if any(item is None for _,item in prepared):return False
        # HTML owns an independent browser clock and keeps its existing path.
        if any(getattr(item,'web',None) is not None for _,item in prepared):return True
        rect=page.position_overlay._content_rect().toRect()
        if rect.isEmpty():return False
        token=scene.scene_token(cues,rect,page.video._playback_clock.generation)
        key=scene.frame_key(token)
        with scene.lock:
            cached=scene.frames.get(key)
            done=scene.warm_completed.get(key)
            if cached is not None:
                scene.frames.move_to_end(key)
                scene._seek_reserved_frame=(key,cached)
                return True
            if any(animated_caption(p) for _,p in prepared) and isinstance(done,tuple) and done[1]>=request['started']:
                return True
            scene._priority_warm_time=target
        scene.warm_times([target],include_motion=True)
        return False

    def tick(self):
        request=self.pending
        if request is None or self.closed:self.timer.stop();return
        page=self.page;video=page.video
        if (request['scope']!=self._scope() or getattr(page,'_close_requested',False)):
            self.cancel();return
        elapsed=time.perf_counter()-request['started']
        if elapsed>.1 and self.status_owned is None:
            from ..i18n import tr
            self.status_before=page.save_state.text()
            self.status_owned=self.status_before+' · '+tr('正在准备跳转')
            page.save_state.setText(self.status_owned)
        if elapsed>8:
            page._studio_trace('CAPTION_SEEK_TIMEOUT',request_sequence=request['serial'],phase=request['phase'])
            self.cancel()
            page._seek_immediate(request['target']/1000,accurate=request['accurate'])
            return
        if request['phase']=='reveal':
            if self._removal_applied(request):self._finish(request,resume=True)
            return
        if request['phase']=='prepare':
            prepared=self._prepare_caption(request)
            if prepared:request.setdefault('caption_ready_at',time.perf_counter())
            covered=self._publish_cover()
            if self.pending is not request or not prepared or not covered:return
            request['prepared_at']=time.perf_counter();request['phase']='seek'
            if self.cover is not None:
                request['capture_ms']=(self.cover.finished-self.cover.started)*1000
                request['capture_pack']=dict(self.cover.timings or {})
            scene=page._caption_scene
            with scene.lock:scene._priority_warm_time=None
            page._seek_immediate(request['target']/1000,accurate=request['accurate'])
            if self.pending is not request:return
            request['scope']=self._scope();self.cover_scope=request['scope']
            request['committed_generation']=video._playback_clock.generation
            trace=getattr(video,'_active_seek_trace',None)
            if isinstance(trace,dict):
                trace['presentation_request_sequence']=request['serial']
                trace['caption_preparation_ms']=(request['prepared_at']-request['started'])*1000
                trace['markers']['T0_user_input']=request['started']
                trace['markers']['T1_handler_entered']=request['started']
                trace['markers']['T2_optimistic_playhead_visible']=request['optimistic_at']
                trace['markers']['C1_target_caption_prepared']=request['prepared_at']
            return
        from .studio_readiness import player_surface_ready
        if not self._publish_cover():return
        if not player_surface_ready(page):return
        page._present_caption_scene()
        scene=page._caption_scene
        cues=active_cues(page,page._caption_sample_ms())
        if cues:
            if not complete_scene_for_seek(scene,cues[0].id,video._playback_clock.generation):return
            sample=getattr(scene,'_last_published_sample_ms',None)
            if not any(row.get('applied') and row.get('scene_token')==scene.token
                       and row.get('sample_ms')==sample for row in getattr(video,'_prepared_caption_publications',())):
                return
        elif getattr(scene,'published',None) is not None:return
        intended=video.playback_intended
        if not page._playback_buffers_ready(include_seek=False,include_audio=intended):return
        if self.pending is not request:return
        if self.cover is not None:
            request['phase']='reveal';request['reveal_posted']=time.perf_counter()
            video.remove_compositor_overlay(COVER_ID,force=True)
            return
        self._finish(request,resume=True)

    def _removal_applied(self, request):
        state=self.page.video.controller.applied_visual_state().get('overlays',{}).get(COVER_ID,{})
        return state.get('visible') is False and state.get('monotonic',0)>=request.get('reveal_posted',float('inf'))

    def _finish(self, request, *, resume):
        if self.pending is not request:return
        page=self.page;video=page.video;intended=video.playback_intended
        request['revealed_at']=time.perf_counter()
        self.samples.append({key:value for key,value in request.items() if key!='scope'})
        del self.samples[:-128]
        self.pending=None;self.timer.stop();self._release_cover(remove=False)
        page._studio_trace('CAPTION_SEEK_PRESENTED',request_sequence=request['serial'],
            generation=video._playback_clock.generation,elapsed_ms=(request['revealed_at']-request['started'])*1000)
        self._restore_status()
        if intended and resume:
            if video._seek_hold_active:video._resume_after_seek_hold(video._seek_hold_token)
            else:video.set_paused(False)

    def _restore_status(self):
        if self.status_owned is not None:
            if self.page.save_state.text()==self.status_owned:self.page.save_state.setText(self.status_before)
            self.status_owned=None

    def _release_cover(self, *, remove=True):
        if remove and self.cover is not None:
            try:self.page.video.remove_compositor_overlay(COVER_ID,force=True)
            except RuntimeError:pass
        self.cover=None;self.cover_scope=None;self.cover_posted=0.;self.cover_ready=False
        with self.lock:self.cover_epoch+=1
        scene=getattr(self.page,'_caption_scene',None)
        if scene is not None:
            with scene.lock:scene._priority_warm_time=None;scene._seek_reserved_frame=None

    def cancel(self, *, closing=False):
        with self.lock:
            self.closed=bool(closing);self.cover_epoch+=1
        try:self.timer.stop()
        except RuntimeError:pass
        request,self.pending=self.pending,None;self.serial+=1
        if not closing:
            self._release_cover();self._restore_status()
            if request is not None and request['scope']==self._scope() and self.page.video._seek_hold_active:
                self.page.video.set_paused(True)
        else:self.cover=None;self.cover_scope=None


def coordinate_caption_seek(page, seconds, accurate):
    scene=getattr(page,'_caption_scene',None)
    if (not getattr(scene,'active',False) or not getattr(page,'project',None)
            or not getattr(page.project,'cues',()) or not isinstance(page,QObject)):
        return False
    owner=getattr(page,'_caption_seek_preparation',None)
    if owner is None:owner=page._caption_seek_preparation=CaptionSeekPreparation(page)
    return owner.request(seconds,accurate)
