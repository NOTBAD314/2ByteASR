"""Clock-driven CSS previews, with one page lease per consumer.

PlaybackClock supplies cue-local time. Each worker has one in-flight browser
operation and reads the newest clock/configuration after every await. The
shared browser service owns the pages; no whole-cue recording can block play.
The legacy strip data types remain readable for cache compatibility only.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Mapping

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

_POLL_SECONDS = 0.015          # 回放泵查询节奏（条带查询是本地内存操作）
_RECORD_POLL_SECONDS = 0.010   # 录制期推帧采样节奏（screencast 60fps，漏帧≈24fps）
_TAIL_MS = 400.0               # 出场尾巴（与 provider 的出界窗口一致）
_MAX_CONSECUTIVE_FAILURES = 3
_WARM_QUEUE_CAP = 8


@dataclass(frozen=True)
class WebPreviewConfiguration:
    html: str
    theme_key: str
    strip_key: str
    text: str
    speaker: str
    duration: float
    placement: dict
    explicit_motion: bool
    proxy_safe: bool = False


@lru_cache(maxsize=8)
def _compiled_theme_page(serialized_theme):
    from .web_theme import theme_archive_html
    return theme_archive_html(json.loads(serialized_theme), sample_text='字幕预览',
        speaker='', duration_seconds=3., auto_replay=False)


def prepare_web_configuration(theme, text, speaker='', duration_seconds=3., placement=None):
    """Compile once per theme on the caption preparation worker."""
    from .web_placement import normalize_placement
    text = str(text or '字幕预览ABC123')
    speaker = str(speaker or '')
    duration = max(.05, float(duration_seconds))
    placement = normalize_placement(placement)
    serialized = json.dumps(document_theme_digest(theme), ensure_ascii=False, sort_keys=True)
    theme_key = hashlib.sha1(serialized.encode('utf8')).hexdigest()[:16]
    strip_key = _strip_key_for(theme_key, json.dumps([text,speaker,round(duration,3),placement], ensure_ascii=False, sort_keys=True))
    return WebPreviewConfiguration(_compiled_theme_page(serialized),theme_key,strip_key,text,speaker,duration,
        placement,bool(theme.get('motionSpec')),not bool(str(theme.get('stageHtml','')).strip() or str(theme.get('stageCss','')).strip()
            or 'animation' in str(theme.get('cueCss','')).lower() or '@keyframes' in str(theme.get('cueCss','')).lower()))


def document_theme_digest(theme: Mapping[str, Any]) -> dict[str, Any]:
    """Theme identity without the cue text (drives the reload-vs-swap choice)."""
    payload = dict(theme)
    payload.pop("debug", None)
    return payload


def live_preview_enabled() -> bool:
    """Live pump gate: offscreen (CI/单测) stays off unless explicitly forced."""
    if os.environ.get("TWOBYTEASR_DISABLE_WEB_LIVE", "") == "1":
        return False
    if os.environ.get("TWOBYTEASR_FORCE_WEB_LIVE", "") == "1":
        return True
    return os.environ.get("QT_QPA_PLATFORM", "").strip().lower() != "offscreen"


def _strip_budget_bytes() -> int:
    try:
        mb = int(os.environ.get("TWOBYTEASR_WEB_STRIP_MB", "512"))
    except ValueError:
        mb = 512
    return max(32, mb) * 1024 * 1024


# ---------------------------------------------------------------------------
# 条带存储：一个 strip = 某主题在某文案/时长下的完整帧序列（[(t_ms, png)]）。
# ---------------------------------------------------------------------------


class WebStrip:
    """Recorded frame sequence for one (theme, text, speaker, duration)."""

    __slots__ = ("key", "span_ms", "times", "frames", "total_bytes", "done", "recording", "last_touch")

    def __init__(self, key: str, span_ms: float) -> None:
        self.key = str(key)
        self.span_ms = float(span_ms)
        self.times: list[float] = []
        self.frames: list[bytes] = []
        self.total_bytes = 0
        self.done = False
        self.recording = False
        self.last_touch = time.monotonic()

    def frame_at(self, t_ms: float) -> tuple[bytes, float] | None:
        """Nearest recorded frame at or before ``t_ms`` (clamped to [0, last])."""
        if not self.frames:
            return None
        idx = bisect.bisect_right(self.times, float(t_ms)) - 1
        if idx < 0:
            idx = 0
        return self.frames[idx], self.times[idx]


class WebStripStore:
    """Thread-safe LRU strip cache with a byte budget."""

    def __init__(self, budget_bytes: int | None = None) -> None:
        self._budget = int(budget_bytes if budget_bytes is not None else _strip_budget_bytes())
        self._strips: OrderedDict[str, WebStrip] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def budget_bytes(self) -> int:
        return self._budget

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return sum(strip.total_bytes for strip in self._strips.values())

    def peek(self, key: str, *, touch: bool = True) -> WebStrip | None:
        with self._lock:
            strip = self._strips.get(str(key))
            if strip is not None and touch:
                strip.last_touch = time.monotonic()
                self._strips.move_to_end(strip.key)
            return strip

    def is_complete(self, key: str) -> bool:
        strip = self.peek(key, touch=False)
        return bool(strip is not None and strip.done)

    def frame(self, key: str, t_ms: float) -> tuple[bytes, float] | None:
        strip = self.peek(key)
        if strip is None or not strip.done:
            return None
        return strip.frame_at(t_ms)

    def create(self, key: str, span_ms: float) -> WebStrip:
        with self._lock:
            strip = WebStrip(str(key), span_ms)
            strip.recording = True
            self._strips[strip.key] = strip
            self._evict_locked(protect=strip.key)
            return strip

    def append(self, strip: WebStrip, t_ms: float, png: bytes) -> None:
        with self._lock:
            strip.times.append(float(t_ms))
            strip.frames.append(bytes(png))
            strip.total_bytes += len(png)
            strip.last_touch = time.monotonic()
            self._evict_locked(protect=strip.key)

    def finish(self, strip: WebStrip) -> None:
        with self._lock:
            strip.done = True
            strip.recording = False
            strip.last_touch = time.monotonic()

    def abandon(self, strip: WebStrip) -> None:
        """中断录制：保留已录帧（下次续录），标记不在录制态。"""
        with self._lock:
            strip.recording = False

    def discard(self, key: str) -> None:
        with self._lock:
            self._strips.pop(str(key), None)

    def _evict_locked(self, *, protect: str) -> None:
        total = sum(strip.total_bytes for strip in self._strips.values())
        while total > self._budget:
            victim: WebStrip | None = None
            for strip in self._strips.values():  # OrderedDict: LRU first
                if strip.key == protect or strip.recording:
                    continue
                victim = strip
                break
            if victim is None:
                return
            total -= victim.total_bytes
            self._strips.pop(victim.key, None)


GLOBAL_WEB_STRIP_STORE = WebStripStore()

# 进程级 live 页互斥：任何时刻只有一个录制者使用 node 的 live 页；回放不碰页。
GLOBAL_PAGE_LOCK = threading.Lock()
_PAGE_STATE: dict[str, str | None] = {"strip": None, "theme": None}


def reset_page_state() -> None:
    """Live 页状态未知（服务重启/浏览器死亡）时作废登记，强制下次重载。"""
    _PAGE_STATE["strip"] = None
    _PAGE_STATE["theme"] = None
    _PAGE_STATE["text"] = None
    _PAGE_STATE["speaker"] = None


def _strip_key_for(theme_key: str, text: str) -> str:
    return hashlib.sha1(f"{theme_key}|{text}".encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Worker v3
# ---------------------------------------------------------------------------


def _content_bounds(image: QImage):
    """帧的不透明内容包围盒（numpy 扫描，~1-2ms）。

    overlay 发布用它裁掉大面积透明区（1280x720 全帧 3.7MB RGBA → 字幕带
    ~1.2MB），发布线程的写盘与 mpv 投递都随之变小。numpy 不可用时返回 None
    （回退全帧发布，语义不变）。二十七轮终版：在发布线程内调用（worker 只
    发原始 PNG 字节——同步解码曾把 worker 发射周期拖到 ~47ms=22fps）。
    """
    height, width = image.height(), image.width()
    if width <= 0 or height <= 0 or image.format() != QImage.Format.Format_ARGB32:
        return None
    from PySide6.QtCore import QRect
    # Opposite occupied corners prove the exact bounding box is the canvas.
    # Full-stage vignette themes otherwise scan/copy an alpha mask per frame.
    if (image.pixel(0, 0) >> 24) > 8 and (image.pixel(width-1, height-1) >> 24) > 8:
        return QRect(0, 0, width, height)
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        buffer = np.frombuffer(
            image.constBits(), dtype=np.uint8, count=image.sizeInBytes(),
        ).reshape(height, image.bytesPerLine())
        alpha = buffer[:, : width * 4][:, 3::4]
        mask = alpha > 8
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
    except (ValueError, RuntimeError):
        return None
    if rows.size == 0 or cols.size == 0:
        return None
    left = max(0, int(cols[0]) - 6)
    top = max(0, int(rows[0]) - 6)
    right = min(width - 1, int(cols[-1]) + 6)
    bottom = min(height - 1, int(rows[-1]) + 6)
    return QRect(left, top, right - left + 1, bottom - top + 1)


def _decode_frame(data: bytes):
    """解码 + ARGB32 归一 + 内容 bbox——发布快速通道的重活半成品。

    只应在**非 GUI**线程调用（发布线程/测试）；worker 发射的是原始 PNG
    字节，不在发射路径上同步解码（解码 ~15-20ms 会把发射周期拖到 47ms
    ≈22fps，二十七轮实测）。
    """
    try:
        image = QImage.fromData(bytes(data))
        if image.isNull():
            return None
        if image.format() != QImage.Format.Format_ARGB32:
            image = image.convertToFormat(QImage.Format.Format_ARGB32)
        return image, _content_bounds(image)
    except Exception:
        return None


class WebFrame(bytes):
    """PNG with immutable publication identity across queued Qt signals."""

    def __new__(cls, png, worker_id, content_key, generation, clock_generation=None):
        obj = super().__new__(cls, png)
        obj.worker_id, obj.content_key, obj.generation = worker_id, content_key, generation
        obj.clock_generation = clock_generation
        obj.pixel_digest = hashlib.blake2s(obj,digest_size=16).digest()
        obj.produced_at = time.monotonic()
        return obj


class LiveWebPreviewWorker(QObject):
    """Stream the current clock from an independently owned browser page."""

    frame_ready = Signal(object, float, float)  # 原始 PNG bytes（发布线程再解码），cue_ms, stage_ms
    failed = Signal(str)
    exited = Signal()
    configured = Signal(str)   # html/strip key（live_set 完成后）
    recorded = Signal(str)     # strip key（条带录制完成）
    selection_geometry_ready = Signal(object, object)

    def __init__(
        self,
        *,
        time_provider: Callable[..., Any] | None = None,
        loop_seconds: float | None = None,
        width: int = 1280,
        height: int = 720,
        name: str = "live-web-preview",
        proxy_cache: bool = False,
        quality: str = "full",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._time_provider = time_provider
        self._loop_seconds = loop_seconds
        self._width = int(width)
        self._height = int(height)
        self._name = str(name)
        self._proxy_cache = bool(proxy_cache)
        self._quality = quality
        self._proxy_key = None
        self._proxy_prepared = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._recorder: threading.Thread | None = None
        self._html: str = ""
        self._html_key: str = ""
        self._theme_key: str = ""
        self._strip_key: str = ""
        self._strip_text: str = ""
        self._strip_speaker: str = ""
        self._strip_placement: dict = {}
        self._strip_span_ms: float = 0.0
        self._html_dirty = False
        self._loaded_text: str = ""
        self._loaded_speaker: str = ""
        self._pending_text: tuple[str, str] | None = None
        self._warm_queue: list[dict[str, Any]] = []
        self._record_failures = 0
        self._last_emit_t: float | None = None
        self._html_lock = threading.Lock()
        self.metrics = []
        self._configuration_generation = 0
        self._explicit_motion_clock = False
        self._selection_geometry_request = None

    def request_selection_geometry(self,key):
        self._selection_geometry_request=key

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        *,
        theme: Mapping[str, Any],
        text: str,
        speaker: str = "",
        duration_seconds: float | None = None,
        placement: Mapping[str, Any] | None = None,
    ) -> str:
        """Compatibility for editors; playback submits an already prepared object."""
        return self.configure_prepared(prepare_web_configuration(theme,text,speaker,
            duration_seconds if duration_seconds is not None else (self._loop_seconds or 2.4),placement))

    def configure_prepared(self, prepared: WebPreviewConfiguration) -> str:
        from .caption_proxy import with_quality
        prepared = with_quality(prepared,self._quality)
        proxy_key = None
        if self._proxy_cache:
            from .caption_proxy import proxy_store
            proxy_key = proxy_store().ensure(prepared,self._width,self._height,cancel_check=self._stop.is_set)
        html,theme_key,strip_key = prepared.html,prepared.theme_key,prepared.strip_key
        text,speaker,duration,placement = prepared.text,prepared.speaker,prepared.duration,prepared.placement
        with self._html_lock:
            self._proxy_key = proxy_key
            self._proxy_prepared = prepared if proxy_key else None
            self._explicit_motion_clock = prepared.explicit_motion
            if self._strip_key != strip_key:
                self._configuration_generation += 1
            self._html = html
            self._strip_span_ms = max(50.0, duration * 1000.0)
            self._strip_key = strip_key
            self._strip_text = text
            self._strip_speaker = speaker
            self._strip_placement = placement
            if theme_key != self._theme_key:
                self._html_key = theme_key
                self._theme_key = theme_key
                self._html_dirty = True
                self._loaded_text = text
                self._loaded_speaker = speaker
                self._pending_text = None
            elif text != self._loaded_text or speaker != self._loaded_speaker:
                self._pending_text = (text, speaker)
        return theme_key

    def warm(self, **kwargs) -> None:
        # Browser/font warmup is shared. Never navigate the active consumer's
        # page to an upcoming cue or record whole strips behind a page lock.
        return

    def warm_prepared(self, prepared) -> None:
        if self._proxy_cache:
            from .caption_proxy import proxy_store,with_quality
            proxy_store().ensure(with_quality(prepared,self._quality),self._width,self._height,cancel_check=self._stop.is_set)
        with self._html_lock:
            if prepared.theme_key != self._theme_key: return
            self._warm_queue = [item for item in self._warm_queue if item['text'] != prepared.text]
            self._warm_queue.append({'text':prepared.text,'speaker':prepared.speaker})
            self._warm_queue = self._warm_queue[-4:]

    def mark_dirty(self) -> None:
        """Recovery path: drop the active strip and force a page reload."""
        with self._html_lock:
            self._html_dirty = True
            self._pending_text = None
            key = self._strip_key
        if key:
            GLOBAL_WEB_STRIP_STORE.discard(key)
        with self._html_lock:
            self._configuration_generation += 1

    @property
    def html_key(self) -> str:
        with self._html_lock:
            return self._html_key

    @property
    def strip_key(self) -> str:
        with self._html_lock:
            return self._strip_key

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=self._name,
        )
        self._thread.start()
    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    # ------------------------------------------------------------------
    # replay pump（零页调用）
    # ------------------------------------------------------------------

    def _run(self) -> None:
        from .renderer_service import GLOBAL_RENDERER_SERVICE, LiveRendererSession, RendererLiveRequestSuperseded

        service = LiveRendererSession(GLOBAL_RENDERER_SERVICE)
        started = time.perf_counter()
        loaded_theme = loaded_content = ""
        applied = None
        applied_clock_generation = None
        seq = 0
        failures = 0
        paused_png = None
        try:
            while not self._stop.is_set():
                generation_of_clock = getattr(self._time_provider, 'discontinuity_generation', lambda: None)
                info_clock_generation = generation_of_clock()
                info = self._resolve_time(started)
                if info_clock_generation != generation_of_clock():
                    continue
                if info is None:
                    # At a cue boundary the clock can outrun the GUI binding
                    # by one tick. An inactive cue is not a dead browser lease.
                    # Explicit stop/project close still retires this worker.
                    self._stop.wait(.005)
                    continue
                with self._html_lock:
                    generation = self._configuration_generation
                    theme_key, content_key = self._theme_key, self._strip_key
                    html, text, speaker = self._html, self._strip_text, self._strip_speaker
                    span, dirty = self._strip_span_ms, self._html_dirty
                    placement = dict(self._strip_placement)
                    explicit_motion = self._explicit_motion_clock
                    proxy_key = self._proxy_key
                    proxy_prepared = self._proxy_prepared
                if not content_key:
                    self._stop.wait(.01)
                    continue
                try:
                    cue, stage, playing, rate = info
                    # Ready alpha sequences use the same publication identity/clock guards.
                    # Exact paused frames and selection geometry continue through HTML.
                    if proxy_key:
                        from .caption_proxy import proxy_store
                        t0 = time.perf_counter()
                        if t0-getattr(self,'_proxy_retry_at',0)>1:
                            self._proxy_retry_at=t0
                            if proxy_store().status(proxy_key)=='missing' and proxy_prepared is not None:
                                proxy_store().ensure(proxy_prepared,self._width,self._height,cancel_check=self._stop.is_set)
                        # Paused seeks on the exact frame grid can reuse the
                        # same pixels. Off-grid stills keep precise HTML seek.
                        from .caption_proxy import FPS
                        on_grid=abs(cue*FPS/1000-round(cue*FPS/1000))<.001
                        cached = (proxy_store().frame_at(proxy_key,cue)
                                  if (playing or on_grid) and self._selection_geometry_request is None else None)
                        if cached is not None:
                            png, sampled_ms = cached
                            if (not self._stop.is_set() and generation == self._configuration_generation
                                    and info_clock_generation == generation_of_clock()):
                                token=(content_key,sampled_ms,info_clock_generation)
                                if token != getattr(self,'_last_proxy_token',None):
                                    self.frame_ready.emit(WebFrame(png,id(self),content_key,generation,info_clock_generation),sampled_ms,stage-cue+sampled_ms)
                                    self._last_proxy_token=token
                                    self._metric('proxy_frame',t0)
                            applied=None
                            self._stop.wait(.004)
                            continue
                    self._last_proxy_token=None
                    if loaded_content != content_key or dirty:
                        t0 = time.perf_counter()
                        with self._html_lock:
                            upcoming, self._warm_queue = self._warm_queue, []
                        if loaded_theme != theme_key or dirty:
                            service.live_set(html, width=self._width, height=self._height)
                            # Theme HTML is shared across cues; bind the first
                            # caption before publishing any generic seed pixels.
                            service.live_text(text=text, speaker=speaker, duration_ms=span, placement=placement, prepared_cues=upcoming)
                            phase = "page_load"
                        else:
                            service.live_text(text=text, speaker=speaker, duration_ms=span, placement=placement, prepared_cues=upcoming)
                            phase = "cue_dom"
                        self._metric(phase, t0)
                        self.metrics[-1].update(getattr(service,'last_live_text_metrics',{}))
                        loaded_theme, loaded_content = theme_key, content_key
                        with self._html_lock:
                            if generation == self._configuration_generation:
                                self._html_dirty = False
                        applied = None
                        seq = 0
                        if generation != self._configuration_generation or self._stop.is_set():
                            continue
                        self.configured.emit(content_key)
                        # Time spent loading is not playback time: read the
                        # clock again before applying any animation state.
                        continue
                    cue, stage, playing, rate = info
                    if explicit_motion and playing:
                        # The shared GSAP timeline always remains paused. Each
                        # frame consumes the canonical cue time supplied here;
                        # neither CSS nor a browser timer advances the theme.
                        t0=time.perf_counter()
                        png=service.live_frame(cue_ms=cue,stage_ms=stage)
                        current=self._resolve_time(started)
                        if (not self._stop.is_set() and generation==self._configuration_generation
                                and info_clock_generation==generation_of_clock() and current is not None
                                and current[2] and abs((current[1]-current[0])-(stage-cue))<45):
                            self.frame_ready.emit(WebFrame(png,id(self),content_key,generation,info_clock_generation),cue,stage)
                        self._metric('motion_clock_frame',t0)
                        applied=None
                        self._stop.wait(max(.001,1/30-(time.perf_counter()-t0)))
                        continue
                    wall = time.perf_counter()
                    expected = (applied[0] + (wall-applied[4])*1000*applied[3]
                                if applied and applied[2] else applied[0] if applied else None)
                    # A paused frame follows explicit seek generations. Tiny
                    # decoder observation corrections must not start a second
                    # screenshot between two user operations.
                    compare_position = playing or info_clock_generation is None
                    changed = (applied is None or playing != applied[2] or rate != applied[3]
                               or info_clock_generation != applied_clock_generation
                               or (compare_position and abs(cue-expected) > (45 if playing else .5))
                               or abs((stage-cue)-(applied[1]-applied[0])) > 45)
                    if changed:
                        sync_clock_generation = info_clock_generation
                        if sync_clock_generation != generation_of_clock():
                            continue
                        sync_reason = ('initial' if applied is None else 'pause_change' if playing != applied[2]
                            else 'rate_change' if rate != applied[3] else 'clock_drift')
                        drift_ms = cue-expected if expected is not None else None
                        t0 = time.perf_counter()
                        if playing:
                            service.live_play(cue_ms=cue, stage_ms=stage, rate=rate, every_nth_frame=1)
                            png = None
                        else:
                            png = service.live_pause(cue_ms=cue, stage_ms=stage,
                                still_current=lambda: not self._stop.is_set()
                                    and generation == self._configuration_generation
                                    and sync_clock_generation == generation_of_clock())
                        self._metric("play" if playing else "seek", t0)
                        if not playing:
                            self.metrics[-1].update(getattr(service, 'last_live_pause_metrics', {}))
                        self.metrics[-1].update(sync_reason=sync_reason,drift_ms=drift_ms)
                        applied = (cue, stage, playing, rate, wall)
                        applied_clock_generation = sync_clock_generation
                        latest = self._resolve_time(started)
                        if self._stop.is_set() or generation != self._configuration_generation or latest is None:
                            continue
                        if sync_clock_generation != generation_of_clock():
                            applied=None
                            continue
                        # A pause/seek may have changed while CDP was in flight.
                        expected_now = cue + (time.perf_counter()-wall)*1000*rate if playing else cue
                        if latest[2] != playing or abs(latest[0]-expected_now) > 60:
                            continue
                        if png:
                            if not playing:paused_png=png
                            self.frame_ready.emit(WebFrame(png,id(self),content_key,generation,sync_clock_generation), cue, stage)
                        # Discard any frames from the state preceding sync.
                        seq, _ = service.live_latest(since_seq=0)
                    if playing:
                        t0 = time.perf_counter()
                        generation_of_clock = getattr(self._time_provider, 'discontinuity_generation', lambda: None)
                        clock_generation = generation_of_clock()
                        before_frame = self._resolve_time(started)
                        seq, png = service.live_latest(since_seq=seq)
                        if png and generation == self._configuration_generation and not self._stop.is_set():
                            current = self._resolve_time(started)
                            elapsed_ms=(time.perf_counter()-t0)*1000
                            clock_changed=clock_generation != generation_of_clock()
                            if clock_changed:
                                applied=None
                            if (current and before_frame and current[2] and current[3] == before_frame[3]
                                and not clock_changed
                                and abs(current[0]-(before_frame[0]+elapsed_ms*before_frame[3])) <= 60):
                                self.frame_ready.emit(WebFrame(png,id(self),content_key,generation,clock_generation), current[0], current[1])
                                self._metric("frame_transport", t0)
                                self.metrics[-1].update(getattr(service, 'last_live_frame_metrics', {}))
                    geometry_key=self._selection_geometry_request
                    if not playing and paused_png and geometry_key is not None:
                        self._selection_geometry_request=None
                        try:
                            measured=service._live_request({'type':'live_selection_geometry'},timeout=5)['geometry']
                            from .selection_geometry import alpha_bounds
                            measured['bounds']=alpha_bounds(paused_png,measured['subject_rect']) if measured.get('subject_rect') else None
                        except Exception as exc:
                            # Selection handles are ancillary. Their failure
                            # must never discard a ready animation page.
                            measured=dict(bounds=None,error=str(exc))
                            self.metrics.append(dict(phase='selection_geometry_error',message=str(exc),wall=time.monotonic()))
                        measured.update(renderer='html-live',worker_id=id(self),content_key=content_key,
                                        configuration_generation=generation,clock_generation=info_clock_generation)
                        if (generation==self._configuration_generation and not self._stop.is_set()
                                and generation_of_clock()==info_clock_generation):
                            self.selection_geometry_ready.emit(geometry_key,measured)
                    failures = 0
                    self._stop.wait(.005 if playing else .010)
                except RendererLiveRequestSuperseded:
                    self._metric('seek_superseded', t0)
                    applied = None
                    continue
                except Exception as exc:
                    if self._stop.is_set():
                        return
                    failures += 1
                    import traceback
                    self.metrics.append({"phase":"error", "message":str(exc), "wall":time.monotonic(),
                                         "traceback":traceback.format_exc()})
                    if failures >= _MAX_CONSECUTIVE_FAILURES:
                        self.failed.emit(str(exc))
                        return
                    loaded_theme = loaded_content = ""
                    self._stop.wait(.05)
        finally:
            try:
                service.close()
            except Exception:
                pass  # service shutdown already closes its page leases

    def _metric(self, phase, started):
        self.metrics.append({"phase":phase,"duration_ms":(time.perf_counter()-started)*1000,
                             "wall":time.monotonic()})
        if len(self.metrics)>600:
            del self.metrics[:-600]

    # ------------------------------------------------------------------
    # time resolution
    # ------------------------------------------------------------------

    def _resolve_time(self, started: float):
        """None (temporarily inactive) | (cue_ms, stage_ms, playing, rate)."""
        if self._time_provider is not None:
            value = self._time_provider()
            if value is None:
                return None
            if len(value) == 4:
                cue_ms, stage_ms, playing, rate = value
            else:
                cue_ms, stage_ms = value
                playing, rate = True, 1.0
            return float(cue_ms), float(stage_ms), bool(playing), float(rate or 1.0)
        loop_ms = max(0.2, float(self._loop_seconds or 2.4)) * 1000.0
        stage_ms = (time.perf_counter() - started) * 1000.0
        return stage_ms % loop_ms, stage_ms, True, 1.0
