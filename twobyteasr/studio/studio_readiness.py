"""Real first-interaction readiness, inside the existing Studio window."""
from __future__ import annotations

import threading
import os
import sys
import time
import weakref
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QLabel, QPushButton, QProgressBar, QVBoxLayout, QHBoxLayout,
                               QApplication, QWidget)

from ..i18n import bind_text
from .studio_loading import StudioLoadingSession, ReadinessSteps, TASKS


def project_file_identity(path):
    """Atomic saves at the same path invalidate a previously loaded project."""
    try:
        stat = Path(path).stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


# 准备超时 means nothing moved for this long. Until 2026-10-21 it was 30 s from
# the click, so a large project (2,000 cues: 6–17 s here) or the autosave
# recovery prompt left open for a while failed while still moving.
STALL_TIMEOUT_S = 30.0
# Reading has no progress of its own; a live reader may take longer than the
# stall limit on a slow computer, but an offline network path must end.
READ_TIMEOUT_S = 120.0


def caption_rows_prepared(state):
    """Caption rows already rendered for the opening frame (progress while preparing captions)."""
    return sum(1 for row in state.get('cue_pixels') or () if row.get('status') != 'pending')


def caption_scene_ready(state):
    rows = state.get('cue_pixels') or ()
    rendered = {row.get('cue_id') for row in rows if row.get('status') != 'pending'}
    return (set(state.get('expected_cue_ids') or ()).issubset(rendered)
            and all(row.get('status') != 'pending' for row in rows))


def first_frame_caption_cues(page):
    """Use the renderer's current target; None means no target evidence yet."""
    project = getattr(page, 'project', None)
    if project is None:
        return None
    if not project.cues or getattr(page, '_empty_playback_state', False):
        return ()
    sample = getattr(page, '_caption_sample_ms', None)
    if not callable(sample):
        return None
    from ..rendering.caption_scene import active_cues
    return active_cues(page, sample())


def owns_hidden_preparation(page):
    """Only the hydrated, current loading request may prepare a hidden editor."""
    gate = getattr(page, '_readiness', None)
    owns = getattr(gate, '_owns_request', None)
    return bool(gate is not None and getattr(gate, 'active', False) and getattr(gate, 'hydrated', False)
        and not getattr(page, '_close_requested', False)
        and callable(owns) and owns() and getattr(page, 'project', None) is not None
        and getattr(page, 'project_path', None) is not None
        and os.path.normcase(str(page.project_path)) == os.path.normcase(str(gate.path)))


def player_surface_ready(page):
    """Readiness is a current source/frame observation, never an IPC ACK."""
    video = page.video
    if getattr(video, '_clock_only', False) or getattr(page, '_empty_playback_state', False):
        return True  # The existing canvas owns the explicit gap/empty placeholder.
    project = getattr(page, 'project', None)
    if (project is not None and not getattr(video, '_media_path', '')
            and not getattr(video, '_media_attached', False)
            and not any(getattr(track, 'enabled', True) and any(getattr(clip, 'enabled', True)
                for clip in track.clips) for track in getattr(project, 'video_tracks', ()))):
        # Subtitle-only / audio-only placeholders have no video frame to await.
        # An empty legacy primary path never skips an enabled video clip.
        return True
    if getattr(video, '_startup_state', '') != 'READY':
        return False
    clock = getattr(video, '_playback_clock', None)
    if clock is not None and clock.exact_seek_pending:
        return False
    if not getattr(video, '_media_has_video', True):
        # For audio-only media READY belongs to the existing PCM clock. mpv is
        # intentionally aid=no, so it may have no time-pos or video property.
        # The separate audio buffer gate below still requires actual data.
        return True
    controller = getattr(video, 'controller', None)
    if callable(getattr(controller, 'observed_frame', None)):
        from ..playback.frame_readiness import video_frame_witness
        return video_frame_witness(video)['ready']
    # QVideoSink owns an explicit decoded-frame timestamp. The mpv backend
    # instead needs the generation-scoped playback-restart witness above;
    # its picture-type/timecode properties alone do not prove a fresh frame.
    if getattr(controller, 'backend', '') != 'qt-video-sink':
        return False
    if clock is not None:
        if getattr(controller, 'source_epoch', None) != clock.generation:
            return False
        applied = getattr(controller, 'applied_seek_state', lambda: {})()
        if applied.get('generation') != clock.generation:
            return False
    surface = getattr(controller, 'surface', None)
    if surface is None or surface.frame.isNull():
        return False
    observe = getattr(controller, 'observed_properties', None)
    if not callable(observe):
        return not getattr(video, '_media_has_video', True)
    state = observe()
    source, current = str(getattr(video, '_media_path', '') or ''), str(state.get('path') or '')
    if not source or not current or os.path.normcase(os.path.abspath(source)) != os.path.normcase(os.path.abspath(current)):
        return False
    if state.get('seeking') or state.get('idle-active'):
        return False
    frame = state.get('video-frame-info') or {}
    if not any(frame.get(key) is not None for key in ('pts', 'estimated-frame-number', 'picture-type')):
        return False
    pts, position = frame.get('pts'), state.get('time-pos')
    if pts is not None and position is not None:
        fps = float(state.get('container-fps') or state.get('estimated-vf-fps') or 24.0)
        if abs(float(pts)-float(position)) > max(.050, 1.5/max(1., fps)):
            return False
    return True


