"""Lightweight video-track painting helpers and a lazy thumbnail cache."""

from __future__ import annotations

import hashlib
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from .studio_edit_sequence import (
    EditSequence, HighlightCandidate, TimelineMarker, VideoSegment, sequence_of,
)
from .processes import run_hidden_subprocess
from .studio_project import MediaAsset, SubtitleProject, VideoTrack, studio_data_root
from .timeline_theme import TimelinePalette, mix, rgba_color
from .themed_icons import paint_cached_icon
from .studio_track_header import ACTIONS, action_at, button_rect, paint_button, CONTROL_LEFT


VIDEO_TRACK_HEIGHT = 58
CANDIDATE_LANE_HEIGHT = 18
VIDEO_TRACK_HEADER_ACTIONS = {
    action: button_rect('video', action, QRectF(0, 0, 228, VIDEO_TRACK_HEIGHT))
    for action in ACTIONS['video']
}


def _merged_pixel_spans(spans) -> tuple[tuple[int, int], ...]:
    ordered = sorted((int(left), int(right)) for left, right in spans if int(right) >= int(left))
    merged: list[tuple[int, int]] = []
    for left, right in ordered:
        if merged and left <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return tuple(merged)


def _density_pixel_spans(spans) -> tuple[tuple[int, int, int], ...]:
    events: dict[int, int] = {}
    for left, right in spans:
        first, last = int(left), int(right)
        if last < first:
            continue
        events[first] = events.get(first, 0) + 1
        events[last + 1] = events.get(last + 1, 0) - 1
    active = 0
    previous: int | None = None
    result: list[tuple[int, int, int]] = []
    for position in sorted(events):
        if previous is not None and active > 0 and position > previous:
            result.append((previous, position - 1, active))
        active += events[position]
        previous = position
    return tuple(result)


def ffmpeg_executable() -> Path:
    return Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"


class VideoThumbnailCache(QObject):
    updated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._memory: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()

    def get(
        self,
        source_path: str,
        source_ms: int,
        width: int = 96,
        *,
        request_missing: bool = True,
    ) -> QPixmap | None:
        key = self._key(source_path, source_ms, width)
        cached = self._memory.get(key)
        if cached is not None:
            return cached
        disk = self._disk_path(key)
        if disk.is_file():
            pixmap = QPixmap(str(disk))
            if not pixmap.isNull():
                self._memory[key] = pixmap
                return pixmap
        if request_missing:
            self.request(source_path, source_ms, width)
        return None

    def request(self, source_path: str, source_ms: int, width: int = 96) -> None:
        if width < 32 or not source_path:
            return
        key = self._key(source_path, source_ms, width)
        with self._lock:
            if key in self._memory or key in self._pending:
                return
            self._pending.add(key)
        thread = threading.Thread(
            target=self._extract,
            args=(key, source_path, source_ms, width),
            daemon=True,
            name="video-thumb",
        )
        thread.start()

    def _extract(self, key: str, source_path: str, source_ms: int, width: int) -> None:
        ffmpeg = ffmpeg_executable()
        dest = self._disk_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if ffmpeg.is_file() and Path(source_path).is_file():
                seconds = max(0.0, source_ms / 1000.0)
                run_hidden_subprocess(
                    [
                        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{seconds:.3f}", "-i", str(source_path),
                        "-frames:v", "1", "-vf", f"scale={int(width)}:-1",
                        str(dest),
                    ],
                    purpose="ffmpeg thumbnail",
                    check=False,
                    timeout=8,
                )
        except (OSError, subprocess.SubprocessError):
            dest = dest
        pixmap = QPixmap(str(dest)) if dest.is_file() else QPixmap()
        with self._lock:
            self._pending.discard(key)
            if not pixmap.isNull():
                self._memory[key] = pixmap
        if not pixmap.isNull():
            self.updated.emit(key)

    @staticmethod
    @lru_cache(maxsize=256)
    def _source_digest(source_path: str) -> str:
        try:
            normalized_path = str(Path(source_path).resolve())
        except (OSError, ValueError):
            normalized_path = str(Path(source_path))
        return hashlib.sha1(normalized_path.encode("utf-8", "replace")).hexdigest()[:16]

    @staticmethod
    def _key(source_path: str, source_ms: int, width: int) -> str:
        digest = VideoThumbnailCache._source_digest(source_path)
        time_bucket = max(0, int(source_ms)) // 250 * 250
        return f"{digest}-{time_bucket}-{int(width)}"

    @staticmethod
    def _disk_path(key: str) -> Path:
        return studio_data_root() / "thumbnails" / f"{key}.jpg"


