"""Source drags over the timeline: where it will land, then one undoable insert.

2026-11-18 (user: adding GIFs, pictures and clips should be as easy as in
Premiere / 剪映): a drop is never refused because the spot is taken or the
pointer is not on a matching track. The track under the pointer is used when
that time is free there, else the next free track above, else a new track
(``resolve_insert_targets``); the ghost shows which before the button is let
go. The start snaps to the playhead and to clip edges.
"""
from PySide6.QtCore import QObject, QEvent, Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition
from ..i18n import tr
from ..timeline.source_selection import (SOURCE_MIME, SourceInsertCommand, plan_source_insert,
                                         resolve_insert_targets)
from .studio_helpers import format_timeline_timecode
from .studio_source_monitor import selection_from_mime

SNAP_PX = 8.0


def _short_timecode(ms):
    text = format_timeline_timecode(ms)
    return text[3:] if text.startswith('00:') else text


def snapped_start(timeline, project, start, duration, *, enabled=True):
    """Start moved so either edge meets the playhead, 0 or a clip edge within 8 px."""
    if not enabled or not getattr(timeline, 'snap_enabled', True):
        return start
    width = max(1, timeline._content_right() - timeline.TRACK_HEADER_WIDTH)
    threshold = SNAP_PX * timeline.visible_duration_ms / width
    targets = {0, int(timeline.playhead_ms)}
    for track in (*project.video_tracks, *project.audio_tracks):
        for clip in track.clips:
            targets.update((int(clip.timeline_in_ms), int(clip.timeline_out_ms)))
    best = None
    for target in targets:
        for candidate in (target, target - duration):
            if candidate >= 0 and abs(candidate - start) <= threshold and (
                    best is None or abs(candidate - start) < abs(best - start)):
                best = candidate
    return start if best is None else best


def insert_placement(page, selection, position_ms, pointer_video='', pointer_audio=''):
    """The validated landing for a selection; raises ValueError with the reason."""
    project = page.project
    video, audio = resolve_insert_targets(project, selection, position_ms, pointer_video, pointer_audio)
    return plan_source_insert(project, selection, position_ms, video, audio)


def placement_label(placement):
    """「新建视频轨 · 00:02.000 → 00:06.000」 for the ghost and the status line."""
    mode = placement['mode']
    video, audio = placement['video_track_id'], placement['audio_track_id']
    if mode == 'audio':
        where = tr('新建音频轨') if audio == 'new' else audio
    else:
        where = tr('新建视频轨') if video == 'new' else video
    return f'{where} · {_short_timecode(placement["start_ms"])} → {_short_timecode(placement["end_ms"])}'


def push_insert(page, selection, placement):
    """Insert as one undo step, keep the new lane in view; returns the command."""
    command = SourceInsertCommand(page.project, selection, placement['start_ms'],
                                  placement['video_track_id'], placement['audio_track_id'])
    page.undo_stack.push(command)
    created = 'new' in (placement['video_track_id'] if selection.mode != 'audio' else '',
                        placement['audio_track_id'] if selection.mode == 'audio' else '')
    if created and hasattr(page, '_ensure_timeline_lane_space'):
        page._ensure_timeline_lane_space()
    return command


