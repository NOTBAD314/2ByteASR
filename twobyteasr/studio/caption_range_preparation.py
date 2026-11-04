"""Progressive preparation of an explicit range; current presentation wins."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import time

from PySide6.QtCore import QObject, QTimer

from ..i18n import bind_text


def preparation_times(cues, start_ms, end_ms):
    """Every active-set interval, including a remaining cue after an overlap."""
    bounds = {int(start_ms), int(end_ms)}
    for cue in cues:
        if cue.start_ms < end_ms and cue.end_ms > start_ms:
            bounds.add(max(int(start_ms), int(cue.start_ms)))
            bounds.add(min(int(end_ms), int(cue.end_ms)))
    ordered = sorted(bounds)
    return [left+min(80,(right-left)//2) for left,right in zip(ordered,ordered[1:]) if right>left]


class CaptionRangePreparation(QObject):
    def __init__(self, page, start_ms, end_ms):
        super().__init__(page)
        self.page, self.project = page, page.project
        self.revision = page._revision_store.render.visual_revision
        self.start_ms, self.end_ms = int(start_ms), int(end_ms)
        runtime = page.session.runtime
        first=bisect_left(runtime._cue_starts,self.start_ms)
        last=bisect_right(runtime._cue_starts,self.end_ms)
        cues=[*runtime.cues_at(self.start_ms),
              *(runtime.cue_by_id[key] for key in runtime._cue_order[first:last])]
        self.times=preparation_times(cues,self.start_ms,self.end_ms)
        self.index=0
        self.active=True
        self.state='preparing'
        self.started=time.perf_counter()
        self.last_generation=page.video._playback_clock.generation
        self.resume_after=0.
        self.timer=QTimer(self);self.timer.setInterval(80);self.timer.timeout.connect(self.tick)
        self.timer.start()
        page.destroyed.connect(self.cancel)

    def cancel(self, *_):
        if not self.active:return
        self.active=False
        self.state='cancelled'
        self.timer.stop()

    def snapshot(self):
        return dict(active=self.active,state=self.state,completed=self.index,total=len(self.times),
                    start_ms=self.start_ms,end_ms=self.end_ms,elapsed_ms=(time.perf_counter()-self.started)*1000)

    def tick(self):
        page=self.page
        if (not self.active or page.project is not self.project or getattr(page,'_close_requested',False)
                or page._revision_store.render.visual_revision!=self.revision):
            self.cancel()
            return
        # Seek preparation deliberately holds the old playback generation.
        # Yield immediately, before the eventual native seek advances it.
        if getattr(getattr(page,'_caption_seek_preparation',None),'pending',None) is not None:
            return
        generation=page.video._playback_clock.generation
        if generation!=self.last_generation:
            self.last_generation=generation
            self.resume_after=time.perf_counter()+.25
        if time.perf_counter()<self.resume_after:
            return
        scene=getattr(page,'_caption_scene',None)
        if scene is None or scene.closed:
            return
        with scene.lock:
            if scene.pending is not None:
                return
        if self.index>=len(self.times):
            self.cancel()
            self.state='complete'
            bind_text(page.save_state,'范围字幕准备完成 · 静态画面可复用，动效按播放位置呈现')
            page._studio_trace('CAPTION_RANGE_PREPARED',**self.snapshot())
            return
        at=self.times[self.index]
        from ..rendering.caption_scene import active_cues
        cues=active_cues(page,at)
        if not cues:
            self.index+=1
            return
        rect=page.position_overlay._content_rect().toRect()
        if rect.isEmpty():return
        cache=getattr(page,'_caption_playback_cache',None)
        if cache is None:
            page._prepare_caption_window(page._caption_sample_ms())
            return
        ids=tuple(c.id for c in cues)
        width,height=page._advanced_preview_size()
        cache.prepare(page._revision_store.render,ids,width,height,merge=True)
        prepared=scene.scene_items(cues)
        if any(p is None for _,p in prepared):return
        token=scene.scene_token(cues,rect,generation);key=scene.frame_key(token)
        with scene.lock:
            done=key in scene.frames or key in scene.warm_completed
        if done:
            self.index+=1
            bind_text(page.save_state,'正在准备字幕范围 · {done}/{total}',done=self.index,total=len(self.times))
        else:
            scene.warm_times([at],include_motion=True)


def start_range_preparation(page, start_ms, end_ms):
    old=getattr(page,'_caption_range_preparation',None)
    if old is not None:
        old.cancel();old.deleteLater()
    task=CaptionRangePreparation(page,start_ms,end_ms)
    page._caption_range_preparation=task
    return task


def add_preparation_action(page, menu):
    from ..i18n import tr
    from ..projects.project_range import effective_range, range_summary
    _,explicit=range_summary(page.project)
    if explicit:
        start,end=effective_range(page.project)
    else:
        start=page.timeline.visible_start_ms
        end=min(page.project.media.duration_ms,start+page.timeline.visible_duration_ms)
    menu.addAction(tr('提前准备入出点范围的字幕' if explicit else '提前准备当前可见范围的字幕'),
                   lambda:start_range_preparation(page,start,end))
    task=getattr(page,'_caption_range_preparation',None)
    if task is not None and task.active:
        menu.addAction(tr('停止提前准备'),task.cancel)