def _format_duration(ms: int) -> str:
    total = max(0, int(ms) // 1000)
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def video_track_header_action_at(x: float, y=None, row=None) -> str:
    return action_at('video', x, y, row)


def video_track_accent(palette: TimelinePalette, track_id: str) -> QColor:
    if track_id == "V1":
        return QColor(palette.clip_selected_border)
    accents = palette.speaker_accents or (palette.clip_selected_border,)
    try:
        index = int(track_id.lstrip("V"))
    except ValueError:
        index = 2
    return QColor(accents[index % len(accents)])


def paint_video_track_header(
    painter: QPainter,
    palette: TimelinePalette,
    track: QRectF,
    *,
    track_id: str,
    track_name: str,
    enabled: bool,
    muted: bool,
    locked: bool,
    hovered_action: str = "",
    role_label: str = "",
) -> None:
    """Paint one video-lane header (id/name + eye/lock/delete icons).

    2026-09-06（四图反馈·图二）：公开为模块级入口——WaveformTimeline 的
    头部列快速重绘路径（悬停/选中 invalidation）此前只重画音频轨与说话人轨
    图标，视频轨图标被背景清除后无人补画，V1/V2 轨道头图标"划过即消失"。
    """
    from .themed_icons import _prime_platform_font_fallback

    _prime_platform_font_fallback()

    # The track name remains draggable; a color rail replaces the six-dot
    # grip, which collided with the V number in compact timeline lanes.
    accent = video_track_accent(palette, track_id)
    painter.fillRect(QRectF(0, track.top(), 228, track.height()), mix(palette.header, accent, 0.09))
    # 2026-09-18 VIII（可变轨高）：徽章+名称按轨高垂直居中。默认 58px 时
    # 居中公式与旧硬编码（badge top+7 / name top+31 / 色条 top+9）逐像素
    # 一致；压到 52px 以下时名称行放不下，隐藏次要信息避免与图标重叠。
    lane_height = track.height()
    show_name = lane_height >= 52
    inset = max(9.0, lane_height * 0.155)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(accent)
    painter.drawRoundedRect(QRectF(4, track.top() + inset, 3, lane_height - 2 * inset), 1.5, 1.5)
    if show_name:
        badge_top = track.top() + max(7.0, (lane_height - 51) / 2)
    else:
        badge_top = track.top() + (lane_height - 23) / 2
    painter.setBrush(mix(palette.header, accent, 0.18))
    painter.setPen(QColor(palette.header_name))
    letter = QFont(painter.font())
    letter.setPointSize(10)
    letter.setBold(True)
    letter.setItalic(False)
    painter.setFont(letter)
    painter.drawRoundedRect(QRectF(13, badge_top, 34, 23), 6, 6)
    painter.drawText(
        QRectF(13, badge_top, 34, 23),
        Qt.AlignmentFlag.AlignCenter,
        str(track_id),
    )
    if show_name:
        painter.setPen(QColor(palette.header_name))
        name_font = QFont(painter.font())
        name_font.setPointSize(8)
        name_font.setWeight(QFont.Weight.Medium)
        painter.setFont(name_font)
        painter.drawText(
            QRectF(13, badge_top + 24, 114, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                (role_label if track_name in ("", track_id) else str(track_name)),
                Qt.TextElideMode.ElideRight,
                114,
            ),
        )
    icons = {
        "enabled": "fa5s.eye" if enabled else "fa5s.eye-slash",
        "locked": "fa5s.lock" if locked else "fa5s.unlock",
        "more": "fa5s.trash-alt",
    }
    for action in ACTIONS['video']:
        active = (
            action == hovered_action
            or (action == "enabled" and not enabled)
            or (action == "locked" and locked)
        )
        paint_button(painter, palette, 'video', action, track, icons[action],
                     active=active, disabled=action == 'more' and locked)


def paint_video_track(
    painter: QPainter,
    sequence: EditSequence,
    palette: TimelinePalette,
    track: QRectF,
    header_width: float,
    content_right: float,
    time_to_x,
    selected_id: str,
    thumbnails: VideoThumbnailCache | None,
    locked: bool,
    lock_hovered: bool = False,
    request_missing_thumbnails: bool = True,
    selected_ids: set[str] | None = None,
    segments: tuple[VideoSegment, ...] | None = None,
    track_id: str = "V1",
    track_name: str = "视频",
    enabled: bool = True,
    muted: bool = False,
    hovered_action: str = "",
    role_label: str = "",
    paint_stats: dict | None = None,
    offline_sources: set[str] | None = None,
) -> None:
    video_fill = QColor(getattr(palette, "video_clip", "") or mix(palette.track_background, palette.clip_selected_border, 0.35))
    video_border = QColor(getattr(palette, "video_clip_border", "") or palette.clip_selected_border)
    painter.fillRect(
        QRectF(header_width, track.top(), max(0.0, content_right - header_width), track.height()),
        mix(palette.track_background, video_fill, 0.18),
    )
    paint_video_track_header(
        painter,
        palette,
        track,
        track_id=track_id,
        track_name=track_name,
        enabled=enabled,
        muted=muted,
        locked=locked,
        hovered_action=hovered_action or ("locked" if lock_hovered else ""),
        role_label=role_label,
    )

    painter.save()
    painter.setClipRect(QRectF(header_width, track.top(), max(0.0, content_right - header_width), track.height()))
    visible_segments = tuple(segments) if segments is not None else tuple(sequence.segments)
    offline_sources = offline_sources or set()
    content_width = max(1.0, content_right - header_width)
    # Long overviews can have only a few hundred clips while every block is
    # still narrower than a readable label.  Count-vs-pixel alone kept that
    # path in the expensive rounded-card/text renderer.
    average_width = content_width / max(1, len(visible_segments))
    dense_lod = len(visible_segments) > 240 or average_width < 12.0
    if dense_lod:
        occupied: list[tuple[int, int]] = []
        offline_spans: list[tuple[int, int]] = []
        selected_set = set(selected_ids or ()) | ({selected_id} if selected_id else set())
        for segment in visible_segments:
            if segment.id in selected_set:
                continue
            left = max(round(header_width), round(time_to_x(segment.timeline_in_ms)))
            right = min(round(content_right), max(left + 1, round(time_to_x(segment.timeline_out_ms))))
            spans = offline_spans if (segment.source_path or sequence.source_path) in offline_sources else occupied
            spans.append((left, right))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(video_fill)
        for left, right in _merged_pixel_spans(occupied):
            if paint_stats is not None and track.top()+8 < paint_stats.get('viewport_height', float('inf')):
                paint_stats['dense_video_spans'] = paint_stats.get('dense_video_spans', 0) + 1
            painter.drawRect(
                QRectF(left, track.top() + 8, right - left + 1, track.height() - 16)
            )
        painter.setBrush(QColor(palette.playhead))
        for left, right in _merged_pixel_spans(offline_spans):
            painter.drawRect(QRectF(left, track.top() + 8, right - left + 1, track.height() - 16))
        visible_segments = tuple(
            item for item in visible_segments if item.id in selected_set
        )
    for index, segment in enumerate(visible_segments):
        left = time_to_x(segment.timeline_in_ms)
        right = time_to_x(segment.timeline_out_ms)
        if right < header_width or left > content_right:
            continue
        if paint_stats is not None and track.top()+8 < paint_stats.get('viewport_height', float('inf')):
            paint_stats['video_items'] = paint_stats.get('video_items', 0) + 1
        block = QRectF(
            max(header_width, left),
            track.top() + 8,
            max(4.0, min(content_right, right) - max(header_width, left)),
            track.height() - 16,
        )
        selected = segment.id == selected_id or segment.id in (selected_ids or set())
        source = segment.source_path or sequence.source_path
        offline = source in offline_sources
        border = QColor(palette.playhead) if offline else video_border
        painter.setPen(QPen(QColor(palette.clip_selected_border) if selected else border, 2.0 if selected else 1.2))
        painter.setBrush(video_fill.lighter(108 if index % 2 == 0 else 96))
        painter.drawRoundedRect(block, 5, 5)
        if selected:
            painter.setPen(QPen(QColor(palette.clip_selected_border), 2))
            painter.setBrush(rgba_color(palette.clip_selected_glow))
            painter.drawRoundedRect(block.adjusted(-1, -1, 1, 1), 6, 6)
        thumb_width = 0 if offline else min(88, max(0, int(block.width()) - 18))
        filmstrip = thumbnails is not None and hasattr(thumbnails, 'paint') and not offline
        if filmstrip:
            thumbnails.paint(painter,block.adjusted(1,1,-1,-1),segment.source_path or sequence.source_path,
                left,right,segment.source_in_ms,segment.source_out_ms)
            thumb_width=0
            painter.setPen(QPen(QColor(palette.clip_selected_border) if selected else video_border,2 if selected else 1))
            painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRoundedRect(block,5,5)
        if thumbnails is not None and not filmstrip and thumb_width >= 40:
            mid = segment.source_in_ms + segment.duration_ms // 2
            pixmap = thumbnails.get(
                segment.source_path or sequence.source_path,
                mid,
                96,
                request_missing=request_missing_thumbnails,
            )
            if pixmap is not None and not pixmap.isNull():
                thumb = QRectF(block.left() + 6, block.top() + 4, min(72, block.width() * 0.28), block.height() - 8)
                painter.drawPixmap(thumb.toRect(), pixmap)
        painter.setPen(QColor(palette.clip_text))
        font = QFont(painter.font())
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        name_text = Path(source).name or "源视频"
        if offline:
            name_text = f"媒体脱机 · {name_text}"
        text_left = block.left() + (86 if thumb_width >= 40 else 10)
        if filmstrip:
            label_width=min(block.width()-16,painter.fontMetrics().horizontalAdvance(name_text)+12)
            painter.fillRect(QRectF(text_left-3,block.top()+2,max(4,label_width),19),QColor(18,18,22,195))
            painter.setPen(QColor('#FFFDF7'))
        painter.drawText(
            QRectF(text_left, block.top() + 4, max(8, block.right() - text_left - 8), 18),
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            name_text,
        )
        font.setBold(False)
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QColor(palette.header_letter))
        painter.drawText(
            QRectF(text_left, block.top() + 22, max(8, block.right() - text_left - 8), 16),
            Qt.AlignmentFlag.AlignVCenter,
            '' if filmstrip else _format_duration(segment.duration_ms),
        )
        # Clip boundary ticks.
        painter.setPen(QPen(video_border, 2))
        painter.drawLine(round(left), round(track.top() + 4), round(left), round(track.bottom() - 4))
    painter.restore()


