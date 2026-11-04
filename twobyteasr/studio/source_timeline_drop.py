"""Source-selection drag preview and commit, sharing the same placement planner."""
from PySide6.QtCore import QObject, QEvent, Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition
from ..timeline.source_selection import SOURCE_MIME, SourceInsertCommand, plan_source_insert
from .studio_helpers import format_timeline_timecode
from .studio_source_monitor import selection_from_mime


class _PlacementOverlay(QWidget):
    def __init__(self, timeline):
        super().__init__(timeline)
        self.timeline = timeline
        self.placement = None
        self.message = ''
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.hide()

    def paintEvent(self, event):
        if self.placement is None:
            return
        timeline, placement = self.timeline, self.placement
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        color = QColor(theme.danger if self.message else theme.accent)
        fill = QColor(color); fill.setAlpha(65)
        painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine)); painter.setBrush(fill)
        rects = []
        if placement['mode'] in {'av', 'video'}:
            rects.append(timeline._video_track_rects().get(placement['video_track_id']))
        if placement['mode'] in {'av', 'audio'}:
            rects.append(timeline._audio_track_rects().get(placement['audio_track_id']))
        left, right = timeline._time_to_x(placement['start_ms']), timeline._time_to_x(placement['end_ms'])
        for row in rects:
            if row is not None:
                painter.drawRoundedRect(QRectF(left, row.top()+3, max(2, right-left), row.height()-6), 5, 5)
        painter.setBrush(QColor(theme.surface))
        label = self.message or (f'{placement["video_track_id"] if placement["mode"] != "audio" else placement["audio_track_id"]}  '
            f'{format_timeline_timecode(placement["start_ms"])} → {format_timeline_timecode(placement["end_ms"])}  '
            f'长度 {format_timeline_timecode(placement["end_ms"]-placement["start_ms"])}')
        box = QRectF(timeline.TRACK_HEADER_WIDTH+8, 4, max(100, self.width()-timeline.TRACK_HEADER_WIDTH-20), 28)
        painter.drawRoundedRect(box, 5, 5)
        painter.setPen(QColor(theme.text)); painter.drawText(box.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, label)


class SourceTimelineDrop(QObject):
    def __init__(self, page):
        super().__init__(page)
        self.page, self.timeline = page, page.timeline
        self.overlay = _PlacementOverlay(page.timeline)
        self.selection = None
        self.targets = None
        self.timeline.setAcceptDrops(True)
        self.timeline.installEventFilter(self)

    def _update(self, event):
        project, timeline = self.page.project, self.timeline
        point = event.position().toPoint()
        selection = selection_from_mime(project, event.mimeData())
        start = max(0, int(timeline._x_to_time(point.x())))
        video, audio = timeline._video_track_at(point), timeline._audio_track_at(point)
        if selection.mode == 'av' and audio and not video:
            video = next((g.video_track_id for g in project.av_track_groups if g.audio_track_id == audio), '')
        placement = dict(start_ms=start, end_ms=start+selection.duration_ms, mode=selection.mode,
                         video_track_id=video, audio_track_id=audio)
        self.overlay.placement = placement
        self.overlay.message = ''
        try:
            if point.x() < timeline.TRACK_HEADER_WIDTH:
                raise ValueError('请拖到时间尺右侧的兼容轨道；也可在源预览选择新建轨道')
            if selection.mode in {'av', 'video'} and not video:
                raise ValueError('请选择视频轨道；缺少轨道时在源预览选择「新建视频轨」')
            if selection.mode == 'audio' and not audio:
                raise ValueError('请选择音频轨道；缺少轨道时在源预览选择「新建独立音轨」')
            placement = plan_source_insert(project, selection, start, video or 'new', audio or 'new')
            self.overlay.placement = placement
            self.selection, self.targets = selection, (start, video or 'new', audio or 'new')
        except (ValueError, KeyError) as exc:
            self.overlay.message = str(exc)
            self.selection, self.targets = None, None
        self.overlay.setGeometry(timeline.rect()); self.overlay.show(); self.overlay.raise_(); self.overlay.update()
        event.setDropAction(Qt.DropAction.CopyAction)
        # Accept enter/move to keep receiving feedback even at invalid rows.
        event.accept()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.DragLeave:
            self.overlay.hide(); self.selection = None; self.targets = None
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
                if self.selection is not None and self.targets is not None:
                    start, video, audio = self.targets
                    command = SourceInsertCommand(self.page.project, self.selection, start, video, audio)
                    self.page.undo_stack.push(command)
                    self.page.source_monitor.status.setText('源选段已加入时间线；可一步撤销')
                else:
                    self.page.source_monitor.status.setText(self.overlay.message)
                    event.ignore()
                self.overlay.hide()
        except (KeyError, ValueError, TypeError) as exc:
            self.page.source_monitor.status.setText(str(exc)); event.ignore(); self.overlay.hide()
        return True