def player_wait_snapshot(page):
    """Cached observations only: diagnostics must not create the missing frame."""
    from dataclasses import asdict
    video = page.video
    controller = getattr(video, 'controller', None)
    def cached(name):
        reader = getattr(controller, name, None)
        return reader() if callable(reader) else {}
    properties = cached('observed_properties')
    clock = getattr(video, '_playback_clock', None)
    clock_state = asdict(clock.snapshot()) if callable(getattr(clock, 'snapshot', None)) else {}
    engine = getattr(page, 'audio_engine', None)
    audio = engine.telemetry_snapshot() if engine is not None else {}
    return dict(measurement='cached observations; no screenshot or synchronous IPC',
        observed_frame=cached('observed_frame'), applied_seek_state=cached('applied_seek_state'),
        observed_properties={key: properties.get(key) for key in (
            'path', 'time-pos', 'playback-time', 'pause', 'seeking', 'idle-active', 'eof-reached',
            'core-idle', 'video-frame-info', 'video-params', 'container-fps', 'current-vo')},
        clock=dict(clock_state, generation=getattr(clock, 'generation', None),
                   exact_seek_pending=getattr(clock, 'exact_seek_pending', None)),
        target=dict(media_path=getattr(video, '_media_path', ''),
            preview_source=getattr(page, '_active_video_preview_source_path', ''),
            preview_key=getattr(page, '_active_video_preview_key', ''),
            preview_clip=getattr(page, '_active_video_preview_clip_id', ''),
            pending_seek_target=getattr(video, '_pending_seek_target', None),
            startup_state=getattr(video, '_startup_state', ''),
            media_has_video=getattr(video, '_media_has_video', None),
            clock_only=getattr(video, '_clock_only', False),
            source_epoch=getattr(controller, 'source_epoch', None),
            media_epoch=getattr(controller, '_subtitle_binding_epoch', None)),
        audio={key: audio.get(key) for key in ('state', 'buffer_bytes', 'decoded_bytes',
            'decoder_startup_pending', 'decoder_error', 'source_generation', 'transport_generation', 'paused')})


