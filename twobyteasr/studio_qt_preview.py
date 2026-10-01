# SPDX-License-Identifier: GPL-3.0-only
"""Mac Studio video-only Qt backend, embedded in the existing canvas.

QVideoSink supplies decoded frames, not screenshots or a second media clock.
The existing PlaybackClock and PCM/QAudioSink engine remain authoritative.
All player/widget operations run on the Qt GUI thread; immutable overlay
pixels may arrive from the existing publisher threads. No QAudioOutput is
constructed or attached, so this backend cannot become another audio owner.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import threading
import time

from PySide6.QtCore import QObject, QEvent, QRectF, QThread, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QPainter
from PySide6.QtMultimedia import QMediaPlayer, QMediaMetaData, QVideoSink
from PySide6.QtWidgets import QApplication, QWidget


class EmbeddedVideoSurface(QWidget):
    """One normal child widget: decoded video below existing bitmap slots."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('macEmbeddedVideoSurface')
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.frame = QImage()
        self.overlays = {}
        self.painted_frames = 0
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)
        self.show()
        self.lower()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Show):
            self.setGeometry(watched.rect())
        return False

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if not self.frame.isNull():
            size = self.frame.size().scaled(self.size(), Qt.KeepAspectRatio)
            rect = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2,
                          size.width(), size.height())
            painter.drawImage(rect, self.frame)
            self.painted_frames += 1
        dpr = max(1.0, float(self.devicePixelRatioF()))
        for _slot, (image, geometry) in sorted(self.overlays.items()):
            # Canvas publisher geometry is in physical pixels (mpv contract).
            # QWidget coordinates are logical: apply Retina conversion once.
            x, y, width, height = geometry
            painter.drawImage(QRectF(x/dpr, y/dpr, width/dpr, height/dpr), image)
        painter.end()


