"""Lightweight video-track painting helpers and a lazy thumbnail cache."""

from __future__ import annotations

import hashlib
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from ..timeline.studio_edit_sequence import (
    EditSequence, HighlightCandidate, TimelineMarker, VideoSegment, sequence_of,
)
from ..system.processes import run_hidden_subprocess
from ..projects.studio_project import MediaAsset, SubtitleProject, VideoTrack, studio_data_root
from ..design.timeline_theme import TimelinePalette, mix, rgba_color
from ..design.themed_icons import paint_cached_icon
from .studio_track_header import ACTIONS, action_at, button_rect, paint_button, CONTROL_LEFT
from .media_clip_shape import media_clip_shape
from ..design.typography import weighted_font


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
    from ..system.platform_media import ffmpeg_tool
    return ffmpeg_tool()


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


def paint_folder_media_clip(
    painter: QPainter,
    palette: TimelinePalette,
    *,
    left: float,
    right: float,
    top: float,
    height: float,
    header_width: float,
    content_right: float,
    source: str,
    source_in: int,
    source_out: int,
    label: str,
    duration_ms: int,
    selected: bool,
    offline: bool,
    thumbnails=None,
    join_left: bool = False,
    join_right: bool = False,
    flush_left: bool = False,
    flush_right: bool = False,
):
    """One video clip in draft D style (2026-11-23): full-bleed 16:9 cells,
    a source-colour bottom line and the name in a frosted pill."""
    from .media_clip_folder import (
        clip_shape, format_clip_duration, media_colors, paint_name_pill,
        paint_video_card, paint_video_card_finish, thumbnail_cells, thumbnail_height,
    )
    from .video_filmstrip import filmstrip_lod_ms

    colors = media_colors(palette, source, offline=offline)
    shape = clip_shape(left, right, top, height, header_width, content_right,
                       join_left=join_left, join_right=join_right,
                       flush_left=flush_left, flush_right=flush_right)
    if shape.body.width() <= 0:
        return shape
    paint_video_card(painter, shape, colors)
    if thumbnails is not None and hasattr(thumbnails, "paint") and source and not offline and right > left:
        lod = filmstrip_lod_ms((right - left) * 1000 / max(1, source_out - source_in), thumbnail_height(shape))
        cells = thumbnail_cells(shape, source_in, source_out, header_width, content_right, lod)
        if cells:
            painter.save()
            painter.setClipPath(shape.path(), Qt.ClipOperation.IntersectClip)
            visible = shape.body.intersected(
                QRectF(header_width, shape.body.top(), max(0.0, content_right - header_width), shape.body.height())
            )
            thumbnails.paint(painter, visible, source, left, right, source_in, source_out,
                             cells, 0.0, mix(colors.base, colors.ink, 0.1))
            painter.restore()
    paint_video_card_finish(painter, shape, colors, palette, selected)
    paint_name_pill(painter, shape, colors, label, format_clip_duration(duration_ms), header_width, content_right)
    return shape


def paint_cut_bridges(painter, palette, cuts, time_to_x, header_width, content_right, top, height):
    """Draft B bridges under razor cuts inside one source.

    ``cuts``: (ms, before_key, after_key, continuous, before_offline,
    after_offline). Draw before the clips; cuts between different sources
    get a flush seam from ``paint_cut_seams`` after the clips instead.
    """
    from .media_clip_folder import media_colors, paint_cut_bridge

    for ms, before, after, continuous, before_offline, after_offline in cuts:
        x = time_to_x(ms)
        if not continuous or x < header_width - 20 or x > content_right + 20:
            continue
        paint_cut_bridge(painter, x, top, height,
                         media_colors(palette, before, offline=before_offline).ink,
                         media_colors(palette, after, offline=after_offline).ink,
                         continuous=True)