def paint_project_video_track(
    painter: QPainter,
    video_track: VideoTrack,
    assets: dict[str, MediaAsset],
    palette: TimelinePalette,
    track: QRectF,
    header_width: float,
    content_right: float,
    time_to_x,
    *,
    selected_clip_id: str = "",
    thumbnails: VideoThumbnailCache | None = None,
    request_missing_thumbnails: bool = True,
    hovered_action: str = "",
    role_label: str = "",
    clip_preview: dict[str, tuple[int, int]] | None = None,
    paint_stats: dict | None = None,
) -> None:
    accent = video_track_accent(palette, video_track.id)
    fill = mix(palette.track_background, accent, 0.13)
    painter.fillRect(
        QRectF(
            header_width,
            track.top(),
            max(0.0, content_right - header_width),
            track.height(),
        ),
        fill if video_track.enabled else mix(fill, palette.background, 0.62),
    )
    paint_video_track_header(
        painter,
        palette,
        track,
        track_id=video_track.id,
        track_name=video_track.name,
        enabled=video_track.enabled,
        muted=video_track.muted,
        locked=video_track.locked,
        hovered_action=hovered_action,
        role_label=role_label,
    )
    painter.save()
    painter.setClipRect(
        QRectF(
            header_width,
            track.top(),
            max(0.0, content_right - header_width),
            track.height(),
        )
    )
    painter.setOpacity(1.0 if video_track.enabled else 0.5)
    for index, clip in enumerate(video_track.clips):
        preview = (clip_preview or {}).get(clip.id)
        in_ms = preview[0] if preview else clip.timeline_in_ms
        out_ms = preview[1] if preview else clip.timeline_out_ms
        left = time_to_x(in_ms)
        right = time_to_x(out_ms)
        if right < header_width or left > content_right:
            continue
        if paint_stats is not None and track.top()+7 < paint_stats.get('viewport_height', float('inf')):
            paint_stats['video_items'] = paint_stats.get('video_items', 0) + 1
        block = QRectF(
            max(header_width, left),
            track.top() + 7,
            max(4.0, min(content_right, right) - max(header_width, left)),
            track.height() - 14,
        )
        asset = assets.get(clip.asset_id)
        offline = asset is None or asset.offline
        selected = clip.id == selected_clip_id
        border = QColor(palette.playhead) if offline else accent
        painter.setPen(
            QPen(
                QColor(palette.clip_selected_border) if selected else border,
                2.2 if selected else 1.2,
            )
        )
        painter.setBrush(
            mix(palette.track_background, accent, 0.46 if not palette.dark else 0.42)
        )
        painter.drawRoundedRect(block, 4, 4)
        source = asset.canonical_source if asset else ""
        filmstrip = thumbnails is not None and hasattr(thumbnails, 'paint') and source and not offline
        if filmstrip:
            thumbnails.paint(painter,block.adjusted(1,1,-1,-1),source,left,right,clip.source_in_ms,clip.source_out_ms)
            painter.setPen(QPen(QColor(palette.clip_selected_border) if selected else border,2.2 if selected else 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRoundedRect(block,4,4)
        if (
            thumbnails is not None
            and not filmstrip
            and block.width() >= 92
            and source
            and not offline
        ):
            pixmap = thumbnails.get(
                source,
                clip.source_in_ms
                + max(0, clip.source_out_ms - clip.source_in_ms) // 2,
                72,
                request_missing=request_missing_thumbnails,
            )
            if pixmap is not None and not pixmap.isNull():
                thumb = QRectF(
                    block.left() + 4,
                    block.top() + 4,
                    58,
                    block.height() - 8,
                )
                painter.drawPixmap(thumb.toRect(), pixmap)
        painter.setPen(QColor(palette.clip_text))
        font = QFont(painter.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        label = asset.display_name if asset else clip.asset_id
        if offline:
            label = f"离线 · {label}"
        text_left = block.left() + (68 if block.width() >= 92 and not filmstrip else 7)
        available = max(4, round(block.right() - text_left - 5))
        label_rect=QRectF(text_left, block.top(), available, block.height())
        if filmstrip:
            available=min(available,240,painter.fontMetrics().horizontalAdvance(label)+8)
            label_rect=QRectF(text_left,block.top()+1,available,18)
            painter.fillRect(label_rect.adjusted(-2,0,2,0),QColor(18,18,22,195))
            painter.setPen(QColor('#FFFDF7'))
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                label, Qt.TextElideMode.ElideRight, available
            ),
        )
    painter.restore()


def paint_candidate_lane(
    painter: QPainter,
    sequence: EditSequence,
    palette: TimelinePalette,
    lane: QRectF,
    header_width: float,
    content_right: float,
    time_to_x,
    source_to_timeline,
    candidates: tuple[HighlightCandidate, ...] | None = None,
) -> None:
    painter.fillRect(
        QRectF(header_width, lane.top(), max(0.0, content_right - header_width), lane.height()),
        mix(palette.track_background, QColor("#e8a54b"), 0.12),
    )
    painter.setPen(QColor(palette.header_name))
    font = painter.font()
    font.setPointSize(9)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(10, lane.top(), 210, lane.height()), Qt.AlignmentFlag.AlignVCenter, "AI CANDIDATES")
    fill = QColor(getattr(palette, "candidate_fill", "") or "#e8a54b")
    painter.save()
    painter.setClipRect(QRectF(header_width, lane.top(), max(0.0, content_right - header_width), lane.height()))
    duration = max(1, sequence.source_duration_ms or sequence.timeline_duration_ms)
    visible_candidates = tuple(candidates) if candidates is not None else tuple(sequence.clip_candidates)
    content_width = max(1.0, content_right - header_width)
    average_width = content_width / max(1, len(visible_candidates))
    dense_lod = len(visible_candidates) > 200 or average_width < 8.0
    occupied: list[tuple[int, int]] = []
    for candidate in visible_candidates:
        if candidate.status == "ignored":
            continue
        source_in = min(duration, max(0, int(candidate.source_in_ms)))
        source_out = min(duration, max(source_in + 1, int(candidate.source_out_ms)))
        mapped_in = source_to_timeline(source_in)
        mapped_out = source_to_timeline(max(source_in, source_out - 1))
        if mapped_in is None or mapped_out is None:
            continue
        left = time_to_x(mapped_in.timeline_ms)
        right = time_to_x(mapped_out.timeline_ms)
        if right < header_width or left > content_right:
            continue
        if dense_lod:
            first = max(round(header_width), round(left))
            last = min(round(content_right), max(first, round(right)))
            occupied.append((first, last))
            continue
        block = QRectF(
            max(header_width, left),
            lane.top() + 3,
            max(3.0, min(content_right, right) - max(header_width, left)),
            lane.height() - 6,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(fill)
        if candidate.status == "accepted":
            color = mix(fill, QColor(palette.clip_selected_border), 0.4)
        color.setAlpha(200 if candidate.status == "accepted" else 150)
        painter.setBrush(color)
        painter.drawRoundedRect(block, 3, 3)
        signal_in = candidate.signal_in_ms if candidate.signal_in_ms is not None else candidate.source_in_ms
        signal_out = candidate.signal_out_ms if candidate.signal_out_ms is not None else candidate.source_out_ms
        signal_mapped_in = source_to_timeline(int(signal_in))
        signal_mapped_out = source_to_timeline(max(int(signal_in), int(signal_out) - 1))
        if signal_mapped_in is not None and signal_mapped_out is not None:
            signal_left = time_to_x(signal_mapped_in.timeline_ms)
            signal_right = time_to_x(signal_mapped_out.timeline_ms)
            core = QRectF(
                max(header_width, signal_left),
                lane.top() + 2,
                max(3.0, min(content_right, signal_right) - max(header_width, signal_left)),
                lane.height() - 4,
            )
            core_color = QColor(fill).darker(145)
            core_color.setAlpha(235)
            painter.setBrush(core_color)
            painter.drawRoundedRect(core, 3, 3)
    if dense_lod and occupied:
        density_spans = _density_pixel_spans(occupied)
        peak = max(count for _left, _right, count in density_spans)
        painter.setPen(Qt.PenStyle.NoPen)
        for left, right, count in density_spans:
            color = QColor(fill)
            color.setAlpha(90 + round(145 * count / max(1, peak)))
            painter.setBrush(color)
            painter.drawRect(
                QRectF(left, lane.top() + 2, right - left + 1, lane.height() - 4)
            )
    painter.restore()


def paint_markers(
    painter: QPainter,
    sequence: EditSequence,
    palette: TimelinePalette,
    ruler_bottom: float,
    time_to_x,
    header_width: float,
    content_right: float,
    markers: tuple[TimelineMarker, ...] | None = None,
) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(getattr(palette, "marker", "") or "#f0c040"))
    visible_markers = tuple(markers) if markers is not None else tuple(sequence.markers)
    content_width = max(1.0, content_right - header_width)
    dense_lod = len(visible_markers) > 120 or (
        content_width / max(1, len(visible_markers)) < 6.0
    )
    occupied: set[int] = set()
    critical = {"chapter", "warning", "critical", "cut"}
    for marker in visible_markers:
        x = time_to_x(marker.time_ms)
        if x < header_width or x > content_right:
            continue
        if dense_lod and marker.kind.casefold() not in critical:
            occupied.add(round(x))
            continue
        painter.drawEllipse(QRectF(x - 4, 6, 8, 8))
        painter.setPen(QColor(palette.time_label))
        painter.drawText(QRectF(x + 6, 2, 80, 16), Qt.AlignmentFlag.AlignVCenter, marker.label[:8])
        painter.setPen(Qt.PenStyle.NoPen)
    if occupied:
        painter.setPen(QPen(QColor(getattr(palette, "marker", "") or "#f0c040"), 1.0))
        for x in occupied:
            painter.drawLine(x, 4, x, 14)


def sequence_for(project: SubtitleProject | None) -> EditSequence | None:
    if project is None:
        return None
    return sequence_of(project)