class StudioReadiness(QObject):
    loaded = Signal(int, object, str)
    player_loaded = Signal(int, object, str)
    finished = Signal()
    TASKS = TASKS
    # The audio engine rebuilds a failed endpoint at the current position by
    # itself. While opening, a failure only fails the gate if it is not
    # recovered within this time (macOS reopen, 2026-10-14: the endpoint
    # dropped once and was back about 1 s later, but Studio reported 准备音频).
    AUDIO_RECOVERY_GRACE_S = 8.0

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.generation = 0
        self.active = False
        self.ready = False
        self.path = ''
        self.loaded_file_identity = None
        self.profile = {}
        self.on_ready = None
        self.completed = set()
        owner = page.window()
        session = getattr(owner, '_studio_loading_session', None)
        if session is None:
            session = StudioLoadingSession(page)
        self.loading = session
        session.attach_surface(page.video)
        self.overlay = session.view
        for name in ('card', 'icon', 'project_name', 'bar', 'steps_view', 'label', 'retry', 'copy_error', 'back'):
            setattr(self, name, getattr(self.overlay, name))
        page.installEventFilter(self)
        page.timeline.installEventFilter(self)
        self.loaded.connect(self._loaded)
        self.player_loaded.connect(self._player_loaded)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._tick)

    def eventFilter(self, watched, event):
        if self.active and watched is self.page.timeline and event.type() == QEvent.Type.Paint:
            self.painted = True
        return False

    def invalidate_surface_geometry(self):
        """A paint at the previous size cannot witness this request's first screen."""
        if not self._owns_request():
            return False
        self.painted = False
        self.completed.discard('首屏绘制')
        self.profile.pop('timeline_surface_prepared', None)
        self.profile.pop('timeline_prepared_hidden', None)
        return True

    def mark(self, name):
        if name not in self.completed:
            project = self.page.project
            reason = ''
            if name == '准备字幕':
                reason = getattr(self, '_caption_skip_reason', '')
                if not reason and project is not None and not project.cues:
                    reason = '工程没有字幕'
            elif name == '准备音频' and project is not None and not any(
                track.enabled and not track.muted and track.clips for track in project.audio_tracks):
                reason = '没有启用的音轨'
            elif name == '准备播放器' and project is not None and not project.media.path and not project.video_tracks:
                reason = '空工程使用占位画面'
            if reason:
                self.loading.skip(name, reason)
            else:
                self.loading.mark(name)
            self.last_progress = time.perf_counter()
            self.profile['stages_ms'][name] = round((time.perf_counter()-self.started)*1000, 3)
            self.bar.setValue(len(self.completed))
            self.steps_view.set_state(self.completed, self.steps_view.current)
            self.page._studio_trace('STUDIO_OPEN_STAGE', generation=self.generation, stage=name,
                                    elapsed_ms=self.profile['stages_ms'][name])

    @contextmanager
    def user_wait(self):
        """A question asked while opening: the time it stays up is not a stall."""
        began = time.perf_counter()
        try:
            yield
        finally:
            waited = time.perf_counter() - began
            self.last_progress = getattr(self, 'last_progress', began) + waited
            if isinstance(self.profile, dict):
                self.profile['user_wait_ms'] = round(self.profile.get('user_wait_ms', 0.0) + waited * 1000, 1)

    def _set_stage_label(self, stage: str) -> None:
        self.loading.stage(str(stage))

    def _fit_card(self) -> None:
        self.overlay.fit_card()

    def _failed_stage(self) -> str:
        return self.steps_view.current or next((task for task in self.TASKS if task not in self.completed), '')

    def _owns_request(self, epoch=None, *, allow_ready=False):
        loading = self.loading
        state_ok = (self.active and loading.active and loading.state == 'preparing')
        if allow_ready:
            state_ok = state_ok or (self.ready and loading.state in {'preparing', 'ready'})
        return bool(state_ok and not getattr(self.page, '_close_requested', False)
                    and (epoch is None or epoch == self.generation)
                    and self.generation == getattr(self, 'loading_generation', self.generation) == loading.generation
                    and self.path == loading.path)

    def _retire_preparation(self):
        """Stop an old gate without cancelling a newer shared loading session."""
        self.active = self.ready = False
        self.steps = None
        timer = getattr(self, 'timer', None)
        if timer is not None: timer.stop()
        timeline = getattr(self.page, 'timeline', None)
        if timeline is not None: timeline.setUpdatesEnabled(True)
        heap = getattr(self.page, '_project_heap', None)
        if heap is not None: heap.load_finished(settle=False)

    @contextmanager
    def confirmation_wait(self):
        running = self.timer.isActive()
        self.timer.stop()
        try:
            with self.user_wait():
                yield
        finally:
            if running and self._owns_request():
                self.timer.start()

    def begin(self, path, *, skip_dirty_guard=False,expected_result_ref=None):
        page = self.page
        intent_generation = self.loading.generation
        self.expected_result_ref = expected_result_ref
        path = str(Path(path).resolve())
        file_identity = project_file_identity(path)
        if (self.active and StudioReadiness._owns_request(self) and self.path == path
                and getattr(self, 'requested_file_identity', None) == file_identity):
            # A repeated same-file request joins the current preparation. The
            # controller already replaced on_ready with the latest callback.
            return
        replacing_same_path = self.active and self.path == path
        if (self.ready and self.path == path and page.project is not None
                and not self.loading.active and page.project_path is not None
                and (getattr(self, '_ready_project', None) is None or self._ready_project() is page.project)
                and str(Path(page.project_path).resolve()) == path
                and file_identity is not None and self.loaded_file_identity == file_identity):
            if not StudioReadiness._owns_request(self, allow_ready=True):
                resumed_generation = self.loading.resume_ready(path)
                if self.loading.generation != resumed_generation:
                    return  # Retirement may have rebound this same gate to a newer request.
                self.generation = self.loading_generation = resumed_generation
                self.completed = self.loading.completed
            self.profile = {'kind': 'hot', 'total_ms': 0., 'stages_ms': {}, 'gui_gaps_ms': []}
            self._finish()
            return
        if self.ready and self.path == path:
            page._studio_trace('PROJECT_RELOAD_REQUIRED', project_path=path,
                reason='saved_file_changed', previous_identity=self.loaded_file_identity,
                current_identity=file_identity)
        # A dirty/recovery prompt runs a nested event loop. The old reader/tick
        # must lose authority before that loop can process another callback.
        if self.active:
            StudioReadiness._retire_preparation(self)
        if page.project is not None and not skip_dirty_guard:
            confirmed = page.project_controller.dirty_guard.confirm('打开工程')
            if self.loading.generation != intent_generation:
                return  # A newer request/cancel won during the modal prompt.
            if not confirmed:
                if self.loading.active:
                    reject = getattr(page.window(), '_reject_studio_loading', None)
                    if callable(reject):
                        reject()
                    else:
                        self.loading.abort()
                self.on_ready = None
                return
        if replacing_same_path:
            self.loading.begin(path, on_cancel=self.loading.on_cancel,
                               return_target=self.loading.return_target)
        if not self.loading.active or self.loading.path != path:
            owner = page.window()
            prepare = getattr(owner, '_prepare_studio_loading', None)
            if callable(prepare) and getattr(owner, '_studio_loading_session', None) is self.loading:
                prepare(path)
            else:
                self.loading.begin(path, on_cancel=self.cancel, return_target='hub')
        callback = self.on_ready
        def retry():
            self.on_ready = callback
            self.begin(path, skip_dirty_guard=True, expected_result_ref=expected_result_ref)
        self.loading.on_retry = retry
        self.loading.mark('创建工作台界面')
        self.generation = self.loading.generation
        self.loading_generation = self.generation
        epoch = self.generation
        self.path, self.active, self.ready = path, True, False
        page.video.set_paused(True)
        from ..design.ui_motion import settle_layout
        settle_layout(page)
        heap = getattr(page, '_project_heap', None)
        if heap is not None:
            heap.load_started()
        self.requested_file_identity = file_identity
        self.started = self.loading.started
        self.last_tick = self.last_progress = time.perf_counter()
        self._caption_rows_prepared = 0
        self._caption_skip_reason = ''
        self._reader = None
        self.profile = {'kind': 'warm' if getattr(self, '_ever_ready', False) else 'cold',
                        'stages_ms': {}, 'gui_gaps_ms': []}
        self.completed = self.loading.completed
        self._audio_failed_since = None
        self._player_wait_next = self.started + 1.0
        self.painted = False
        self.steps = None
        self.next_stage = ''
        self.hydrated = False
        self.loading.stage('读取工程')
        self.overlay.raise_()
        self.page.timeline.setUpdatesEnabled(False)
        self.timer.start()
        self.player_ready = (os.environ.get("TWOBYTEASR_DIAGNOSTIC_NO_PLAYER") == "1"
                             or bool(page.video.controller is not None and page.video.controller.running))
        if not self.player_ready:
            if sys.platform == 'darwin':
                # QMediaPlayer/QVideoSink and the embedded QWidget belong to
                # the GUI thread. Only the Windows mpv child starts off-thread.
                try:
                    page.video._ensure_controller_started()
                    self._player_loaded(epoch, page.video.controller, '')
                except Exception as exc:
                    self._player_loaded(epoch, None, str(exc))
            else:
                self._start_mpv_player(epoch)
        def read():
            try:
                from ..projects.studio_project import load_project
                value, error = load_project(path), ''
                from ..media.media_availability import apply_availability, stat_sources_in_reader
                results = stat_sources_in_reader(
                    [a.canonical_source for a in value.media_pool],
                    # Existing source metadata is enough to bind captions.
                    # Decode/codec probing continues through the page's media
                    # availability service; it must not delay subtitle data.
                    cancel_check=lambda: epoch != self.generation or not self.active,
                )
                apply_availability(value, results)
                if not self.expected_result_ref and epoch == self.generation and self.active:
                    from ..projects.project_recovery_inspection import inspect_recovery
                    value._recovery_inspection = inspect_recovery(path, value)
            except Exception as exc:
                value, error = exc, str(exc)
            try:
                self.loaded.emit(epoch, value, error)
            except RuntimeError:
                pass  # The window may have closed while disk IO was pending.
        self._reader = threading.Thread(target=read, name='studio-project-read', daemon=True)
        self._reader.start()

    def _start_mpv_player(self, epoch):
        page = self.page
        from ..playback.studio_mpv import MpvController
        from ..projects.studio_project import studio_data_root
        hwnd = int(page.video.winId())
        page.video._embed_hwnd = hwnd
        log_path = studio_data_root()/'logs/mpv.log'
        previous = page.video.controller
        def player():
            controller = MpvController()
            try:
                if previous is not None:
                    previous.close()
                log_path.parent.mkdir(parents=True,exist_ok=True)
                controller.start(hwnd,log_path=str(log_path))
                self.player_loaded.emit(epoch,controller,'')
            except Exception as exc:
                controller.close()
                try:self.player_loaded.emit(epoch,None,str(exc))
                except RuntimeError:pass
        threading.Thread(target=player,name='studio-player-start',daemon=True).start()

    def _player_loaded(self, epoch, controller, error):
        if not self._owns_request(epoch):
            if controller is not None:
                threading.Thread(target=controller.close,daemon=True).start()
            return
        if error:
            self.fail('准备播放器',error)
            return
        self.page.video.controller=controller
        self.page.video._native_subtitle_visibility_controller=None
        self.page.video._playback_source_dead=False
        self.player_ready=True
        self.last_progress=time.perf_counter()
        self.profile['player_process_ready_ms']=round((time.perf_counter()-self.started)*1000,3)

    def _loaded(self, epoch, project, error):
        if not self._owns_request(epoch):
            return
        if error:
            self.fail('读取工程', error)
            from ..projects.studio_project import ProjectValidationError
            if isinstance(project, ProjectValidationError):
                from ..projects.subtitle_consistency_ui import show_load_failure
                show_load_failure(self.page, self.path, project)
            return
        self.mark('读取工程')
        if not self._owns_request(epoch):
            return
        self.steps = self.page.project_controller._open_project_steps(
            self.path, single_shot_fn=QTimer.singleShot, skip_dirty_guard=True, loaded_project=project,
            expected_result_ref=self.expected_result_ref)

    def _tick(self):
        if not self._owns_request():
            if self.active:
                self._retire_preparation()
            return
        tick_epoch = self.generation
        now = time.perf_counter()
        self.profile['gui_gaps_ms'].append(round((now-self.last_tick)*1000, 3))
        self.last_tick = now
        if '准备播放器' not in self.completed:
            # 2026-10-17：没有 vulkan-1.dll 的电脑上 mpv 约 0.5 秒就被 Windows 拒绝启动，
            # 以前要等满 30 秒才说“准备超时”。退出码已能说明原因时立刻说清楚。
            message = self._player_start_failure()
            if message:
                self.fail('准备播放器', message)
                return
        reader = getattr(self, '_reader', None)
        reading = reader is not None and reader.is_alive() and '读取工程' not in self.completed
        stalled = now - getattr(self, 'last_progress', self.started)
        if stalled > (READ_TIMEOUT_S if reading else STALL_TIMEOUT_S):
            self.profile['stalled_s'] = round(stalled, 3)
            self.fail(self._failed_stage(), '准备超时；请检查素材和播放器状态。')
            return
        try:
            if self.steps is not None:
                if self.next_stage == '准备播放器' and not self.player_ready:
                    # 等待播放器进程时保持已用时间跳动（动画不僵死）。
                    self._set_stage_label(self.next_stage or '准备播放器')
                    return
                try:
                    epoch, steps = self.generation, self.steps
                    stage = next(steps)
                    if not self._owns_request(epoch):
                        return
                    self.last_progress = time.perf_counter()
                    self.next_stage = stage
                    self._set_stage_label(str(stage))
                    self.overlay.raise_()
                    return
                except StopIteration:
                    if not self._owns_request(epoch):
                        return
                    self.steps = None
                    self.hydrated = True
                    self.page.timeline.setUpdatesEnabled(True)
                    from ..design.ui_motion import settle_layout
                    settle_layout(self.page)
                    self.page.timeline.update()
                    if (self.page.project is None or self.page.project_path is None
                            or Path(self.page.project_path).resolve() != Path(self.path).resolve()):
                        self.fail('建立时间轴', '工程未能打开')
                        return
                    self.mark('建立时间轴')
                    self.page.video.playback_prepare()
            if not self.hydrated:
                return
            page = self.page
            # A ready tick can run before the queued resize callback. Resolve
            # the current owner's rectangle before checking its frame/paint
            # witnesses; the helper is constant-time when it already matches.
            owner = page.window() if callable(getattr(page, 'window', None)) else None
            prepare_geometry = getattr(owner, '_prepare_hidden_studio_geometry', None)
            if callable(prepare_geometry) and not page.isVisible():
                prepared_geometry = prepare_geometry(page)
                if prepared_geometry is False or not self._owns_request(tick_epoch):
                    return
            prepare_frame = getattr(page.video, 'prepare_loading_frame', None)
            if os.environ.get("TWOBYTEASR_DIAGNOSTIC_NO_PLAYER") != "1" and callable(prepare_frame):
                prepare_frame()
            if os.environ.get("TWOBYTEASR_DIAGNOSTIC_NO_PLAYER") == "1":
                for skipped in ("准备播放器", "准备音频", "准备字幕"):
                    self.mark(skipped)
                self.profile["diagnostic_player_disabled"] = True
            audio_state = page.audio_engine.telemetry_snapshot()
            if audio_state.get('state') == 'ENDPOINT_FAILED':
                now = time.monotonic()
                if getattr(self, '_audio_failed_since', None) is None:
                    self._audio_failed_since = now
                if now - self._audio_failed_since >= self.AUDIO_RECOVERY_GRACE_S:
                    self.fail('准备音频', str(audio_state.get('decoder_error') or '音频进程已退出'))
                    return
            else:
                self._audio_failed_since = None
            surface_ready = player_surface_ready(page)
            if surface_ready:
                self.mark('准备播放器')
            elif '准备播放器' not in self.completed:
                StudioReadiness._record_player_wait(self)
            if '准备播放器' in self.completed and page._playback_buffers_ready():
                self.mark('准备音频')
            opening_cues = first_frame_caption_cues(page) if surface_ready else None
            no_caption_target = opening_cues is not None and not opening_cues
            if no_caption_target and '准备字幕' not in self.completed:
                StudioReadiness._retire_empty_caption_target(self)
                self._caption_skip_reason = ('工程没有字幕' if not page.project.cues else '首屏没有可显示字幕')
                self.mark('准备字幕')
            prepared_renderer = True
            if ('准备播放器' in self.completed and '准备字幕' not in self.completed
                    and owns_hidden_preparation(page) and not page.isVisible()):
                prepare_caption = getattr(page, '_prepare_loading_subtitles', None)
                if callable(prepare_caption):
                    prepared_renderer = prepare_caption()
            # ASS/LIVE initialization is complete only after the initial job
            # and visible renderer have a result, not after their scheduling.
            worker = getattr(page, '_web_live_worker', None)
            web_ready = prepared_renderer and (worker is None or bool(getattr(page.video, '_web_last_decoded', None)))
            scene = getattr(page, '_caption_scene', None)
            if not no_caption_target and getattr(scene, 'active', False):
                # A cache-ready signal can arrive while project hydration is
                # suppressing presentation. A paused project has no following
                # playback tick to submit that prepared scene. Reconcile the
                # current frame here; present() deduplicates pending work and
                # guards project/revision/generation itself.
                if '准备播放器' in self.completed and '准备字幕' not in self.completed:
                    page._present_caption_scene()
                state = scene.trace()
                prepared = caption_rows_prepared(state)
                if prepared > getattr(self, '_caption_rows_prepared', 0):
                    self._caption_rows_prepared = prepared
                    self.last_progress = now
                # The scene token names source cues; bilingual rendering adds
                # a #tr companion pixel row. Row-count equality would leave a
                # paused bilingual frame loading forever until playback left it.
                web_ready = caption_scene_ready(state)
                current = getattr(scene, 'still_current', None)
                if callable(current):
                    token = getattr(scene, 'token', None)
                    web_ready = web_ready and token is not None and current(token)
                if not web_ready and now-self.started > 2 and 'caption_wait' not in self.profile:
                    self.profile['caption_wait'] = state
                    page._studio_trace('STUDIO_CAPTION_WAIT', generation=self.generation, **state)
            if not no_caption_target and (page._preview_path is not None or not page.project.cues):
                if web_ready:
                    self.mark('准备字幕')
            resources_ready = all(stage in self.completed for stage in self.TASKS if stage != '首屏绘制')
            if resources_ready and not self.painted and not StudioReadiness._prepare_timeline_surface(self):
                return
            if self.painted:
                self.mark('首屏绘制')
            pending = [x for x in self.TASKS if x not in self.completed]
            if pending:
                self._set_stage_label(pending[0])
                return
            self.active, self.ready = False, True
            self._ready_project = weakref.ref(page.project)
            self.loaded_file_identity = self.requested_file_identity
            self._ever_ready = True
            self.timer.stop()
            self.profile['total_ms'] = round((time.perf_counter()-self.started)*1000, 3)
            self.profile['open_phases'] = dict(getattr(page, 'last_open_profile', {}))
            heap = getattr(page, '_project_heap', None)
            if heap is not None:
                heap.load_finished()
            self._finish()
            # Bind delayed work to this opening. Dictionary construction can
            # contend for the GIL even on its worker; English source captions
            # do not need Chinese proofreading dictionaries (translations do
            # not change the language of the source being proofread).
            epoch = self.generation
            QTimer.singleShot(1500, lambda: self._warm_text_analysis(epoch))
        except Exception as exc:
            if self._owns_request(tick_epoch, allow_ready=True):
                self.fail(self._failed_stage(), str(exc))

    def _retire_empty_caption_target(self):
        """Retire old tokens/producers once; no current cue must become READY."""
        page = self.page
        scene = getattr(page, '_caption_scene', None)
        if scene is not None:
            scene.close()  # Reject in-flight accepts before retiring its Qt owner.
            scene.deleteLater()
            page._caption_scene = None
        revoke = getattr(page, '_revoke_advanced_preview', None)
        if callable(revoke):
            revoke(reason='loading_no_caption_target')
        video = page.video
        clear = getattr(video, 'clear_caption_boundaries', None)
        if callable(clear):
            clear()
        remove = getattr(video, 'remove_compositor_overlay', None)
        if callable(remove):
            remove(video.ADVANCED_OVERLAY_ID, force=True)
        sample = getattr(page, '_caption_playhead_sample', None)
        if isinstance(sample, dict):
            sample.pop('presented_key', None)
        ownership = getattr(page, '_visual_ownership', None)
        if ownership is not None:
            from ..rendering.visual_runtime import VisualOwner
            ownership.commit(VisualOwner.NONE)
        page._advanced_active_cue_id = ''
        self.profile['caption_target_skipped'] = True

    def _prepare_timeline_surface(self):
        """Render the owned Qt timeline once, including behind a StackOne page."""
        if self.painted:
            return True
        timeline = getattr(self.page, 'timeline', None)
        if timeline is None or not timeline.updatesEnabled():
            self.fail('首屏绘制', '时间轴尚未启用绘制')
            return False
        # QWidget.grab renders a hidden widget without showing it. This is
        # timeline preparation, never a screenshot request to the mpv actor.
        epoch = self.generation
        timeline.grab()
        if not self._owns_request(epoch):
            return False
        self.profile['timeline_surface_prepared'] = True
        self.profile['timeline_prepared_hidden'] = not timeline.isVisible()
        if not self.painted:
            self.fail('首屏绘制', '时间轴首屏准备未完成')
            return False
        return True

    def _warm_text_analysis(self, epoch):
        if epoch != self.generation or not self.ready or getattr(self.page, '_close_requested', False):
            return
        project = self.page.project
        if project is None:
            return
        from ..subtitle_rules.stutter_cleanup import HANZI, warm_text_analysis
        if any(HANZI.search(cue.text) for cue in project.cues):
            warm_text_analysis()

    def _player_start_failure(self):
        """Why Windows could not load mpv at all, or '' (still starting / other errors)."""
        from ..playback.studio_mpv import startup_failure_message
        controller = getattr(self.page.video, 'controller', None)
        return startup_failure_message(getattr(controller, 'exit_code', None))

    def _record_player_wait(self, *, failed=False):
        now = time.perf_counter()
        rows = self.profile.setdefault('player_wait', [])
        if not failed and (now < getattr(self, '_player_wait_next', self.started + 1.) or len(rows) >= 7):
            return
        self._player_wait_next = now + 5.
        try:
            snapshot = player_wait_snapshot(self.page)
            row = dict(elapsed_ms=round((now-self.started)*1000, 3), failed=failed, **snapshot)
            rows.append(row)
            self.page._studio_trace('STUDIO_PLAYER_WAIT', generation=self.generation, **row)
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass  # Diagnostics never alter readiness or the failure being reported.

    def fail(self, stage, error):
        if stage == '准备播放器':
            StudioReadiness._record_player_wait(self, failed=True)
        self.page.video.set_paused(True)
        self.on_ready = None
        self.generation += 1
        self.page.timeline.setUpdatesEnabled(True)
        self.active, self.ready = False, False
        heap = getattr(self.page, '_project_heap', None)
        if heap is not None:
            heap.load_finished(settle=False)
        self.timer.stop()
        self.steps = None
        self.profile['error'] = {'stage': stage, 'message': error}
        self.loading.fail(stage, error)
        # 2026-09-17：识别交接的 reload 在此静默失败过——字幕已写入工程文件
        # 但 Studio 保持旧数据，用户只能回工程库重开。失败必须可见且可重试。
        try:
            self.page._studio_trace('STUDIO_OPEN_FAILED', project_path=self.path,
                                    stage=str(stage), error=str(error))
        except Exception:
            pass
        pending = str(getattr(self.page, '_pending_recognition_reload', '') or '')
        if pending and pending == self.path:
            notifier = getattr(self.page, 'fail_recognition_runtime', None)
            if callable(notifier):
                notifier('工程载入未完成，字幕已写入工程文件；返回 Studio 将自动重载')

    def cancel(self, *, navigate: bool = True, reveal=None):
        self.page.video.set_paused(True)
        self.page.timeline.setUpdatesEnabled(True)
        heap = getattr(self.page, '_project_heap', None)
        if heap is not None:
            heap.load_finished(settle=False)
        self.generation += 1
        self.active = self.ready = False
        self.steps = None
        self.timer.stop()
        self.on_ready = None
        try:
            pending = str(getattr(self.page, '_pending_recognition_reload', '') or '')
            self.page._studio_trace('STUDIO_OPEN_CANCELLED', project_path=self.path,
                                    had_pending_recognition_reload=bool(pending))
        except Exception:
            pass
        if reveal is None:
            self.loading.abort()
        else:
            self.loading.abort(reveal=reveal)
        if navigate and self.page.project is not None:
            self.page._project_view_state = 'open'
            self.page._sync_navigation_chrome()
            self.finished.emit()
        elif navigate:
            self.page.show_project_hub(skip_dirty_guard=True)

    def _finish(self):
        if not self._owns_request(allow_ready=True):
            return
        if self.expected_result_ref:
            from ..recognition.recognition_result import verify_result_reference
            try:
                verify_result_reference(self.expected_result_ref, project=self.page.project,project_path=self.page.project_path)
            except Exception as exc:
                self.fail('核对识别结果', str(exc))
                return
        callback, self.on_ready = self.on_ready, None
        if self.loading.active:
            if not self.loading.deliver(self.loading_generation):
                return
            if not self._owns_request(allow_ready=True):
                return
            self.profile['loading_session'] = self.loading.snapshot()
            self.page._studio_trace('STUDIO_READY_GATE', **self.profile)
        if callback is not None:
            callback()
        # A ready callback is allowed to navigate again. The retired request
        # then has no right to resume playback or reclaim window focus.
        if not self._owns_request(allow_ready=True):
            return
        self.finished.emit()
        if not self._owns_request(allow_ready=True):
            return
        self.page.video.resume_requested_playback()
        # 2026-09-19：open 过程中创建/销毁的原生子窗口（mpv、overlay、内嵌
        # 预览）会把 Win32 焦点打到 NULL——Qt activeWindow=None 后快捷键全
        # 部静默失效（打开工程直接按空格无反应的根因）。ready 即收回焦点。
        try:
            reclaim = getattr(self.page, "_reclaim_window_focus", None)
            if callable(reclaim):
                reclaim()
            else:
                window = self.page.window()
                if QApplication.activeWindow() is not window and self.page.isVisible():
                    window.raise_()
                    window.activateWindow()
        except Exception:
            pass