def paint_cut_seams(painter, palette, cuts, time_to_x, header_width, content_right, top, height):
    """Draft D seams over cuts between two different sources (after the clips)."""
    from .media_clip_folder import paint_cut_seam

    for ms, _before, _after, continuous, _before_offline, _after_offline in cuts:
        x = time_to_x(ms)
        if continuous or x < header_width or x > content_right:
            continue
        paint_cut_seam(painter, palette, x, top, height)


def video_track_header_action_at(x: float, y=None, row=None) -> str:
    return action_at('video', x, y, row)


def video_track_accent(palette: TimelinePalette, track_id: str) -> QColor:
    if track_id == "V1":
        return QColor(palette.video_accent or palette.clip_selected_border)
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
    from ..design.themed_icons import _prime_platform_font_fallback

    _prime_platform_font_fallback()

    # 2026-11-23 (header draft B): the rounded card and its colour rail are
    # painted by the timeline (one card per video lane and its linked audio);
    # here only [V2] + name, with the layer role under a custom name.
    from ..i18n import tr
    from .studio_track_header import CONTENT_LEFT, paint_track_tag, paint_track_title

    x = paint_track_tag(painter, palette, str(track_id), CONTENT_LEFT, track.center().y()) + 7
    custom = track_name not in ("", track_id)
    title = str(track_name) if custom else (role_label or tr("视频"))
    paint_track_title(painter, palette, x, CONTROL_LEFT - 6, track, title,
                      second_line=role_label if custom and role_label else "")
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
    # The timeline already painted the empty canvas and time grid. Only the
    # actual clip shapes below may cover it.
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
    ordered = visible_segments
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
            left = time_to_x(segment.timeline_in_ms)
            right = time_to_x(segment.timeline_out_ms)
            if right <= header_width or left >= content_right:
                continue
            spans = offline_spans if (segment.source_path or sequence.source_path) in offline_sources else occupied
            spans.append((left, right))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(video_fill)
        for left, right in occupied:
            if paint_stats is not None and track.top()+8 < paint_stats.get('viewport_height', float('inf')):
                paint_stats['dense_video_spans'] = paint_stats.get('dense_video_spans', 0) + 1
            _, shape = media_clip_shape(left, right, track.top() + 4, track.height() - 8, header_width, content_right)
            painter.drawPath(shape)
        painter.setBrush(QColor(palette.playhead))
        for left, right in offline_spans:
            _, shape = media_clip_shape(left, right, track.top() + 4, track.height() - 8, header_width, content_right)
            painter.drawPath(shape)
        visible_segments = tuple(
            item for item in visible_segments if item.id in selected_set
        )
    by_out = {item.timeline_out_ms: item for item in ordered}
    by_in = {item.timeline_in_ms: item for item in ordered}
    def continuous_cut(before, after):
        return ((before.source_path or sequence.source_path) == (after.source_path or sequence.source_path)
                and before.source_out_ms == after.source_in_ms)

    cuts = []
    if not dense_lod:
        for segment in ordered:
            previous = by_out.get(segment.timeline_in_ms)
            if previous in (None, segment):
                continue
            before, after = previous.source_path or sequence.source_path, segment.source_path or sequence.source_path
            cuts.append((segment.timeline_in_ms, before, after,
                         before == after and previous.source_out_ms == segment.source_in_ms,
                         before in offline_sources, after in offline_sources))
        paint_cut_bridges(painter, palette, cuts, time_to_x, header_width, content_right,
                          track.top() + 4, track.height() - 8)
    for index, segment in enumerate(visible_segments):
        left = time_to_x(segment.timeline_in_ms)
        right = time_to_x(segment.timeline_out_ms)
        if right < header_width or left > content_right:
            continue
        if paint_stats is not None and track.top()+8 < paint_stats.get('viewport_height', float('inf')):
            paint_stats['video_items'] = paint_stats.get('video_items', 0) + 1
        selected = segment.id == selected_id or segment.id in (selected_ids or set())
        source = segment.source_path or sequence.source_path
        offline = source in offline_sources
        name_text = Path(source).name or "源视频"
        if offline:
            name_text = f"媒体脱机 · {name_text}"
        previous, following = by_out.get(segment.timeline_in_ms), by_in.get(segment.timeline_out_ms)
        previous = None if previous is segment else previous
        following = None if following is segment else following
        split_left = previous is not None and continuous_cut(previous, segment)
        split_right = following is not None and continuous_cut(segment, following)
        paint_folder_media_clip(
            painter, palette, left=left, right=right, top=track.top() + 4, height=track.height() - 8,
            header_width=header_width, content_right=content_right, source=source,
            source_in=segment.source_in_ms, source_out=segment.source_out_ms, label=name_text,
            duration_ms=segment.duration_ms, selected=selected, offline=offline,
            thumbnails=thumbnails, join_left=split_left, join_right=split_right,
            flush_left=previous is not None and not split_left,
            flush_right=following is not None and not split_right,
        )
    if not dense_lod:
        paint_cut_seams(painter, palette, cuts, time_to_x, header_width, content_right,
                        track.top() + 4, track.height() - 8)
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
    spans = {}
    for clip in video_track.clips:
        preview = (clip_preview or {}).get(clip.id)
        spans[clip.id] = (preview[0], preview[1]) if preview else (clip.timeline_in_ms, clip.timeline_out_ms)
    by_out = {spans[clip.id][1]: clip for clip in video_track.clips}
    by_in = {spans[clip.id][0]: clip for clip in video_track.clips}
    cuts = []
    for clip in video_track.clips:
        previous = by_out.get(spans[clip.id][0])
        if previous in (None, clip):
            continue
        before_asset, after_asset = assets.get(previous.asset_id), assets.get(clip.asset_id)
        cuts.append((spans[clip.id][0],
                     before_asset.canonical_source if before_asset else previous.asset_id,
                     after_asset.canonical_source if after_asset else clip.asset_id,
                     previous.asset_id == clip.asset_id and previous.source_out_ms == clip.source_in_ms,
                     before_asset is None or before_asset.offline, after_asset is None or after_asset.offline))
    paint_cut_bridges(painter, palette, cuts, time_to_x, header_width, content_right,
                      track.top() + 4, track.height() - 8)
    for index, clip in enumerate(video_track.clips):
        in_ms, out_ms = spans[clip.id]
        left = time_to_x(in_ms)
        right = time_to_x(out_ms)
        if right < header_width or left > content_right:
            continue
        if paint_stats is not None and track.top()+7 < paint_stats.get('viewport_height', float('inf')):
            paint_stats['video_items'] = paint_stats.get('video_items', 0) + 1
        asset = assets.get(clip.asset_id)
        offline = asset is None or asset.offline
        source = asset.canonical_source if asset else ""
        label = asset.display_name if asset else clip.asset_id
        if offline:
            label = f"离线 · {label}"
        previous, following = by_out.get(in_ms), by_in.get(out_ms)
        previous = None if previous is clip else previous
        following = None if following is clip else following
        split_left = previous is not None and previous.asset_id == clip.asset_id and previous.source_out_ms == clip.source_in_ms
        split_right = following is not None and following.asset_id == clip.asset_id and clip.source_out_ms == following.source_in_ms
        paint_folder_media_clip(
            painter, palette, left=left, right=right, top=track.top() + 4, height=track.height() - 8,
            header_width=header_width, content_right=content_right, source=source or clip.asset_id,
            source_in=clip.source_in_ms, source_out=clip.source_out_ms, label=label,
            duration_ms=out_ms - in_ms, selected=clip.id == selected_clip_id, offline=offline,
            thumbnails=thumbnails if source else None, join_left=split_left, join_right=split_right,
            flush_left=previous is not None and not split_left,
            flush_right=following is not None and not split_right,
        )
    paint_cut_seams(painter, palette, cuts, time_to_x, header_width, content_right,
                    track.top() + 4, track.height() - 8)
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
    weighted_font(font, 700)
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