class _PlacementOverlay(QWidget):
    def __init__(self, timeline):
        super().__init__(timeline)
        self.timeline = timeline
        self.placement = None
        self.message = ''
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.hide()

    def ghost_rows(self):
        """[(row rect, is a new track)] for the lanes the selection will occupy."""
        timeline, placement = self.timeline, self.placement
        videos, audios = timeline._video_track_rects(), timeline._audio_track_rects()
        project = timeline.project
        rows = []
        mode = placement['mode']
        if mode in {'av', 'video'}:
            video_id = placement['video_track_id']
            if video_id == 'new':
                # A new track goes on top of the video stack.
                top = min((r.top() for r in videos.values()), default=timeline._stack_bottom())
                height = timeline._video_track_height()
                rows.append((QRectF(0, max(timeline.RULER_HEIGHT, top - height), timeline.width(), height), True))
            else:
                rows.append((videos.get(video_id), False))
                lane = next((g.audio_track_id for g in project.av_track_groups
                             if g.linked and g.video_track_id == video_id), '') if mode == 'av' else ''
                if lane:
                    rows.append((audios.get(lane), False))
        else:
            audio_id = placement['audio_track_id']
            if audio_id == 'new':
                # A new audio track goes under the last lane.
                height = timeline._audio_track_height()
                bottom = min(timeline._canvas_bottom(), timeline._stack_bottom() + height)
                rows.append((QRectF(0, bottom - height, timeline.width(), height), True))
            else:
                rows.append((audios.get(audio_id), False))
        return [(row, new) for row, new in rows if row is not None]

    def paintEvent(self, event):
        if self.placement is None:
            return
        timeline, placement = self.timeline, self.placement
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.danger if self.message else theme.accent)
        fill = QColor(color); fill.setAlpha(70)
        left = max(float(timeline.TRACK_HEADER_WIDTH), timeline._time_to_x(placement['start_ms']))
        right = min(float(timeline._content_right()), timeline._time_to_x(placement['end_ms']))
        right = max(right, left + 6)
        label = self.message or placement_label(placement)
        first = None
        if not self.message:
            for row, new in self.ghost_rows():
                rect = QRectF(left, row.top() + 3, right - left, max(6.0, row.height() - 6))
                first = first or rect
                if new:
                    # The whole future lane, so it is clear a track is added.
                    band = QColor(color); band.setAlpha(26)
                    painter.fillRect(QRectF(timeline.TRACK_HEADER_WIDTH, row.top(),
                                            timeline._content_right() - timeline.TRACK_HEADER_WIDTH, row.height()), band)
                painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine if new else Qt.PenStyle.SolidLine))
                painter.setBrush(fill)
                painter.drawRoundedRect(rect, 6, 6)
            # Start line through every lane: the exact frame it lands on.
            painter.setPen(QPen(color, 1))
            painter.drawLine(round(left), timeline.RULER_HEIGHT, round(left), timeline._stack_bottom())
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(label) + 20
        anchor_x = left if first is None else first.left()
        anchor_y = (timeline.RULER_HEIGHT + 6) if first is None else first.top() - 26
        x = min(max(timeline.TRACK_HEADER_WIDTH + 4, anchor_x), max(timeline.TRACK_HEADER_WIDTH + 4, self.width() - width - 8))
        y = max(4, anchor_y)
        box = QRectF(x, y, width, 22)
        painter.setPen(QPen(color, 1)); painter.setBrush(QColor(theme.surface))
        painter.drawRoundedRect(box, 11, 11)
        painter.setPen(QColor(theme.text))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)


class SourceTimelineDrop(QObject):
    def __init__(self, page):
        super().__init__(page)
        self.page, self.timeline = page, page.timeline
        self.overlay = _PlacementOverlay(page.timeline)
        self.selection = None
        self.placement = None
        self.timeline.setAcceptDrops(True)
        self.timeline.installEventFilter(self)

    def _update(self, event):
        project, timeline = self.page.project, self.timeline
        point = event.position().toPoint()
        selection = selection_from_mime(project, event.mimeData())
        video, audio = timeline._video_track_at(point), timeline._audio_track_at(point)
        if point.x() < timeline.TRACK_HEADER_WIDTH:
            # On a track name: that track, at the playhead.
            start = int(timeline.playhead_ms)
        else:
            bypass = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            start = snapped_start(timeline, project, max(0, int(timeline._x_to_time(point.x()))),
                                  selection.duration_ms, enabled=not bypass)
        self.overlay.placement = dict(start_ms=start, end_ms=start + selection.duration_ms, mode=selection.mode,
                                      video_track_id=video, audio_track_id=audio)
        self.overlay.message = ''
        try:
            placement = insert_placement(self.page, selection, start, video, audio)
            self.overlay.placement = placement
            self.selection, self.placement = selection, placement
        except (ValueError, KeyError) as exc:
            self.overlay.message = str(exc)
            self.selection, self.placement = None, None
        self.overlay.setGeometry(timeline.rect()); self.overlay.show(); self.overlay.raise_(); self.overlay.update()
        event.setDropAction(Qt.DropAction.CopyAction)
        # Accept enter/move to keep receiving feedback wherever the pointer is.
        event.accept()

    def _say(self, text):
        self.page.source_monitor.status.setText(text)
        if hasattr(self.page, 'save_state'):
            self.page.save_state.setText(text)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.DragLeave:
            self.overlay.hide(); self.selection = None; self.placement = None
            return False
        if kind not in {QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop}:
            return False
        if not event.mimeData().hasFormat(SOURCE_MIME):
            return False
        if self.page.project is None:
            event.ignore(); return True
        try:
            self._update(event)
            if kind == QEvent.Type.Drop:
                if self.selection is not None and self.placement is not None:
                    label = placement_label(self.placement)
                    push_insert(self.page, self.selection, self.placement)
                    self._say(tr('已加入 {value0}；Ctrl+Z 撤销', value0=label))
                else:
                    self._say(self.overlay.message)
                    event.ignore()
                self.overlay.hide()
        except (KeyError, ValueError, TypeError) as exc:
            self._say(str(exc)); event.ignore(); self.overlay.hide()
        return True
