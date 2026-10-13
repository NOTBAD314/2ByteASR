"""Playback flow: position tracking, seeks, play/pause, volume/speed,
and visual route preparation for Subtitle Studio."""

from __future__ import annotations
from .playback_probe import measured

from collections.abc import Mapping
from PySide6.QtCore import QTimer, Qt, QObject, Signal
from .studio_edit_sequence import (sequence_of, timeline_duration_ms)
from .studio_helpers import _format_ms, format_timeline_timecode
from .studio_sequence_mapper import (source_to_timeline, timeline_to_source)
from .studio_widgets import _icon
from .style_recipe import (recipe_payload_for_style, route_recipe)
from .visual_runtime import VisualOwner


class _CaptionFrameBridge(QObject):
    observed=Signal(object)

class StudioPlaybackFlowMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _invalidate_audio_tail(self):
        self._owned_audio_tail = None
        self._audio_tail_seek_pending = None
        self.video._playback_clock.set_presentation_hold(False)
        self.video.set_external_clock_enabled(bool(self.project is not None
            and not getattr(self, '_close_requested', False)
            and not getattr(self.video, '_media_has_video', True)))

    def _owned_tail_sample(self, *, paused):
        from .owned_audio_tail import owned_audio_sample
        engine = getattr(self, 'audio_engine', None)
        if engine is None:
            return None
        payload = engine.clock_observation()
        source = str(getattr(self, '_active_video_preview_source_path', ''))
        rate = float(self.video._playback_rate) * float(getattr(self.video, '_source_rate_multiplier', 1.))
        if owned_audio_sample(payload, engine._last_payload,
                generation=self.video._playback_clock.generation,
                session=engine._session_generation, source=source, paused=paused, rate=rate):
            return payload
        return None

    def _begin_audio_tail(self, *, paused=False):
        from .owned_audio_tail import OwnedAudioTail, audio_pcm_drained
        payload = self._owned_tail_sample(paused=paused)
        if payload is None or (not paused and audio_pcm_drained(payload)):
            return False
        active = str(getattr(self, '_active_video_preview_clip_id', ''))
        clip = next((c for t in self.project.video_tracks for c in t.clips if c.id == active), None)
        if clip is None or int(self.timeline.playhead_ms) >= clip.timeline_out_ms:
            return False
        self._owned_audio_tail = OwnedAudioTail(id(self.project),
            str(self._active_video_preview_key), active, str(self._active_video_preview_source_path),
            self.video._playback_clock.generation, self.audio_engine._session_generation,
            tuple(payload['transport_generation']), int(payload.get('source_generation') or 0),
            clip.timeline_out_ms, paused, float(payload['effective_rate']))
        self._audio_tail_seek_pending = None
        self.video._playback_clock.set_presentation_hold(False)
        self._audio_only_subtitle_active = True
        self.video.set_external_clock_enabled(True)
        self._studio_trace('VIDEO_EOF_AUDIO_TAIL', paused=paused,
            generation=self.video._playback_clock.generation,
            source_ms=payload.get('estimated_source_ms'), clip_id=active)
        return True

    def _prepare_audio_tail_seek(self, source_seconds, project_ms, *, transition=False):
        """A seek beyond the last video frame waits for real, owned audio PCM."""
        receipt = getattr(self, '_owned_audio_tail', None) if transition else None
        payload = self._owned_tail_sample(paused=bool(self.video._paused)) if receipt is not None else None
        if payload is None or not receipt.matches(project=self.project,
                key=str(self._active_video_preview_key), clip=str(self._active_video_preview_clip_id),
                generation=self.video._playback_clock.generation, payload=payload):
            receipt = None
        self._invalidate_audio_tail()
        if self.project is None or not getattr(self.video, '_media_has_video', True):
            return
        from .media_service import GLOBAL_MEDIA_SERVICE
        try:
            metadata = GLOBAL_MEDIA_SERVICE.metadata(self._active_video_preview_source_path)
        except (OSError, RuntimeError, ValueError):
            return
        end = float(metadata.video_stream_end_ms or 0)
        source_ms = float(source_seconds) * 1000
        if not metadata.has_audio or end <= 0 or source_ms < end:
            return
        from .owned_audio_tail import AudioTailWait
        self._audio_tail_seek_pending = AudioTailWait(id(self.project),
            str(self._active_video_preview_key), str(self._active_video_preview_clip_id),
            str(self._active_video_preview_source_path), self.video._playback_clock.generation,
            self.audio_engine._session_generation,
            float(self.video._playback_rate) * float(getattr(self.video, '_source_rate_multiplier', 1.)),
            int(project_ms), source_ms, receipt)
        import time
        self._audio_tail_seek_started = time.monotonic()
        self.video._playback_clock.set_presentation_hold(True)

    def _refresh_audio_tail_clock(self):
        if self.project is None or getattr(self, '_close_requested', False):
            self._invalidate_audio_tail()
            return False
        pending = getattr(self, '_audio_tail_seek_pending', None)
        if pending is not None:
            if (not self._audio_tail_waiting()
                    or (pending.visual_receipt is not None and not self._audio_tail_visual_active())):
                self._invalidate_audio_tail()
                return False
            self._begin_audio_tail(paused=bool(self.video._paused))
        token = getattr(self, '_owned_audio_tail', None)
        if token is None:
            return False
        payload = self._owned_tail_sample(paused=bool(self.video._paused))
        if payload is None or not token.matches(project=self.project,
                key=str(self._active_video_preview_key), clip=str(self._active_video_preview_clip_id),
                generation=self.video._playback_clock.generation, payload=payload):
            self._invalidate_audio_tail()
            return False
        from .owned_audio_tail import audio_pcm_drained
        if not self.video._paused and audio_pcm_drained(payload):
            self._studio_trace('VIDEO_AUDIO_TAIL_DRAINED', source_ms=payload.get('estimated_source_ms'))
            self._invalidate_audio_tail()
            self._advance_project_boundary(token.boundary_ms)
            return False
        self._audio_only_subtitle_active = True
        self.video.set_external_clock_enabled(True)
        return True

    def _audio_tail_waiting(self):
        pending = getattr(self, '_audio_tail_seek_pending', None)
        import time
        return bool(pending is not None and self.project is not None
            and not getattr(self, '_close_requested', False)
            and time.monotonic() - self._audio_tail_seek_started <= 10.
            and pending.matches(project=self.project, key=str(self._active_video_preview_key),
                clip=str(self._active_video_preview_clip_id), source=str(self._active_video_preview_source_path),
                generation=self.video._playback_clock.generation, session=self.audio_engine._session_generation,
                rate=float(self.video._playback_rate) * float(getattr(self.video, '_source_rate_multiplier', 1.))))

    def _audio_tail_visual_active(self):
        if getattr(self, '_owned_audio_tail', None) is not None:
            return True
        if not self._audio_tail_waiting():
            return False
        pending = self._audio_tail_seek_pending
        from .owned_audio_tail import held_video_frame_ready
        controller = self.video.controller
        return bool(pending.may_hold_visual(self.audio_engine._last_payload)
            and held_video_frame_ready(pending.visual_receipt,
                generation=self.video._playback_clock.generation,
                attached=self.video._media_attached, running=controller is not None and controller.running,
                frame=getattr(controller, 'observed_position', lambda:{})(),
                properties=getattr(controller, 'observed_properties', lambda:{})()))

    def _audio_tail_startup_caption_ready(self):
        from .caption_scene import active_cues
        from .owned_audio_tail import tail_caption_publication_ready
        expected = tuple(c.id for c in active_cues(self, self._caption_sample_ms()))
        self._present_caption_scene()
        return tail_caption_publication_ready(getattr(self, '_caption_scene', None),
            project=self.project, generation=self.video._playback_clock.generation,
            expected=expected, publications=getattr(self.video, '_prepared_caption_publications', ()))

    def _finish_project_playback(self):
        if self.video._eof_reached:
            return
        self.video.set_paused(True)
        # Source duration can differ from the project end. Do not use the
        # canvas' legacy _set_eof(), which reanchors to that source duration.
        self.video._eof_reached = True
        self._sync_play_button(True)

    def _advance_project_boundary(self, boundary_ms):
        end = timeline_duration_ms(self.project)
        point = min(end, max(0, int(boundary_ms)))
        if self._loop_enabled and self._loop_region_ms and point >= self._loop_region_ms[1]:
            self._seek(self._loop_region_ms[0] / 1000.0)
            self.video.set_paused(False)
        elif point < end:
            self._seek(point / 1000.0)
            self.video.set_paused(False)
        else:
            self._finish_project_playback()
            self._apply_project_playhead(end)

    def _handle_source_eof(self):
        """A decoder EOF belongs to the active clip, never the whole project."""
        if self.project is None or getattr(self, '_close_requested', False):
            return False
        clock = self.video._playback_clock
        observation = getattr(self.video.controller, 'observed_position', lambda: {})()
        if clock.exact_seek_pending or (observation and int(observation.get('source_generation', -1)) != clock.generation):
            return True  # ignore the previous load/seek's late EOF
        if self.video._paused:
            return True  # EOF must never override an explicit user pause
        if self._audio_tail_waiting():
            return True  # a resumed tail waits for this epoch's unpaused PCM
        if self._refresh_audio_tail_clock() or self._begin_audio_tail():
            return True
        active = getattr(self, '_active_video_preview_clip_id', '')
        clip = next((c for t in self.project.video_tracks for c in t.clips if c.id == active), None)
        boundary = clip.timeline_out_ms if clip else timeline_duration_ms(self.project)
        self._advance_project_boundary(boundary)
        return True

    def _mapped_sequence_segment(self):
        from .studio_edit_sequence import segment_at
        sequence = sequence_of(self.project)
        active = getattr(self, "_active_video_preview_clip_id", "")
        return next((s for s in sequence.segments if s.id == active), None) or segment_at(
            sequence, int(self.timeline.playhead_ms))

    def _caption_sample_ms(self, milliseconds=None):
        """Use the Clock's observed frame for captions and smooth time for UI."""
        cached=getattr(self,'_caption_tick_time_ms',None)
        if cached is not None:return cached
        value=self.timeline.playhead_ms if milliseconds is None else milliseconds
        video=self.video;clock=getattr(video,'_playback_clock',None)
        if (clock is None or video._paused or clock.exact_seek_pending
                or not getattr(video,'_media_has_video',True)):return value
        from .caption_frame_time import project_frame_rate
        cache=getattr(self,'_caption_rate_cache',None)
        store=getattr(self,'_revision_store',None)
        key=(id(self.project),getattr(getattr(store,'render',None),'mapping_revision',0))
        if cache is None or cache[0]!=key:
            cache=self._caption_rate_cache=(key,project_frame_rate(self.project))
        value=clock.media_frame_ms(cache[1])
        if getattr(self,'_playback_mode','source')=='mapped' and self.project:
            mapped=source_to_timeline(sequence_of(self.project),int(value),segment=self._mapped_sequence_segment())
            if mapped is not None:value=mapped.timeline_ms
        return value

    @measured('qt_position')
    def _position_changed(self, seconds: float, *, defer_follow: bool = False, _bypass_throttle: bool = False) -> None:
        if getattr(self, '_loading_project_media', False):
            return
        if getattr(self, "_defer_next_video_position_follow", False):
            defer_follow = True
            self._defer_next_video_position_follow = False
        clock = getattr(self.video, "_playback_clock", None)
        # 2026-09-02（倍速卡顿二段根治）：播放期 UI 播头更新改为"常驻 20ms
        # 刷新定时器取最新位置"。此前 singleShot(20)+16ms 信号源形成 10/32ms
        # 拍频（实测 stdev≈12ms），2~4 倍速下播头步长忽大忽小=一卡一卡。
        # 定时器在播放期间持续运行，节流分支只写 pending；暂停后某次
        # flush 发现无新位置即自行停表。精确 seek 挂起与暂停态不节流。
        if (
            not _bypass_throttle
            and clock is not None
            and not getattr(clock, "exact_seek_pending", False)
            and not bool(getattr(self.video, "_paused", True))
            # The visual tick is already paced at 16 ms. Passing it through a
            # second independent 16 ms timer delayed cue identity one frame.
            and getattr(getattr(clock,'snapshot',lambda:None)(),'source','')!='visual_tick'
        ):
            self._playhead_ui_pending = (seconds, defer_follow, clock.generation,
                                         getattr(self, '_playback_mode', 'source'))
            timer = self._ensure_playhead_flush_timer()
            if timer is not None and not timer.isActive():
                timer.start()
            return
        # An unthrottled update is always fresher than anything queued.
        self._playhead_ui_pending = None
        playback_mode = getattr(self, "_playback_mode", "source")
        if clock is not None and getattr(clock, "exact_seek_pending", False):
            target = getattr(clock, "_seek_target_ms", None)
            if target is not None:
                display_ms = int(target)
                if playback_mode == "mapped" and self.project:
                    # The seek target is SOURCE time on the primary route;
                    # the playhead displays timeline time.
                    pending_map = source_to_timeline(
                        sequence_of(self.project), display_ms,
                        segment=self._mapped_sequence_segment(),
                    )
                    if pending_map is not None:
                        display_ms = pending_map.timeline_ms
                self._apply_project_playhead(display_ms, defer_follow=defer_follow)
                return
        milliseconds = int(float(seconds) * 1000)
        if playback_mode == "mapped" and self.project:
            sequence = sequence_of(self.project)
            current_segment = self._mapped_sequence_segment()
            mapped = source_to_timeline(sequence, milliseconds, segment=current_segment)
            if mapped is None:
                if current_segment is not None and milliseconds < current_segment.source_in_ms:
                    if self.video.controller:
                        self.video.seek(current_segment.source_in_ms / 1000.0, accurate=True)
                    return
                if current_segment is not None and self.video.controller and not self.video._paused:
                    self._advance_project_boundary(current_segment.timeline_out_ms)
                return
            milliseconds = mapped.timeline_ms
        self._apply_project_playhead(milliseconds, defer_follow=defer_follow)

    def _ensure_playhead_flush_timer(self):
        timer = getattr(self, "_playhead_flush_timer", None)
        if timer is not None:
            return timer
        try:
            timer = QTimer(self)
            timer.setInterval(16)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.timeout.connect(lambda: self._flush_pending_playhead())
            self._playhead_flush_timer = timer
            return timer
        except RuntimeError:
            return None

    def _flush_pending_playhead(self) -> None:
        pending = getattr(self, "_playhead_ui_pending", None)
        self._playhead_ui_pending = None
        if pending is None:
            # No fresh position since the last flush: the producer (visual
            # tick) stopped — paused or EOF. Disarm until playback resumes.
            timer = getattr(self, "_playhead_flush_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
            return
        import time as _time

        self._playhead_ui_last_ts = _time.monotonic()
        seconds, defer_follow, generation, mode = pending
        clock=getattr(self.video,'_playback_clock',None)
        if clock is not None and (generation != clock.generation
                or mode != getattr(self, '_playback_mode', 'source')):
            return
        if clock is not None and not self.video._paused and not clock.exact_seek_pending:
            # The GUI can be busy switching a cue. Its queued position is then
            # old, while the independent follower has already extrapolated
            # past it. Sample the same Clock now instead of resetting demand
            # to that old position with a fresh timestamp.
            elapsed = getattr(self.video, '_clock', None)
            seconds=clock.sample_presentation(
                source='ui_flush',
                elapsed_ms=elapsed.elapsed() if elapsed is not None else None,
            ).presentation_media_ms/1000.
        self._position_changed(seconds, defer_follow=defer_follow, _bypass_throttle=True)

    @measured('apply_playhead')
    def _apply_project_playhead(self, milliseconds: int, *, defer_follow: bool = False) -> None:
        # Several owner/cache checks share this GUI tick. Read widget/DPI
        # geometry once, without caching across edits, resizes or queued work.
        previous=getattr(self,'_caption_tick_geometry',None)
        previous_time=getattr(self,'_caption_tick_time_ms',None)
        sampler=getattr(self,'_caption_sample_ms',None)
        self._caption_tick_time_ms=sampler(milliseconds) if callable(sampler) else milliseconds
        size=getattr(self,'_advanced_preview_size',None)
        self._caption_tick_geometry=size() if callable(size) else None
        try:
            self._apply_project_playhead_frame(milliseconds,defer_follow=defer_follow)
        finally:
            self._caption_tick_geometry=previous
            self._caption_tick_time_ms=previous_time

    def _apply_project_playhead_frame(self, milliseconds: int, *, defer_follow: bool = False) -> None:
        milliseconds = max(0, int(milliseconds))
        duration = timeline_duration_ms(self.project) if self.project else 0
        if duration and milliseconds >= duration and not self.video._paused and not self._loop_enabled:
            milliseconds = duration
            self._finish_project_playback()
        # Queue the cursor's minimal damage before caption/list work. This
        # remains a consumer of PlaybackClock, with no presentation timer.
        self.timeline.set_playhead(milliseconds)
        arm=getattr(self,'_arm_caption_boundary',None)
        if callable(arm):arm(milliseconds)
        # Buffering/loading still has a paused observation while the user's
        # play request is pending. A rebind must preserve that request.
        intended = getattr(self.video, 'playback_intended', None)
        if intended is None:
            intended = not self.video._paused or bool(getattr(self.video, '_buffered_play_pending', False))
        paused = not intended
        if getattr(self.video, '_startup_state', 'READY') != 'READY' and getattr(self.video, '_startup_play_requested', False):
            paused = False
        preview = self._activate_multitrack_preview(milliseconds)
        if preview is not None:
            target, switched = preview
            if switched:
                try:
                    if not bool(target.get("switch_seek_posted")):
                        self.video.seek(
                            int(target["source_ms"]) / 1000.0,
                            accurate=True,
                            project_ms=milliseconds,
                        )
                    self.video.set_paused(paused)
                except RuntimeError:
                    pass
        if hasattr(self, "advanced_cue_overlay") and self.advanced_cue_overlay.isVisible():
            self.advanced_cue_overlay.sync_time(
                milliseconds, paused=bool(getattr(self.video, "_paused", True)),
            )
        self.position_label.setText(format_timeline_timecode(milliseconds))
        timecode_input = getattr(self, "timecode_input", None)
        if timecode_input is not None and not timecode_input.hasFocus():
            timecode_input.setText(format_timeline_timecode(milliseconds))
        self._update_active_cues(milliseconds)
        deferred_follow = bool(
            defer_follow
            and self.project
            and not self._review_mode
            and self.follow_playhead_toggle.isChecked()
            and not self._editing_has_focus()
        )
        self._activate_selected_advanced_if_needed()
        self.ensure_active_subtitle_renderer(
            reason="seek_playhead" if deferred_follow else "playhead",
        )
        if self._loop_enabled and self._loop_region_ms and milliseconds >= self._loop_region_ms[1]:
            self._seek(self._loop_region_ms[0] / 1000.0)
            return
        if (self.follow_playhead_toggle.isChecked() and not self._editing_has_focus()
                and not getattr(self.timeline, '_scrub_drag', False)
                and not getattr(self.timeline, '_pan_drag', None)):
            # 播放态连续微滚跟随（2026-09-18 III：翻页跟随在窄视口下每 ~6s
            # 跳一页=用户"时间轴 6 秒一跳"）；暂停/seek 保持单次翻页 reveal。
            if not bool(getattr(self.video, "_paused", True)):
                self.timeline.follow_playing_playhead(milliseconds)
            else:
                self.timeline.reveal_playhead(milliseconds)
        elif not self.follow_playhead_toggle.isChecked():
            self.timeline.page_playhead(milliseconds)
        duration = timeline_duration_ms(self.project) if self.project else 0
        self._sync_timeline_duration_label(duration)
        if duration and not self.position_slider.isSliderDown():
            self.position_slider.setValue(round(milliseconds * 1000 / duration))
        # Playback never enters the formal editor selection/transaction path.
        # Follow affects the timeline viewport only, never cue-list scrolling.

    def _arm_caption_boundary(self, milliseconds):
        """One boundary deadline samples the same Clock, never extends a cue.

        A 16 ms UI cadence can straddle a cue start even with ready pixels.
        The deadline carries no independent advancing position and is checked
        again after seeks, pauses, project replacement and clock corrections.
        """
        clock=getattr(self.video,'_playback_clock',None)
        runtime=getattr(getattr(self,'session',None),'runtime',None)
        if clock is None or runtime is None or self.video._paused:return
        controller=getattr(self.video,'controller',None)
        if controller is not None and hasattr(controller,'observed_position'):
            bridge=getattr(self,'_caption_frame_bridge',None)
            if bridge is None:
                bridge=self._caption_frame_bridge=_CaptionFrameBridge(self)
                bridge.observed.connect(self._caption_observation_ready)
            controller._position_observer=bridge.observed.emit
        from bisect import bisect_right
        sample=self._caption_sample_ms(milliseconds)
        next_index=bisect_right(runtime._cue_starts,sample)
        times=[cue.end_ms for cue in runtime.cues_at(sample) if cue.end_ms>sample]
        if next_index<len(runtime._cue_starts):times.append(runtime._cue_starts[next_index])
        if not times:return
        boundary=min(times)
        from .caption_frame_time import first_frame_ms,project_frame_rate
        frame_rate=project_frame_rate(self.project)
        boundary=first_frame_ms(boundary,frame_rate)
        if getattr(self,'_playback_mode','source') == 'mapped':
            current_segment = self._mapped_sequence_segment()
            if current_segment is not None and boundary >= current_segment.timeline_out_ms:
                # A later edit segment may run backwards in source time. Its
                # caption deadline is armed after the transport crosses the cut.
                return
            mapped_boundary=timeline_to_source(sequence_of(self.project),round(boundary))
            if mapped_boundary is None:
                return
            # The cue index is in edit time while this mpv clock is in source
            # time. Mixing them made every future caption look overdue and
            # rearmed a 1 ms timer throughout non-contiguous playback.
            boundary=mapped_boundary.source_ms
        key=(id(self.project),clock.generation,boundary,float(self.video._playback_rate))
        if key==getattr(self,'_caption_waiting_observation',None):return
        timer=getattr(self,'_caption_boundary_timer',None)
        if timer is None:
            timer=self._caption_boundary_timer=QTimer(self)
            timer.setSingleShot(True);timer.setTimerType(Qt.PreciseTimer)
            timer.timeout.connect(self._caption_boundary_due)
        import math
        delay=max(1,math.ceil(clock.milliseconds_until_media_frame(boundary,frame_rate)))
        if (key==getattr(self,'_caption_boundary_deadline',None) and timer.isActive()
                and timer.remainingTime()<=delay+1):return
        self._caption_boundary_deadline=key
        timer.start(delay)

    def _caption_observation_ready(self, observation):
        """An arriving media frame can make a prepared boundary due immediately.

        Steady frames do no layout, rasterization or UI repaint here. Waiting
        for the next 16 ms visual tick would miss a short genuine gap's exit.
        """
        key=getattr(self,'_caption_boundary_deadline',None)
        clock=getattr(self.video,'_playback_clock',None)
        if (key is None or clock is None or self.video._paused or getattr(self,'_close_requested',False)
                or observation.get('source_generation')!=clock.generation):return
        self.video._observe_cached_video_clock()
        from .caption_frame_time import project_frame_rate
        if clock.media_frame_ms(project_frame_rate(self.project))>=key[2]:
            self._caption_boundary_due()

    def _caption_boundary_due(self):
        key=getattr(self,'_caption_boundary_deadline',None)
        self._caption_boundary_deadline=None
        self._caption_waiting_observation=None
        clock=getattr(self.video,'_playback_clock',None)
        if (key is None or clock is None or self.video._paused or id(self.project)!=key[0]
                or clock.generation!=key[1]):return
        self.video._observe_cached_video_clock()
        from .caption_frame_time import project_frame_rate
        frame_rate=project_frame_rate(self.project)
        if clock.media_frame_ms(frame_rate)<key[2]:
            # The estimate is due but the decoder has not presented that frame.
            # The existing observation callback resumes it; do not spin a 1ms
            # timer or publish a future cue and roll back on the next frame.
            self._caption_boundary_deadline=key
            self._caption_waiting_observation=key
            return
        elapsed=getattr(self.video,'_clock',None)
        seconds=clock.sample_presentation(source='caption_boundary',
            elapsed_ms=elapsed.nsecsElapsed()/1_000_000 if elapsed is not None else None).presentation_media_ms/1000.
        self._position_changed(seconds,_bypass_throttle=True)

    def _sync_timeline_duration_label(self, duration_ms: int) -> None:
        """播放头 tick 上的廉价同步：文本变化才 setText。

        总时长用去毫秒短形态（hh:mm:ss / mm:ss）：当前时间已带毫秒，总时长
        只需定位参照，紧凑排版把传输条占用压到最小（窄窗口友好）。
        """
        label = getattr(self, "timeline_duration_label", None)
        if label is None:
            return
        try:
            if int(getattr(self, "_timeline_duration_label_ms", -1)) == int(duration_ms):
                return
        except (AttributeError, ValueError):
            pass
        self._timeline_duration_label_ms = int(duration_ms)
        if duration_ms <= 0:
            label.setText("")
            return
        seconds = int(duration_ms) // 1000
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
        label.setText(f"/ {text}")

    def _finish_deferred_seek_feedback(self, milliseconds: int) -> None:
        if (getattr(self, '_timeline_scrub_active', False)
                or abs(milliseconds - self.timeline.playhead_ms) > 1):
            return
        self._update_active_cues(milliseconds)
        self._activate_selected_advanced_if_needed()
        self.ensure_active_subtitle_renderer(reason="deferred_seek")

    def _follow_playhead_selection(self, milliseconds: int) -> None:
        """Clock activity and editing target, including paused seeks."""
        self._update_active_cues(milliseconds)

    @measured('active_cues')
    def _update_active_cues(self, milliseconds: int) -> None:
        from .studio_runtime_state import state_for
        self.cue_controller.sync_playhead_target(milliseconds, rule=self._playhead_target_rule())
        sample=getattr(self,'_caption_sample_ms',None)
        if callable(sample):milliseconds=sample(milliseconds)
        session = self.session
        runtime = session.runtime
        if self.project is not None and runtime is None:
            runtime = session.runtime = state_for(self.project)
        candidates = runtime.cues_at(milliseconds) if runtime is not None else ()
        candidates = [
            cue for cue in candidates
            if self._subtitle_track_visibility.get(cue.speaker_id, True)
            and cue.speaker_id not in getattr(self.timeline, "hidden_speakers", set())
        ]
        ids = frozenset(cue.id for cue in candidates)
        previous = self._cue_lookup.get(session.active_cue_id)
        active = next((cue for cue in candidates if previous and cue.speaker_id == previous.speaker_id), None)
        active = active or next(iter(candidates), None)
        session.active_cue_id = active.id if active else ""
        if ids == session.active_cue_ids:
            return
        session.active_cue_ids = ids
        self.cue_model.set_active_cues(ids)
        self.timeline.set_active_cues(ids)
        prepare = getattr(self, '_prepare_caption_window', None)
        if callable(prepare): prepare(milliseconds)

    def _timeline_cue_clicked(self, cue_id: str) -> None:
        """Manual selection remains usable until the clock target changes."""
        self._manual_selection_hold = True
        cue = self._cue_lookup.get(cue_id)
        if cue:
            self.session.preferred_subtitle_speaker = cue.speaker_id
        self.select_cue(cue_id)

    def _follow_toggle_changed(self, checked: bool) -> None:
        # Viewport policy never changes the user's explicit editing target.
        pass

    def _slider_seek(self, value: int) -> None:
        if self.project:
            duration = timeline_duration_ms(self.project)
            if duration:
                self._seek(value * duration / 1_000_000)

    @measured('seek_request')
    def _seek(self, seconds: float, *, accurate: bool = True) -> None:
        if getattr(self, "_empty_playback_state", False) or not self.video.controller:
            return
        timeline_ms = round(seconds * 1000)
        self._invalidate_audio_tail()
        self.cue_controller.sync_playhead_target(timeline_ms, force=True, rule=self._playhead_target_rule())
        visual_expectation = self._prepare_visual_route_for_time(timeline_ms)
        try:
            from .clip_time_mapper import ClipTimeTrace, record_clip_time_trace

            self._explicit_project_seek = True
            try:
                preview = self._activate_multitrack_preview(timeline_ms)
            finally:
                self._explicit_project_seek = False
            source_seconds = seconds
            if preview is not None:
                target, _switched = preview
                source_seconds = int(target["source_ms"]) / 1000.0
                record_clip_time_trace(
                    ClipTimeTrace(
                        project_target_ms=int(timeline_ms),
                        clip_id=str(target.get("clip_id") or ""),
                        track_id=str(target.get("track_id") or ""),
                        timeline_in_ms=int(target.get("timeline_in_ms") or 0),
                        source_in_ms=int(target.get("source_in_ms") or 0),
                        playback_rate=float(target.get("playback_rate") or 1.0),
                        computed_source_ms=int(target["source_ms"]),
                        decoder_requested_ms=int(target["source_ms"]),
                        decoder_reported_ms=None,
                        frame_pts_ms=None,
                        presentation_ms=int(timeline_ms),
                        generation=int(getattr(self.video, "_playback_clock", None).generation or 0)
                        if getattr(self.video, "_playback_clock", None)
                        else 0,
                        reason="project_seek",
                    )
                )
            elif getattr(self, "_playback_mode", "source") == "mapped" and self.project:
                mapped = timeline_to_source(sequence_of(self.project), timeline_ms)
                if mapped is not None:
                    source_seconds = mapped.source_ms / 1000.0
            self._defer_next_video_position_follow = True
            self.video.seek(source_seconds, accurate=accurate, project_ms=timeline_ms)
            self.video.set_seek_visual_expectation(visual_expectation)
            self._schedule_seek_trace_settlement()
            if self._defer_next_video_position_follow:
                self._defer_next_video_position_follow = False
                self._apply_project_playhead(timeline_ms, defer_follow=True)
        except RuntimeError as exc:
            self._defer_next_video_position_follow = False
            self._show_video_error(str(exc))

    def _schedule_seek_trace_settlement(self, attempt: int = 0) -> None:
        trace = getattr(self.video, "_active_seek_trace", None)
        if not isinstance(trace, dict):
            return
        generation = int(trace.get("generation", -1))
        if self._close_requested:
            self.video._expire_seek_trace(generation, reason="page closing")
            return
        if attempt > 0:
            observed = self.subtitle_visibility_trace(reason="seek_t8_probe")
            expectation = trace.get("visual_expectation")
            expected = dict(expectation) if isinstance(expectation, Mapping) else {}
            expected_cue_id = str(expected.get("cue_id") or "")
            expected_route = str(expected.get("renderer_route") or "none")
            owner = str(observed.get("foreground_owner") or "none")
            owner_cue_id = str(observed.get("foreground_owner_cue_id") or "")
            owner_count = int(observed.get("foreground_owner_count") or 0)
            observed_cue_id = str(observed.get("cue_id") or "")
            observed_route = str(observed.get("renderer_route") or "none")
            if not expected_cue_id:
                passed = bool(
                    not observed_cue_id
                    and owner == VisualOwner.NONE.value
                    and not owner_cue_id
                    and owner_count == 0
                )
            elif expected_route == "advanced":
                passed = bool(
                    observed_cue_id == expected_cue_id
                    and observed_route == "advanced"
                    and owner in {
                        VisualOwner.ADVANCED_LIVE.value,
                        VisualOwner.ADVANCED_FIDELITY.value,
                    }
                    and owner_cue_id == expected_cue_id
                    and owner_count == 1
                    and bool(observed.get("visible"))
                    and bool(observed.get("advanced_canvas_visible"))
                    and not bool(observed.get("native_overlay_visible"))
                )
            else:
                passed = bool(
                    observed_cue_id == expected_cue_id
                    and observed_route == "native"
                    and owner == VisualOwner.NATIVE.value
                    and owner_cue_id == expected_cue_id
                    and owner_count == 1
                    and bool(observed.get("visible"))
                    and bool(observed.get("native_overlay_visible"))
                    and not bool(observed.get("advanced_canvas_visible"))
                )
            trace["T8_passed"] = passed
            trace["T8_attempts"] = attempt
            trace["T8_expected"] = {
                "cue_id": expected_cue_id,
                "renderer_route": expected_route,
            }
            trace["T8_observed"] = {
                "cue_id": observed_cue_id,
                "renderer_route": observed_route,
                "foreground_owner": owner,
                "foreground_owner_cue_id": owner_cue_id,
                "foreground_owner_count": owner_count,
                "visible": bool(observed.get("visible")),
                "native_overlay_visible": bool(observed.get("native_overlay_visible")),
                "advanced_canvas_visible": bool(observed.get("advanced_canvas_visible")),
            }
            if passed:
                self.video.mark_seek_stage(
                    "T8_active_cue_visual_owner_correct",
                    T8_passed=True,
                )
        if self.video._finish_seek_trace(generation):
            return
        if attempt < 80:
            timer = getattr(self, '_seek_trace_timer', None)
            if timer is None:
                timer = self._seek_trace_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setTimerType(Qt.TimerType.PreciseTimer)
                def settle_current():
                    current, count = self._seek_trace_pending
                    active = getattr(self.video, '_active_seek_trace', None)
                    if isinstance(active, dict) and int(active.get('generation', -2)) == current:
                        self._schedule_seek_trace_settlement(count)
                timer.timeout.connect(settle_current)
            # Reuse one diagnostic timer. Registering a new singleShot lambda
            # for every seek/poll took 25 ms in the real GUI profile and left
            # obsolete generation callbacks behind during rapid scrubbing.
            self._seek_trace_pending = (generation, attempt+1)
            timer.start(25)
        else:
            self.video._expire_seek_trace(
                generation,
                reason="seek settlement exceeded 2000 ms",
            )

    def _prepare_visual_route_for_time(self, milliseconds: int) -> dict[str, object]:
        """Queue Native revocation before a seek can expose an Advanced cue."""
        project = self.project
        if project is None:
            return {"cue_id": "", "renderer_route": "none"}
        target_ms = max(0, int(milliseconds))
        runtime = self.session.runtime
        candidates = list(runtime.cues_at(target_ms)) if runtime else [
            cue for cue in project.cues
            if cue.start_ms <= target_ms < cue.end_ms
        ]
        candidates = [
            cue for cue in candidates
            if self._subtitle_track_visibility.get(cue.speaker_id, True)
            and cue.speaker_id not in getattr(self.timeline, "hidden_speakers", set())
        ]
        selected = next(
            (cue for cue in candidates if cue.id == self.selected_cue_id), None
        )
        cue = selected or min(
            candidates,
            key=lambda item: (
                abs(item.start_ms - target_ms), item.end_ms - item.start_ms
            ),
            default=None,
        )
        payload = (
            recipe_payload_for_style(project.style_recipes, cue.style_id)
            if cue is not None else {}
        )
        canonical_advanced = bool(
            isinstance(payload, Mapping)
            and payload
            and route_recipe(payload).engine == "remotion"
        )
        compositor_promotion = bool(
            cue is not None
            and len(self._multitrack_preview_layers(target_ms)) >= 2
            and not canonical_advanced
        )
        from .studio_caption_timeline import independent_captions
        independent = independent_captions(project)
        advanced = canonical_advanced or compositor_promotion or independent
        self.video.set_native_subtitle_visible(not advanced)
        if advanced and cue is not None and not independent:
            # 2026-09-18 III：跳转目标是 advanced cue 时在 seek 当拍就预约其
            # 视觉渲染——此前要等 playhead tick 链经 ensure_active 才排程，
            # 冷 cue 多付一段 tick+排程空转（用户"跳转后字幕 1-2s 才对"）。
            # _schedule_advanced_preview 按 identity 去重，±3s 连点同 cue 只排一次。
            self._schedule_advanced_preview(payload, force=False, queue_fidelity=False)
        self._studio_trace(
            "ROUTE_PREPARE",
            cue_id=cue.id if cue is not None else "",
            target_ms=target_ms,
            route="advanced" if advanced else "native",
            canonical_route="advanced" if canonical_advanced else "native",
            multitrack_foreground_promotion=compositor_promotion,
            native_visible=not advanced,
        )
        return {
            "cue_id": cue.id if cue is not None else "",
            "renderer_route": (
                "advanced" if cue is not None and advanced
                else "native" if cue is not None
                else "none"
            ),
            "target_ms": target_ms,
        }

    def _toggle_playback(self) -> None:
        if getattr(self, "_empty_playback_state", False) or not self.video.controller:
            return
        if (getattr(self.video, "_buffered_play_pending", False)
                or getattr(self.video, "_seek_hold_active", False)):
            # Still "playing" for the user while a seek waits for its audio.
            self.video.set_paused(True)
            self._sync_play_button(True)
            return
        if getattr(self.video, "playback_source_dead", False):
            # mpv/media clock is the playback truth: a dead transport is not
            # "Playing". The play click is the user's revive request.
            revived = bool(self.video.revive_dead_source(paused=False))
            self._sync_play_button(not revived)
            if revived:
                self.save_state.setText("播放已恢复")
                self.video.setToolTip("")
            else:
                self._show_video_error("播放器已停止且自动恢复失败，请重新打开工程。")
            return
        try:
            duration = timeline_duration_ms(self.project) if self.project else 0
            if self.video.at_eof and duration and int(self.timeline.playhead_ms) >= duration - 1:
                # Timeline 0, not source 0: a head-trimmed sequence must
                # restart at the first retained frame instead of the deleted
                # head (which would immediately trigger the gap re-seek).
                self._seek(0.0)
                self.video.set_paused(False)
                self._sync_play_button(False)
                return
            if self.video.at_eof:
                self._seek(self.timeline.playhead_ms / 1000.0)
            paused = bool(self.video.playback_position_snapshot().paused)
            self.video.set_paused(not paused)
            self._sync_play_button(not paused)
        except RuntimeError as exc:
            self._show_video_error(str(exc))

    def _frame_step(self, backwards: bool) -> None:
        if not getattr(self, "_empty_playback_state", False) and self.video.controller:
            self.video.controller.frame_step(backwards)
            self._sync_play_button(True)

    def _sync_play_button(self, paused: bool) -> None:
        if paused and not getattr(self, "_rate_transition", False):
            self._clear_shuttle_rate()
        self.play_button.setIcon(_icon("fa5s.play" if paused else "fa5s.pause"))

    def _playback_buffers_ready(self) -> bool:
        if not self.audio_engine.ready_for_playback():
            return False
        scene = getattr(self, "video_compositor", None)
        if scene is not None:
            layers = list(scene._layers)
            if scene._composes_base and scene._base_layer:
                layers.append(scene._base_layer)
            for layer in layers:
                source = scene._players.get(str(layer.get("clip_id")))
                if source is not None and (source.image.isNull() or abs(source.pts_ms-int(layer["source_ms"])) > 100):
                    if source.performance_snapshot().get("state") not in {"FAILED", "EOF"}:
                        return False
        return True

    def _playhead_target_rule(self) -> str:
        """'edit' while a paused user-placed playhead decides Q/W; else the clock rule."""
        if getattr(self, '_review_mode', False):
            return 'clock'
        return 'edit' if bool(getattr(getattr(self, 'video', None), '_paused', True)) else 'clock'

    def _playback_state_changed(self, paused: bool) -> None:
        if getattr(self.video, '_seek_hold_active', False):
            # A seek during playback holds the picture until its audio is
            # ready. The user is still playing: no Q/W retarget, full GC,
            # thumbnail/governor switch or play-button flicker; the audio
            # graph still follows the hold so both clocks stop and resume.
            if self.project and hasattr(self, "timeline"):
                self._sync_video_compositor(int(self.timeline.playhead_ms))
            return
        if (paused and self.project is not None and not getattr(self, '_review_mode', False)
                and not getattr(self, '_manual_selection_hold', False)):
            # Paused in a gap: show the caption Q/W would edit (nearest boundary).
            # Inside a caption both rules agree; that selection is left alone.
            playhead = int(self.timeline.playhead_ms)
            runtime = getattr(self.session, 'runtime', None)
            if runtime is not None and not runtime.cues_at(playhead):
                self.cue_controller.sync_playhead_target(playhead, rule='edit')
        budget = getattr(self, '_playback_gc_budget', None)
        if budget is not None:
            budget.set_playing(not paused)
        self._prepare_caption_window(int(getattr(self.timeline, 'playhead_ms', 0)))
        thumbnails = getattr(getattr(self, 'timeline', None), '_thumbnails', None)
        if callable(getattr(thumbnails, 'set_paused', None)):
            thumbnails.set_paused(not paused)
        self._sync_play_button(paused)
        self._resource_governor.set_playback(not paused)
        if paused and self.selected_cue_id and getattr(self, '_selection_needs_hydration', False):
            # Explicit fast review selections may defer their own inspector.
            self.select_cue(self.selected_cue_id)
        if self.project and hasattr(self, "timeline"):
            self._sync_video_compositor(int(self.timeline.playhead_ms))
        cue = self._renderer_cue_at_playhead() if self.project else None
        payload = (
            self.project.style_recipes.get(cue.style_id, {})
            if self.project and cue is not None
            else {}
        )
        graph = payload.get("visualGraph") if isinstance(payload, Mapping) else {}
        if isinstance(graph, Mapping) and graph:
            if paused:
                # A paused graph may use Remotion, but it must represent the
                # current cue-local frame rather than the historical 300ms
                # thumbnail. Playback keeps the continuously sampled LIVE
                # compositor as foreground owner.
                self._queue_advanced_preview(payload, delay_ms=0)
            else:
                snapshot = getattr(self, "_advanced_preview_snapshot", None)
                identity = self._advanced_preview_state.identity
                if (
                    snapshot is not None
                    and identity is not None
                    and snapshot.cue_id == cue.id
                ):
                    self._publish_advanced_live(snapshot, identity)
        self.ensure_active_subtitle_renderer(reason="playback_state")

    def _jump(self, seconds: float) -> None:
        if not self.video.controller:
            return
        try:
            current = self.video.visual_position()
            target = max(0.0, current + seconds)
            route_ms = round(target * 1000)
            if getattr(self, "_playback_mode", "source") == "mapped" and self.project:
                # visual_position() is source-domain; the visual route prep
                # expects a timeline position. Translate before preparing.
                mapped = source_to_timeline(sequence_of(self.project), route_ms)
                route_ms = (
                    mapped.timeline_ms if mapped is not None
                    else int(self.timeline.playhead_ms)
                )
            self._prepare_visual_route_for_time(route_ms)
            self.video.seek(target, accurate=True)
        except (RuntimeError, TypeError, ValueError) as exc:
            self._show_video_error(str(exc))

    def _toggle_fullscreen(self) -> None:
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()

    def _set_volume(self, value: int) -> None:
        controller = self.video.controller
        if controller is None:
            return
        self._active_video_preview_volume = None
        self._apply_active_video_track_volume(self._active_video_preview_track_id)
        if self.project:
            self._sync_video_compositor(int(self.timeline.playhead_ms))

    def _set_speed(self, value: float) -> None:
        """An explicit dropdown choice persists across ordinary pauses."""
        self._manual_playback_rate = float(value)
        self._shuttle_rate = None
        self._apply_transport_rate(value)

    def _apply_transport_rate(self, value: float, *, resume_playback=True) -> None:
        # Internal pause/resume during a rate change is not a user pause.
        # Keep video Clock, the audio graph transport and the dropdown in the
        # same synchronous transition, through their existing public owners.
        prior_transition = getattr(self, "_rate_transition", False)
        self._rate_transition = True
        try:
            resume = bool(resume_playback and self.video.controller and not getattr(self.video, "_paused", True))
            if resume:
                self.video.set_paused(True)
            self._shuttle_speed = float(value)  # compatibility: effective transport rate
            if hasattr(self, "speed_box"):
                index = self.speed_box.findData(float(value))
                if index >= 0 and index != self.speed_box.currentIndex():
                    self.speed_box.blockSignals(True)
                    self.speed_box.setCurrentIndex(index)
                    self.speed_box.blockSignals(False)
            if self.video.controller:
                self.video.set_speed(value)
            if self.project:
                self._sync_video_compositor(int(self.timeline.playhead_ms))
            if resume:
                self.video.set_paused(False)
        finally:
            self._rate_transition = prior_transition

    def _clear_shuttle_rate(self) -> None:
        if getattr(self, "_shuttle_rate", None) is None:
            return
        self._shuttle_rate = None
        self._apply_transport_rate(1.0, resume_playback=False)

    def _shuttle(self, direction: int) -> None:
        if not self.video.controller:
            return
        reverse_timer = getattr(self, "_reverse_timer", None)
        if reverse_timer is None:
            reverse_timer = QTimer(self)
            reverse_timer.setInterval(42)
            reverse_timer.timeout.connect(lambda: self._frame_step(True))
            self._reverse_timer = reverse_timer
        reverse_timer.stop()
        try:
            if direction < 0:
                self.video.set_paused(True)
                self._sync_play_button(True)
                reverse_timer.start()
            elif direction == 0:
                self.video.set_paused(True)
                self._set_speed(1.0)
                self._sync_play_button(True)
            else:
                current = float(getattr(self, "_shuttle_rate", 0.0) or 0.0)
                speed = 1.0 if current not in (1.0, 2.0, 4.0) else current * 2.0
                self._shuttle_rate = min(8.0, speed)
                self._apply_transport_rate(self._shuttle_rate)
                self.video.set_paused(False)
                self._sync_play_button(False)
        except RuntimeError as exc:
            self._show_video_error(str(exc))

    def _show_video_error(self, message: str) -> None:
        self.save_state.setText("视频预览不可用")
        self.video.setToolTip(message)
