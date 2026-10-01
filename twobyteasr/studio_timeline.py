"""Waveform timeline widget, ruler tick helpers, and inline cue editor."""

from __future__ import annotations

from .studio_track_header import ACTIONS, CONTROL_LEFT, action_at, button_rect, paint_button
from .playback_probe import ENABLED as PLAYBACK_PROBE_ENABLED, measured, mark as playback_mark

from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
    QRegion,
    QPolygonF,
    QTransform,
    QPen,
    QTextOption,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QScrollBar, QToolTip, QWidget

from .selection_scope import SelectionMode, SelectionScope
from .studio_commands import cue_by_id
from .studio_cue_table import _speaker_color, _speaker_name
from .studio_edit_sequence import runtime_of, sequence_of, timeline_duration_ms
from .studio_helpers import _format_ms
from .studio_project import StudioCue, SubtitleProject
from .studio_sequence_mapper import source_to_timeline
from .studio_timing import resolve_split
from .studio_video_track import (
    CANDIDATE_LANE_HEIGHT,
    VIDEO_TRACK_HEIGHT,
    VideoThumbnailCache,
    paint_candidate_lane,
    paint_markers,
    paint_project_video_track,
    paint_video_track,
    paint_video_track_header,
    video_track_header_action_at,
)
from .themed_icons import paint_cached_icon
from .timeline_theme import TimelinePalette, mix, rgba_color, timeline_palette
from .waveform_cache import WaveformCache, clip_waveform_cache_key
from .timeline_cue_gesture import CueInterval, preview_intervals

from .i18n import bind_text, tr

# Vertical waveform display scale. Buckets carry absolute float amplitude in
# [-1, 1]; the display maps |amplitude| through a fixed dBFS curve so the same
# audio keeps the same visual strength at every zoom level (no per-view AGC).
WAVEFORM_FLOOR_DB = 48.0


def waveform_db_heights(values, floor_db: float = WAVEFORM_FLOOR_DB):
    """Map bucket min/max amplitudes to display heights in [0, 1].

    1.0 (0 dBFS) draws at full amplitude, -floor_db and below draws flat.
    Digital silence (0.0) maps to 0 — genuinely silent stretches stay visibly
    silent while quiet-but-real speech (-30 dB or so) stays clearly visible.
    """
    import numpy as np

    magnitude = np.abs(values)
    db = 20.0 * np.log10(np.maximum(magnitude, 1e-5))
    return np.clip((db + float(floor_db)) / float(floor_db), 0.0, 1.0)


