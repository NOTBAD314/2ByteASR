"""Real first-interaction readiness, inside the existing Studio window."""
from __future__ import annotations

import threading
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QProgressBar, QVBoxLayout, QHBoxLayout, QApplication

from .i18n import bind_text


def project_file_identity(path):
    """Atomic saves at the same path invalidate a previously loaded project."""
    try:
        stat = Path(path).stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


class StudioReadiness(QObject):
    loaded = Signal(int, object, str)
    player_loaded = Signal(int, object, str)
    finished = Signal()
    TASKS = ('读取工程', '建立时间轴', '准备播放器', '准备音频', '准备字幕', '首屏绘制')

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
        self.overlay = QFrame(page)
        self.overlay.setObjectName('studioLoadingSurface')
        # A native CHILD can cover mpv while loading without reparenting mpv
        # or creating a flashing top-level splash window.
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        layout = QVBoxLayout(self.overlay)
        layout.addStretch()
        title = QLabel('准备工作台', self.overlay)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel('', self.overlay)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.bar = QProgressBar(self.overlay)
        self.bar.setRange(0, len(self.TASKS))
        self.bar.setFixedWidth(360)
        self.bar.setTextVisible(False)
        layout.addWidget(title)
        layout.addSpacing(12)
        layout.addWidget(self.label)
        layout.addSpacing(16)
        layout.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignHCenter)
        actions = QHBoxLayout()
        actions.addStretch()
        self.retry = QPushButton('重试')
        self.retry.clicked.connect(lambda: self.begin(self.path, skip_dirty_guard=True))
        back = QPushButton('返回主页')
        back.clicked.connect(self.cancel)
        actions.addWidget(self.retry)
        actions.addWidget(back)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        self.overlay.hide()
        page.installEventFilter(self)
        page.timeline.installEventFilter(self)
        self.loaded.connect(self._loaded)
        self.player_loaded.connect(self._player_loaded)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._tick)

    def eventFilter(self, watched, event):
        if watched is self.page and event.type() == QEvent.Type.Resize:
            self.overlay.setGeometry(self.page.rect())
        if self.active and watched is self.page.timeline and event.type() == QEvent.Type.Paint:
            self.painted = True
        return False

    def mark(self, name):
        if name not in self.completed:
            self.completed.add(name)
            self.profile['stages_ms'][name] = round((time.perf_counter()-self.started)*1000, 3)
            self.bar.setValue(len(self.completed))

    def _set_stage_label(self, stage: str) -> None:
        """阶段文案带已用时间（用户要求：显示真实阶段，可附已用时间）。"""
        try:
            from .i18n import translate, current_language
            language = current_language()
        except Exception:
            language = "zh"
        elapsed = time.perf_counter() - self.started
        text = translate(str(stage), language) if language != "zh" else str(stage)
        self.label.setText(f"{text} · {elapsed:.1f}s")

    def begin(self, path, *, skip_dirty_guard=False):
        page = self.page
        path = str(Path(path).resolve())
        file_identity = project_file_identity(path)
        if (self.ready and self.path == path and page.project is not None
                and file_identity is not None and self.loaded_file_identity == file_identity):
            self.profile = {'kind': 'hot', 'total_ms': 0., 'stages_ms': {}, 'gui_gaps_ms': []}
            self._finish()
            return
        if self.ready and self.path == path:
            page._studio_trace('PROJECT_RELOAD_REQUIRED', project_path=path,
                reason='saved_file_changed', previous_identity=self.loaded_file_identity,
                current_identity=file_identity)
        if page.project is not None and not skip_dirty_guard:
            if not page.project_controller.dirty_guard.confirm('打开工程'):
                return
        self.generation += 1
        epoch = self.generation
        self.path, self.active, self.ready = path, True, False
        self.requested_file_identity = file_identity
        self.started = self.last_tick = time.perf_counter()
        self.profile = {'kind': 'warm' if getattr(self, '_ever_ready', False) else 'cold',
                        'stages_ms': {}, 'gui_gaps_ms': []}
        self.completed = set()
        self.painted = False
        self.steps = None
        self.next_stage = ''
        self.hydrated = False
        self.retry.hide()
        self.bar.setValue(0)
        bind_text(self.label, '读取工程')
        from .theme_manager import theme_key, theme_definition
        theme = theme_definition(theme_key())
        self.overlay.setStyleSheet(
            f'QFrame#studioLoadingSurface {{background:{theme.app_background};}}'
            f'QLabel {{color:{theme.text};background:transparent;}}'
            f'QProgressBar {{border:0;background:{theme.surface};height:5px;}}'
            f'QProgressBar::chunk {{background:{theme.accent};}}')
        self.overlay.setGeometry(page.rect())
        self.overlay.show()
        self.overlay.raise_()
        self.page.timeline.setUpdatesEnabled(False)
        self.timer.start()
        self.player_ready = bool(page.video.controller is not None and page.video.controller.running)
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
                from .studio_project import load_project
                value, error = load_project(path), ''
                from .media_availability import apply_availability, probe_sources
                results = probe_sources(
                    [a.canonical_source for a in value.media_pool],
                    decode=True,
                    cancel_check=lambda: epoch != self.generation or not self.active,
                )
                apply_availability(value, results)
            except Exception as exc:
                value, error = None, str(exc)
            try:
                self.loaded.emit(epoch, value, error)
            except RuntimeError:
                pass  # The window may have closed while disk IO was pending.
        threading.Thread(target=read, name='studio-project-read', daemon=True).start()

    def _start_mpv_player(self, epoch):
        page = self.page
        from .studio_mpv import MpvController
        from .studio_project import studio_data_root
        hwnd = int(page.video.winId())
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
        if epoch != self.generation or not self.active:
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
        self.profile['player_process_ready_ms']=round((time.perf_counter()-self.started)*1000,3)

    def _loaded(self, epoch, project, error):
        if epoch != self.generation or not self.active:
            return
        if error:
            self.fail('读取工程', error)
            return
        self.mark('读取工程')
        self.steps = self.page.project_controller._open_project_steps(
            self.path, single_shot_fn=QTimer.singleShot, skip_dirty_guard=True, loaded_project=project)

    def _tick(self):
        now = time.perf_counter()
        self.profile['gui_gaps_ms'].append(round((now-self.last_tick)*1000, 3))
        self.last_tick = now
        if now-self.started > 30:
            self.fail(self.label.text(), '准备超时；请检查素材和播放器状态。')
            return
        try:
            if self.steps is not None:
                if self.next_stage == '准备播放器' and not self.player_ready:
                    # 等待播放器进程时保持已用时间跳动（动画不僵死）。
                    self._set_stage_label(self.next_stage or '准备播放器')
                    return
                try:
                    stage = next(self.steps)
                    self.next_stage = stage
                    self._set_stage_label(str(stage))
                    self.overlay.raise_()
                    return
                except StopIteration:
                    self.steps = None
                    self.hydrated = True
                    self.page.timeline.setUpdatesEnabled(True)
                    self.page.timeline.update()
                    if self.page.project is None:
                        self.fail('建立时间轴', '工程未能打开')
                        return
                    self.mark('建立时间轴')
                    self.page.video.playback_prepare()
            if not self.hydrated:
                return
            page = self.page
            audio_state = page.audio_engine.telemetry_snapshot()
            if audio_state.get('state') == 'ENDPOINT_FAILED':
                self.fail('准备音频', str(audio_state.get('decoder_error') or '音频进程已退出'))
                return
            has_media = bool(page.project.media.path)
            if not has_media or page.video._startup_state == 'READY':
                self.mark('准备播放器')
            if '准备播放器' in self.completed and page._playback_buffers_ready():
                self.mark('准备音频')
            # ASS/LIVE initialization is complete only after the initial job
            # and visible renderer have a result, not after their scheduling.
            worker = getattr(page, '_web_live_worker', None)
            web_ready = worker is None or bool(getattr(page.video, '_web_last_decoded', None))
            scene = getattr(page, '_caption_scene', None)
            if getattr(scene, 'active', False):
                state = scene.trace()
                web_ready = (len(state['cue_pixels']) == len(state['expected_cue_ids'])
                             and all(row['status'] != 'pending' for row in state['cue_pixels']))
            if page._preview_path is not None or not page.project.cues:
                if web_ready:
                    self.mark('准备字幕')
            if self.painted:
                self.mark('首屏绘制')
            pending = [x for x in self.TASKS if x not in self.completed]
            if pending:
                self._set_stage_label(pending[0])
                return
            self.active, self.ready = False, True
            self.loaded_file_identity = self.requested_file_identity
            self._ever_ready = True
            self.timer.stop()
            self.profile['total_ms'] = round((time.perf_counter()-self.started)*1000, 3)
            self.profile['open_phases'] = dict(getattr(page, 'last_open_profile', {}))
            self.overlay.hide()
            page._studio_trace('STUDIO_READY_GATE', **self.profile)
            self._finish()
        except Exception as exc:
            self.fail(self.label.text(), str(exc))

    def fail(self, stage, error):
        self.page.timeline.setUpdatesEnabled(True)
        self.active, self.ready = False, False
        self.timer.stop()
        self.steps = None
        self.profile['error'] = {'stage': stage, 'message': error}
        bind_text(self.label, '{stage}失败\n{error}\n工程文件仍保留，可重试载入：\n{value2}', stage=stage, error=error, value2=self.path)
        self.retry.show()
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

    def cancel(self):
        self.page.timeline.setUpdatesEnabled(True)
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
        self.overlay.hide()
        self.page._request_return_home()

    def _finish(self):
        callback, self.on_ready = self.on_ready, None
        if callback is not None:
            callback()
        self.finished.emit()
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