class QtEmbeddedVideoController(QObject):
    """MpvCanvas-compatible transport adapter for the Mac Qt video backend."""
    _queued = Signal()
    supports_native_subtitles = False
    backend = 'qt-video-sink'

    def __init__(self, canvas):
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError('Embedded video must be created on the QApplication GUI thread.')
        if canvas is None:
            raise ValueError('Embedded video requires the owned Studio canvas.')
        super().__init__(canvas)
        self.surface = EmbeddedVideoSurface(canvas)
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.player.setAudioOutput(None)
        self._lock = threading.RLock()
        self._jobs = OrderedDict()
        self._running = False
        self._closed = False
        self._source_epoch = 0
        self._load_serial = 0
        self._seek_target = None
        self._seek_pending = False
        self._seek_applied = {}
        self._desired_paused = True
        self._loaded = False
        self._first_frame = False
        self._last_error = ''
        self._last_activity = time.monotonic()
        self._frame_sequence = 0
        self._observation_sequence = 0
        self._observation = {}
        self._visual_sequence = 0
        self._visual = {'subtitle': {'visible': False, 'sequence': 0}, 'overlays': {}}
        self._subtitle_path = ''
        self._position_observer = None
        self._caption_boundary_publisher = None
        self._properties = {'pause': True, 'speed': 1.0, 'volume': 0.0, 'aid': 'no',
                            'path': '', 'time-pos': None, 'duration': 0.0,
                            'idle-active': True, 'eof-reached': False, 'seeking': False,
                            'video-out-params': {}, 'video-frame-info': {}}
        self._queued.connect(self._drain, Qt.QueuedConnection)
        self.player.mediaStatusChanged.connect(self._status)
        self.player.positionChanged.connect(self._position)
        self.player.durationChanged.connect(self._duration)
        self.player.playbackStateChanged.connect(self._state)
        self.player.errorOccurred.connect(self._error)
        self.sink.videoFrameChanged.connect(self._frame)

    @property
    def running(self):
        return self._running and not self._closed

    @property
    def source_epoch(self):
        return self._source_epoch

    def _advance_source_epoch(self, generation):
        self._source_epoch = max(self._source_epoch, int(generation))

    def start(self, _window_id=0, *, log_path=''):
        self._require_gui()
        if self._closed:
            raise RuntimeError('Embedded video controller is closed.')
        self._running = True
        self.surface.show()

    def _require_gui(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError('Synchronous video/player operation requires the Qt GUI thread.')

    def _post(self, callback, key, on_discard=None):
        with self._lock:
            if not self.running:
                if on_discard: on_discard()
                return False
            previous = self._jobs.pop(key, None)
            self._jobs[key] = (callback, on_discard)
        if previous and previous[1]: previous[1]()
        self._queued.emit()
        return True

    @Slot()
    def _drain(self):
        self._require_gui()
        while True:
            with self._lock:
                if not self._jobs: return
                _key, (callback, discarded) = self._jobs.popitem(last=False)
            if not self.running:
                if discarded: discarded()
                continue
            try:
                callback()
            except Exception as exc:
                self._last_error = f'{type(exc).__name__}: {exc}'
                if discarded: discarded()

    def _status(self, status):
        if not self.running or not self._properties['path']:
            return
        self._last_activity = time.monotonic()
        if status == QMediaPlayer.InvalidMedia:
            self._error(self.player.error(), self.player.errorString())
        elif status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and not self._loaded:
            self._loaded = True
            self._properties['idle-active'] = False
            if self._seek_target is not None:
                self.player.setPosition(round(self._seek_target*1000))
            # Preroll a REAL first frame. Muted video pauses as soon as that
            # decoded frame arrives when the requested state is paused.
            self.player.play()
        elif status == QMediaPlayer.EndOfMedia:
            self._desired_paused = True
            self._properties.update({'eof-reached': True, 'pause': True})
            self._publish_position(self.player.duration(), 'qt-media-end')

    def _error(self, _code, text=''):
        self._last_error = str(text or self.player.errorString() or 'Qt media error')
        self._properties['pause'] = True

    def _state(self, _state):
        # During muted first-frame preroll, requested pause remains true.
        self._properties['pause'] = self._desired_paused

    def _duration(self, milliseconds):
        self._properties['duration'] = max(0, milliseconds)/1000.0

    def _position(self, milliseconds):
        self._publish_position(milliseconds, 'qt-media-position')

    def _publish_position(self, milliseconds, source):
        self._last_activity = time.monotonic()
        self._observation_sequence += 1
        position = max(0, milliseconds)/1000.0
        self._properties['time-pos'] = self._properties['playback-time'] = position
        self._observation = {'source': source, 'source_generation': self._source_epoch,
                             'actor_sequence': self._observation_sequence,
                             'observed_monotonic_ts': time.monotonic(),
                             'observed_perf_counter_ts': time.perf_counter(),
                             'position': position, 'seek_target': self._seek_target,
                             'paused': self._desired_paused,
                             'playback_rate': self._properties['speed'],
                             'seeking': self._seek_pending}
        boundary = self._caption_boundary_publisher
        if boundary is not None: boundary.observe(dict(self._observation))
        observer = self._position_observer
        if callable(observer):
            try: observer(dict(self._observation))
            except RuntimeError: pass  # Closed Qt recipient cannot revive media.

    def _frame(self, frame):
        self._require_gui()
        if not self.running or not self._loaded or not frame.isValid(): return
        image = frame.toImage()
        if image.isNull(): return
        pts = max(0, frame.startTime())/1_000_000.0 if frame.startTime() >= 0 else None
        if self._seek_pending and pts is not None and self._seek_target is not None:
            duration = max(1, frame.endTime()-frame.startTime())/1_000_000.0
            # Reject a late pre-seek frame rather than rebadging its epoch.
            if abs(pts-self._seek_target) > max(.05, duration*2): return
        self.surface.frame = image.copy()
        self.surface.update()
        self._first_frame = True
        self._frame_sequence += 1
        self._properties['video-out-params'] = {'w': image.width(), 'h': image.height(),
                                               'dw': image.width(), 'dh': image.height()}
        self._properties['video-frame-info'] = {'pts': pts, 'estimated-frame-number': self._frame_sequence,
                                               'picture-type': 'decoded-qt-video-frame'}
        self._properties['idle-active'] = False
        if self._seek_pending:
            self._seek_pending = False
            self._properties['seeking'] = False
            self._seek_applied = {'generation': self._source_epoch, 'target': self._seek_target,
                                  'perf_counter': time.perf_counter(), 'frame_pts': pts}
        if self._desired_paused: self.player.pause()
        self._publish_position(self.player.position(), 'qt-decoded-video-frame')

    def post_load_at(self, media_path, seconds, *, generation):
        return self._post(lambda: self._load(media_path, seconds, generation), 'loadfile')

    def post_load(self, media_path):
        return self.post_load_at(media_path, 0, generation=self._source_epoch)

    def load(self, media_path):
        self._load(media_path, 0, self._source_epoch)

    def _load(self, media_path, seconds, generation):
        self._require_gui()
        source = Path(media_path).resolve()
        if not source.is_file(): raise FileNotFoundError(str(source))
        self.player.stop()
        self._advance_source_epoch(generation)
        self._load_serial += 1
        self._loaded = self._first_frame = False
        self._last_error = ''
        self._last_activity = time.monotonic()
        self._seek_target = max(0, float(seconds))
        self._seek_pending = True
        self._properties.update({'path': str(source), 'time-pos': None,
                                 'idle-active': True, 'eof-reached': False,
                                 'seeking': True, 'video-frame-info': {}, 'video-out-params': {}})
        self.surface.frame = QImage()
        self.surface.overlays.clear()
        for slot in tuple(self._visual['overlays']):
            self._record_visual(slot, False)
        self.surface.update()
        self.player.setSource(QUrl.fromLocalFile(str(source)))

    def post_seek(self, seconds, *, accurate=True, generation=0):
        return self._post(lambda: self._seek(seconds, generation), 'seek')

    def seek(self, seconds, *, accurate=True):
        self._seek(seconds, self._source_epoch)

    def _seek(self, seconds, generation):
        self._require_gui()
        self._advance_source_epoch(generation)
        self._seek_target = max(0, float(seconds))
        self._seek_pending = True
        self._properties.update({'seeking': True, 'eof-reached': False, 'video-frame-info': {}})
        self.player.setPosition(round(self._seek_target*1000))
        if self.player.playbackState() == QMediaPlayer.StoppedState:
            self.player.play()  # Muted first target frame restores paused EOF.

    def post_set_paused(self, paused, *, position_seconds=None):
        def perform():
            if position_seconds is not None and paused and not self._seek_pending:
                self._seek(position_seconds, self._source_epoch)
            self.set_paused(paused)
        return self._post(perform, 'pause')

    def set_paused(self, paused):
        self._require_gui()
        self._desired_paused = bool(paused)
        self._properties['pause'] = bool(paused)
        if paused:
            if self._first_frame: self.player.pause()
        elif self._loaded:
            if self._properties['eof-reached']:
                self._seek(0, self._source_epoch)
            self._properties['eof-reached'] = False
            self.player.play()

    def post_set_speed(self, value):
        return self._post(lambda: self.set_speed(value), 'speed')

    def set_speed(self, value):
        self._require_gui()
        speed = max(.1, min(8.0, float(value)))
        self.player.setPlaybackRate(speed)
        self._properties['speed'] = speed

    def post_set_volume(self, value):
        return self._post(lambda: self.set_volume(value), 'volume')

    def set_volume(self, _value):
        self._properties['volume'] = 0.0  # Existing PCM owner handles volume.

    def post_set_audio_enabled(self, enabled):
        return self._post(lambda: self.set_audio_enabled(enabled), 'audio')

    def set_audio_enabled(self, _enabled):
        self._require_gui()
        self.player.setAudioOutput(None)
        self._properties['aid'] = 'no'

    def frame_step(self, backwards=False):
        self._require_gui()
        self.set_paused(True)
        fps = self.player.metaData().value(QMediaMetaData.VideoFrameRate) or 30.0
        self._seek(self.player.position()/1000.0 + (-1 if backwards else 1)/float(fps), self._source_epoch)

    def post_clear_media(self):
        return self._post(self.clear_media, 'loadfile')

    def clear_media(self):
        self._require_gui()
        self.player.stop()
        self.player.setSource(QUrl())
        self._load_serial += 1
        self._loaded = self._first_frame = False
        self._seek_pending = False
        self._properties.update({'path': '', 'time-pos': None, 'pause': True,
                                 'idle-active': True, 'eof-reached': False, 'seeking': False,
                                 'video-frame-info': {}, 'video-out-params': {}})
        self.surface.frame = QImage()
        self.surface.overlays.clear()
        for slot in tuple(self._visual['overlays']):
            self._record_visual(slot, False)
        self.surface.update()

    def post_subtitle_file(self, path):
        return self._post(lambda: self.set_subtitle_file(path), 'subtitle-file')

    def set_subtitle_file(self, path):
        self._require_gui()
        if not Path(path).is_file(): raise FileNotFoundError(str(path))
        self._subtitle_path = str(path)
        # CaptionScene renders ordinary and authored subtitles through the
        # existing raster pipeline. This adapter does not pretend to run libass.

    def post_set_subtitle_visible(self, visible):
        return self._post(lambda: self.set_subtitle_visible(visible), 'subtitle-visible')

    def set_subtitle_visible(self, _visible):
        self._record_visual('subtitle', False)

    def _record_visual(self, target, visible):
        self._visual_sequence += 1
        state = {'visible': bool(visible), 'sequence': self._visual_sequence,
                 'monotonic': time.monotonic(), 'perf_counter': time.perf_counter()}
        if target == 'subtitle': self._visual['subtitle'] = state
        else: self._visual['overlays'][int(target)] = state

    def post_raw_overlay(self, overlay_id, path, *, valid_when=None, on_applied=None,
                         on_started=None, coalesce_key=None, cue_id='', **geometry):
        serial = self._load_serial
        def apply():
            if serial != self._load_serial or (valid_when and not valid_when()):
                if on_applied: on_applied(False)
                return
            if on_started: on_started()
            self.set_raw_overlay(overlay_id, path, **geometry)
            if on_applied: on_applied(True)
        return self._post(apply, coalesce_key or f'overlay:{overlay_id}',
                          (lambda: on_applied(False)) if on_applied else None)

    def set_raw_overlay(self, overlay_id, path, *, x, y, width, height, stride,
                        display_width=None, display_height=None, offset=0, **_unused):
        self._require_gui()
        width, height, stride = int(width), int(height), int(stride)
        if min(width, height) <= 0 or stride < width*4 or stride*height > 128*1024*1024:
            raise ValueError('Invalid or oversized premultiplied BGRA overlay.')
        with Path(path).open('rb') as stream:
            stream.seek(int(offset))
            pixels = stream.read(stride*height)
        if len(pixels) != stride*height: raise ValueError('Truncated overlay pixels.')
        image = QImage(pixels, width, height, stride, QImage.Format_ARGB32_Premultiplied).copy()
        rect = (float(x), float(y), float(display_width or width), float(display_height or height))
        self.surface.overlays[int(overlay_id)] = (image, rect)
        self.surface.update()
        self._record_visual(int(overlay_id), True)

    def post_remove_overlay(self, overlay_id, *, cue_id=None):
        return self._post(lambda: self.remove_overlay(overlay_id), f'overlay:{overlay_id}')

    def remove_overlay(self, overlay_id):
        self._require_gui()
        self.surface.overlays.pop(int(overlay_id), None)
        self.surface.update()
        self._record_visual(int(overlay_id), False)

    def observed_properties(self):
        with self._lock: return dict(self._properties)

    def observed_property(self, name, default=None):
        return self.observed_properties().get(name, default)

    def get_property(self, name, default=None):
        return self.observed_property(name, default)

    def observed_position(self):
        with self._lock: return dict(self._observation)

    def applied_seek_state(self):
        with self._lock: return dict(self._seek_applied)

    def applied_visual_state(self):
        return {'sequence': self._visual_sequence, 'subtitle': dict(self._visual['subtitle']),
                'overlays': {key: dict(value) for key, value in self._visual['overlays'].items()}}

    def source_alive(self, *, max_silence_s=5.0):
        return bool(self.running and not self._last_error and
                    (self._desired_paused or time.monotonic()-self._last_activity <= max_silence_s))

    def actor_status(self):
        return {'backend': self.backend, 'degraded': bool(self._last_error),
                'last_error': self._last_error, 'thread_alive': self.running, 'pipe_open': False,
                'gui_thread': True, 'frame_sequence': self._frame_sequence,
                'painted_frames': self.surface.painted_frames,
                'audio_output_attached': self.player.audioOutput() is not None}

    def subtitle_diagnostics(self):
        return {'native_subtitles_supported': False, 'subtitle_file': self._subtitle_path,
                'renderer': 'existing-caption-scene-raster', 'sub-visibility': False, 'sub-text': ''}

    def screenshot_to_file(self, path, *, mode='window'):
        self._require_gui()
        if not self.surface.grab().save(str(path)):
            raise OSError(f'Cannot save embedded widget frame: {path}')

    def close(self):
        # Studio normally retires mpv on a background thread. Queue Qt-owned
        # shutdown onto the GUI thread; never operate QObject media there.
        if self._closed:
            return
        if QThread.currentThread() != self.thread():
            self._post(self.close, 'close')
            return
        self._position_observer = None
        if self._caption_boundary_publisher is not None:
            self._caption_boundary_publisher.close()
            self._caption_boundary_publisher = None
        self.clear_media()
        self._running = False
        self._closed = True
        with self._lock:
            jobs = tuple(self._jobs.values())
            self._jobs.clear()
        for _callback, discarded in jobs:
            if discarded: discarded()
        self.surface.hide()
        self.surface.deleteLater()
        self.deleteLater()