def adaptive_timeline_ticks(
    visible_duration_ms: int,
    content_width: int,
    *,
    target_label_px: int = 92,
) -> tuple[int, int]:
    """Return readable major/minor tick intervals for any timeline scale."""
    candidates = (
        100, 200, 500, 1_000, 2_000, 5_000, 10_000, 15_000, 30_000,
        60_000, 120_000, 300_000, 600_000, 900_000, 1_800_000,
        3_600_000, 7_200_000,
    )
    width = max(1, int(content_width))
    minimum = max(1, int(visible_duration_ms)) * target_label_px / width
    major = next((item for item in candidates if item >= minimum), candidates[-1])
    minor = max(20, major // (5 if major / max(minimum, 1) >= 1.8 else 2))
    return major, minor


def format_timeline_ruler_label(milliseconds: int, major_ms: int) -> str:
    value = max(0, int(milliseconds))
    total_seconds, millis = divmod(value, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    if major_ms < 1000:
        return f"{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}"


class _TimelineInlineEdit(QPlainTextEdit):
    commit_requested = Signal(int)
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._finished = False
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setTabChangesFocus(False)

    # Keep the small compatibility surface used by existing Studio tests and
    # integrations while the editor itself is now multiline and readable.
    def setText(self, value: str) -> None:
        self.setPlainText(str(value))

    def text(self) -> str:
        return self.toPlainText()

    def event(self, event) -> bool:
        # QWidget consumes Tab for focus traversal before keyPressEvent.
        if event.type() == QEvent.Type.KeyPress and event.key() in {
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
        }:
            self._finished = True
            backwards = (
                event.key() == Qt.Key.Key_Backtab
                or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
            self.commit_requested.emit(-1 if backwards else 1)
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finished = True
            self.commit_requested.emit(0)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._finished = True
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        if not self._finished:
            self._finished = True
            self.commit_requested.emit(0)
        super().focusOutEvent(event)


class WaveformTimeline(QWidget):
    cue_selected = Signal(str)
    seek_requested = Signal(float)
    scrub_finished = Signal(float)
    timing_changed = Signal(str, int, int)
    timing_preview_changed = Signal(object)
    timing_edit_started = Signal(object)
    timing_edit_committed = Signal(object)
    timing_edit_finished = Signal(bool)
    context_menu_requested = Signal(str, object)
    razor_split_requested = Signal(str, int)
    merge_pair_requested = Signal(str, str)
    video_razor_requested = Signal(int)
    video_clip_razor_requested = Signal(str, str, int)
    edit_blocked = Signal(str)
    video_lock_toggled = Signal()
    video_track_action_requested = Signal(str, str)
    video_track_reorder_requested = Signal(str, str)
    audio_track_action_requested = Signal(str, str)
    track_delete_requested = Signal(str, str)
    track_menu_requested = Signal(str, str, object)
    video_track_menu_requested = Signal(str, str, object)
    video_clip_selected = Signal(str, str)
    video_clip_move_committed = Signal(str, str, int)
    video_clip_reassign_committed = Signal(str, str, str, int)
    # 2026-09-06（四图反馈·图二）：主轨 segment 纵向拖上叠加轨=提取为独立片段。
    video_segment_lift_requested = Signal(str, str)
    # 四十八轮（用户"要更换V1和V2的轨道"+agy 语义判定）：拖片段跨到主轨泳道
    # =两条轨层级对调（等效轨道头换序），不是序列插入。
    video_track_swap_requested = Signal(str, str)
    video_clip_trim_committed = Signal(str, str, int, int)
    segment_selected = Signal(str)
    segment_selection_changed = Signal(object)
    candidate_clicked = Signal(str)
    text_edit_committed = Signal(str, bool, str)
    speaker_changed = Signal(str, str, str)
    selection_changed = Signal(object)
    interaction_changed = Signal(bool)
    subtitle_visibility_changed = Signal(str, bool)
    snap_changed = Signal(bool)

    TRACK_HEADER_WIDTH = 228
    RULER_HEIGHT = 34
    VIDEO_CLIP_TRIM_HANDLE_PX = 10.0

    SPEAKER_TRACK_HEIGHT = 48
    TRANSLATION_TRACK_HEIGHT = 44
    WAVEFORM_TRACK_HEIGHT = 52
    AUDIO_TRACK_HEIGHT = 36
    VIDEO_TRACK_HEIGHT = VIDEO_TRACK_HEIGHT
    CANDIDATE_LANE_HEIGHT = CANDIDATE_LANE_HEIGHT
    # 2026-09-18 VIII：三类轨高独立可调（右侧 rail + 泳道分界线拖动）。
    # 未设置 override 时保持既有默认（常量/说话人量化档位）。
    TRACK_HEIGHT_BOUNDS = {
        "video": (32, 240),      # 默认 58（VIDEO_TRACK_HEIGHT）
        "audio": (24, 200),      # 默认 36（AUDIO_TRACK_HEIGHT）
        "subtitle": (40, 200),   # 默认量化档位 52/68/84/96
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.project: SubtitleProject | None = None
        self.cache: WaveformCache | None = None
        self.waveform_caches: dict[str, WaveformCache] = {}
        self.waveform_clip_keys: dict[str, str] = {}
        self._timeline_palette_cache: TimelinePalette | None = None
        self.visible_start_ms = 0
        self.visible_duration_ms = 60_000
        self.playhead_ms = 0
        self.selected_id = ""
        self.selected_audio_track_id = ""
        self.selected_ids: set[str] = set()
        self.selection_scope = SelectionScope.empty()
        self.bilingual = False
        self.waveform_visible = True
        self.waveform_state = "EMPTY"
        self.waveform_message = ""
        self.hidden_speakers: set[str] = set()
        self.locked_speakers: set[str] = set()
        self.selected_track_header = None
        self.selected_gap = None
        self._hover_header_action: tuple[str, str] | None = None
        self._drag = None
        self._pan_drag = None
        self._track_resize_hover = False
        self._pan_drag_moved = False
        self._scrub_drag = False
        self.snap_enabled = True
        self._resize_hover = None
        self._snap_target = None
        self._snap_bypass = False
        self._snap_alt_held = False
        self._drag_preview: tuple[int, int] | None = None
        self._drag_speaker_preview = ""
        self._drag_originals: dict[str, CueInterval] = {}
        self._timing_preview: dict[str, CueInterval] = {}
        self._drag_origin_time = 0
        self._pending_timing_pointer = None
        self._timing_frame_timer = QTimer(self)
        self._timing_frame_timer.setSingleShot(True)
        self._timing_frame_timer.setInterval(0)
        self._timing_frame_timer.timeout.connect(self._flush_timing_preview)
        self.timing_preview_metrics = []
        self._marquee_origin: QPoint | None = None
        self._marquee_rect: QRectF | None = None
        self.tool_mode = "selection"
        # Razor/merge drag interaction state. The razor preview must show the
        # exact split the controller would commit, so both go through
        # resolve_split(); see _razor_preview / _merge_state. Hovering alone
        # never paints a preview (user feedback 2026-09-03: it reads as if the
        # cue had already been cut).
        self._razor_drag: dict[str, object] | None = None
        self._merge_anchor_id = ""
        self._merge_drag: dict[str, object] | None = None
        self.horizontal_scrollbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self.horizontal_scrollbar.setObjectName("timelineHorizontalScroll")
        self.horizontal_scrollbar.valueChanged.connect(self._horizontal_scrolled)
        self.vertical_scrollbar = QScrollBar(Qt.Orientation.Vertical, self)
        self.vertical_scrollbar.setObjectName("timelineTrackScroll")
        self.vertical_scrollbar.valueChanged.connect(lambda _value: self.update())
        self._inline_editor: _TimelineInlineEdit | None = None
        self._inline_target: tuple[str, bool] | None = None
        self._cues_by_start: list[StudioCue] = []
        self._timeline_cue_by_id: dict[str, StudioCue] = {}
        self._timeline_row_by_id: dict[str, int] = {}
        self._cue_starts: list[int] = []
        self._cue_prefix_max_ends: list[int] = []
        self._speaker_ids: list[str] = []
        self._project_duration_ms = 0
        self._text_layout_cache: dict[tuple, str] = {}
        self._visible_cue_window_key: tuple[int, int] | None = None
        self._visible_cue_window: list[StudioCue] = []
        self._dense_cue_span_cache: dict[
            tuple[int, int, int, tuple[str, ...]],
            dict[str, tuple[tuple[int, int], ...]],
        ] = {}
        self.selected_segment_id = ""
        self.selected_segment_ids: set[str] = set()
        self.selected_video_track_id = ""
        self.selected_video_clip_id = ""
        self._clip_drag: dict[str, object] | None = None
        self._clip_scroll_timer = QTimer(self)
        self._clip_scroll_timer.setInterval(30)
        self._clip_scroll_timer.timeout.connect(self._scroll_clip_drag)
        self._segment_drag: dict[str, object] | None = None
        self._track_reorder_drag: dict[str, object] | None = None
        self.thumbnail_requests_enabled = True
        from .video_filmstrip import FilmstripCache
        self.filmstrip_visible = True
        self._thumbnails = FilmstripCache(self)
        self.interaction_changed.connect(lambda active:self._thumbnails.set_interacting(active))
        self._thumbnails.updated.connect(lambda _key: self.update())
        from .transport_cursor_overlay import TransportCursorOverlay
        self._transport_overlay = TransportCursorOverlay(self)

        # 2026-09-18 VIII：三类轨高独立可调（右侧控制区边界把手 + 泳道
        # 分界线拖动；2026-09-19 P1 整合为滚动条列内的矮把手，无独立 rail）。
        self._track_height_overrides: dict[str, int] = {}
        self._track_resize_drag: dict | None = None
        self._track_resize_hover_kind = ""

    # ---------------------------------------------------- track heights (VIII)
    def _video_track_height(self) -> int:
        override = self._track_height_overrides.get("video")
        return int(override) if override else VIDEO_TRACK_HEIGHT

    def _audio_track_height(self) -> int:
        override = self._track_height_overrides.get("audio")
        return int(override) if override else self.AUDIO_TRACK_HEIGHT

    def track_heights(self) -> dict[str, int]:
        return dict(self._track_height_overrides)

    def set_track_heights(self, heights: dict) -> None:
        for kind in self.TRACK_HEIGHT_BOUNDS:
            value = heights.get(kind) if isinstance(heights, dict) else None
            if value:
                self._track_height_overrides[kind] = self._clamp_track_height(kind, int(value))
            else:
                self._track_height_overrides.pop(kind, None)
        self._apply_track_heights_changed()

    def set_track_height(self, kind: str, height: int) -> None:
        if kind not in self.TRACK_HEIGHT_BOUNDS:
            return
        clamped = self._clamp_track_height(kind, int(height))
        if self._track_height_overrides.get(kind) == clamped:
            return
        self._track_height_overrides[kind] = clamped
        self._apply_track_heights_changed()

    def _clamp_track_height(self, kind: str, height: int) -> int:
        minimum, maximum = self.TRACK_HEIGHT_BOUNDS[kind]
        return max(minimum, min(maximum, int(height)))

    def _reset_track_height_kind(self, kind: str = "") -> None:
        for key in ([kind] if kind else list(self.TRACK_HEIGHT_BOUNDS)):
            self._track_height_overrides.pop(key, None)
        self._apply_track_heights_changed()

    def _apply_track_heights_changed(self) -> None:
        # 波形包络缓存键含 rect.height()，轨高变化自动换键，无需手动失效；
        # 缩略图 LOD 只在跨档时换 key，绘制端有粗格兜底缩放显示，不重抽帧。
        self._sync_track_minimum_height()
        self._sync_scrollbars()
        self.update()

    # ---------------------------------------------------- 右侧统一控制区（2026-09-19 P1）
    # 右缘只保留一条窄控制区=纵向滚动条所在的列。滚动滑块承担滚动；
    # 泳道分界处的矮把手（画在滚动条列内、与实际边界对齐）承担轨高
    # 调整——无第二列、无叠放控件、无常驻文字；V1/A1/S00 等轨头标识
    # 在左侧轨头列不受影响。字幕边界位于滚动条覆盖段内时，该处仍由
    # 画布内分界线拖动入口承担（同一套轨高状态）。
    def _track_height_strip_width(self) -> int:
        return self.vertical_scrollbar.sizeHint().width()

    def _track_height_boundaries(self) -> list[tuple[str, float]]:
        """泳道分界（kind, y）：调"分界线上方那条轨"（Premiere 语义）。"""
        boundaries: list[tuple[str, float]] = []
        for rect in self._video_track_rects().values():
            boundaries.append(("video", rect.bottom()))
        for rect in self._audio_track_rects().values():
            boundaries.append(("audio", rect.bottom()))
        viewport = self._track_viewport()
        if viewport.height() > 0:
            boundaries.append(("subtitle", viewport.bottom()))
        return boundaries

    def _track_resize_boundary_at(self, point: QPoint) -> tuple[str, float] | None:
        """泳道分界线命中（含右侧控制区列与画布任意位置）。"""
        if point.x() < self.TRACK_HEADER_WIDTH:
            return None
        for kind, y in self._track_height_boundaries():
            if abs(point.y() - y) <= 6:
                return kind, y
        return None

    def _paint_track_height_grips(self, painter: QPainter, palette: TimelinePalette) -> None:
        """滚动条列内的边界把手：平时低对比度，悬停/拖动适度强调。"""
        strip = self._track_height_strip_width()
        x0 = self.width() - strip
        if x0 <= self.TRACK_HEADER_WIDTH:
            return
        drag = self._track_resize_drag
        drag_kind = str(drag["kind"]) if drag else ""
        hover_kind = self._track_resize_hover_kind or ""
        for kind, y in self._track_height_boundaries():
            emphasized = kind == hover_kind or kind == drag_kind
            color = QColor(palette.playhead) if emphasized else mix(
                QColor(palette.header), QColor(palette.header_name), 0.38
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            grip = QRectF(x0 + 1.5, y - 1.5, strip - 3.0, 3.0)
            painter.drawRoundedRect(grip, 1.5, 1.5)

    def _timeline_palette(self) -> TimelinePalette:
        if self._timeline_palette_cache is None:
            self._timeline_palette_cache = timeline_palette()
        return self._timeline_palette_cache

    def refresh_theme_palette(self) -> None:
        """Called by apply_application_theme after a theme switch."""
        self._timeline_palette_cache = None
        self.update()

    def _duration_ms(self) -> int:
        drag = getattr(self, '_clip_drag', None)
        return max(self._project_duration_ms, int(drag.get('extent_ms', 0)) if drag else 0)

    def _bounded_time_ms(self, milliseconds: float | int) -> int:
        """所有指针→时间定位的唯一边界：0 ≤ t ≤ 工程时长。

        2026-09-18 P1：拖拽/点击把 x 线性外推到视口右缘之外（一次宽甩即
        +N 小时），playhead_ms 无上界 → 1.5h 工程被拖到 3h+。工程时长 =
        max(序列/视频片段/cue)——合法的更晚内容（片段超出主轨）仍可延长；
        无工程（duration=0）保持原行为不设上界。
        """
        value = max(0, int(milliseconds))
        duration = self._duration_ms()
        if duration > 0:
            value = min(value, duration)
        return value

    def _waveform_pairs(self, content_width: int):
        start = self.visible_start_ms
        end = self.visible_start_ms + self.visible_duration_ms
        sequence = sequence_of(self.project) if self.project else None
        if sequence is None or sequence.is_linear_source():
            return self.cache.read_window(start, end, content_width)
        import numpy as np
        duration = max(1, end - start)
        chunks = []
        runtime = runtime_of(self.project) if self.project else None
        visible_segments = (
            runtime.visible_segments(start, end) if runtime is not None
            else tuple(sequence.segments)
        )
        for segment in visible_segments:
            overlap_in = max(start, segment.timeline_in_ms)
            overlap_out = min(end, segment.timeline_out_ms)
            if overlap_out <= overlap_in:
                continue
            source_in = segment.source_in_ms + (overlap_in - segment.timeline_in_ms)
            source_out = segment.source_in_ms + (overlap_out - segment.timeline_in_ms)
            pixels = max(1, round(content_width * (overlap_out - overlap_in) / duration))
            _level, pairs = self.cache.read_window(source_in, source_out, pixels)
            if len(pairs):
                chunks.append(pairs)
        if not chunks:
            return self.cache.read_window(0, 1, 1)
        return None, np.concatenate(chunks, axis=0)

    def _rebuild_cue_index(self) -> None:
        # 2026-09-19 P0：时间轴字幕索引消费当前活动序列的投影视图
        # （identity=源列表直通；剪辑=派生 cue+序列时间）。源全集在
        # project.cues 中永不被剪辑操作改写。
        if self.project:
            from .studio_edit_sequence import projected_cues

            view_cues = projected_cues(self.project, domain="timeline")
        else:
            view_cues = []
        cues = sorted(view_cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
        self._cues_by_start = cues
        self._timeline_cue_by_id = {cue.id: cue for cue in cues}
        self._timeline_row_by_id = {
            cue.id: row for row, cue in enumerate(cues)
        }
        self._cue_starts = [cue.start_ms for cue in cues]
        self._cue_prefix_max_ends = []
        maximum_end = 0
        for cue in cues:
            maximum_end = max(maximum_end, cue.end_ms)
            self._cue_prefix_max_ends.append(maximum_end)
        speaker_ids = list(dict.fromkeys([*(s.id for s in self.project.speakers)] + [cue.speaker_id for cue in cues])) if self.project else []
        if self.project:
            saved_order = self.project.studio_state.get("speaker_track_order", [])
            metrics = {
                speaker_id: (
                    sum(max(0, cue.end_ms - cue.start_ms) for cue in cues if cue.speaker_id == speaker_id),
                    sum(1 for cue in cues if cue.speaker_id == speaker_id),
                )
                for speaker_id in speaker_ids
            }
            saved_ids = [str(item) for item in saved_order] if isinstance(saved_order, list) else []
            saved_metrics = [metrics[item] for item in saved_ids if item in metrics]
            if saved_ids:
                self._speaker_ids = list(dict.fromkeys([key for key in saved_ids if key in speaker_ids]+speaker_ids))
            else:
                # Keep the primary speaker closest to the waveform. The
                # busiest track is therefore last; ties remain cue-count
                # stable through the same duration/count ranking.
                self._speaker_ids = sorted(speaker_ids, key=lambda item: metrics[item])
                self.project.studio_state["speaker_track_order"] = list(self._speaker_ids)
        else:
            self._speaker_ids = speaker_ids
        sequence_duration = timeline_duration_ms(self.project) if self.project else 0
        media_duration = max(
            (
                clip.timeline_out_ms
                for track in self.project.video_tracks
                for clip in track.clips
            ),
            default=0,
        ) if self.project else 0
        # Source-domain subtitles must never extend an authored edit back to
        # the original recording's duration. Subtitle-only projects retain it.
        has_media = bool(self.project and (self.project.video_tracks or self.project.audio_tracks))
        self._project_duration_ms = max(sequence_duration, media_duration) if has_media else maximum_end
        self._text_layout_cache.clear()
        self._visible_cue_window_key = None
        self._visible_cue_window = []
        self._dense_cue_span_cache.clear()

    def _cues_intersecting(self, start_ms: int, end_ms: int) -> list[StudioCue]:
        if not self._cues_by_start or end_ms <= start_ms:
            return []
        left = bisect_right(self._cue_prefix_max_ends, int(start_ms))
        right = bisect_left(self._cue_starts, int(end_ms))
        result = [cue for cue in self._cues_by_start[left:right]
                  if cue.end_ms > start_ms and cue.id not in self._timing_preview]
        for cue_id, value in self._timing_preview.items():
            cue = self._timeline_cue_by_id.get(cue_id)
            if cue is not None and value.end_ms > start_ms and value.start_ms < end_ms:
                result.append(replace(cue, start_ms=value.start_ms, end_ms=value.end_ms,
                                      speaker_id=value.speaker_id))
        return result

    def visible_cues(self) -> list[StudioCue]:
        key = (
            int(self.visible_start_ms),
            int(self.visible_start_ms + self.visible_duration_ms),
        )
        if key != self._visible_cue_window_key:
            self._visible_cue_window_key = key
            self._visible_cue_window = self._cues_intersecting(*key)
        return self._visible_cue_window

    def invalidate_cue(self, cue_id: str, *, timing: bool = False) -> None:
        cue_id = str(cue_id)
        self._text_layout_cache = {
            key: value for key, value in self._text_layout_cache.items() if key[0] != cue_id
        }
        if timing:
            self._rebuild_cue_index()
            self._sync_scrollbars()
        cue = self._timeline_cue_by_id.get(cue_id)
        ranges = ((cue.start_ms, cue.end_ms),) if cue is not None else ()
        self.invalidate_ranges(ranges, {cue_id})

    def invalidate_ranges(
        self,
        ranges: Iterable[tuple[int, int]],
        cue_ids: Iterable[str] = (),
    ) -> None:
        speaker_rects, translation_rect, _waveform = self._track_layout()
        ids = {str(item) for item in cue_ids if str(item)}
        speakers = {
            self._timeline_cue_by_id[cue_id].speaker_id
            for cue_id in ids
            if cue_id in self._timeline_cue_by_id
        }
        tracks = [speaker_rects[item] for item in speakers if item in speaker_rects]
        if translation_rect is not None:
            tracks.append(translation_rect)
        vertical = QRectF()
        for track in tracks:
            vertical = track if vertical.isEmpty() else vertical.united(track)
        if vertical.isEmpty():
            vertical = self._track_viewport()
        dirty = QRectF()
        for start_ms, end_ms in ranges:
            left = self._time_to_x(int(start_ms)) - 8
            right = self._time_to_x(int(end_ms)) + 8
            item = QRectF(left, vertical.top(), max(16.0, right - left), vertical.height())
            dirty = item if dirty.isEmpty() else dirty.united(item)
        if dirty.isEmpty():
            dirty = vertical
        clipped = dirty.intersected(QRectF(self.rect())).toAlignedRect()
        if not clipped.isEmpty():
            self.update(clipped)

    def reindex_project(self, *, repaint: bool = True) -> None:
        self._rebuild_cue_index()
        self._sync_track_minimum_height()
        self._sync_scrollbars()
        if repaint:
            self.update()

    def _content_right(self) -> int:
        return max(self.TRACK_HEADER_WIDTH + 1, self.width() - self.vertical_scrollbar.width())

    def _canvas_bottom(self) -> int:
        return max(self.RULER_HEIGHT + 1, self.height() - (self.horizontal_scrollbar.height() if self.horizontal_scrollbar.isVisible() else 0))

    def _candidate_lane_visible(self) -> bool:
        sequence = sequence_of(self.project) if self.project else None
        return bool(sequence is not None and sequence.clip_candidates)

    def _pinned_bottom_height(self) -> int:
        track_count = len(self.project.video_tracks) if self.project else 1
        height = track_count * self._video_track_height()
        if self.waveform_visible:
            height += (len(self.project.audio_tracks) if self.project else 1) * self._audio_track_height()
        if self._candidate_lane_visible():
            height += CANDIDATE_LANE_HEIGHT
        return height

    def _sync_track_minimum_height(self) -> None:
        # Keep every pinned video lane below the scrollable subtitle viewport.
        # Clamping each lane to the ruler made V2/V3 paint over S01/S02.
        # 字幕区自带纵向滚动，其最小高度不随用户调高的说话人行高增长
        # （否则大轨高会把整个时间轴 widget 的最小高度撑爆）。
        subtitle_minimum = max(
            56,
            max(1, len(self.speaker_ids())) * 52
            + (44 if self.bilingual else 0),
        )
        minimum = (
            self.RULER_HEIGHT
            + self._pinned_bottom_height()
            + subtitle_minimum
        )
        self.setMinimumHeight(max(180, minimum))

    def _video_track_rects(self) -> dict[str, QRectF]:
        bottom = self._canvas_bottom()
        if self._candidate_lane_visible():
            bottom -= CANDIDATE_LANE_HEIGHT
        video_height = self._video_track_height()
        tracks = list(self.project.video_tracks) if self.project and self.project.video_tracks else []
        track_ids = [track.id for track in tracks] if self.project else ["V1"]
        group_height = video_height + (self._audio_track_height() if self.waveform_visible else 0)
        linked_audio = {g.audio_track_id for g in self.project.av_track_groups if g.video_track_id} if self.project else set()
        standalone = sum(t.id not in linked_audio for t in self.project.audio_tracks) if self.project and self.waveform_visible else 0
        y = bottom - len(track_ids) * group_height - standalone*self._audio_track_height()
        if y < self.RULER_HEIGHT:
            # Never collapse extra lanes onto V1. Grow downward from the ruler
            # when the widget is still catching up to setMinimumHeight.
            y = self.RULER_HEIGHT
        # 四十五轮：泳道顺序与渲染层级一致（Premiere 语义）——z 序越高的
        # 轨道（列表越靠后）画在越上面的泳道，V1 永远是最底泳道。此前
        # V1 顶/V2 底与"V2 盖在 V1 上"的合成顺序相反，跨轨拖拽的方向
        # 直觉全反（用户实录"想把 V2 的视频移到 V1 上方却没反应"）。
        ordered_ids = list(reversed(track_ids))
        return {
            track_id: QRectF(
                0,
                y + index * group_height,
                self.width(),
                video_height,
            )
            for index, track_id in enumerate(ordered_ids)
        }

    def _audio_track_rects(self) -> dict[str, QRectF]:
        if not self.waveform_visible:
            return {}
        audio_height = self._audio_track_height()
        video_rects = self._video_track_rects()
        if not self.project:
            primary = video_rects.get("V1", QRectF())
            return {"A1": QRectF(0, primary.bottom(), self.width(), audio_height)}
        audio_by_video = {
            group.video_track_id: group.audio_track_id
            for group in self.project.av_track_groups
            if group.video_track_id and group.audio_track_id
        }
        result = {
            audio_by_video.get(video_id, f"A{index + 1}"): QRectF(
                0,
                rect.bottom(),
                self.width(),
                audio_height,
            )
            for index, (video_id, rect) in enumerate(video_rects.items())
        }
        standalone = [t for t in self.project.audio_tracks if t.id not in audio_by_video.values()]
        bottom = self._canvas_bottom() - (CANDIDATE_LANE_HEIGHT if self._candidate_lane_visible() else 0)
        for index,track in enumerate(standalone):
            result[track.id] = QRectF(0,bottom-(len(standalone)-index)*audio_height,self.width(),audio_height)
        return result

    def _audio_track_at(self, point: QPoint) -> str:
        for track_id, rect in self._audio_track_rects().items():
            if rect.contains(point):
                return track_id
        return ""

    @staticmethod
    def _audio_header_action_at(x: float, y=None, row=None) -> str:
        return action_at('audio', x, y, row)

    def _video_track_rect(self, track_id: str = "") -> QRectF:
        rects = self._video_track_rects()
        if track_id and track_id in rects:
            return rects[track_id]
        if self.project:
            from .studio_media_pool import primary_video_track_id

            primary_id = primary_video_track_id(self.project)
            if primary_id in rects:
                return rects[primary_id]
        return next(iter(rects.values()), QRectF())

    def _video_tracks_rect(self) -> QRectF:
        rects = list(self._video_track_rects().values())
        if not rects:
            return QRectF()
        return QRectF(
            rects[0].left(),
            rects[0].top(),
            rects[0].width(),
            rects[-1].bottom() - rects[0].top(),
        )

    def _video_track_at(self, point: QPoint) -> str:
        for track_id, rect in self._video_track_rects().items():
            if rect.contains(point):
                return track_id
        return ""

    def _clip_drag_preview(self) -> dict[str, tuple[int, int]]:
        drag = self._clip_drag
        if not drag:
            return {}
        clip_id = str(drag.get("clip_id") or "")
        if not clip_id:
            return {}
        preview = {clip_id: (int(drag["preview_in"]), int(drag["preview_out"]))}
        if drag['mode'] == 'move':
            delta = int(drag['preview_in']) - int(drag['origin_in'])
            preview.update({key:(a+delta,b+delta) for key,(a,b) in drag.get('group_intervals',{}).items()})
        return preview

    def _begin_video_drag(self, track_id, clip, event):
        from .studio_clip_edit import trim_bounds
        from .studio_media_pool import asset_by_id
        x = event.position().x()
        distance, edge = min((abs(x-self._time_to_x(clip.timeline_in_ms)), 'trim_left'),
                             (abs(x-self._time_to_x(clip.timeline_out_ms)), 'trim_right'))
        mode = edge if distance <= self.VIDEO_CLIP_TRIM_HANDLE_PX else 'move'
        low, high = trim_bounds(clip, asset_by_id(self.project, clip.asset_id).duration_ms)
        self._snap_target = None
        self._clip_drag = dict(track_id=track_id, clip_id=clip.id, mode=mode,
            origin_x=x, origin_y=event.position().y(), origin_in=clip.timeline_in_ms,
            origin_out=clip.timeline_out_ms, origin_source_in=clip.source_in_ms,
            origin_source_out=clip.source_out_ms, preview_in=clip.timeline_in_ms,
            preview_out=clip.timeline_out_ms, min_in=low, max_out=high,
            target_track_id=track_id, swap_target_id='', moved=False,
            origin_pointer_ms=self._x_to_time(x), pointer=QPointF(event.position()), modifiers=Qt.NoModifier)
        self._clip_drag['group_intervals'] = {c.id:(c.timeline_in_ms,c.timeline_out_ms)
            for t in self.project.video_tracks if t.id == track_id for c in t.clips
            if c.id in self.selected_segment_ids and mode == 'move'}
        self.interaction_changed.emit(True)

    def _update_clip_drag(self, point, modifiers):
        drag = self._clip_drag
        if not drag:
            return
        started = perf_counter()
        drag['pointer'], drag['modifiers'] = QPointF(point), modifiers
        delta = self._x_to_time(point.x()) - drag['origin_pointer_ms']
        origin_in, origin_out = drag['origin_in'], drag['origin_out']
        if (abs(point.x() - drag['origin_x']) >= QApplication.startDragDistance()
                or abs(point.y() - drag['origin_y']) >= QApplication.startDragDistance()):
            drag['moved'] = True
        mode = drag['mode']
        target = drag['track_id']
        if mode == 'move':
            earliest = min((a for a, b in drag['group_intervals'].values()), default=origin_in)
            start = origin_in + max(-earliest, delta)
            end = start + origin_out - origin_in
            target = self._video_track_at(point.toPoint())
            if not target:
                audio_id = self._audio_track_at(point.toPoint())
                target = next((g.video_track_id for g in self.project.av_track_groups
                               if g.audio_track_id == audio_id), '')
        elif mode == 'trim_left':
            start, end = min(origin_out - 1, max(drag['min_in'], origin_in + delta)), origin_out
        else:
            start, end = origin_in, min(drag['max_out'], max(origin_in + 1, origin_out + delta))
        drag['target_track_id'] = target
        self._snap_bypass = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        start, end = self._snap_video_interval(start, end, drag)
        drag['preview_in'], drag['preview_out'] = start, end
        key = (target, start, end, tuple(sorted(self.locked_speakers)))
        if key != drag.get('preview_key'):
            drag['preview_key'] = key
            try:
                if not target:
                    raise ValueError('请放到视频轨道或其关联音频行；移出泳道将取消')
                from .studio_clip_edit import preview_clip_edit
                drag['snapshot'] = preview_clip_edit(self.project, drag, self.locked_speakers)
                drag['invalid'] = ''
            except (ValueError, KeyError) as exc:
                drag['snapshot'] = None
                drag['invalid'] = str(exc)
        self.setCursor(Qt.CursorShape.ForbiddenCursor if drag.get('invalid') else Qt.CursorShape.ClosedHandCursor)
        self.setToolTip(str(drag.get('invalid') or ''))
        at_edge = point.x() < self.TRACK_HEADER_WIDTH + 24 or point.x() > self._content_right() - 24
        if drag['moved'] and at_edge:
            self._clip_scroll_timer.start()
        else:
            self._clip_scroll_timer.stop()
        drag.setdefault('update_ms', []).append((perf_counter() - started) * 1000)
        self.update()

    def _scroll_clip_drag(self):
        drag = self._clip_drag
        if not drag:
            self._clip_scroll_timer.stop()
            return
        x = drag['pointer'].x()
        direction = -1 if x < self.TRACK_HEADER_WIDTH + 24 else 1 if x > self._content_right() - 24 else 0
        if not direction:
            self._clip_scroll_timer.stop()
            return
        start = max(0, self.visible_start_ms + direction * max(1, round(self.visible_duration_ms * .015)))
        # Moving beyond the current project tail must be possible. This extent
        # belongs only to the drag viewport, never the persisted timeline.
        drag['extent_ms'] = max(self._duration_ms(), start + self.visible_duration_ms)
        self.set_visible_window(start, self.visible_duration_ms)

    def _snap_video_interval(self, start, end, drag):
        """One logical-pixel threshold, one shared displacement, integer ms."""
        held = self._snap_target
        self._snap_target = None
        if not self.snap_enabled or self._snap_bypass:
            return start, end
        threshold = 8.0 * self.visible_duration_ms / max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
        moving_ids = set(drag.get('group_intervals', {})) | {drag['clip_id']}
        candidates = [(0, '时间轴零点'), (self.playhead_ms, '播放头')]
        for track in [*self.project.video_tracks, *self.project.audio_tracks]:
            for clip in track.clips:
                if clip.id in moving_ids or getattr(clip, 'linked_video_clip_id', '') in moving_ids:
                    continue
                candidates.extend(((clip.timeline_in_ms, f'{track.id} 片段开头'), (clip.timeline_out_ms, f'{track.id} 片段结尾')))
        candidates.extend((m.time_ms, f'标记 {m.label}') for m in sequence_of(self.project).markers)
        from .studio_media_pool import primary_video_track_id
        primary_drag = drag['track_id'] == primary_video_track_id(self.project)
        for cue in self.visible_cues():
            if any(cue.id.endswith('#' + key) for key in moving_ids) or (primary_drag and sequence_of(self.project).is_identity()):
                continue
            candidates.extend(((cue.start_ms, '字幕开头'), (cue.end_ms, '字幕结尾')))
        mode = drag['mode']
        edges = [('left', start), ('right', end)] if mode == 'move' else [('left', start)] if mode == 'trim_left' else [('right', end)]
        target_id = (drag.get('target_track_id') or drag['track_id']) if mode == 'move' else drag['track_id']
        track = next(t for t in self.project.video_tracks if t.id == target_id)
        def legal(a, b):
            if a < 0 or b <= a or (mode != 'move' and (a < drag['min_in'] or b > drag['max_out'])):
                return False
            delta = a - drag['origin_in']
            intervals = [(a,b)]
            if mode == 'move':
                intervals = [(x+delta,y+delta) for x,y in drag.get('group_intervals',{}).values()] or intervals
            return all(x >= 0 and not any(c.id not in moving_ids and x < c.timeline_out_ms and y > c.timeline_in_ms for c in track.clips) for x,y in intervals)
        options = []
        for edge, value in edges:
            for target, label in candidates:
                if not self.visible_start_ms <= target <= self.visible_start_ms + self.visible_duration_ms:
                    continue
                delta = target - value
                stable = bool(held and held['time'] == target and held.get('moving_edge') == edge)
                if abs(delta) > threshold * (1.5 if stable else 1):
                    continue
                a = start + delta if mode == 'move' or edge == 'left' else start
                b = end + delta if mode == 'move' or edge == 'right' else end
                if legal(a, b):
                    options.append((not stable, abs(delta), target, edge, label, a, b))
        if options:
            _, _, target, edge, label, start, end = min(options)
            self._snap_target = dict(time=target, label=label, cue_id='', edge='', moving_edge=edge)
        return start, end

    def _video_clip_at(self, track_id: str, timeline_ms: int):
        if not self.project:
            return None
        track = next(
            (item for item in self.project.video_tracks if item.id == track_id),
            None,
        )
        if track is None:
            return None
        return next(
            (
                clip
                for clip in reversed(track.clips)
                if clip.timeline_in_ms <= timeline_ms < clip.timeline_out_ms
            ),
            None,
        )

    def _candidate_lane_rect(self) -> QRectF | None:
        if not self._candidate_lane_visible():
            return None
        bottom = self._canvas_bottom()
        y = bottom - CANDIDATE_LANE_HEIGHT
        return QRectF(0, max(self.RULER_HEIGHT, y), self.width(), CANDIDATE_LANE_HEIGHT)

    def _track_viewport(self) -> QRectF:
        pinned = self._pinned_bottom_height()
        return QRectF(
            0,
            self.RULER_HEIGHT,
            self._content_right(),
            max(0, self._canvas_bottom() - self.RULER_HEIGHT - pinned),
        )

    def _sync_scrollbars(self) -> None:
        duration = self._duration_ms()
        maximum = max(0, duration - self.visible_duration_ms,
                      min(duration, getattr(self, '_page_tail_start_ms', 0)))
        self.horizontal_scrollbar.blockSignals(True)
        self.horizontal_scrollbar.setRange(0, maximum)
        self.horizontal_scrollbar.setPageStep(min(duration, self.visible_duration_ms))
        self.horizontal_scrollbar.setSingleStep(max(50, self.visible_duration_ms // 20))
        self.horizontal_scrollbar.setValue(min(maximum, self.visible_start_ms))
        self.horizontal_scrollbar.setVisible(maximum > 0)
        self.horizontal_scrollbar.blockSignals(False)

        track_height = len(self.speaker_ids()) * self._speaker_track_height()
        if self.bilingual:
            track_height += self.TRANSLATION_TRACK_HEIGHT
        track_maximum = max(0, track_height - round(self._track_viewport().height()))
        self.vertical_scrollbar.setRange(0, track_maximum)
        self.vertical_scrollbar.setPageStep(max(1, round(self._track_viewport().height())))
        # 2026-09-19 P1：右缘统一控制区常驻——无纵向溢出（单轨）时滚动
        # 条也保持可见，轨高把手不因滚动范围消失而失去入口。
        self.vertical_scrollbar.setVisible(True)
        scrollbar_height = self.horizontal_scrollbar.sizeHint().height()
        scrollbar_width = self.vertical_scrollbar.sizeHint().width()
        self.horizontal_scrollbar.setGeometry(
            self.TRACK_HEADER_WIDTH,
            self.height() - scrollbar_height,
            max(0, self.width() - self.TRACK_HEADER_WIDTH - scrollbar_width),
            scrollbar_height,
        )
        self.vertical_scrollbar.setGeometry(
            self.width() - scrollbar_width,
            self.RULER_HEIGHT,
            scrollbar_width,
            max(0, self._canvas_bottom() - self.RULER_HEIGHT - self._pinned_bottom_height()),
        )

    def _horizontal_scrolled(self, value: int) -> None:
        self._follow_suspended_until = perf_counter() + 2.0
        self.visible_start_ms = int(value)
        self.update()

    def set_visible_window(self, start_ms: int, duration_ms: int) -> None:
        duration = self._duration_ms()
        visible_duration = min(max(1000, int(duration_ms)), max(1000, duration or int(duration_ms)))
        maximum = max(0, duration - visible_duration,
                      min(duration, getattr(self, '_page_tail_start_ms', 0)))
        visible_start = min(maximum, max(0, int(start_ms)))
        changed = (
            visible_duration != self.visible_duration_ms
            or visible_start != self.visible_start_ms
        )
        self.visible_duration_ms = visible_duration
        self.visible_start_ms = visible_start
        self._sync_scrollbars()
        if changed:
            if self._clip_drag and self._clip_drag.get('pointer') is not None:
                self._update_clip_drag(self._clip_drag['pointer'], self._clip_drag['modifiers'])
            self.update()

    def reveal_playhead(self, milliseconds: int, *, force: bool = False) -> bool:
        left = self.visible_start_ms
        right = left + self.visible_duration_ms
        # 2026-09-02 修复（倍速跳变风暴）：旧参数把跳变后的播头放在窗口 72%
        # 处，而触发阈值是 76%——只剩 4% 余量，4x/缩放窗口下每零点几秒就
        # 跳一次（真机实测 10s 内 35 次视窗跳变=「一跳一跳的闪烁」）。
        # 阈值后移到 85%、落位 30%，跳一次留 55% 窗口的跑道。
        threshold = left + round(self.visible_duration_ms * 0.85)
        if not force and left <= milliseconds <= threshold:
            return False
        target = milliseconds - round(self.visible_duration_ms * (0.18 if milliseconds < left else 0.30))
        self.set_visible_window(target, self.visible_duration_ms)
        return True

    def _viewport_manipulated(self) -> bool:
        return bool(getattr(self, '_scrub_drag', False) or getattr(self, '_pan_drag', None)
            or any(getattr(self, attr, None) for attr in ('_drag', '_clip_drag', '_segment_drag',
                '_track_reorder_drag', '_track_resize_drag', '_razor_drag', '_merge_drag'))
            or self.horizontal_scrollbar.isSliderDown()
            or perf_counter() < getattr(self, '_follow_suspended_until', 0))

    def page_playhead(self, milliseconds: int) -> bool:
        """Reveal only on overflow, anchored to the actual content left edge."""
        if self._viewport_manipulated():
            return False
        x = self._time_to_x(milliseconds)
        if self.TRACK_HEADER_WIDTH - .5 <= x < self._content_right():
            return False
        target = max(0, min(int(milliseconds), self._duration_ms()))
        self._page_tail_start_ms = target
        before = self.visible_start_ms
        self.set_visible_window(target, self.visible_duration_ms)
        return self.visible_start_ms != before

    def follow_playing_playhead(self, milliseconds: int) -> bool:
        """播放态连续跟随：播头锚定视口 ~35%，按 tick 微滚视口。

        2026-09-18 III：翻页跟随（85% 阈值/30% 落位）在放大的视口（约
        10-12s 宽）下每 ~6s 跳一页——用户感知为"时间轴每 6 秒才更新一次，
        没有实时跟随"。播放期间视口与播头一起平推（每 tick 一步 tick 步长，
        复用字幕布局、文本及波形缓存）。暂停/seek 仍走 reveal 翻页
        （单次跳转），用户抓取滚动条/平移时不抢回。
        """
        if self._viewport_manipulated():
            return False
        anchor = round(self.visible_duration_ms * 0.35)
        target_left = int(milliseconds) - anchor
        # 0.4% was ~5 pixels on a typical viewport, not a subpixel. It caused
        # seconds of stalled scrolling when zoomed out. Let Qt coalesce paints.
        if target_left == self.visible_start_ms:
            return False
        self.set_visible_window(target_left, self.visible_duration_ms)
        return True

    def set_tool_mode(self, mode: str) -> None:
        self.selected_gap = None
        normalized = mode if mode in {"razor", "merge"} else "selection"
        if normalized == self.tool_mode:
            return
        had_preview_state = (
            self._razor_drag is not None
            or self._merge_drag is not None
            or bool(self._merge_anchor_id)
        )
        self.tool_mode = normalized
        self._razor_drag = None
        self._merge_drag = None
        self._merge_anchor_id = ""
        cursor = (
            Qt.CursorShape.CrossCursor if normalized == "razor"
            else Qt.CursorShape.PointingHandCursor if normalized == "merge"
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)
        if had_preview_state:
            # Clear any leftover cut line / anchor highlight from the tool.
            self.update()

    def set_project(self, project: SubtitleProject | None) -> None:
        self._page_tail_start_ms = 0
        self.selected_gap = None
        if project is not self.project:self.selected_track_header=None
        if getattr(self._thumbnails,'closed',False):
            from .video_filmstrip import FilmstripCache
            self._thumbnails=FilmstripCache(self)
            self._thumbnails.updated.connect(lambda _key:self.update())
        self.cancel_timing_edit()
        if project is not self.project:
            self.cache = None
            self.waveform_caches.clear()
            self.waveform_clip_keys.clear()
            getattr(self, "_waveform_envelope_cache", {}).clear()
            # 时间轴是跨工程常驻控件：上一工程的播放头绝不许漏进下一个
            # 工程（2026-09-20 新工程被残留位置污染的防线）。已存工程的
            # 保存位置由 open_project hydration 在其后 set_playhead 恢复。
            self.playhead_ms = 0
        self._clip_drag = None
        self._clip_scroll_timer.stop()
        self.project = project
        self.filmstrip_visible = bool(project.studio_state.get('video_thumbnails_visible', True)) if project else True
        self.snap_enabled = bool(project.studio_state.get("timeline_snap_enabled", True)) if project else True
        self.thumbnail_requests_enabled = True
        self._rebuild_cue_index()
        self.selected_video_track_id = (
            str(project.studio_state.get("selected_video_track_id") or "")
            if project else ""
        )
        if project and not any(
            track.id == self.selected_video_track_id for track in project.video_tracks
        ):
            self.selected_video_track_id = project.video_tracks[0].id if project.video_tracks else ""
        self.selected_video_clip_id = ""
        duration = project.media.duration_ms if project else 0
        self.visible_duration_ms = min(max(10_000, duration or 60_000), 300_000)
        self.visible_start_ms = 0
        self._sync_track_minimum_height()
        self._sync_scrollbars()
        self.update()

    def set_cache(self, cache: WaveformCache | None) -> None:
        self.cache = cache
        if self.project and cache:
            source = str(Path(cache.metadata.source_path).resolve())
            target = next(
                (
                    asset for asset in self.project.media_pool
                    if str(Path(asset.canonical_source).resolve()) == source
                ),
                None,
            )
            if target is not None:
                self.waveform_caches[target.asset_id] = cache
                if not target.duration_ms:
                    target.duration_ms = cache.metadata.duration_ms
            if str(Path(self.project.media.path).resolve()) == source:
                self.project.media.duration_ms = max(
                    int(self.project.media.duration_ms or 0),
                    int(cache.metadata.duration_ms or 0),
                )
        self.update()

    def waveform_cache_for_source(self, source_path: str) -> WaveformCache | None:
        if not self.project:
            return None
        try:
            source = str(Path(source_path).resolve())
        except (OSError, ValueError):
            return None
        asset = next(
            (
                item for item in self.project.media_pool
                if str(Path(item.canonical_source).resolve()) == source
            ),
            None,
        )
        cache = self.waveform_caches.get(asset.asset_id) if asset is not None else None
        # A relink retains the asset ID, but its old waveform belongs to a
        # different source. Never let the queue mistake that cache for ready.
        if cache is not None and str(Path(cache.metadata.source_path).resolve()) != source:
            self.waveform_caches.pop(asset.asset_id, None)
            self.waveform_clip_keys.clear()
            return None
        return cache

    def refresh_media_graph(self) -> None:
        if self.project and not any(
            track.id == self.selected_video_track_id for track in self.project.video_tracks
        ):
            self.selected_video_track_id = self.project.video_tracks[0].id if self.project.video_tracks else ""
        self._rebuild_cue_index()
        self._sync_track_minimum_height()
        self._sync_scrollbars()
        self.update()

    def set_waveform_state(self, state: str, message: str = "") -> None:
        self.waveform_state = state if state in {"EMPTY", "LOADING", "READY", "ERROR"} else "ERROR"
        self.waveform_message = str(message or "")
        self.update()

    @measured('playhead_target')
    def set_playhead(self, milliseconds: int) -> None:
        if self._scrub_drag:
            return  # A late decoder observation cannot drag the pointer back.
        self._paint_playhead_at(milliseconds)

    def _paint_playhead_at(self, milliseconds: int) -> None:
        """Invalidate only the old and new transport cursor, including drag."""
        previous = self.playhead_ms
        next_value = self._bounded_time_ms(milliseconds)
        if next_value == previous:
            return
        self.playhead_ms = next_value
        self._thumbnails.note_activity()
        region = self._transport_cursor_region(previous) | self._transport_cursor_region(next_value)
        if PLAYBACK_PROBE_ENABLED:
            playback_mark('playhead_update_request', project_ms=self.playhead_ms,
                          dirty_rects=region.rectCount(), dirty_width=region.boundingRect().width(),
                          dirty_height=region.boundingRect().height())
        if self._scrub_drag and getattr(self, '_static_timeline_cache', None) and not getattr(self, '_static_timeline_dirty', True):
            # Cursor-only paint is a cached raster blit (<1ms in the audit).
            # Present pointer feedback before its seek work. Ordinary Clock
            # ticks remain coalesced by Qt; never rebuild the base here.
            self._transport_overlay.repaint(region)
        else:
            self._transport_overlay.update(region)

    def _transport_cursor_region(self, milliseconds: int) -> QRegion:
        x = self._time_to_x(milliseconds)
        label_left = max(
            self.TRACK_HEADER_WIDTH,
            min(x - 41, self._content_right() - 82),
        )
        # 竖线脏区同样钳在内容区，播放头在视口左侧之外时不弄脏轨头列。
        content_left = self.TRACK_HEADER_WIDTH
        cursor_left = max(content_left, round(x) - 2)
        region = QRegion(QRect(cursor_left, 0, 5, self._canvas_bottom()+2))
        region |= QRegion(QRectF(label_left-2, 2, 86, 27).toAlignedRect())
        return region.intersected(QRegion(self.rect()))

    def set_snap_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.snap_enabled:
            return
        self.snap_enabled = enabled
        if self.project is not None:
            self.project.studio_state["timeline_snap_enabled"] = enabled
        self.snap_changed.emit(enabled)
        self.update()

    def set_selected(self, cue_id: str) -> None:
        if cue_id:
            self.selected_gap = None
        previous_ids = set(self.selected_ids)
        if self.selected_id:
            previous_ids.add(self.selected_id)
        self.selected_id = str(cue_id)
        self.selected_ids = {self.selected_id} if self.selected_id else set()
        self.selection_scope = SelectionScope.explicit(
            self.selected_ids, self.selected_id
        )
        changed_ids = previous_ids | self.selected_ids
        ranges = [
            (cue.start_ms, cue.end_ms)
            for item in changed_ids
            if (cue := self._timeline_cue_by_id.get(item)) is not None
        ]
        self.invalidate_ranges(ranges, changed_ids)

    @measured('timeline_activity')
    def set_active_cues(self, cue_ids: Iterable[str]) -> None:
        """Invalidate old/new playback markers without evicting the base raster."""
        ids = frozenset(cue_ids)
        changed = ids ^ getattr(self, 'active_cue_ids', frozenset())
        self.active_cue_ids = ids
        for cue_id in changed:
            rect = self._active_cue_rect(cue_id)
            if not rect.isEmpty():
                super().update(rect.adjusted(-3, -3, 3, 3).toAlignedRect())

    def _active_cue_rect(self, cue_id: str) -> QRectF:
        cue = self._timeline_cue_by_id.get(cue_id)
        if cue is None or cue.speaker_id in self.hidden_speakers:
            return QRectF()
        tracks, _, _ = self._track_layout()
        track = tracks.get(cue.speaker_id)
        if track is None:
            return QRectF()
        left = max(self.TRACK_HEADER_WIDTH, self._time_to_x(cue.start_ms))
        right = min(self._content_right(), self._time_to_x(cue.end_ms))
        if right < left:
            return QRectF()
        return QRectF(left, track.top()+7, max(3., right-left), track.height()-14).intersected(self._track_viewport())

    def set_selected_ids(self, cue_ids: Iterable[str], active_id: str = "") -> None:
        self.selected_gap = None
        self.selected_ids = {str(item) for item in cue_ids if str(item)}
        self.selected_id = str(active_id or (next(iter(self.selected_ids), "")))
        self.selection_scope = SelectionScope.explicit(
            self.selected_ids, self.selected_id
        )
        self.update()

    def set_selection_scope(self, scope: SelectionScope) -> None:
        self.selected_gap = None
        self.selection_scope = scope
        self.selected_id = str(scope.active_id)
        self.selected_ids = (
            set(scope.explicit_ids)
            if scope.mode == SelectionMode.EXPLICIT_IDS
            else set()
        )
        self.update()

    def _cue_is_selected(self, cue: StudioCue) -> bool:
        return cue.id == self.selected_id or self.selection_scope.contains(
            cue.id,
            row=self._timeline_row_by_id.get(cue.id),
        )

    def set_bilingual(self, enabled: bool) -> None:
        self.bilingual = bool(enabled)
        self._sync_scrollbars()
        self.updateGeometry()
        self.update()

    def set_waveform_visible(self, enabled: bool) -> None:
        self.waveform_visible = bool(enabled)
        self._sync_scrollbars()
        self.update()

    def speaker_ids(self) -> list[str]:
        return list(self._speaker_ids)

    def _track_layout(self) -> tuple[dict[str, QRectF], QRectF | None, QRectF]:
        speakers = self.speaker_ids()
        speaker_height = self._speaker_track_height()
        translation_height = 0
        if self.bilingual:
            translation_height = max(self.TRANSLATION_TRACK_HEIGHT, min(74, speaker_height))
        content_height = len(speakers) * speaker_height + translation_height
        viewport = self._track_viewport()
        if content_height < viewport.height():
            # Sit subtitle tracks immediately above V1/waveform (scheme A).
            top = viewport.bottom() - content_height
        else:
            top = viewport.top() - self.vertical_scrollbar.value()
        speaker_rects: dict[str, QRectF] = {}
        for speaker_id in speakers:
            speaker_rects[speaker_id] = QRectF(0, top, self.width(), speaker_height)
            top += speaker_height
        translation = None
        if self.bilingual:
            translation = QRectF(0, top, self.width(), translation_height)
            top += translation_height
        # Audio rows are paired with V1/V2/... in the pinned media groups.
        waveform = QRectF()
        return speaker_rects, translation, waveform

    def _waveform_track_height(self) -> int:
        return 0

    def _speaker_track_height(self) -> int:
        override = self._track_height_overrides.get("subtitle")
        if override:
            return int(override)
        count = max(1, len(self.speaker_ids()))
        available = max(0, round(self._track_viewport().height()))
        translation_floor = 44 if self.bilingual else 0
        usable = max(0, available - translation_floor)
        per_track = usable // count if usable else 52
        if per_track >= 96:
            return 96
        if per_track >= 84:
            return 84
        if per_track >= 68:
            return 68
        return 52

    @staticmethod
    def _timeline_text_font(row_height: int, block_width: float = 0) -> QFont:
        """Choose timeline UI text size from the available track and zoom."""
        height = max(1, int(row_height))
        if height < 58:
            size = 14
        elif height < 76:
            size = 15
        elif height < 90:
            size = 17
        else:
            size = 18
        if float(block_width) >= 260 and height >= 58:
            size = min(18, size + 1)
        font = QFont()
        font.setPointSize(size)
        return font

    def _time_to_x(self, milliseconds: int) -> float:
        content_width = max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
        return self.TRACK_HEADER_WIDTH + (milliseconds - self.visible_start_ms) * content_width / max(1, self.visible_duration_ms)

    def _x_to_time(self, x: float) -> int:
        content_width = max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
        return round(self.visible_start_ms + (x - self.TRACK_HEADER_WIDTH) * self.visible_duration_ms / content_width)

    def _cue_at(self, point: QPoint) -> tuple[StudioCue | None, str]:
        if not self.project or point.x() < self.TRACK_HEADER_WIDTH:
            return None, ""
        if not self._track_viewport().contains(point):
            return None, ""
        speaker_rects, translation, _waveform = self._track_layout()
        if translation and translation.contains(point):
            translations = self.project.generation_metadata.get("translations", {})
            if isinstance(translations, dict):
                for cue in reversed(self.visible_cues()):
                    if cue.id not in translations:
                        continue
                    if self._time_to_x(cue.start_ms) <= point.x() <= self._time_to_x(cue.end_ms):
                        return cue, "translation"
        visible = self.visible_cues()
        # The active cue wins ties when neighboring blocks touch. This keeps
        # the selected cue recoverable while dragging it back from an overlap.
        ordered = sorted(visible, key=lambda cue: cue.id != self.selected_id)
        edge_hits = []
        bodies = []
        for cue in ordered:
            track = speaker_rects.get(cue.speaker_id)
            if not track or cue.speaker_id in self.hidden_speakers or not track.contains(point):
                continue
            left = self._time_to_x(cue.start_ms)
            right = self._time_to_x(cue.end_ms)
            # Qt event coordinates are logical pixels. The whole edge is a
            # target, including 10px outside the painted block; dots are only
            # decoration. All edges take priority over any neighboring body.
            if track.top()+7 <= point.y() <= track.bottom()-7:
                for edge, x in (("left", left), ("right", right)):
                    distance = abs(point.x()-x)
                    if distance <= 10:
                        edge_hits.append((distance, cue.id != self.selected_id, cue, edge))
            if left <= point.x() <= right:
                bodies.append(cue)
        if edge_hits:
            _distance, _inactive, cue, edge = min(edge_hits, key=lambda hit: (hit[0], hit[1]))
            return cue, edge
        if bodies:
            return bodies[0], "move"
        return None, ""

    def _merge_neighbor(self, anchor_id: str, direction: int) -> StudioCue | None:
        row = self._timeline_row_by_id.get(anchor_id)
        if row is None:
            return None
        target = row + (1 if direction > 0 else -1)
        if not 0 <= target < len(self._cues_by_start):
            return None
        return self._cues_by_start[target]

    def _nearest_cue_for_razor(self, milliseconds: int) -> StudioCue | None:
        """Cue under the play position, else the chronologically nearest one."""
        value = int(milliseconds)
        for cue in self._cues_by_start:
            if cue.start_ms <= value < cue.end_ms:
                return cue
        return min(
            self._cues_by_start,
            key=lambda cue: min(abs(value - cue.start_ms), abs(value - cue.end_ms)),
            default=None,
        )

    def _start_razor_drag(self, cue_id: str, x: float) -> None:
        self._razor_drag = {
            "cue_id": cue_id,
            "origin_x": x,
            "pressed_ms": self._x_to_time(x),
            "split_ms": self._x_to_time(x),
            "moved": False,
        }
        self.interaction_changed.emit(True)
        self.update()

    def _snap_time(self, value: int, moving_id: str) -> int:
        if not self.snap_enabled or self._snap_bypass:
            self._snap_target = None
            return int(value)
        content_width = max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
        threshold_ms = 8.0 * self.visible_duration_ms / content_width
        held = self._snap_target
        if self._drag and held and abs(held["time"]-value) <= threshold_ms*1.75 and self._valid_snap(held["time"], moving_id):
            return held["time"]
        self._snap_target = None
        candidates = [(self.playhead_ms, "播放头", "", "")]
        if self.project:
            for cue in self._cues_intersecting(value - threshold_ms * 2, value + threshold_ms * 2):
                if cue.id != moving_id and cue.id not in self._drag_originals:
                    name = _speaker_name(self.project, cue.speaker_id)
                    candidates.extend(((cue.start_ms, f"{name} 轨 · 字幕开头", cue.id, "left"),
                                       (cue.end_ms, f"{name} 轨 · 字幕结尾", cue.id, "right")))
            for track in [*self.project.video_tracks, *self.project.audio_tracks]:
                for clip in track.clips:
                    candidates.extend(((clip.timeline_in_ms, f"{track.name or track.id} 素材开头", "", ""),
                                       (clip.timeline_out_ms, f"{track.name or track.id} 素材结尾", "", "")))
            sequence = sequence_of(self.project)
            if sequence:
                if not self.project.video_tracks:
                    for segment in sequence.segments:
                        candidates.extend(((segment.timeline_in_ms, "V1 视频切点", "", ""),
                                           (segment.timeline_out_ms, "V1 视频切点", "", "")))
                for marker in sequence.markers:
                    candidates.append((marker.time_ms, f"标记 {marker.label}", "", ""))
        candidates = [item for item in candidates if self.visible_start_ms <= item[0] <= self.visible_start_ms + self.visible_duration_ms
                      and self._valid_snap(item[0], moving_id)]
        nearest = min(candidates, key=lambda item: abs(item[0] - value), default=None)
        if nearest and abs(nearest[0] - value) <= threshold_ms:
            if self._drag:
                self._snap_target = dict(time=nearest[0], label=nearest[1], cue_id=nearest[2], edge=nearest[3])
            return nearest[0]
        return value

    def _valid_snap(self, target, moving_id):
        if not self._drag or not self._drag_originals:
            return True
        original = self._drag_originals.get(moving_id)
        if original is None:
            return False
        mode = self._drag[1]
        edge = original.end_ms if mode == "right" else original.start_ms
        proposed = preview_intervals(self._drag_originals, moving_id, mode, target-edge)
        anchor = proposed[moving_id]
        if (anchor.end_ms if mode == "right" else anchor.start_ms) != target:
            return False  # minimum duration / zero boundary clipped the target
        for key, value in proposed.items():
            before = self._drag_originals[key]
            for other in self._cues_intersecting(value.start_ms, value.end_ms):
                if other.id in proposed or other.speaker_id != value.speaker_id:
                    continue
                overlaps = min(value.end_ms, other.end_ms) > max(value.start_ms, other.start_ms)
                already = min(before.end_ms, other.end_ms) > max(before.start_ms, other.start_ms)
                if overlaps and not already:
                    return False
        return True

    def _speaker_at(self, point: QPoint) -> str:
        speaker_rects, translation, _waveform = self._track_layout()
        if translation is not None and translation.contains(point):
            return ""
        for speaker_id, rect in speaker_rects.items():
            if rect.contains(point):
                return speaker_id
        return ""

    def _cue_interval_rect(
        self,
        cue: StudioCue,
        start_ms: int,
        end_ms: int,
        speaker_id: str = "",
    ) -> QRect:
        track = self._track_layout()[0].get(speaker_id or cue.speaker_id)
        if track is None:
            return QRect()
        left = self._time_to_x(int(start_ms)) - 10
        right = self._time_to_x(int(end_ms)) + 10
        return QRectF(
            left,
            track.top(),
            max(20.0, right - left),
            track.height(),
        ).intersected(QRectF(self.rect())).toAlignedRect()

    def _header_hover_rect(self, hover: tuple[str, str] | None) -> QRect:
        if hover is None:
            return QRect()
        owner, action = hover
        if owner == "video":
            track = self._video_track_rect()
        elif owner.startswith("video:"):
            track = self._video_track_rect(owner.partition(":")[2])
        elif owner.startswith("audio:"):
            track = self._audio_track_rects().get(owner.partition(":")[2], QRectF())
        else:
            track = self._track_layout()[0].get(owner, QRectF())
        if track.isEmpty():
            return QRect()
        kind = 'audio' if owner.startswith('audio:') else 'video' if owner.startswith('video') else 'subtitle'
        return button_rect(kind, action, track).adjusted(-2, -2, 2, 2).toAlignedRect()

    def _update_header_hover(
        self,
        before: tuple[str, str] | None,
        after: tuple[str, str] | None,
    ) -> None:
        dirty = self._header_hover_rect(before).united(self._header_hover_rect(after))
        if not dirty.isEmpty():
            self.update(dirty)

    def _paint_video_lanes(
        self,
        painter: QPainter,
        palette: TimelinePalette,
        *,
        sequence,
        visible_segments,
    ) -> None:
        """Paint every video lane (headers + clips) in stable z order.

        主渲染路径与视频区快速重绘路径共用——快速路径此前只画播放头，
        局部 invalidation 命中时泳道内容（含轨道头图标）会被背景清除。
        """

        video_rects = self._video_track_rects()
        snapshot = self._clip_drag.get('snapshot') if self._clip_drag else None
        tracks = list(snapshot[0] if snapshot else self.project.video_tracks) if self.project else []
        if snapshot:
            sequence = snapshot[3]
            visible_segments = sequence.segments
        from .studio_media_pool import primary_video_track_id

        primary_track_id = primary_video_track_id(self.project) if self.project else ""
        primary = next(
            (track for track in tracks if track.id == primary_track_id),
            tracks[0] if tracks else None,
        )
        primary_id = primary.id if primary is not None else "V1"
        offline_sources = {asset.canonical_source for asset in self.project.media_pool if asset.offline} if self.project else set()
        thumbnails = self._thumbnails if self.filmstrip_visible else None
        if thumbnails is not None:
            from .video_filmstrip import FilmstripView,filmstrip_tiles,filmstrip_lod_ms
            view_left=self.TRACK_HEADER_WIDTH+1;view_right=self._content_right()-1
            view_width=max(1,view_right-view_left)
            views=[]
            def collect(path,tin,tout,sin,sout,track_id,owner):
                if not path or tout<=tin:return
                # FLV 的优化副本路由在 FilmstripCache 解码端内部完成：
                # key/身份统一基于 canonical 路径（paint 查询的就是它），
                # 此前 collect 侧路由到 optimized/proxy 身份导致两边身份
                # 永不相等、解码出的格子永远画不上。
                rect=video_rects.get(track_id,QRectF())
                if rect.bottom()<0 or rect.top()>=self.height():return
                left,right=self._time_to_x(tin),self._time_to_x(tout)
                height=rect.height()-(18 if track_id==primary_id else 16)
                visible=tuple(t for x,e,t in filmstrip_tiles(left,right,view_left,view_right,sin,sout,height))
                nearby=tuple(t for x,e,t in filmstrip_tiles(left,right,view_left-view_width*.15,view_right+view_width*.15,sin,sout,height) if t not in visible)
                if visible or nearby:
                    focus=sin+max(0,min(tout-tin,self.playhead_ms-tin))*(sout-sin)/(tout-tin)
                    lod=filmstrip_lod_ms((right-left)*1000/max(1,sout-sin),height)
                    views.append(FilmstripView(path,visible,nearby,int(focus),f'{track_id}:{owner}',int(sin),int(sout),lod))
            for segment in sequence.segments:
                if (segment.source_path or sequence.source_path) in offline_sources:
                    continue
                collect(segment.source_path or sequence.source_path,segment.timeline_in_ms,segment.timeline_out_ms,
                        segment.source_in_ms,segment.source_out_ms,primary_id,segment.id)
            media={asset.asset_id:asset for asset in self.project.media_pool} if self.project else {}
            for item in tracks:
                if item is primary:continue
                for clip in item.clips:
                    asset=media.get(clip.asset_id)
                    if asset and not asset.offline:
                        collect(asset.canonical_source,clip.timeline_in_ms,clip.timeline_out_ms,clip.source_in_ms,clip.source_out_ms,item.id,clip.id)
            thumbnails.set_view(views)
        paint_video_track(
            painter,
            sequence,
            palette,
            video_rects.get(primary_id, self._video_track_rect()),
            self.TRACK_HEADER_WIDTH,
            self._content_right(),
            self._time_to_x,
            self.selected_segment_id,
            thumbnails,
            sequence.video_track_locked,
            self._hover_header_action == (f"video:{primary_id}", "locked"),
            self.thumbnail_requests_enabled,
            set(self.selected_segment_ids),
            visible_segments,
            track_id=primary_id,
            track_name=primary.name if primary is not None else "视频",
            enabled=primary.enabled if primary is not None else True,
            muted=primary.muted if primary is not None else False,
            hovered_action=(
                self._hover_header_action[1]
                if self._hover_header_action and self._hover_header_action[0] == f"video:{primary_id}"
                else ""
            ),
            role_label=self._video_header_role(primary_id),
            paint_stats=getattr(self, '_paint_item_counts', None),
            offline_sources=offline_sources,
        )
        assets = {asset.asset_id: asset for asset in self.project.media_pool} if self.project else {}
        for track in (item for item in tracks if item is not primary):
            paint_project_video_track(
                painter,
                track,
                assets,
                palette,
                video_rects[track.id],
                self.TRACK_HEADER_WIDTH,
                self._content_right(),
                self._time_to_x,
                selected_clip_id=self.selected_video_clip_id,
                thumbnails=thumbnails,
                request_missing_thumbnails=self.thumbnail_requests_enabled,
                clip_preview={},
                hovered_action=(
                    self._hover_header_action[1]
                    if self._hover_header_action and self._hover_header_action[0] == f"video:{track.id}"
                    else ""
                ),
                role_label=self._video_header_role(track.id),
                paint_stats=getattr(self, '_paint_item_counts', None),
            )
        if self._clip_drag and self._clip_drag.get('moved'):
            drag = self._clip_drag
            rect = video_rects.get(drag.get('target_track_id') or drag['track_id'])
            if rect is not None:
                invalid = str(drag.get('invalid') or '')
                color = QColor('#E66B79' if invalid else palette.playhead)
                painter.save()
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(self.TRACK_HEADER_WIDTH, rect.top(),
                                       self._content_right() - self.TRACK_HEADER_WIDTH, rect.height()))
                if invalid:
                    painter.fillRect(QRectF(self.TRACK_HEADER_WIDTH, rect.top(),
                                           self._content_right() - self.TRACK_HEADER_WIDTH, 24), QColor(35, 25, 30, 235))
                    painter.drawText(QRectF(self.TRACK_HEADER_WIDTH + 8, rect.top(),
                                           self._content_right() - self.TRACK_HEADER_WIDTH - 16, 24),
                                     Qt.AlignmentFlag.AlignVCenter, '不能放置：' + invalid)
                painter.restore()
        if self._track_reorder_drag and self._track_reorder_drag.get("target_track_id"):
            highlight = self._video_track_rect(str(self._track_reorder_drag["target_track_id"]))
            painter.fillRect(
                QRectF(0, highlight.top(), self._content_right(), highlight.height()),
                QColor(palette.header_hover),
            )
        if self._segment_drag and self._segment_drag.get("target_track_id"):
            # 主轨 segment 上移的落点泳道高亮（与轨道换序同款提示）。
            highlight = self._video_track_rect(str(self._segment_drag["target_track_id"]))
            painter.fillRect(
                QRectF(0, highlight.top(), self._content_right(), highlight.height()),
                QColor(palette.header_hover),
            )
        swap_source = ""
        swap_target = ""
        if self._clip_drag and self._clip_drag.get("swap_target_id"):
            # 四十八轮（agy 评审）：拖片段到主轨泳道=层级对调待定。反馈必须是
            # 整轨级联动（双泳道高亮+交界指示条），只画幽灵片段会被读成
            # "插入到这个时间点"——用户上一轮正是这么误解的。
            swap_source = str(self._clip_drag.get("track_id") or "")
            swap_target = str(self._clip_drag.get("swap_target_id") or "")
        if swap_source and swap_target:
            source_rect = video_rects.get(swap_source, QRectF())
            target_rect = video_rects.get(swap_target, QRectF())
            for rect in (source_rect, target_rect):
                if rect.isEmpty():
                    continue
                painter.fillRect(
                    QRectF(0, rect.top(), self._content_right(), rect.height()),
                    QColor(58, 134, 255, 25),
                )
            if not source_rect.isEmpty() and not target_rect.isEmpty():
                top = min(source_rect.bottom(), target_rect.bottom())
                bottom = max(source_rect.top(), target_rect.top())
                divider_y = round((top + bottom) / 2.0)
                badge = QRectF(self._content_right() / 2.0 - 118, divider_y - 13, 236, 26)
                painter.setPen(QPen(QColor("#3A86FF"), 1.5))
                painter.setBrush(QColor(30, 30, 35, 220))
                painter.drawRoundedRect(badge, 13, 13)
                painter.setPen(QColor(Qt.GlobalColor.white))
                painter.drawText(
                    badge,
                    Qt.AlignmentFlag.AlignCenter,
                    f"⇄ 松手交换 {swap_source}/{swap_target} 层级",
                )

    def _video_header_role(self, track_id: str) -> str:
        """四十八轮（agy）：轨道头角色徽标——用户不知道谁盖谁。"""

        if not self.project:
            return ""
        from .studio_media_pool import primary_video_track_id

        if track_id == primary_video_track_id(self.project):
            return tr("主画面·底层")
        tracks = list(self.project.video_tracks)
        if len(tracks) > 1 and tracks and track_id == tracks[-1].id:
            return "顶层·覆盖"
        return ""

    def _paint_video_lane_headers(
        self,
        painter: QPainter,
        palette: TimelinePalette,
        dirty: QRect,
    ) -> None:
        """Repaint video-lane headers intersecting ``dirty`` (header-column fast path)."""

        if self.project is None:
            return
        from .studio_media_pool import primary_video_track_id

        sequence = sequence_of(self.project)
        primary_id = primary_video_track_id(self.project)
        tracks = {track.id: track for track in self.project.video_tracks}
        for track_id, rect in self._video_track_rects().items():
            lane_header = QRectF(rect.left(), rect.top(), self.TRACK_HEADER_WIDTH, rect.height())
            if not lane_header.intersects(QRectF(dirty)):
                continue
            track = tracks.get(track_id)
            is_primary = track_id == primary_id
            paint_video_track_header(
                painter,
                palette,
                rect,
                track_id=track_id,
                track_name=track.name if track is not None else track_id,
                enabled=track.enabled if track is not None else True,
                muted=track.muted if track is not None else False,
                locked=(
                    sequence.video_track_locked
                    if is_primary
                    else (track.locked if track is not None else False)
                ),
                hovered_action=(
                    self._hover_header_action[1]
                    if self._hover_header_action and self._hover_header_action[0] == f"video:{track_id}"
                    else ""
                ),
                role_label=self._video_header_role(track_id),
            )

    def _waveform_envelope(self, cache, source_in, source_out, pixels, left, right, rect):
        """Reuse static waveforms while only the playhead moves (no disk read)."""
        paths = getattr(self, "_waveform_envelope_cache", None)
        if paths is None:
            paths = self._waveform_envelope_cache = {}
        key = (id(cache), source_in, source_out, pixels, right-left, rect.height())
        cached = paths.get(key)
        if cached is not None:
            self._paint_envelope_hits = getattr(self, '_paint_envelope_hits', 0) + 1
            self._last_waveform_envelope_stats = cached[2]
            return QTransform.fromTranslate(left, rect.center().y()).map(cached[1])
        self._paint_envelope_misses = getattr(self, '_paint_envelope_misses', 0) + 1
        envelope_started = perf_counter()
        try:
            _level, pairs = cache.read_window(source_in, source_out, pixels)
        except (OSError, ValueError):
            return None
        if not len(pairs):
            return None
        import numpy as np
        amplitude = rect.height() * 0.36
        # Absolute dBFS display heights in [0, 1] — see waveform_db_heights.
        # The previous per-view AGC (gain = 0.72 / visible-peak) tied the
        # vertical scale to the zoom level: zoomed out the view always
        # contained the global peak, so ordinary speech collapsed to ~1px
        # ("looks like silence"), while zooming into a quiet stretch boosted
        # the same audio up to 4x. One sound must keep one visual strength.
        heights = waveform_db_heights
        stride = max(1, int(np.ceil(len(pairs) / max(1, pixels / 2))))
        # Map buckets by *time*, not by count: while a level is still filling,
        # read_window returns only the covered prefix — stretching that prefix
        # across the whole clip width used to draw covered audio at the wrong
        # positions. The uncovered tail stays blank instead of faking data.
        expected_buckets = max(
            1.0, (float(source_out) - float(source_in)) / _level.milliseconds_per_frame
        )
        x_scale = max(1.0, right - left) / expected_buckets
        indices=np.arange(0,len(pairs),stride)
        highs=heights(np.maximum.reduceat(pairs[:,1],indices))
        lows=heights(np.minimum.reduceat(pairs[:,0],indices))
        upper=[QPointF(float(i*x_scale),float(-v*amplitude)) for i,v in zip(indices,highs)]
        lower=[QPointF(float(i*x_scale),float(v*amplitude)) for i,v in zip(indices,lows)]
        if not upper:
            return None
        envelope = QPainterPath()
        envelope.addPolygon(QPolygonF(upper+list(reversed(lower))))
        envelope.closeSubpath()
        self._last_waveform_envelope_stats = dict(level=_level.level,
            milliseconds_per_bucket=_level.milliseconds_per_frame,
            buckets=len(pairs), vertices=len(upper)+len(lower),
            render_ms=round((perf_counter()-envelope_started)*1000.0, 2))
        self._trace_waveform_lod(_level, self._last_waveform_envelope_stats)
        paths[key] = (cache, envelope, self._last_waveform_envelope_stats)
        while len(paths) > 32:
            paths.pop(next(iter(paths)))
        return QTransform.fromTranslate(left, rect.center().y()).map(envelope)

    def _trace_waveform_lod(self, level, stats: dict) -> None:
        """Log LOD selection only on change or slow rebuilds — zoom stays cheap to diagnose."""
        signature = (level.file, int(level.frames))
        slow = float(stats.get('render_ms') or 0.0) > 30.0
        last = getattr(self, '_waveform_lod_last', None)
        if signature == last and not slow:
            return
        self._waveform_lod_last = signature
        try:
            from .runtime_trace import GLOBAL_STUDIO_TRACE
            GLOBAL_STUDIO_TRACE.emit("WaveformLOD", {
                "level": int(level.level), "level_file": level.file,
                "level_frames": int(level.frames),
                "milliseconds_per_bucket": round(float(level.milliseconds_per_frame), 2),
                "buckets": int(stats.get('buckets') or 0),
                "vertices": int(stats.get('vertices') or 0),
                "render_ms": float(stats.get('render_ms') or 0.0),
            })
        except Exception:
            pass

    def _paint_linked_audio_tracks(
        self,
        painter: QPainter,
        palette: TimelinePalette,
    ) -> None:
        if not self.waveform_visible:
            return
        rects = self._audio_track_rects()
        snapshot = self._clip_drag.get('snapshot') if self._clip_drag else None
        tracks = {track.id: track for track in (snapshot[1] if snapshot else self.project.audio_tracks)} if self.project else {}
        assets = {asset.asset_id: asset for asset in self.project.media_pool} if self.project else {}
        video_for_audio = {
            group.audio_track_id: group.video_track_id
            for group in self.project.av_track_groups
        } if self.project else {}
        from .studio_media_pool import audio_master_track_id

        master_video_id = audio_master_track_id(self.project) if self.project else ""
        visible_start = int(self.visible_start_ms)
        visible_end = visible_start + int(self.visible_duration_ms)
        painter.save()
        for audio_id, rect in rects.items():
            painter.fillRect(
                QRectF(
                    self.TRACK_HEADER_WIDTH,
                    rect.top(),
                    self._content_right() - self.TRACK_HEADER_WIDTH,
                    rect.height(),
                ),
                QColor(palette.waveform_background),
            )
            track = tracks.get(audio_id)
            muted = bool(track and track.muted)
            locked = bool(track and track.locked)
            header_font = painter.font()
            header_font.setBold(True)
            header_font.setPointSize(9)
            painter.setFont(header_font)
            painter.setPen(QColor(palette.waveform_header_text))
            painter.drawText(
                QRectF(12, rect.top(), 90, rect.height()),
                Qt.AlignmentFlag.AlignVCenter,
                tr("{track}  波形", track=audio_id),
            )
            video_id = video_for_audio.get(audio_id, "")
            soloed = bool(track and getattr(track, "soloed", False))
            for action, icon_name in (
                ("muted", "fa5s.volume-mute" if muted else "fa5s.volume-up"),
                ("solo", "S"),
                ("delete", "fa5s.trash-alt"),
            ):
                active = (self._hover_header_action == (f"audio:{audio_id}", action)
                          or action == 'muted' and muted or action == 'solo' and soloed)
                paint_button(painter, palette, 'audio', action, rect, icon_name,
                             active=active, solo=action == 'solo' and soloed,
                             disabled=action == 'delete' and locked)
            if track is None or not track.enabled or not track.clips:
                # 四十五轮（agy 两轮评审）：空轨不再画文字提示（228px 轨头放不下
                # 三个字，曾先后与图标穿模/被截断）——整行半透明压暗表达空态。
                # 四十七轮 agy 评审：压暗只覆盖泳道画布，轨头列（0~228px）保持
                # 与其它轨头一致的浅底——整列米白里一块黑=轨道控制列"被挖走"。
                painter.fillRect(
                    QRectF(
                        self.TRACK_HEADER_WIDTH,
                        rect.top(),
                        self._content_right() - self.TRACK_HEADER_WIDTH,
                        rect.height(),
                    ),
                    QColor(0, 0, 0, 90),
                )
                painter.drawLine(self.TRACK_HEADER_WIDTH, round(rect.bottom()), self._content_right(), round(rect.bottom()))
                continue

            painter.save()
            painter.setClipRect(QRectF(
                self.TRACK_HEADER_WIDTH,
                rect.top(),
                self._content_right() - self.TRACK_HEADER_WIDTH,
                rect.height(),
            ))
            for clip in track.clips:
                overlap_in = max(visible_start, int(clip.timeline_in_ms))
                overlap_out = min(visible_end, int(clip.timeline_out_ms))
                if overlap_out <= overlap_in:
                    continue
                asset = assets.get(clip.asset_id)
                cache = self.waveform_cache_for_source(asset.canonical_source) if asset else None
                if asset is None or cache is None:
                    continue
                from .clip_time_mapper import project_to_source
                source_in = project_to_source(clip, overlap_in)
                source_out = (clip.source_out_ms if overlap_out == clip.timeline_out_ms
                              else project_to_source(clip, overlap_out))
                self.waveform_clip_keys[clip.id] = clip_waveform_cache_key(
                    asset.fingerprint,
                    clip.stream_index,
                    source_in,
                    source_out,
                )
                left = max(self.TRACK_HEADER_WIDTH, self._time_to_x(overlap_in))
                right = min(self._content_right(), self._time_to_x(overlap_out))
                pixels = max(1, round(right - left))
                envelope = self._waveform_envelope(cache, source_in, source_out, pixels, left, right, rect)
                if envelope is None:
                    continue
                center = rect.center().y()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(rgba_color(palette.waveform))
                # The min/max envelope already samples physical-width bins.
                # Coverage antialiasing of its dense zig-zag polygon dominates
                # every zoom paint; keep pixel coverage exact for this raster.
                antialias = painter.testRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                painter.drawPath(envelope)
                counted=self._count_paint_item('waveform_items', bounds=rect)
                stats=getattr(self, '_paint_item_counts', None)
                if stats is not None and counted:
                    stats.setdefault('waveforms', []).append(dict(self._last_waveform_envelope_stats))
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, antialias)
                painter.setPen(QPen(QColor(palette.waveform_edge), 1.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawLine(round(left), round(center), round(right), round(center))
            painter.restore()
            painter.setPen(QPen(mix(palette.grid_minor, palette.background, 0.4), 1))
            painter.drawLine(0, round(rect.bottom()), self._content_right(), round(rect.bottom()))
        painter.restore()
        if self.waveform_state == "LOADING" and self.waveform_message:
            first_rect = next(iter(rects.values()), None)
            if first_rect is not None:
                message_font = painter.font()
                message_font.setPointSize(9)
                painter.setFont(message_font)
                painter.setPen(QColor(palette.waveform_header_text))
                painter.drawText(
                    QRectF(
                        self.TRACK_HEADER_WIDTH + 12,
                        first_rect.top(),
                        self._content_right() - self.TRACK_HEADER_WIDTH - 24,
                        first_rect.height(),
                    ),
                    Qt.AlignmentFlag.AlignVCenter,
                    self.waveform_message,
                )

    def update(self, *args):
        # Every edit/hover/theme update invalidates the static timeline. The
        # transport cursor calls QWidget.update directly and reuses it.
        # Keep the backing raster allocated. At 175% DPI discarding it on
        # each followed cue repeatedly destroys/reallocates a multi-MB pixmap.
        self._static_timeline_dirty = True
        super().update(*args)

    def closeEvent(self,event):
        self._thumbnails.close()
        super().closeEvent(event)

    @measured('timeline_paint')
    def paintEvent(self, event):
        started = perf_counter()
        if PLAYBACK_PROBE_ENABLED:
            playback_mark('timeline_paint_begin', project_ms=self.playhead_ms,
                          dirty_width=event.rect().width(), dirty_height=event.rect().height(),
                          static_dirty=getattr(self, '_static_timeline_dirty', True))
        self._paint_timeline(event)
        if PLAYBACK_PROBE_ENABLED:
            playback_mark('timeline_paint_end', project_ms=self.playhead_ms)
        pending = getattr(self, "_timing_paint_input", None)
        if pending is not None:
            received, row = pending
            row["input_to_paint_ms"] = (perf_counter() - received) * 1000
            row["paint_ms"] = (perf_counter() - started) * 1000
            self._timing_paint_input = None

    def _paint_timeline(self, event):
        palette = self._timeline_palette()
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, repr(palette), self.font().key())
        cached = getattr(self, "_static_timeline_cache", None)
        self._paint_item_counts = {'viewport_height': self.height()}
        self._paint_envelope_hits = self._paint_envelope_misses = 0
        if cached is None or cached[0] != key or getattr(self, '_static_timeline_dirty', False):
            if cached is not None and cached[0] == key:
                image = cached[1]
            else:
                image = QPixmap(max(1, round(self.width()*dpr)), max(1, round(self.height()*dpr)))
                image.setDevicePixelRatio(dpr)
            image.fill(Qt.GlobalColor.transparent)
            backing = QPainter(image)
            backing.setFont(self.font())
            self._paint_timeline_contents(backing, QPaintEvent(self.rect()), palette)
            backing.end()
            self._static_timeline_cache = (key, image, dict(self._paint_item_counts))
            self._static_timeline_dirty = False
            self._last_paint_stats = {**self._paint_item_counts, 'static_cache_hit': False}
        else:
            image = cached[1]
            self._last_paint_stats = {**cached[2], 'static_cache_hit': True}
        painter = QPainter(self)
        painter.drawPixmap(0, 0, image)
        self._paint_item_counts = {'viewport_height': self.height()}
        if self._drag and self._timing_preview:
            speaker_rects,translation,_waveform=self._track_layout()
            rows=list(speaker_rects.values())+([translation] if translation else [])
            if rows:
                top=min(row.top() for row in rows);bottom=max(row.bottom() for row in rows)
                region=QRect(0,max(self.RULER_HEIGHT,round(top)),self.width(),max(1,round(bottom-top)+2))
                painter.save()
                painter.setClipRect(region)
                self._paint_timeline_contents(painter,QPaintEvent(region),palette,timing_only=True)
                painter.restore()
            self._paint_timing_guides(painter,palette)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_active_cues(painter, palette)
        if self.selected_gap:
            track_id, start, end = self.selected_gap
            row = self._video_track_rect(track_id)
            left = max(self.TRACK_HEADER_WIDTH, self._time_to_x(start))
            right = min(self._content_right(), self._time_to_x(end))
            color = QColor(palette.clip_selected_border)
            color.setAlpha(45)
            rect = QRectF(left, row.top()+3, max(0, right-left), row.height()-6)
            painter.fillRect(rect, color)
            painter.setPen(QPen(QColor(palette.clip_selected_border), 1, Qt.PenStyle.DashLine))
            painter.drawRect(rect)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, '空白 · Delete 闭合')
        self._paint_edge_feedback(painter, palette)
        # 右侧统一控制区：泳道分界把手（滚动/调高同列，直绘在滚动条列）。
        self._paint_track_height_grips(painter, palette)
        painter.end()

    def _paint_active_cues(self, painter, palette):
        painter.save()
        painter.setClipRect(self._track_viewport())
        painter.setPen(QPen(QColor(palette.playhead), 3))
        for cue_id in getattr(self, 'active_cue_ids', ()):
            rect = self._active_cue_rect(cue_id)
            if not rect.isEmpty():
                painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()

    def _paint_edge_feedback(self, painter, palette):
        speaker_rects, _translation, _waveform = self._track_layout()
        painter.save()
        painter.setClipRect(self._track_viewport())
        painter.setPen(QPen(QColor(palette.clip_selected_border), 3))
        def highlight(cue_id, edge):
            cue = self._timeline_cue_by_id.get(cue_id)
            if cue is None:
                return
            interval = self._timing_preview.get(cue_id)
            speaker = interval.speaker_id if interval else cue.speaker_id
            rect = speaker_rects.get(speaker)
            if rect is None:
                return
            value = (interval.start_ms if edge == "left" else interval.end_ms) if interval else (cue.start_ms if edge == "left" else cue.end_ms)
            x = round(self._time_to_x(value))
            painter.drawLine(x, round(rect.top()+7), x, round(rect.bottom()-7))
        if self._resize_hover:
            highlight(*self._resize_hover)
        if self._drag and self._drag[1] in {"left", "right"}:
            highlight(self._drag[0], self._drag[1])
        target = self._snap_target if self._drag or self._clip_drag else None
        if target:
            highlight(target["cue_id"], target["edge"])
            x = round(self._time_to_x(target["time"]))
            painter.setPen(QPen(QColor(palette.clip_selected_border), 2))
            viewport = self._track_viewport()
            painter.drawLine(x, round(viewport.top()), x, round(viewport.bottom()))
            label = f"吸附：{target['label']} {_format_ms(target['time'])}  · Alt 临时关闭"
            font = painter.font(); font.setPointSize(10); painter.setFont(font)
            width = min(self._content_right()-self.TRACK_HEADER_WIDTH, QFontMetrics(font).horizontalAdvance(label)+20)
            left = max(self.TRACK_HEADER_WIDTH, min(x+8, self._content_right()-width))
            rect = QRectF(left, viewport.top()+30, width, 28)
            painter.fillRect(rect, QColor(palette.background))
            painter.setPen(QColor(palette.clip_text))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def _count_paint_item(self, kind, count=1, *, bounds=None):
        if bounds is not None and (bounds.bottom() <= self.RULER_HEIGHT or bounds.top() >= self.height()):
            return False
        stats = getattr(self, '_paint_item_counts', None)
        if stats is not None:
            stats[kind] = stats.get(kind, 0) + count
            return True
        return False

    def _paint_timeline_contents(self, painter, event, palette, *, timing_only=False):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(palette.background))
        painter.fillRect(
            QRectF(0, 0, self.TRACK_HEADER_WIDTH, self._canvas_bottom()),
            QColor(palette.header),
        )
        painter.fillRect(
            QRectF(self.TRACK_HEADER_WIDTH, 0, self._content_right() - self.TRACK_HEADER_WIDTH, self.RULER_HEIGHT),
            QColor(palette.ruler),
        )
        speaker_rects, translation_rect, waveform_rect = self._track_layout()
        track_viewport = self._track_viewport()
        sequence = sequence_of(self.project) if self.project else None
        sequence_runtime = runtime_of(self.project) if self.project else None
        if sequence is not None and (sequence.in_point_ms is not None or sequence.out_point_ms is not None):
            from .project_range import effective_range
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            start, end = effective_range(self.project)
            left = max(self.TRACK_HEADER_WIDTH, self._time_to_x(start))
            right = min(self._content_right(), self._time_to_x(end))
            if right > left:
                painter.fillRect(QRectF(left,0,right-left,self.RULER_HEIGHT),QColor(147,191,165,45))
            for value, direction, label in ((sequence.in_point_ms,1,'I'),(sequence.out_point_ms,-1,'O')):
                if value is None:continue
                x = self._time_to_x(value)
                if not self.TRACK_HEADER_WIDTH <= x <= self._content_right():continue
                painter.setPen(QColor('#93bfa5')); painter.setBrush(QColor('#93bfa5'))
                painter.drawPolygon(QPolygonF([QPointF(x,0),QPointF(x+direction*10,0),QPointF(x,12)]))
                painter.drawLine(QPointF(x,0),QPointF(x,self.RULER_HEIGHT))
                painter.drawText(QRectF(x-9,13,18,16),Qt.AlignCenter,label)
        overscan = max(1_000, int(self.visible_duration_ms * 0.02))
        visible_start = max(0, int(self.visible_start_ms) - overscan)
        visible_end = int(self.visible_start_ms + self.visible_duration_ms) + overscan
        visible_segments = (
            sequence_runtime.visible_segments(visible_start, visible_end)
            if sequence_runtime is not None else None
        )
        visible_candidates = (
            sequence_runtime.visible_candidates(visible_start, visible_end)
            if sequence_runtime is not None else None
        )
        visible_markers = (
            sequence_runtime.visible_markers(visible_start, visible_end)
            if sequence_runtime is not None else None
        )
        video_rect = self._video_tracks_rect()
        if sequence is not None and not timing_only:
            self._paint_video_lanes(
                painter,
                palette,
                sequence=sequence,
                visible_segments=visible_segments,
            )
            candidate_rect = self._candidate_lane_rect()
            if candidate_rect is not None:
                def map_candidate_source(source_ms: int):
                    segment = sequence_runtime.segment_for_source(source_ms)
                    if segment is None:
                        return None
                    return source_to_timeline(sequence, source_ms, segment=segment)

                paint_candidate_lane(
                    painter,
                    sequence,
                    palette,
                    candidate_rect,
                    self.TRACK_HEADER_WIDTH,
                    self._content_right(),
                    self._time_to_x,
                    map_candidate_source,
                    visible_candidates,
                )
            paint_markers(
                painter,
                sequence,
                palette,
                self.RULER_HEIGHT,
                self._time_to_x,
                self.TRACK_HEADER_WIDTH,
                self._content_right(),
                visible_markers,
            )

        dirty_rect = event.region().boundingRect()
        if (
            sequence is not None
            and not dirty_rect.isEmpty()
            and dirty_rect.top() >= round(video_rect.top())
            and dirty_rect.bottom() <= round(video_rect.bottom())
        ):
            # Razor/segment-selection invalidation is confined to the video
            # lanes. Avoid rebuilding cue text layouts and reading/drawing
            # waveform LODs — but the lanes themselves (clips + headers) must
            # be repainted, or the invalidated region erases them.
            # 四十八轮（用户实测"划过依旧消失"）：音频行 A2 夹在 V2/V1 视频泳道
            # 之间——联合矩形天然包含 A2，悬停 A2 的 solo/master 图标命中的正是
            # 本路径；此前只补画视频轨，A2 图标被背景清除后无人补画（用户截图
            # 实证：muted 在、solo+皇冠消失）。音频轨头必须一起补画。
            self._paint_linked_audio_tracks(painter, palette)
            x = self._time_to_x(self.playhead_ms)
            painter.setClipRect(QRectF(self.TRACK_HEADER_WIDTH, video_rect.top(),
                                       max(1, self._content_right() - self.TRACK_HEADER_WIDTH),
                                       video_rect.height()))
            painter.setPen(QPen(QColor(palette.playhead), 1.5))
            painter.drawLine(round(x), round(video_rect.top()), round(x), round(video_rect.bottom()))
            painter.end()
            return

        if (
            not dirty_rect.isEmpty()
            and dirty_rect.right() < self.TRACK_HEADER_WIDTH
            and dirty_rect.top() >= self.RULER_HEIGHT
        ):
            # Hover/focus invalidation in track controls must never traverse
            # thousands of visible cue blocks. The header background was
            # cleared above; repaint only the affected control icons.
            # Linked-audio controls share this custom-painted header. They
            # must be redrawn after the background clear or hover erases them.
            # 2026-09-06（四图反馈·图二）：视频轨头图标同在此列——此前 V1/V2
            # 轨道头图标在悬停/选中触发的局部重绘中被清空后无人补画，
            # 用户看到"划过图标就消失"。
            self._paint_linked_audio_tracks(painter, palette)
            self._paint_video_lane_headers(painter, palette, QRect(dirty_rect))
            for speaker_id, rect in speaker_rects.items():
                if not rect.intersects(QRectF(dirty_rect)):
                    continue
                visibility = "fa5s.eye-slash" if speaker_id in self.hidden_speakers else "fa5s.eye"
                lock = "fa5s.lock" if speaker_id in self.locked_speakers else "fa5s.unlock"
                for action, icon_name in (('visibility', visibility), ('lock', lock), ('more', 'fa5s.trash-alt')):
                    paint_button(painter, palette, 'subtitle', action, rect, icon_name,
                                 active=self._hover_header_action == (speaker_id, action)
                                     or action == 'visibility' and speaker_id in self.hidden_speakers
                                     or action == 'lock' and speaker_id in self.locked_speakers,
                                 disabled=action == 'more' and speaker_id in self.locked_speakers)
            painter.end()
            return

        for index, rect in enumerate(speaker_rects.values()):
            visible_rect = rect.intersected(track_viewport)
            if visible_rect.isEmpty():
                continue
            painter.fillRect(
                QRectF(self.TRACK_HEADER_WIDTH, visible_rect.top(), self._content_right() - self.TRACK_HEADER_WIDTH, visible_rect.height()),
                QColor(palette.track_background if index % 2 == 0 else palette.track_alternate),
            )
        if translation_rect:
            visible_translation = translation_rect.intersected(track_viewport)
            painter.fillRect(
                QRectF(self.TRACK_HEADER_WIDTH, visible_translation.top(), self._content_right() - self.TRACK_HEADER_WIDTH, visible_translation.height()),
                mix(palette.track_background, palette.translation_clip, 0.3),
            )
        if self.waveform_visible and not timing_only:
            painter.fillRect(
                QRectF(self.TRACK_HEADER_WIDTH, waveform_rect.top(), self._content_right() - self.TRACK_HEADER_WIDTH, waveform_rect.height()),
                QColor(palette.waveform_background),
            )

        content_width = max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
        major_ms, minor_ms = adaptive_timeline_ticks(self.visible_duration_ms, content_width)
        first_tick = (self.visible_start_ms // minor_ms) * minor_ms
        tick = first_tick
        last_label_right = -10_000
        while tick <= self.visible_start_ms + self.visible_duration_ms:
            x = self._time_to_x(tick)
            is_major = tick % major_ms == 0
            if is_major:
                painter.setPen(QPen(QColor(palette.grid_major), 1))
                painter.drawLine(round(x), self.RULER_HEIGHT - 10, round(x), self._canvas_bottom())
                painter.setPen(QColor(palette.time_label))
                font = painter.font()
                font.setPointSize(9)
                painter.setFont(font)
                label = format_timeline_ruler_label(tick, major_ms)
                label_width = painter.fontMetrics().horizontalAdvance(label) + 10
                label_left = round(x - label_width / 2)
                label_left = max(self.TRACK_HEADER_WIDTH + 2, min(self._content_right() - label_width - 2, label_left))
                if label_left >= last_label_right + 8:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(mix(palette.ruler, palette.header_hover, 0.32))
                    painter.drawRoundedRect(QRectF(label_left, 2, label_width, 21), 3, 3)
                    painter.setPen(QColor(palette.time_label))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawText(
                        QRectF(label_left, 3, label_width, 20),
                        Qt.AlignmentFlag.AlignCenter,
                        label,
                    )
                    last_label_right = label_left + label_width
            else:
                painter.setPen(QPen(QColor(palette.grid_minor), 1))
                painter.drawLine(round(x), self.RULER_HEIGHT - 5, round(x), self.RULER_HEIGHT)
            tick += minor_ms

        painter.setPen(QPen(mix(palette.grid_minor, palette.background, 0.4), 1))
        for rect in [*speaker_rects.values(), *([translation_rect] if translation_rect else []), waveform_rect]:
            if 0 <= rect.bottom() <= self._canvas_bottom():
                painter.drawLine(0, round(rect.bottom()), self._content_right(), round(rect.bottom()))
        painter.drawLine(self.TRACK_HEADER_WIDTH, 0, self.TRACK_HEADER_WIDTH, self._canvas_bottom())

        painter.save()
        painter.setClipRect(track_viewport,Qt.ClipOperation.IntersectClip)
        paint_rects = list(event.region())
        content_rects = [
            rect for rect in paint_rects
            if rect.right() >= self.TRACK_HEADER_WIDTH
            and rect.intersects(track_viewport.toAlignedRect())
        ]
        if content_rects and all(rect.width() < self.width() * 0.6 for rect in content_rects):
            visible_cues = []
            seen_cues: set[str] = set()
            for rect in content_rects:
                start_ms = self._x_to_time(max(self.TRACK_HEADER_WIDTH, rect.left() - 4))
                end_ms = self._x_to_time(min(self._content_right(), rect.right() + 4)) + 1
                for cue in self._cues_intersecting(start_ms, end_ms):
                    if cue.id not in seen_cues:
                        seen_cues.add(cue.id)
                        visible_cues.append(cue)
        else:
            visible_cues = self.visible_cues()
        # At multi-hour overview scale thousands of cues collapse onto fewer
        # horizontal pixels.  Running font measurement and rounded-rect text
        # layout for every sub-pixel cue makes an otherwise harmless expose or
        # focus repaint block the GUI for close to a second.  Preserve the
        # ordinary editable rendering path, but coalesce dense overview cues
        # into pixel spans (selected cues are painted again below).
        dense_cue_overview = len(visible_cues) > max(1_200, content_width * 2)
        visible_by_speaker: dict[str, list[StudioCue]] = {}
        dense_spans_by_speaker: dict[str, tuple[tuple[int, int], ...]] = {}
        dense_selected_by_speaker: dict[str, list[StudioCue]] = {}
        dense_all_selected = self.selection_scope.mode == SelectionMode.ALL
        if dense_cue_overview:
            span_key = (
                int(self.visible_start_ms), int(self.visible_duration_ms),
                int(self._content_right()), tuple(self._speaker_ids),
            )
            dense_spans_by_speaker = self._dense_cue_span_cache.get(span_key, {})
            if not dense_spans_by_speaker:
                grouped: dict[str, list[StudioCue]] = {}
                for cue in visible_cues:
                    grouped.setdefault(cue.speaker_id, []).append(cue)
                built: dict[str, tuple[tuple[int, int], ...]] = {}
                for speaker_id, cues in grouped.items():
                    spans: list[tuple[int, int]] = []
                    for cue in cues:
                        left = max(self.TRACK_HEADER_WIDTH, round(self._time_to_x(cue.start_ms)))
                        right = min(self._content_right(), round(self._time_to_x(cue.end_ms)))
                        if right < self.TRACK_HEADER_WIDTH or left > self._content_right():
                            continue
                        right = max(left + 1, right)
                        if spans and left <= spans[-1][1] + 1:
                            spans[-1] = (spans[-1][0], max(spans[-1][1], right))
                        else:
                            spans.append((left, right))
                    built[speaker_id] = tuple(spans)
                dense_spans_by_speaker = built
                self._dense_cue_span_cache[span_key] = built
                while len(self._dense_cue_span_cache) > 8:
                    self._dense_cue_span_cache.pop(next(iter(self._dense_cue_span_cache)))
            if self.selection_scope.mode in {
                SelectionMode.EMPTY,
                SelectionMode.EXPLICIT_IDS,
            }:
                selected_ids = set(self.selection_scope.explicit_ids)
                if self.selected_id:
                    selected_ids.add(self.selected_id)
                for cue_id in selected_ids:
                    cue = self._timeline_cue_by_id.get(cue_id)
                    if (
                        cue is not None
                        and cue.end_ms > visible_start
                        and cue.start_ms < visible_end
                    ):
                        dense_selected_by_speaker.setdefault(cue.speaker_id, []).append(cue)
            elif not dense_all_selected:
                for cue in visible_cues:
                    if self._cue_is_selected(cue):
                        dense_selected_by_speaker.setdefault(cue.speaker_id, []).append(cue)
        else:
            for cue in visible_cues:
                speaker_id = (
                    self._drag_speaker_preview
                    if self._drag and cue.id == self._drag[0] and self._drag_speaker_preview
                    else cue.speaker_id
                )
                visible_by_speaker.setdefault(speaker_id, []).append(cue)
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for index, (speaker_id, rect) in enumerate(speaker_rects.items()):
            color = _speaker_color(self.project, speaker_id, palette)
            name = _speaker_name(self.project, speaker_id)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(14, rect.center().y() - 5, 10, 10))
            painter.setPen(QColor(palette.header_letter))
            letter_font = painter.font()
            letter_font.setPointSize(12 if rect.height() < 84 else 13)
            painter.setFont(letter_font)
            painter.drawText(QRectF(34, rect.top(), 24, rect.height()), Qt.AlignmentFlag.AlignVCenter, letters[index % len(letters)])
            painter.setPen(QColor(palette.header_name))
            name_font = painter.font()
            name_font.setPointSize(14 if rect.height() < 84 else 16)
            name_font.setBold(True)
            painter.setFont(name_font)
            painter.drawText(QRectF(55, rect.top(), CONTROL_LEFT - 61, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(name, Qt.ElideRight, CONTROL_LEFT - 61))
            name_font.setBold(False)
            painter.setFont(name_font)
            visibility = "fa5s.eye-slash" if speaker_id in self.hidden_speakers else "fa5s.eye"
            lock = "fa5s.lock" if speaker_id in self.locked_speakers else "fa5s.unlock"
            for action, icon_name in (('visibility', visibility), ('lock', lock), ('more', 'fa5s.trash-alt')):
                paint_button(painter, palette, 'subtitle', action, rect, icon_name,
                             active=self._hover_header_action == (speaker_id, action)
                                 or action == 'visibility' and speaker_id in self.hidden_speakers
                                 or action == 'lock' and speaker_id in self.locked_speakers,
                             disabled=action == 'more' and speaker_id in self.locked_speakers)
            if speaker_id in self.hidden_speakers:
                continue
            if dense_cue_overview:
                painter.setPen(QPen(
                    QColor(palette.clip_selected_border) if dense_all_selected else palette.clip_border(color),
                    2.0 if dense_all_selected else 1.0,
                ))
                painter.setBrush(palette.clip_fill(color, dense_all_selected))
                for left, right in dense_spans_by_speaker.get(speaker_id, ()):
                    self._count_paint_item('dense_cue_spans', bounds=rect.adjusted(0, 7, 0, -7))
                    painter.drawRect(
                        QRectF(
                            left,
                            rect.top() + 7,
                            max(1, right - left),
                            rect.height() - 14,
                        )
                    )
                selected = dense_selected_by_speaker.get(speaker_id, ())
                painter.setPen(QPen(QColor(palette.clip_selected_border), 2.0))
                painter.setBrush(palette.clip_fill(color, True))
                for cue in selected:
                    self._count_paint_item('cue_items', bounds=rect.adjusted(0, 5, 0, -5))
                    left = max(self.TRACK_HEADER_WIDTH, self._time_to_x(cue.start_ms))
                    right = min(self._content_right(), self._time_to_x(cue.end_ms))
                    painter.drawRect(
                        QRectF(
                            left,
                            rect.top() + 5,
                            max(3.0, right - left),
                            rect.height() - 10,
                        )
                    )
                continue
            for cue in visible_by_speaker.get(speaker_id, ()):
                left = self._time_to_x(cue.start_ms)
                right = self._time_to_x(cue.end_ms)
                if right < self.TRACK_HEADER_WIDTH or left > self._content_right():
                    continue
                clipped_left = max(self.TRACK_HEADER_WIDTH, left)
                clipped_right = min(self._content_right(), right)
                block = QRectF(clipped_left, rect.top() + 7, max(4, clipped_right - clipped_left), rect.height() - 14)
                self._count_paint_item('cue_items', bounds=block)
                selected = cue.id == self.selected_id
                multi_selected = self.selection_scope.contains(
                    cue.id,
                    row=self._timeline_row_by_id.get(cue.id),
                )
                # At a ten-minute scale most cues are only 4–12 pixels wide.
                # Text shaping, rounded corners and the inset stripe have no
                # visible information at that size; hit testing stays indexed.
                if block.width() < 24 and not selected:
                    painter.setPen(QPen(QColor(palette.clip_multi_border) if multi_selected else palette.clip_border(color), 1))
                    painter.setBrush(palette.clip_fill(color, False))
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                    painter.drawRect(block)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    continue
                fill = palette.clip_fill(color, selected)
                if selected:
                    painter.setPen(QPen(QColor(palette.clip_selected_border), 3.0))
                    painter.setBrush(rgba_color(palette.clip_selected_glow))
                    painter.drawRoundedRect(block.adjusted(-2, -2, 2, 2), 6, 6)
                    painter.setBrush(fill)
                else:
                    painter.setPen(QPen(
                        QColor(palette.clip_multi_border) if multi_selected else palette.clip_border(color),
                        1.6 if multi_selected else 1.2,
                    ))
                painter.setBrush(fill)
                painter.drawRoundedRect(block, 5, 5)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color.darker(112))
                painter.drawRoundedRect(QRectF(block.left() + 1, block.top() + 1, 3, block.height() - 2), 1.5, 1.5)
                painter.setPen(QColor(palette.clip_text))
                available = max(8, int(block.width()) - 26)
                inner = block.adjusted(11, 4, -8, -4)
                row_height = rect.height()
                font = self._timeline_text_font(round(row_height), block.width())
                painter.setFont(font)
                if available < 36:
                    max_lines = 1
                elif available < 96 or row_height < 58:
                    max_lines = 1
                elif row_height < 100:
                    max_lines = 2
                else:
                    max_lines = 3
                metrics = QFontMetrics(font)
                flags = int(Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap)
                if available < 28:
                    label = ""
                else:
                    bounds = metrics.boundingRect(inner.toRect(), flags, cue.text)
                    label = cue.text
                    if bounds.height() > inner.height() or max_lines == 1:
                        label = metrics.elidedText(
                            cue.text.replace("\n", " "),
                            Qt.TextElideMode.ElideRight,
                            available * max_lines,
                        )
                painter.drawText(inner, flags, label)
                if selected:
                    painter.setPen(QPen(QColor(palette.handle_dot_border), 1))
                    painter.setBrush(QColor(palette.handle_dot_fill))
                    for handle_x in (block.left(), block.right()):
                        painter.drawEllipse(QRectF(handle_x - 3, block.center().y() - 5, 6, 10))

        translations = self.project.generation_metadata.get("translations", {}) if self.project else {}
        if translation_rect:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.translation_dot))
            painter.drawEllipse(QRectF(14, translation_rect.center().y() - 5, 10, 10))
            painter.setPen(QColor(palette.header_name))
            translation_font = painter.font()
            translation_font.setBold(True)
            painter.setFont(translation_font)
            painter.drawText(QRectF(34, translation_rect.top(), 170, translation_rect.height()), Qt.AlignmentFlag.AlignVCenter, "翻译")
            translation_font.setBold(False)
            painter.setFont(translation_font)
            if isinstance(translations, dict) and translations:
                for cue in visible_cues:
                    text = str(translations.get(cue.id, "") or "")
                    if not text:
                        continue
                    left = max(self.TRACK_HEADER_WIDTH, self._time_to_x(cue.start_ms))
                    right = min(self._content_right(), self._time_to_x(cue.end_ms))
                    if right <= self.TRACK_HEADER_WIDTH or left >= self._content_right():
                        continue
                    block = QRectF(left, translation_rect.top() + 6, max(4, right - left), translation_rect.height() - 12)
                    self._count_paint_item('translation_items', bounds=block)
                    painter.setPen(QPen(QColor(palette.translation_clip_border), 1))
                    painter.setBrush(QColor(palette.translation_clip))
                    painter.drawRoundedRect(block, 5, 5)
                    painter.setPen(QColor(palette.translation_clip_text))
                    label = QFontMetrics(painter.font()).elidedText(text, Qt.TextElideMode.ElideRight, max(8, int(block.width()) - 16))
                    painter.drawText(block.adjusted(8, 2, -6, -2), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine, label)

        painter.restore()

        if not timing_only:self._paint_linked_audio_tracks(painter, palette)
        if self._marquee_rect is not None:
            painter.setPen(QPen(QColor(palette.selection_rect), 1.3, Qt.PenStyle.DashLine))
            painter.setBrush(rgba_color(palette.selection_fill))
            painter.drawRect(self._marquee_rect)
        if self.tool_mode == "razor":
            self._paint_razor_preview(painter, palette)
        elif self.tool_mode == "merge":
            self._paint_merge_preview(painter, palette)
    def _paint_timing_guides(self,painter,palette):
        if self._drag and self._drag_preview:
            start, end = self._drag_preview
            painter.save()
            painter.setClipRect(QRect(self.TRACK_HEADER_WIDTH, 0,
                                     self._content_right()-self.TRACK_HEADER_WIDTH, self._canvas_bottom()))
            painter.setPen(QPen(QColor(palette.clip_selected_border), 1, Qt.PenStyle.DashLine))
            for time_ms in (start, end):
                x = round(self._time_to_x(time_ms))
                painter.drawLine(x, self.RULER_HEIGHT, x, self._canvas_bottom())
            label = f"{_format_ms(start)} → {_format_ms(end)}   {(end-start)/1000:.3f}s"
            font = painter.font(); font.setPointSize(10); painter.setFont(font)
            width = QFontMetrics(font).horizontalAdvance(label) + 20
            left = min(max(self.TRACK_HEADER_WIDTH, self._time_to_x(start)), self._content_right()-width)
            rect = QRectF(left, self.RULER_HEIGHT + 2, width, 26)
            painter.fillRect(rect, QColor(palette.background))
            painter.setPen(QColor(palette.clip_text))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
            painter.restore()

    def _paint_transport_cursor(self, painter, palette):
        # 2026-09-19：播放头竖线/标签必须裁剪在内容区（>= 轨头宽）。
        # 播放头在视口左侧之外（手动滚动、跟随关闭）时 _time_to_x 会给出
        # 落在轨头列内的 x，未裁剪的竖线会画到 S01/V1/A1 控制区之上。
        content_left = self.TRACK_HEADER_WIDTH
        content_width = max(1, self._content_right() - content_left)
        painter.save()
        painter.setClipRect(QRectF(content_left, 0, content_width, self._canvas_bottom()))
        x = self._time_to_x(self.playhead_ms)
        painter.setPen(QPen(QColor(palette.playhead), 1.5))
        painter.drawLine(round(x), 0, round(x), self._canvas_bottom())
        playhead_label = _format_ms(self.playhead_ms)
        label_width = 82
        label_left = max(
            content_left,
            min(self._time_to_x(self.playhead_ms) - label_width / 2, self._content_right() - label_width),
        )
        label_rect = QRectF(label_left, 4, label_width, 23)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.playhead))
        painter.drawRoundedRect(label_rect, 4, 4)
        painter.setPen(QColor(palette.playhead_label_text))
        label_font = painter.font()
        label_font.setBold(True)
        label_font.setPointSize(8)
        painter.setFont(label_font)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, playhead_label)
        painter.restore()

    # ------------------------------------------------------------------
    # Razor / merge tool previews
    # ------------------------------------------------------------------

    TOOL_ACCENT = "#FF7A1A"
    TOOL_ACCENT_DIM = "#FFB25C"

    def _razor_preview(self) -> tuple[object, StudioCue] | None:
        """Resolve the razor cut for the active drag (drag-only; no hover)."""
        if self._razor_drag is None:
            return None
        cue = self._timeline_cue_by_id.get(str(self._razor_drag["cue_id"]))
        if cue is None:
            return None
        split_ms = self._snap_time(int(self._razor_drag["split_ms"]), cue.id)
        preview = resolve_split(cue, split_ms, project=self.project)
        return (preview, cue) if preview is not None else None

    def _merge_state(self) -> tuple[StudioCue | None, StudioCue | None, int]:
        """Return (anchor, neighbour, direction) for the merge tool painting."""
        if self._merge_drag is not None and self._merge_drag["direction"]:
            anchor = self._timeline_cue_by_id.get(str(self._merge_drag["anchor_id"]))
            neighbor = self._timeline_cue_by_id.get(str(self._merge_drag["neighbor_id"]))
            return anchor, neighbor, int(self._merge_drag["direction"])
        if self._merge_anchor_id:
            return self._timeline_cue_by_id.get(self._merge_anchor_id), None, 0
        return None, None, 0

    _TOOL_CARD_TEXT_FLAGS = int(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
    )

    def _tool_card_row_heights(
        self, rows: list[tuple[str, str, str]], card_width: float
    ) -> list[int]:
        """Wrapped text height per row. Long sentences must stay fully
        readable on the card (user feedback 2026-09-03: elided preview text
        hides where the cut lands), so text wraps instead of truncating."""
        body_font = QFont()
        body_font.setPointSize(12)
        metrics = QFontMetrics(body_font)
        text_width = max(120.0, card_width - 56.0)
        heights: list[int] = []
        for _label, text, _meta in rows:
            wrapped = metrics.boundingRect(
                QRect(0, 0, int(text_width), 4),
                self._TOOL_CARD_TEXT_FLAGS,
                text,
            )
            heights.append(max(24, wrapped.height()))
        return heights

    def _tool_card_geometry(
        self,
        rows: list[tuple[str, str, str]],
        title: str,
        anchor_x: float,
        track: QRectF,
    ) -> QRectF:
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        body_font = QFont()
        body_font.setPointSize(12)
        metrics = QFontMetrics(body_font)
        title_metrics = QFontMetrics(title_font)
        widest = max(
            [title_metrics.horizontalAdvance(title)]
            + [metrics.horizontalAdvance(text) for _label, text, _meta in rows],
            default=200,
        )
        card_width = max(
            360.0,
            min(max(520.0, float(self.width() - 24.0)), widest + 72.0),
        )
        heights = self._tool_card_row_heights(rows, card_width)
        card_height = 44 + sum(30 + height for height in heights) + 8
        left = min(
            max(self.TRACK_HEADER_WIDTH + 4.0, anchor_x - card_width / 2),
            max(self.TRACK_HEADER_WIDTH + 4.0, self.width() - card_width - 6.0),
        )
        top = track.top() - card_height - 14
        if top < self.RULER_HEIGHT + 4:
            top = min(
                track.bottom() + 14,
                max(self.RULER_HEIGHT + 4, self._canvas_bottom() - card_height - 6),
            )
        return QRectF(left, top, card_width, card_height)

    def _paint_tool_card(
        self,
        painter: QPainter,
        palette: TimelinePalette,
        rows: list[tuple[str, str, str]],
        title: str,
        anchor_x: float,
        track: QRectF,
    ) -> None:
        card = self._tool_card_geometry(rows, title, anchor_x, track)
        heights = self._tool_card_row_heights(rows, card.width())
        accent = QColor(self.TOOL_ACCENT)
        background = QColor(palette.background).darker(114)
        background.setAlpha(255)
        painter.setPen(QPen(accent, 2.0))
        painter.setBrush(background)
        painter.drawRoundedRect(card, 9, 9)
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(accent)
        painter.drawText(
            QRectF(card.left() + 16, card.top() + 8, card.width() - 32, 24),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            title,
        )
        body_font = QFont()
        body_font.setPointSize(12)
        meta_font = QFont()
        meta_font.setPointSize(8)
        meta_font.setBold(False)
        meta_metrics = QFontMetrics(meta_font)
        y = card.top() + 42
        for (label, text, meta), height in zip(rows, heights):
            chip = QRectF(card.left() + 14, y, 46, 22)
            chip_color = QColor(self.TOOL_ACCENT)
            chip_color.setAlpha(46)
            painter.setPen(QPen(QColor(self.TOOL_ACCENT_DIM), 1.0))
            painter.setBrush(chip_color)
            painter.drawRoundedRect(chip, 5, 5)
            painter.setFont(meta_font)
            painter.setPen(QColor(self.TOOL_ACCENT_DIM))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
            if meta:
                painter.setPen(QColor(palette.time_label))
                painter.drawText(
                    QRectF(card.right() - 16 - meta_metrics.horizontalAdvance(meta), y, 200, 22),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    meta,
                )
            painter.setFont(body_font)
            painter.setPen(QColor(palette.clip_text))
            painter.drawText(
                QRectF(card.left() + 16, y + 26, max(120.0, card.width() - 32.0), height),
                self._TOOL_CARD_TEXT_FLAGS,
                text,
            )
            y += 30 + height

    def _paint_razor_preview(self, painter: QPainter, palette: TimelinePalette) -> None:
        resolved = self._razor_preview()
        if resolved is None:
            return
        preview, cue = resolved
        accent = QColor(self.TOOL_ACCENT)
        x = self._time_to_x(preview.split_ms)
        painter.save()
        # Full-height cut line so the split point reads anywhere on the panel.
        # The cue block itself stays untouched while dragging (2026-09-03 user
        # feedback): painting "already split" halves before the cut happens
        # was misread as a completed split and made short cues vanish.
        painter.setPen(QPen(accent, 2.6))
        painter.drawLine(round(x), 0, round(x), round(self._canvas_bottom()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        marker = QPainterPath(QPointF(x - 8, 0))
        marker.lineTo(QPointF(x + 8, 0))
        marker.lineTo(QPointF(x, 11))
        marker.closeSubpath()
        painter.drawPath(marker)
        painter.restore()
        speaker_rects, _translation, _waveform = self._track_layout()
        track = speaker_rects.get(cue.speaker_id)
        if track is None:
            return
        self._paint_tool_card(
            painter,
            palette,
            [
                (
                    "前段",
                    preview.left_text or "(空)",
                    f"{len(preview.left_text)} 字 · {(preview.left_end_ms - preview.left_start_ms) / 1000:.1f}s",
                ),
                (
                    "后段",
                    preview.right_text or "(空)",
                    f"{len(preview.right_text)} 字 · {(preview.right_end_ms - preview.right_start_ms) / 1000:.1f}s",
                ),
            ],
            f"✂ {_format_ms(preview.split_ms)} · " + ('按字词分配，保留切点' if preview.timing_source == 'exact_token_text' else '文字按比例估算，请试听'),
            x,
            track,
        )

    def _paint_merge_preview(self, painter: QPainter, palette: TimelinePalette) -> None:
        anchor, neighbor, direction = self._merge_state()
        if anchor is None:
            return
        painter.save()
        accent = QColor(self.TOOL_ACCENT)
        speaker_rects, _translation, _waveform = self._track_layout()
        track = speaker_rects.get(anchor.speaker_id)
        if track is None:
            painter.restore()
            return
        fill = QColor(self.TOOL_ACCENT)
        fill.setAlpha(36)
        anchor_left = max(self.TRACK_HEADER_WIDTH, self._time_to_x(anchor.start_ms))
        anchor_right = min(self._content_right(), self._time_to_x(anchor.end_ms))
        painter.setPen(QPen(accent, 2.4))
        painter.setBrush(fill)
        painter.drawRoundedRect(
            QRectF(anchor_left, track.top() + 6, max(4.0, anchor_right - anchor_left), track.height() - 12),
            5, 5,
        )
        if neighbor is not None:
            neighbor_track = speaker_rects.get(neighbor.speaker_id) or track
            neighbor_left = max(self.TRACK_HEADER_WIDTH, self._time_to_x(neighbor.start_ms))
            neighbor_right = min(self._content_right(), self._time_to_x(neighbor.end_ms))
            painter.setPen(QPen(accent, 2.0))
            painter.setBrush(fill)
            painter.drawRoundedRect(
                QRectF(neighbor_left, neighbor_track.top() + 6, max(4.0, neighbor_right - neighbor_left), neighbor_track.height() - 12),
                5, 5,
            )
            # Bold arrow between the two blocks shows the merge direction.
            start_point = QPointF(
                min(max((anchor_left + anchor_right) / 2, self.TRACK_HEADER_WIDTH + 8), self._content_right() - 8),
                track.center().y(),
            )
            end_point = QPointF(
                min(max((neighbor_left + neighbor_right) / 2, self.TRACK_HEADER_WIDTH + 8), self._content_right() - 8),
                neighbor_track.center().y(),
            )
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor(self.TOOL_ACCENT_DIM), 4.0))
            painter.setBrush(QColor(self.TOOL_ACCENT_DIM))
            painter.drawLine(start_point, end_point)
            arrow = QPainterPath()
            delta = end_point - start_point
            length = max(1.0, (delta.x() ** 2 + delta.y() ** 2) ** 0.5)
            unit = QPointF(delta.x() / length, delta.y() / length)
            normal = QPointF(-unit.y(), unit.x())
            head = end_point
            arrow.moveTo(head)
            arrow.lineTo(head - unit * 16 + normal * 8)
            arrow.lineTo(head - unit * 16 - normal * 8)
            arrow.closeSubpath()
            painter.drawPath(arrow)
            painter.restore()
            earlier, later = (
                (anchor, neighbor)
                if (anchor.start_ms, anchor.end_ms, anchor.id) <= (neighbor.start_ms, neighbor.end_ms, neighbor.id)
                else (neighbor, anchor)
            )
            merged_text = earlier.text + later.text
            merged_duration = max(anchor.end_ms, neighbor.end_ms) - min(anchor.start_ms, neighbor.start_ms)
            direction_label = "➔ 向后合并（与下一条）" if direction > 0 else "⬅ 向前合并（与上一条）"
            self._paint_tool_card(
                painter,
                palette,
                [
                    ("前段", earlier.text, f"{len(earlier.text)} 字"),
                    ("后段", later.text, f"{len(later.text)} 字"),
                    ("合并后", merged_text, f"{len(merged_text)} 字 · {merged_duration / 1000:.1f}s"),
                ],
                f"{direction_label} · 松开执行",
                (start_point.x() + end_point.x()) / 2,
                track,
            )
            return
        painter.restore()
        if direction:
            self._paint_tool_card(
                painter,
                palette,
                [],
                "该方向没有可以合并的字幕",
                (anchor_left + anchor_right) / 2,
                track,
            )
            return
        self._paint_tool_card(
            painter,
            palette,
            [("锚点", anchor.text, f"{len(anchor.text)} 字")],
            "已选锚点：按住拖动向左/右合并，或再点击一条字幕配对",
            (anchor_left + anchor_right) / 2,
            track,
        )

    @measured('mouse_press')
    def mousePressEvent(self, event: QMouseEvent):
        self._thumbnails.note_activity()
        self.selected_gap = None
        point = event.position().toPoint()
        # 2026-09-18 VIII：泳道分界线拖动调轨高（优先于其它命中）。
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._track_resize_boundary_at(point) is not None
            and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            kind, _y = self._track_resize_boundary_at(point)
            heights = {"video": self._video_track_height(), "audio": self._audio_track_height(),
                       "subtitle": self._speaker_track_height()}
            self._track_resize_drag = {
                "kind": kind,
                "start_y": event.globalPosition().y(),
                "start_height": heights[kind],
            }
            self.interaction_changed.emit(True)
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            event.accept()
            return
        cue, _mode = self._cue_at(point)
        ruler_area = (
            event.button() == Qt.MouseButton.LeftButton
            and point.y() < self.RULER_HEIGHT
            and point.x() >= self.TRACK_HEADER_WIDTH
        )
        ruler_pan = ruler_area and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        middle_pan = event.button() == Qt.MouseButton.MiddleButton and cue is None
        if ruler_area and not ruler_pan:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._scrub_drag = True
            self.interaction_changed.emit(True)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            milliseconds = self._bounded_time_ms(self._x_to_time(event.position().x()))
            self._paint_playhead_at(milliseconds)
            self.seek_requested.emit(milliseconds / 1000.0)
            event.accept()
            return
        if ruler_pan or middle_pan:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._pan_drag = (event.position().x(), self.visible_start_ms)
            self._pan_drag_moved = False
            self.interaction_changed.emit(True)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.selected_track_header = None
        audio_track_id = self._audio_track_at(point)
        self.selected_audio_track_id = audio_track_id or ""
        if audio_track_id and point.x() < self.TRACK_HEADER_WIDTH:
            self.selected_track_header = ('audio', audio_track_id)
            audio_action = self._audio_header_action_at(point.x(), point.y(), self._audio_track_rects()[audio_track_id])
            if audio_action == 'delete':
                self.track_delete_requested.emit('audio',audio_track_id)
                return
            if audio_action:
                self.audio_track_action_requested.emit(audio_track_id, audio_action)
                self.update(self._audio_track_rects()[audio_track_id].toAlignedRect())
                return
            self.update()
            return
        track_id = self._video_track_at(point)
        if track_id and point.x() < self.TRACK_HEADER_WIDTH:
            self.selected_track_header = ('video', track_id)
        video_rect = self._video_track_rect(track_id) if track_id else QRectF()
        candidate_rect = self._candidate_lane_rect()
        if (
            track_id
            and point.x() < 100
            and event.button() == Qt.MouseButton.LeftButton
            and len(self.project.video_tracks if self.project else []) > 1
        ):
            # 四十六轮：按住轨道头名称区上下拖=整轨换序（泳道与渲染层级
            # 一起对调）。图标区（108px 起）不占用，仍是原有点击行为。
            self._track_reorder_drag = {
                "track_id": track_id,
                "origin_y": event.position().y(),
                "target_track_id": "",
                "moved": False,
            }
            self.interaction_changed.emit(True)
            event.accept()
            return
        if track_id and video_rect.contains(point):
            sequence = sequence_of(self.project) if self.project else None
            self.selected_video_track_id = track_id
            self.video_track_action_requested.emit(track_id, "select")
            if point.x() < self.TRACK_HEADER_WIDTH:
                action = video_track_header_action_at(point.x(), point.y(), self._video_track_rect(track_id))
                if action == "more":
                    self.track_delete_requested.emit('video',track_id)
                elif action:
                    self.video_track_action_requested.emit(track_id, action)
                self.update()
                return
            click_ms = self._x_to_time(event.position().x())
            from .studio_media_pool import primary_video_track_id

            primary_id = primary_video_track_id(self.project) if self.project else "V1"
            clip = self._video_clip_at(track_id, click_ms)
            if self.tool_mode == 'selection':
                row = next(t for t in self.project.video_tracks if t.id == track_id)
                edges = [(abs(event.position().x()-self._time_to_x(value)), c.id != self.selected_video_clip_id, c.id, c)
                         for c in row.clips for value in (c.timeline_in_ms,c.timeline_out_ms)
                         if abs(event.position().x()-self._time_to_x(value)) <= self.VIDEO_CLIP_TRIM_HANDLE_PX]
                if edges:
                    clip = min(edges,key=lambda item:item[:3])[3]
            previous_selection = set(self.selected_segment_ids)
            previous_anchor = self.selected_segment_id
            self.selected_video_clip_id = clip.id if clip else ''
            self.selected_segment_id = ''
            self.selected_segment_ids.clear()
            self.selected_ids.clear()
            self.selection_scope = SelectionScope.empty()
            self.selection_changed.emit(set())
            self.segment_selection_changed.emit(set())
            if clip is None:
                from .studio_clip_edit import lane_gap, video_track_locked
                track = next(t for t in self.project.video_tracks if t.id == track_id)
                if video_track_locked(self.project, track):
                    self.selected_gap = None
                    self.edit_blocked.emit(f'{track_id} 轨道已锁定，请先解锁')
                    self.update()
                    return
                gap = lane_gap(self.project, track_id, click_ms)
                self.selected_gap = (track_id, *gap) if gap and self.tool_mode == 'selection' else None
                if self.selected_gap:
                    self.edit_blocked.emit(f'已选择 {track_id} 空白：Delete 闭合此轨及关联音频；其他轨道保持原位')
                self.update()
                return
            if self.tool_mode == 'selection':
                modifiers = event.modifiers()
                selected = {clip.id}
                if modifiers & Qt.KeyboardModifier.ControlModifier:
                    selected = previous_selection ^ {clip.id}
                elif modifiers & Qt.KeyboardModifier.ShiftModifier and previous_anchor:
                    ordered = [c.id for c in next(t for t in self.project.video_tracks if t.id == track_id).clips]
                    if previous_anchor in ordered:
                        a, b = sorted((ordered.index(previous_anchor), ordered.index(clip.id)))
                        selected = previous_selection | set(ordered[a:b+1])
                elif clip.id in previous_selection:
                    selected = previous_selection
                self.selected_segment_id = clip.id
                self.selected_segment_ids = selected
                self.segment_selected.emit(clip.id)
                self.segment_selection_changed.emit(selected)
                if clip.id not in selected:
                    self.selected_video_clip_id = ''
                    self.update()
                    return
            self.video_clip_selected.emit(track_id, clip.id)
            track = next(t for t in self.project.video_tracks if t.id == track_id)
            if track.locked or (track_id == primary_id and sequence.video_track_locked):
                self.edit_blocked.emit(f'{track_id} 轨道已锁定，请先解锁')
                self.update()
                return
            if self.tool_mode == 'razor':
                self.video_clip_razor_requested.emit(track_id, clip.id, click_ms)
                self.update()
                return
            if self.tool_mode == 'selection':
                self._begin_video_drag(track_id, clip, event)
                self.update()
                return
            self.seek_requested.emit(self._bounded_time_ms(click_ms) / 1000.0)
            self.update(video_rect.toAlignedRect())
            return
        if candidate_rect is not None and candidate_rect.contains(point) and point.x() >= self.TRACK_HEADER_WIDTH:
            sequence = sequence_of(self.project) if self.project else None
            click_ms = self._x_to_time(event.position().x())
            if sequence is not None:
                for candidate in runtime_of(self.project).visible_candidates(click_ms, click_ms + 1):
                    mapped = source_to_timeline(sequence, candidate.source_in_ms)
                    mapped_end = source_to_timeline(sequence, max(candidate.source_in_ms + 1, candidate.source_out_ms - 1))
                    if mapped is None or mapped_end is None:
                        continue
                    if mapped.timeline_ms <= click_ms <= mapped_end.timeline_ms:
                        self.candidate_clicked.emit(candidate.id)
                        break
            self.update()
            return
        if point.x() < self.TRACK_HEADER_WIDTH:
            speaker_rects, _translation, _waveform = self._track_layout()
            for speaker_id, rect in speaker_rects.items():
                if rect.contains(point):
                    self.selected_track_header = ('subtitle', speaker_id)
                    if action_at('subtitle', point.x(), point.y(), rect) == 'visibility':
                        visible = speaker_id in self.hidden_speakers
                        (self.hidden_speakers.remove if visible else self.hidden_speakers.add)(speaker_id)
                        self.subtitle_visibility_changed.emit(speaker_id, visible)
                    elif action_at('subtitle', point.x(), point.y(), rect) == 'lock':
                        (self.locked_speakers.remove if speaker_id in self.locked_speakers else self.locked_speakers.add)(speaker_id)
                    elif action_at('subtitle', point.x(), point.y(), rect) == 'more':
                        self.track_delete_requested.emit('subtitle',speaker_id)
                    self.update()
                    return
        cue, mode = self._cue_at(point)
        if cue:
            self.selected_video_clip_id = ''
            self.selected_video_track_id = ''
            self.selected_segment_id = ""
            self.selected_segment_ids.clear()
            self.segment_selection_changed.emit(set())
            modifiers = event.modifiers()
            if modifiers & Qt.KeyboardModifier.ShiftModifier or modifiers & Qt.KeyboardModifier.ControlModifier:
                current = set(
                    self.selection_scope.materialize(
                        [item.id for item in self._cues_by_start]
                    )
                )
                if modifiers & Qt.KeyboardModifier.ControlModifier:
                    if cue.id in current: current.remove(cue.id)
                    else: current.add(cue.id)
                else:
                    current.add(cue.id)
                self.selected_ids = current
            elif cue.id not in self.selected_ids:
                self.selected_ids = {cue.id}
            self.selected_id = cue.id
            self.selection_scope = SelectionScope.explicit(
                self.selected_ids, self.selected_id
            )
            drag_ids = set(self.selected_ids)
            self.cue_selected.emit(cue.id)
            if self.tool_mode == "razor" and mode != "translation":
                # Press-and-slide shows a full-height cut line plus a large
                # two-sentence preview card; release commits the split.
                self._start_razor_drag(cue.id, event.position().x())
                return
            if self.tool_mode == "merge" and mode != "translation":
                # Click anchors this cue; slide left/right picks the merge
                # direction; a second click on another cue pairs with the
                # anchor. Never auto-merge with the pre-existing selection.
                self._merge_drag = {
                    "anchor_id": cue.id,
                    "prior_anchor_id": self._merge_anchor_id,
                    "origin_x": event.position().x(),
                    "direction": "",
                    "neighbor_id": "",
                }
                self._merge_anchor_id = cue.id
                self.interaction_changed.emit(True)
                self.update()
                return
            if mode != "translation" and cue.speaker_id not in self.locked_speakers:
                self._drag = (cue.id, mode, event.position().x(), cue.start_ms, cue.end_ms)
                self._drag_speaker_preview = cue.speaker_id
                self._drag_originals = {
                    key: CueInterval(item.start_ms, item.end_ms, item.speaker_id)
                    for key in drag_ids
                    if (item := self._timeline_cue_by_id.get(key)) is not None
                    and item.speaker_id not in self.locked_speakers
                }
                self._drag_origin_time = self._x_to_time(event.position().x())
                self._timing_preview = dict(self._drag_originals)
                self.selected_ids = drag_ids
                self.selection_scope = SelectionScope.explicit(drag_ids, cue.id)
                self.selection_changed.emit(drag_ids)
                self.timing_preview_metrics = []
                self.timing_edit_started.emit(dict(self._drag_originals))
                self.interaction_changed.emit(True)
        else:
            # Empty track starts a marquee candidate; a click without movement
            # still resolves to the familiar seek behavior on release.
            # Razor is the exception (2026-09-03 user feedback): pressing on
            # empty track space also starts a cut anchored to the nearest cue,
            # so releasing anywhere commits the cut under the cut line.
            self._merge_anchor_id = ""
            if (
                self.tool_mode == "razor"
                and point.x() >= self.TRACK_HEADER_WIDTH
                and self._track_viewport().contains(point)
            ):
                nearest = self._nearest_cue_for_razor(self._x_to_time(point.x()))
                if nearest is not None:
                    self._start_razor_drag(nearest.id, event.position().x())
                    self.update()
                    return
            self._marquee_origin = point
            self._marquee_rect = QRectF(point, point)
            self.interaction_changed.emit(True)
        self.update()

    def contextMenuEvent(self, event) -> None:
        if event.pos().x() < self.TRACK_HEADER_WIDTH:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            kind, track_id = '', ''
            if self._audio_track_at(event.pos()):kind,track_id='audio',self._audio_track_at(event.pos())
            elif self._video_track_at(event.pos()):kind,track_id='video',self._video_track_at(event.pos())
            else:
                for key,rect in self._track_layout()[0].items():
                    if rect.contains(event.pos()):kind,track_id='subtitle',key;break
            if track_id:
                self.selected_track_header=(kind,track_id)
                if kind=='video':self.video_track_menu_requested.emit(track_id,'',event.globalPos())
                else:self.track_menu_requested.emit(kind,track_id,event.globalPos())
                return
        audio_id = self._audio_track_at(event.pos())
        if audio_id:
            self.selected_audio_track_id = audio_id
            self.track_menu_requested.emit('audio', audio_id, event.globalPos())
            return
        track_id = self._video_track_at(event.pos())
        if track_id:
            clip = (
                self._video_clip_at(track_id, self._x_to_time(event.pos().x()))
                if event.pos().x() >= self.TRACK_HEADER_WIDTH
                else None
            )
            self.video_track_menu_requested.emit(
                track_id,
                clip.id if clip is not None else "",
                event.globalPos(),
            )
            return
        cue, _mode = self._cue_at(event.pos())
        self.context_menu_requested.emit(cue.id if cue else "", event.globalPos())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseDoubleClickEvent(event)
        point = event.position().toPoint()
        # 分界线/控制区把手双击=恢复该类轨高默认（2026-09-19 P1）。
        boundary = self._track_resize_boundary_at(point)
        if boundary is not None:
            self._reset_track_height_kind(str(boundary[0]))
            event.accept()
            return
        track_id = self._video_track_at(point)
        if track_id and point.x() < 126:
            self.video_track_action_requested.emit(track_id, "rename")
            event.accept()
            return
        cue, mode = self._cue_at(event.position().toPoint())
        if not cue:
            return super().mouseDoubleClickEvent(event)
        self.selected_id = cue.id
        self.cue_selected.emit(cue.id)
        translation = mode == "translation"
        translations = self.project.generation_metadata.get("translations", {}) if self.project else {}
        text = str(translations.get(cue.id, "")) if translation and isinstance(translations, dict) else cue.text
        self._open_inline_editor(cue, translation, text)
        event.accept()

    def _open_inline_editor(self, cue: StudioCue, translation: bool, text: str) -> None:
        if self._inline_editor is not None:
            self._cancel_inline_edit()
        speaker_rects, translation_rect, _waveform = self._track_layout()
        track = translation_rect if translation else speaker_rects.get(cue.speaker_id)
        if not track:
            return
        left = max(self.TRACK_HEADER_WIDTH + 2, self._time_to_x(cue.start_ms))
        right = min(self._content_right() - 2, self._time_to_x(cue.end_ms))
        # Keep the editor inside the visible cue block so wrapped text uses the
        # same geometry as the painted cue.
        width = max(24, round(right - left))
        left = min(left, self._content_right() - width - 2)
        editor = _TimelineInlineEdit(self)
        editor.setObjectName("timelineInlineEditor")
        editor.setPlainText(text)
        editor.selectAll()
        row_height = max(24, round(track.height()))
        font = self._timeline_text_font(row_height, width)
        # Editing should be at least as legible as the painted cue.
        font.setPointSize(min(20, font.pointSize() + 1))
        editor.setFont(font)
        editor.setGeometry(round(left), round(track.top() + 4), width, max(32, row_height - 8))
        palette = self._timeline_palette()
        editor.setStyleSheet(
            f"QPlainTextEdit#timelineInlineEditor {{ background: {palette.inline_editor_bg}; "
            f"border: 2px solid {palette.inline_editor_border}; "
            f"border-radius: 5px; padding: 4px 8px; color: {palette.inline_editor_text}; }}"
        )
        editor.commit_requested.connect(
            lambda direction: self._commit_inline_edit(direction)
        )
        editor.cancel_requested.connect(self._cancel_inline_edit)
        self._inline_target = (cue.id, translation)
        self._inline_editor = editor
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def _commit_inline_edit(self, navigate: int = 0) -> None:
        if self._inline_editor is None or self._inline_target is None:
            return
        cue_id, translation = self._inline_target
        text = self._inline_editor.toPlainText()
        self._cancel_inline_edit()
        self.text_edit_committed.emit(cue_id, translation, text)
        if navigate:
            self._open_adjacent_inline_editor(cue_id, translation, navigate)

    def _open_adjacent_inline_editor(
        self, cue_id: str, translation: bool, direction: int
    ) -> None:
        if not self.project:
            return
        ordered = sorted(
            self.project.cues, key=lambda item: (item.start_ms, item.end_ms, item.id)
        )
        index = next((i for i, cue in enumerate(ordered) if cue.id == cue_id), -1)
        target_index = index + (-1 if direction < 0 else 1)
        if index < 0 or not 0 <= target_index < len(ordered):
            return
        cue = ordered[target_index]
        self.selected_id = cue.id
        self.cue_selected.emit(cue.id)
        translations = self.project.generation_metadata.get("translations", {})
        text = (
            str(translations.get(cue.id, ""))
            if translation and isinstance(translations, dict)
            else cue.text
        )
        self._open_inline_editor(cue, translation, text)

    def _cancel_inline_edit(self) -> None:
        editor = self._inline_editor
        self._inline_editor = None
        self._inline_target = None
        if editor is not None:
            editor.hide()
            editor.deleteLater()

    @measured('mouse_move')
    def mouseMoveEvent(self, event: QMouseEvent):
        if self._track_resize_drag is not None:
            drag = self._track_resize_drag
            delta = drag["start_y"] - event.globalPosition().y()  # 上拖=调高
            self.set_track_height(str(drag["kind"]), int(drag["start_height"] + delta))
            event.accept()
            return
        # 分界线悬停光标（仅无其它拖拽/手势活动时接管光标）。
        boundary = self._track_resize_boundary_at(event.position().toPoint())
        pointer_busy = (
            self._drag is not None
            or self._pan_drag
            or self._razor_drag is not None
            or self._merge_drag is not None
            or self._track_reorder_drag
            or self._clip_drag
            or self._segment_drag
            or self._marquee_origin is not None
        )
        if boundary is not None and not pointer_busy:
            kind, _y = boundary
            if not self._track_resize_hover or self._track_resize_hover_kind != kind:
                self.update()  # 把手强调态即时反馈
            self._track_resize_hover = True
            self._track_resize_hover_kind = kind
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            names = {"video": "视频轨", "audio": "音频轨", "subtitle": "字幕轨"}
            bind_text(self, '拖动调整{value0}高度 · 双击恢复默认', property='toolTip', value0=names.get(kind, kind))
        elif getattr(self, "_track_resize_hover", False):
            self._track_resize_hover = False
            self._track_resize_hover_kind = ""
            self.setToolTip("")
            self.unsetCursor()
            self.update()
        if self._razor_drag is not None:
            drag = self._razor_drag
            if abs(event.position().x() - float(drag["origin_x"])) >= QApplication.startDragDistance():
                drag["moved"] = True
            drag["split_ms"] = self._x_to_time(event.position().x())
            # The cut line follows the pointer: sliding it over a different
            # cue retargets the cut to that cue (clamped when over a gap).
            over = next(
                (
                    item for item in self._cues_by_start
                    if item.start_ms <= int(drag["split_ms"]) < item.end_ms
                ),
                None,
            )
            if over is not None and over.id != str(drag["cue_id"]):
                drag["cue_id"] = over.id
            self.update()
            event.accept()
            return
        if self._merge_drag is not None:
            drag = self._merge_drag
            delta = event.position().x() - float(drag["origin_x"])
            if abs(delta) >= QApplication.startDragDistance():
                direction = -1 if delta < 0 else 1
                drag["direction"] = direction
                neighbor = self._merge_neighbor(str(drag["anchor_id"]), direction)
                drag["neighbor_id"] = neighbor.id if neighbor is not None else ""
            self.update()
            event.accept()
            return
        if self._track_reorder_drag:
            drag = self._track_reorder_drag
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if abs(event.position().y() - float(drag["origin_y"])) >= QApplication.startDragDistance():
                drag["moved"] = True
            target = self._video_track_at(event.position().toPoint())
            # 泳道几何只认视频轨 rect；音频行映射回所属视频轨。
            if not target:
                audio_id = self._audio_track_at(event.position().toPoint())
                if audio_id and self.project:
                    groups = {
                        group.audio_track_id: group.video_track_id
                        for group in (getattr(self.project, "av_track_groups", None) or [])
                    }
                    target = groups.get(audio_id, "")
            if target and target != str(drag["track_id"]):
                drag["target_track_id"] = target
            elif target == str(drag["track_id"]):
                drag["target_track_id"] = ""
            self.update()
            event.accept()
            return
        if self._segment_drag:
            drag = self._segment_drag
            if (
                abs(event.position().x() - float(drag["origin_x"])) >= QApplication.startDragDistance()
                or abs(event.position().y() - float(drag["origin_y"])) >= QApplication.startDragDistance()
            ):
                drag["moved"] = True
            target = self._video_track_at(event.position().toPoint())
            if not target:
                # 音频行映射回所属视频轨（与轨道换序手势同款语义）。
                audio_id = self._audio_track_at(event.position().toPoint())
                if audio_id and self.project:
                    groups = {
                        group.audio_track_id: group.video_track_id
                        for group in (getattr(self.project, "av_track_groups", None) or [])
                    }
                    target = groups.get(audio_id, "")
            from .studio_media_pool import primary_video_track_id

            primary_id = primary_video_track_id(self.project) if self.project else ""
            if target and target != primary_id:
                drag["target_track_id"] = target
            else:
                # 拖回主轨/拖出泳道 = 取消（主轨内水平移动不在本轮语义内）。
                drag["target_track_id"] = ""
            self.update()
            event.accept()
            return
        if self._clip_drag:
            self._update_clip_drag(event.position(), event.modifiers())
            event.accept()
            return
        if self._scrub_drag:
            point = event.position().toPoint()
            if point.x() >= self.TRACK_HEADER_WIDTH:
                milliseconds = self._bounded_time_ms(self._x_to_time(point.x()))
                self._paint_playhead_at(milliseconds)
                self.seek_requested.emit(milliseconds / 1000.0)
            event.accept()
            return
        if self._pan_drag:
            origin_x, origin_start = self._pan_drag
            if abs(event.position().x() - origin_x) < QApplication.startDragDistance():
                return
            self._pan_drag_moved = True
            content_width = max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
            delta_ms = round((event.position().x() - origin_x) * self.visible_duration_ms / content_width)
            self.set_visible_window(origin_start - delta_ms, self.visible_duration_ms)
            return
        if self._marquee_origin is not None and not self._drag:
            current = event.position().toPoint()
            self._marquee_rect = QRectF(self._marquee_origin, current).normalized()
            self.update()
            return
        if not self._drag:
            point = event.position().toPoint()
            cue, mode = self._cue_at(point)
            resize_hover = ((cue.id, mode) if cue and mode in {"left", "right"}
                            and cue.speaker_id not in self.locked_speakers and self.tool_mode == "selection" else None)
            if self._resize_hover != resize_hover:
                self._resize_hover = resize_hover
                QWidget.update(self)
            if resize_hover:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                (bind_text(self, '调整字幕起点', property='toolTip') if mode == 'left' else bind_text(self, '调整字幕终点', property='toolTip'))
                return
            if point.y() < self.RULER_HEIGHT and point.x() >= self.TRACK_HEADER_WIDTH:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(
                    Qt.CursorShape.CrossCursor
                    if self.tool_mode == "razor"
                    else Qt.CursorShape.ArrowCursor
                )
            hovered = None
            if point.x() < self.TRACK_HEADER_WIDTH:
                audio_track_id = self._audio_track_at(point)
                audio_action = self._audio_header_action_at(point.x(), point.y(), self._audio_track_rects()[audio_track_id]) if audio_track_id else ""
                if audio_track_id and audio_action:
                    from .studio_track_delete import delete_label
                    hovered = (f"audio:{audio_track_id}", audio_action)
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                    bind_text(self, {'muted': '静音或恢复此音轨', 'solo': 'Solo / 独听（可多选；Mute优先；全关恢复混音）', 'delete': delete_label(self.project, 'audio', audio_track_id) + '（可撤销，不删除文件）'}[audio_action], property='toolTip')
                track_id = self._video_track_at(point)
                action = video_track_header_action_at(point.x(), point.y(), self._video_track_rect(track_id)) if track_id else ""
                if hovered is None and track_id and action:
                    from .studio_track_delete import delete_label
                    hovered = (f"video:{track_id}", action)
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                    tooltips = {
                        "enabled": "启用或停用视频轨",
                        "locked": "锁定或解锁视频轨",
                        "more": delete_label(self.project, 'video', track_id)+'（可撤销，不删除文件）',
                    }
                    self.setToolTip(tooltips[action])
                if (
                    hovered is None
                    and track_id
                    and point.x() < 100
                    and len(self.project.video_tracks if self.project else []) > 1
                ):
                    # 四十八轮（agy）：轨道头名称区（⠿ 抓手区）可按住上下拖=
                    # 整轨换序。OpenHand 光标 + tooltip 是可拖拽的显式暗示。
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
                    bind_text(self, '按住上下拖动调整轨道层级（上层画面覆盖下层）；拖片段到另一条轨也能交换', property='toolTip')
                speaker_rects, _translation, _waveform = self._track_layout()
                for speaker_id, rect in speaker_rects.items() if hovered is None else ():
                    if not rect.contains(point):
                        continue
                    if action_at('subtitle', point.x(), point.y(), rect) == 'visibility':
                        hovered = (speaker_id, "visibility")
                        bind_text(self, '显示或隐藏该说话人轨道', property='toolTip')
                    elif action_at('subtitle', point.x(), point.y(), rect) == 'lock':
                        hovered = (speaker_id, "lock")
                        bind_text(self, '锁定或解锁该说话人轨道', property='toolTip')
                    elif action_at('subtitle', point.x(), point.y(), rect) == 'more':
                        hovered = (speaker_id, "more")
                        bind_text(self, '删除字幕轨道（可撤销，不删除文件）', property='toolTip')
                    break
            if hovered != self._hover_header_action:
                previous_hover = self._hover_header_action
                self._hover_header_action = hovered
                if hovered is None:
                    self.setToolTip("")
                    QToolTip.hideText()
                self._update_header_hover(previous_hover, hovered)
            if hovered is None and point.x() < CONTROL_LEFT:
                if track_id:
                    track = next(t for t in self.project.video_tracks if t.id == track_id)
                    bind_text(self, '{value0} · 按住上下拖动调整轨道层级', property='toolTip', value0=track.name)
                elif audio_track_id:
                    track = next(t for t in self.project.audio_tracks if t.id == audio_track_id)
                    bind_text(self, '{value0} · {audio_track_id} 波形', property='toolTip', value0=track.name, audio_track_id=audio_track_id)
                else:
                    speaker_id = self._speaker_at(point)
                    if speaker_id:self.setToolTip(_speaker_name(self.project, speaker_id))
            return
        # A non-restarted next-frame callback consumes only the newest input.
        self._pending_timing_pointer = (QPointF(event.position()), perf_counter())
        self._snap_bypass = self._snap_alt_held or bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if not self._timing_frame_timer.isActive():
            self._timing_frame_timer.start()

    def _flush_timing_preview(self) -> None:
        if not self._drag or self._pending_timing_pointer is None:
            return
        point, received = self._pending_timing_pointer
        self._pending_timing_pointer = None
        started = perf_counter()
        cue_id, mode, _origin_x, start_ms, end_ms = self._drag
        target_speaker = self._speaker_at(point.toPoint())
        if target_speaker and target_speaker not in self.locked_speakers:
            self._drag_speaker_preview = target_speaker
        self.setCursor(Qt.CursorShape.SizeHorCursor if mode in {"left", "right"} else Qt.CursorShape.ClosedHandCursor)
        delta = self._x_to_time(point.x()) - self._drag_origin_time
        edge = end_ms if mode == "right" else start_ms
        delta = self._snap_time(edge + delta, cue_id) - edge
        self._timing_preview = preview_intervals(self._drag_originals, cue_id, mode, delta,
                                                target_speaker=self._drag_speaker_preview)
        anchor = self._timing_preview[cue_id]
        if self._snap_target and (anchor.end_ms if mode == "right" else anchor.start_ms) != self._snap_target["time"]:
            self._snap_target = None
        start, end = anchor.start_ms, anchor.end_ms
        self._drag_preview = (start, end)
        self._visible_cue_window_key = None
        self.timing_preview_changed.emit(dict(self._timing_preview))
        self.timing_preview_metrics.append({'input_to_flush_ms': (started-received)*1000,
                                            'flush_ms': (perf_counter()-started)*1000})
        self._timing_paint_input = (received, self.timing_preview_metrics[-1])
        QWidget.update(self)

    def cancel_timing_edit(self) -> bool:
        if not self._drag:
            return False
        self._clear_timing_edit()
        self.timing_edit_finished.emit(False)
        self.interaction_changed.emit(False)
        return True

    def _clear_timing_edit(self) -> None:
        self._timing_frame_timer.stop()
        self._pending_timing_pointer = None
        self._drag = None
        self._drag_preview = None
        self._drag_speaker_preview = ""
        self._drag_originals = {}
        self._timing_preview = {}
        self._snap_target = None
        self._resize_hover = None
        self._snap_bypass = False
        self._snap_alt_held = False
        self.setToolTip("")
        self._visible_cue_window_key = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.selected_gap = None
            if self._clip_drag:
                self._clip_drag = None
                self._clip_scroll_timer.stop()
                self.setToolTip("")
                self.unsetCursor()
                self._snap_target = None
                self.interaction_changed.emit(False)
                self.set_visible_window(self.visible_start_ms, self.visible_duration_ms)
            self.update()
        if event.key() == Qt.Key.Key_Alt and self._drag:
            self._snap_alt_held = True
            self._snap_bypass = True
            self._snap_target = None
            QWidget.update(self)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.cancel_timing_edit():
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Alt:
            self._snap_alt_held = False
            self._snap_bypass = False
            event.accept()
            return
        super().keyReleaseEvent(event)

    def hideEvent(self, event) -> None:
        self.cancel_timing_edit()
        super().hideEvent(event)

    def leaveEvent(self, event) -> None:
        self._resize_hover = None
        self._track_resize_hover = False
        self._track_resize_hover_kind = ""
        QWidget.update(self)
        previous_hover = self._hover_header_action
        self._hover_header_action = None
        self.setToolTip("")
        QToolTip.hideText()
        self._update_header_hover(previous_hover, None)
        super().leaveEvent(event)

    @measured('mouse_release')
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._track_resize_drag is not None:
            self._track_resize_drag = None
            self.interaction_changed.emit(False)
            self.unsetCursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._scrub_drag:
            self._scrub_drag = False
            self._paint_playhead_at(self._x_to_time(max(self.TRACK_HEADER_WIDTH, event.position().x())))
            self.scrub_finished.emit(self.playhead_ms / 1000.0)
            self.interaction_changed.emit(False)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._razor_drag is not None:
            # Commit exactly what the screen shows. Re-deriving the split from
            # raw coordinates here (snap -> resolve again) allowed a few ms of
            # drift on the second pass, which lands one character off whenever
            # it crosses a rounding boundary — the user sees the preview card
            # text but gets a different cut. The preview IS the commit source.
            preview_state = self._razor_preview()
            self._razor_drag = None
            self.interaction_changed.emit(False)
            if preview_state is not None:
                preview, cue = preview_state
                self.razor_split_requested.emit(cue.id, int(preview.split_ms))
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._merge_drag is not None:
            drag = self._merge_drag
            self._merge_drag = None
            self.interaction_changed.emit(False)
            if drag["direction"] and drag["neighbor_id"]:
                self.merge_pair_requested.emit(str(drag["anchor_id"]), str(drag["neighbor_id"]))
                self._merge_anchor_id = ""
            else:
                prior = str(drag.get("prior_anchor_id") or "")
                current = str(drag["anchor_id"])
                if prior and prior != current:
                    # Two-click pairing: the previous anchor merges with the
                    # cue that was just clicked.
                    self.merge_pair_requested.emit(prior, current)
                    self._merge_anchor_id = ""
                elif prior:
                    # Clicking the anchored cue again releases the anchor.
                    self._merge_anchor_id = ""
                # else: this click becomes the new anchor; keep it highlighted
                # so the next click pairs with it.
            self.update()
            event.accept()
            return
        if self._track_reorder_drag:
            drag = self._track_reorder_drag
            self._track_reorder_drag = None
            self.interaction_changed.emit(False)
            if drag.get("moved") and drag.get("target_track_id"):
                self.video_track_reorder_requested.emit(
                    str(drag["track_id"]), str(drag["target_track_id"])
                )
            self.update()
            event.accept()
            return
        if self._segment_drag:
            drag = self._segment_drag
            self._segment_drag = None
            self.interaction_changed.emit(False)
            self._clip_scroll_timer.stop()
            self.setToolTip("")
            self.unsetCursor()
            if drag.get('moved') and drag.get('invalid'):
                self.edit_blocked.emit(str(drag['invalid']))
            elif not drag.get("moved"):
                self.seek_requested.emit(
                    self._bounded_time_ms(self._x_to_time(event.position().x())) / 1000.0
                )
            elif drag.get("target_track_id"):
                self.video_segment_lift_requested.emit(
                    str(drag["segment_id"]), str(drag["target_track_id"])
                )
            self.update()
            event.accept()
            return
        if self._clip_drag:
            from .studio_media_pool import primary_video_track_id
            drag = self._clip_drag
            self._clip_drag = None
            self._snap_target = None
            self.interaction_changed.emit(False)
            self._clip_scroll_timer.stop()
            self.setToolTip("")
            self.unsetCursor()
            if drag.get('moved') and drag.get('invalid'):
                self.edit_blocked.emit(str(drag['invalid']))
            elif not drag.get("moved"):
                self.seek_requested.emit(
                    self._bounded_time_ms(self._x_to_time(event.position().x())) / 1000.0
                )
            elif str(drag["mode"]) == "move":
                source_track = str(drag["track_id"])
                if str(drag.get("target_track_id") or "") and str(drag["target_track_id"]) != source_track:
                    self.video_clip_reassign_committed.emit(
                        source_track, str(drag["target_track_id"]), str(drag["clip_id"]), int(drag["preview_in"])
                    )
                else:
                    self.video_clip_move_committed.emit(
                        source_track, str(drag["clip_id"]), int(drag["preview_in"])
                    )
            else:
                self.video_clip_trim_committed.emit(
                    str(drag["track_id"]),
                    str(drag["clip_id"]),
                    int(drag["preview_in"]),
                    int(drag["preview_out"]),
                )
            self.set_visible_window(self.visible_start_ms, self.visible_duration_ms)
            self.update()
            event.accept()
            return
        if self._pan_drag and event.button() in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        }:
            origin_x, _origin_start = self._pan_drag
            was_dragged = self._pan_drag_moved or abs(event.position().x() - origin_x) >= QApplication.startDragDistance()
            self._pan_drag = None
            self._pan_drag_moved = False
            self.interaction_changed.emit(False)
            point = event.position().toPoint()
            if (
                event.button() == Qt.MouseButton.LeftButton
                and not was_dragged
                and point.y() < self.RULER_HEIGHT
                and point.x() >= self.TRACK_HEADER_WIDTH
            ):
                milliseconds = self._bounded_time_ms(self._x_to_time(event.position().x()))
                self.playhead_ms = milliseconds
                self.seek_requested.emit(milliseconds / 1000.0)
                self.update()
            self.setCursor(
                Qt.CursorShape.OpenHandCursor
                if point.y() < self.RULER_HEIGHT and point.x() >= self.TRACK_HEADER_WIDTH
                else Qt.CursorShape.ArrowCursor
            )
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._marquee_origin is not None:
            origin = self._marquee_origin
            rect = self._marquee_rect.normalized() if self._marquee_rect is not None else QRectF(origin, origin)
            self._marquee_origin = None
            self._marquee_rect = None
            self.interaction_changed.emit(False)
            moved = rect.width() >= QApplication.startDragDistance() or rect.height() >= QApplication.startDragDistance()
            if not moved:
                milliseconds = self._bounded_time_ms(self._x_to_time(event.position().x()))
                self.playhead_ms = milliseconds
                self.seek_requested.emit(milliseconds / 1000.0)
                self.set_selected('')
                self.selection_changed.emit(set())
            elif self.project:
                start_ms = self._x_to_time(rect.left())
                end_ms = self._x_to_time(rect.right())
                sequence = sequence_of(self.project)
                video_selected = {
                    segment.id
                    for segment in runtime_of(self.project).visible_segments(
                        min(start_ms, end_ms), max(start_ms, end_ms) + 1,
                    )
                    if rect.intersects(self._video_track_rect())
                    and segment.timeline_out_ms > min(start_ms, end_ms)
                    and segment.timeline_in_ms < max(start_ms, end_ms) + 1
                }
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    video_selected ^= self.selected_segment_ids
                if video_selected:
                    self.selected_segment_ids = video_selected
                    self.selected_segment_id = next(iter(video_selected))
                    self.segment_selected.emit(self.selected_segment_id)
                    self.segment_selection_changed.emit(set(video_selected))
                selected = set()
                speaker_rects, _translation, _waveform = self._track_layout()
                track_viewport = self._track_viewport()
                hit_rect = rect.adjusted(0, -4, 0, 4)
                horizontal_range = rect.height() < QApplication.startDragDistance()
                for cue in self._cues_intersecting(min(start_ms, end_ms), max(start_ms, end_ms) + 1):
                    track = speaker_rects.get(cue.speaker_id)
                    if (
                        track is None
                        or not track.intersects(track_viewport)
                        or (not horizontal_range and not track.intersects(hit_rect))
                    ):
                        continue
                    selected.add(cue.id)
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    selected ^= set(
                        self.selection_scope.materialize(
                            [item.id for item in self._cues_by_start]
                        )
                    )
                self.selected_ids = selected
                self.selected_id = next(iter(sorted(selected)), '')
                self.selection_scope = SelectionScope.explicit(
                    selected, self.selected_id
                )
                self.selection_changed.emit(set(selected))
                if self.selected_id:
                    self.cue_selected.emit(self.selected_id)
            self.update()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self._drag:
            return
        self._flush_timing_preview()
        changes = {key: value for key, value in self._timing_preview.items()
                   if value != self._drag_originals[key]}
        self._clear_timing_edit()
        if changes:
            self.timing_edit_committed.emit(changes)
        self.timing_edit_finished.emit(bool(changes))
        self.interaction_changed.emit(False)

    def wheelEvent(self, event: QWheelEvent):
        self._follow_suspended_until = perf_counter() + 2.0
        self._thumbnails.note_activity()
        delta = event.angleDelta().y()
        duration = self._duration_ms()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # 光标悬在轨头列上缩放时，锚点必须钳在内容区，否则外推到
            # visible_start 之前的时间导致视口跳变。
            anchor_x = max(self.TRACK_HEADER_WIDTH, event.position().x())
            anchor = self._x_to_time(anchor_x)
            factor = 0.8 if delta > 0 else 1.25
            new_duration = min(max(1000, round(self.visible_duration_ms * factor)), max(1000, duration or 18_000_000))
            ratio = (anchor_x - self.TRACK_HEADER_WIDTH) / max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
            self.set_visible_window(round(anchor - new_duration * ratio), new_duration)
        else:
            shift = round(self.visible_duration_ms * (-0.12 if delta > 0 else 0.12))
            self.set_visible_window(self.visible_start_ms + shift, self.visible_duration_ms)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_scrollbars()
        overlay = getattr(self, '_transport_overlay', None)
        if overlay is not None:
            overlay.setGeometry(self.rect())
