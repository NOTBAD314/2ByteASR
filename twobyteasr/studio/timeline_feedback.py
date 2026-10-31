"""Small, dynamic timeline feedback over the cached tracks.

Hover and I/O drags publish no document changes. Only release of a range
handle, or a media razor click, emits an editing request. Geometry is always
the timeline's existing project-time mapping, in logical Qt pixels.
"""
from dataclasses import dataclass
from time import perf_counter

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen, QRegion
from PySide6.QtWidgets import QWidget

from ..timeline.media_edit_time import asset_frame_rate, frame_time, source_at, range_point
from ..timeline.studio_edit_sequence import sequence_of
from ..timeline.studio_media_pool import asset_by_id
from ..projects.project_range import clock_text, range_points, effective_range
from ..i18n import tr


@dataclass(frozen=True)
class MediaCut:
    kind: str
    track_id: str
    clip_id: str
    pointer_ms: int
    split_ms: int
    source_ms: int
    frame: int | None
    rate: object
    snap: str
    blocked: str
    targets: tuple


def _colors(palette):
    return (QColor('#53E0CC' if palette.dark else '#006B60'),
            QColor('#FF9CDE' if palette.dark else '#942171'))


class TimelineFeedbackMixin:
    def _feedback_region(self):
        return QRegion(QRect(self.TRACK_HEADER_WIDTH, 0,
                             max(0, self._content_right() - self.TRACK_HEADER_WIDTH), self._canvas_bottom()))

    def _tail_padding_ms(self, visible_duration=None):
        width = max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
        pixels = min(180, max(32, width * .12))
        return round((self.visible_duration_ms if visible_duration is None else visible_duration) * pixels / width)

    def _scroll_maximum(self, visible_duration=None):
        visible = self.visible_duration_ms if visible_duration is None else visible_duration
        duration = self._duration_ms()
        return max(0, duration + self._tail_padding_ms(visible) - visible,
                   min(duration, getattr(self, '_page_tail_start_ms', 0)))

    def hold_manual_view(self):
        # Paused decoder/refresh observations are not new navigation. Keep the
        # user's view after the short gesture timeout as well. Playback resumes
        # normal follow explicitly through playback_selection_state_changed.
        self._manual_view_hold = True
        self._follow_suspended_until = perf_counter() + 2

    def fit_all_time(self):
        width = max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
        padding = min(width * .25, min(180, max(32, width * .12)))
        duration = max(1000, round(self._project_duration_ms * width / max(1, width - padding)))
        self.set_visible_window(0, duration)
        self._view_mode = 'fit'

    def _media_target_at(self, point):
        hit_point = point.toPoint() if isinstance(point, QPointF) else point
        if self.project is None or not self._feedback_region().contains(hit_point):
            return None
        kind, track_id = self._lane_and_item_at(point)[0]
        if kind not in ('video', 'audio'):
            return None
        tracks = self.project.video_tracks if kind == 'video' else self.project.audio_tracks
        track = next((t for t in tracks if t.id == track_id), None)
        value = self._x_to_time(point.x())
        clip = next((c for c in track.clips if c.timeline_in_ms <= value < c.timeline_out_ms), None) if track else None
        if clip is None:
            return None
        if kind == 'audio' and clip.linked_video_clip_id:
            group = next((g for g in self.project.av_track_groups if g.linked and g.audio_track_id == track_id), None)
            picture = next((t for t in self.project.video_tracks if group and t.id == group.video_track_id), None)
            video = next((c for c in picture.clips if c.id == clip.linked_video_clip_id), None) if picture else None
            if video:
                return 'video', picture, video
        return kind, track, clip

    def _cut_candidates(self, excluded=()):
        candidates = [(0, tr('时间轴零点')), (self.playhead_ms, tr('播放头'))]
        for track in (*self.project.video_tracks, *self.project.audio_tracks):
            for clip in track.clips:
                if clip.id in excluded:
                    continue
                candidates.extend(((clip.timeline_in_ms, f'{track.id} ' + tr('片段开头')),
                                   (clip.timeline_out_ms, f'{track.id} ' + tr('片段结尾'))))
        for cue in self.visible_cues():
            candidates.extend(((cue.start_ms, tr('字幕开头')), (cue.end_ms, tr('字幕结尾'))))
        candidates.extend((m.time_ms, tr('标记') + ' ' + m.label) for m in sequence_of(self.project).markers)
        candidates.extend((value, label) for value, label in zip(range_points(self.project), ('I', 'O')) if value is not None)
        return candidates

    def _update_media_razor(self, point, modifiers):
        if QPointF(point) != getattr(self, '_feedback_pointer', None):
            self._feedback_motion_at = perf_counter()
        self._feedback_pointer = QPointF(point)
        target = self._media_target_at(point) if self.tool_mode == 'razor' else None
        if target is None:
            self._clear_media_razor()
            return False
        kind, track, clip = target
        pointer = self._x_to_time(point.x())
        asset = asset_by_id(self.project, clip.asset_id)
        rate = asset_frame_rate(asset) if kind == 'video' else None
        bypass = bool(modifiers & Qt.AltModifier)
        runtime = getattr(self.project, '_studio_state_runtime', None)
        key = (id(self.project), getattr(runtime, 'revision', 0), kind, track.id, clip.id,
               pointer, self.snap_enabled, bypass, self.playhead_ms, self.visible_start_ms,
               self.visible_duration_ms, self._content_right(), track.locked,
               clip.timeline_in_ms, clip.timeline_out_ms, clip.source_in_ms, clip.source_out_ms,
               tuple((t.id, t.locked) for t in self.project.audio_tracks), clip.playback_rate, rate)
        if key == getattr(self, '_media_cut_key', None):
            return True
        blocked = tr('轨道已锁定，请先解锁') if track.locked else ''
        targets = [(kind, track.id, clip.id)]
        if kind == 'video':
            from ..timeline.studio_clip_edit import split_origin, video_track_locked
            if video_track_locked(self.project, track):
                blocked = tr('轨道已锁定，请先解锁')
            for group in self.project.av_track_groups:
                if group.linked and group.video_track_id == track.id:
                    sound = next((t for t in self.project.audio_tracks if t.id == group.audio_track_id), None)
                    for audio in sound.clips if sound else ():
                        if audio.linked_video_clip_id == clip.id:
                            targets.append(('audio', sound.id, audio.id))
                    if sound and sound.locked:
                        blocked = tr('关联音轨已锁定，请先解锁')
            origin_key = key[:5] + key[13:17]
            if origin_key != getattr(self, '_cut_origin_key', None):
                self._cut_origin_key = origin_key
                self._cut_origin = split_origin(self.project, track, clip)
            origin = self._cut_origin
        else:
            origin = clip
        value, snap = pointer, ''
        if self.snap_enabled and not bypass:
            threshold = 8 * self.visible_duration_ms / max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
            options = [(abs(t - pointer), t, label) for t, label in self._cut_candidates({c[2] for c in targets})
                       if clip.timeline_in_ms < t < clip.timeline_out_ms and abs(t - pointer) <= threshold]
            if options:
                _, value, snap = min(options)
        split, frame = frame_time(clip, value, rate, origin=origin)
        source = round(source_at(origin, split))
        if snap and split != value:
            snap += ' · ' + tr('帧对齐')
        if not clip.timeline_in_ms < split < clip.timeline_out_ms or not clip.source_in_ms < source < clip.source_out_ms:
            blocked = blocked or tr('已到片段边界，不能生成空片段')
        resolution = MediaCut(kind, track.id, clip.id, pointer, split, source, frame, rate, snap, blocked, tuple(targets))
        old = getattr(self, '_media_cut_region', QRegion())
        self._media_cut, self._media_cut_key = resolution, key
        self._media_cut_region = self._media_razor_region(resolution)
        QWidget.update(self, old | self._media_cut_region)
        return True

    def _media_razor_region(self, cut):
        x = round(self._time_to_x(cut.split_ms))
        region = QRegion(QRect(x - 5, 0, 11, self._canvas_bottom()))
        region |= QRegion(QRect(0, 0, self._content_right(), self.RULER_HEIGHT))
        for kind, track_id, clip_id in cut.targets:
            rect = self._media_clip_rect(kind, track_id, clip_id)
            if rect is not None:
                region |= QRegion(rect.adjusted(-3, -3, 3, 3).toAlignedRect())
        return region.intersected(QRegion(self.rect()))

    def _media_clip_rect(self, kind, track_id, clip_id):
        tracks = self.project.video_tracks if kind == 'video' else self.project.audio_tracks
        clip = next((c for t in tracks if t.id == track_id for c in t.clips if c.id == clip_id), None)
        rows = self._video_track_rects() if kind == 'video' else self._audio_track_rects()
        row = rows.get(track_id)
        if clip is None or row is None:
            return None
        rect = QRectF(self._time_to_x(clip.timeline_in_ms), row.top() + 4,
                      self._time_to_x(clip.timeline_out_ms) - self._time_to_x(clip.timeline_in_ms), row.height() - 8)
        return rect.intersected(QRectF(self.TRACK_HEADER_WIDTH, row.top(),
                                      self._content_right() - self.TRACK_HEADER_WIDTH, row.height()))

    def _clear_media_razor(self):
        region = getattr(self, '_media_cut_region', QRegion())
        self._media_cut = self._media_cut_key = None
        self._media_cut_region = QRegion()
        if not region.isEmpty():
            QWidget.update(self, region)

    def _refresh_pointer_feedback(self):
        if (self.tool_mode == 'razor' and self._razor_drag is None
                and (getattr(self, '_media_cut', None) is not None or self._razor_hover is not None)
                and getattr(self, '_feedback_pointer', None) is not None):
            from PySide6.QtWidgets import QApplication
            self._update_razor_hover(self._feedback_pointer, QApplication.keyboardModifiers())

    def _paint_media_razor(self, painter, palette):
        cut = getattr(self, '_media_cut', None)
        if cut is None or self.tool_mode != 'razor':
            return
        from .timeline_razor import razor_colors
        color = razor_colors(palette)['cut']
        if cut.blocked:
            color = razor_colors(palette)['warn']
        painter.save()
        painter.setClipRegion(self._feedback_region())
        x = self._time_to_x(cut.split_ms)
        painter.setPen(QPen(QColor('#17131B' if palette.dark else '#FFFFFF'), 4))
        painter.drawLine(QPointF(x, 0), QPointF(x, self._canvas_bottom()))
        pen = QPen(color, 2, Qt.DashLine)
        pen.setDashPattern([4, 3])
        painter.setPen(pen)
        painter.drawLine(QPointF(x, 0), QPointF(x, self._canvas_bottom()))
        label = '✂ ' + clock_text(cut.split_ms)
        if cut.snap:
            label += ' · ' + tr('吸附') + ' ' + cut.snap
        font = QFont(self.font()); font.setPointSize(9); font.setBold(True)
        painter.setFont(font)
        width = min(self._content_right() - self.TRACK_HEADER_WIDTH - 4,
                    QFontMetrics(font).horizontalAdvance(label) + 18)
        left = min(self._content_right() - width - 2, max(self.TRACK_HEADER_WIDTH + 2, x + 9))
        # Keep the red transport label readable when snapping to it.
        head = self._time_to_x(self.playhead_ms)
        if left < head + 43 and left + width > head - 43:
            left = max(self.TRACK_HEADER_WIDTH + 2, min(self._content_right() - width - 2, head + 46))
        pill = QRectF(left, 2, width, self.RULER_HEIGHT - 5)
        painter.setPen(Qt.NoPen); painter.setBrush(color); painter.drawRoundedRect(pill, 4, 4)
        painter.setPen(QColor('#17131B' if palette.dark else '#FFFFFF'))
        painter.drawText(pill.adjusted(6, 0, -6, 0), Qt.AlignVCenter, label)
        painter.setClipping(False)
        header = QRectF(2, 0, self.TRACK_HEADER_WIDTH - 4, self.RULER_HEIGHT)
        painter.fillRect(header, QColor(palette.header))
        painter.setPen(color)
        small = QFont(font); small.setPointSize(8); painter.setFont(small)
        names = ' + '.join(dict.fromkeys(t[1] for t in cut.targets))
        detail = cut.blocked or (f'F{cut.frame} · {float(cut.rate):g} fps' if cut.frame is not None else tr('毫秒时间基准'))
        painter.drawText(header.adjusted(6, 1, -3, -1), Qt.AlignVCenter, tr('剃刀') + ' · ' + names + '\n' + detail)
        painter.restore()
        self._last_media_cut_paint = (cut.split_ms, perf_counter())

    def _paint_coincident_razor(self, painter, palette):
        cut = getattr(self, '_media_cut', None)
        if cut is None or self.tool_mode != 'razor':
            return
        x = self._time_to_x(cut.split_ms)
        if abs(x-self._time_to_x(self.playhead_ms)) > 3:
            return
        from .timeline_razor import razor_colors
        painter.save(); painter.setClipRegion(self._feedback_region())
        pen=QPen(razor_colors(palette)['cut'],2,Qt.DashLine);pen.setDashPattern([4,3])
        painter.setPen(pen)
        painter.drawLine(QPointF(x,self.RULER_HEIGHT),QPointF(x,self._canvas_bottom()))
        painter.restore()

    def _media_razor_press(self, point, modifiers):
        if self.tool_mode != 'razor':
            return False
        cut = getattr(self, '_media_cut', None)
        target = self._media_target_at(point)
        same_preview = (cut is not None and target is not None
                        and (cut.kind, cut.track_id, cut.clip_id) == (target[0], target[1].id, target[2].id)
                        and abs(point.x()-getattr(self, '_feedback_pointer', QPointF(point)).x()) <= 1)
        if not same_preview and not self._update_media_razor(point, modifiers):
            return False
        cut = self._media_cut
        self.setFocus(Qt.MouseFocusReason)
        self._clear_razor_preview()
        self._clear_media_razor()
        self._razor_swallow_release = True
        if cut.blocked:
            self.edit_blocked.emit(cut.blocked)
        elif cut.kind == 'video':
            self.video_clip_razor_requested.emit(cut.track_id, cut.clip_id, cut.split_ms)
        else:
            self.audio_clip_razor_requested.emit(cut.track_id, cut.clip_id, cut.split_ms)
        return True

    def _media_edge_at(self, point):
        if self.project is None or self.tool_mode != 'selection' or point.x() < self.TRACK_HEADER_WIDTH:
            return None
        track_id = self._video_track_at(point)
        track = next((t for t in self.project.video_tracks if t.id == track_id), None)
        if track is None:
            return None
        from ..timeline.studio_clip_edit import video_track_locked
        if video_track_locked(self.project, track):
            return None
        edges = [(abs(point.x() - self._time_to_x(value)), clip.id != self.selected_video_clip_id, clip.id, edge)
                 for clip in track.clips for edge, value in (('trim_left', clip.timeline_in_ms), ('trim_right', clip.timeline_out_ms))
                 if self.TRACK_HEADER_WIDTH <= self._time_to_x(value) <= self._content_right()
                 and abs(point.x() - self._time_to_x(value)) <= self.VIDEO_CLIP_TRIM_HANDLE_PX]
        if not edges:
            return None
        _, _, key, edge = min(edges)
        return track_id, key, edge

    def _update_media_edge(self, point):
        before = getattr(self, '_media_edge_hover', None)
        current = self._media_edge_at(point)
        if before != current:
            self._media_edge_hover = current
            region = QRegion()
            for state in (before, current):
                if state:
                    rect = self._media_clip_rect('video', state[0], state[1])
                    if rect is not None:
                        region |= QRegion(rect.adjusted(-12, -4, 12, 4).toAlignedRect())
            if not region.isEmpty():
                QWidget.update(self, region)
        return current

    def _paint_media_edges(self, painter, palette):
        state = getattr(self, '_media_edge_hover', None)
        drag = self._clip_drag
        if drag and drag['mode'] in ('trim_left', 'trim_right'):
            state = drag['track_id'], drag['clip_id'], drag['mode']
        if not state:
            return
        track_id, clip_id, edge = state
        clip = next((c for t in self.project.video_tracks if t.id == track_id for c in t.clips if c.id == clip_id), None)
        row = self._video_track_rects().get(track_id)
        if clip is None or row is None:
            return
        value = clip.timeline_in_ms if edge == 'trim_left' else clip.timeline_out_ms
        if drag:
            value = drag['preview_in'] if edge == 'trim_left' else drag['preview_out']
        x = self._time_to_x(value)
        painter.save(); painter.setClipRegion(self._feedback_region())
        color = QColor('#FFD04D' if palette.dark else '#1D5FD1')
        painter.setPen(QPen(QColor(palette.background), 6))
        painter.drawLine(QPointF(x, row.top() + 3), QPointF(x, row.bottom() - 3))
        painter.setPen(QPen(color, 3))
        painter.drawLine(QPointF(x, row.top() + 3), QPointF(x, row.bottom() - 3))
        painter.setBrush(color); painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(x - 4, row.center().y() - 10, 8, 20), 2, 2)
        if drag and (drag.get('limit') or drag.get('invalid')):
            label = drag.get('invalid') or drag['limit']
            painter.setFont(self.font()); width = min(420, QFontMetrics(self.font()).horizontalAdvance(label) + 16)
            left = min(self._content_right() - width - 3, max(self.TRACK_HEADER_WIDTH + 3, x - width / 2))
            rect = QRectF(left, row.top() - 23, width, 22)
            painter.fillRect(rect, QColor(palette.background)); painter.setPen(color)
            painter.drawText(rect, Qt.AlignCenter, label)
        painter.restore()

    def _paint_media_boundaries(self, painter, palette):
        # The static media silhouette already shows the true edges. Keep
        # hit ranges invisible; only an actively hovered/dragged edge is lit.
        return

    def _range_display_points(self):
        return getattr(self, '_range_preview', None) or range_points(self.project)

    def _range_handles(self):
        if self.project is None:
            return []
        points = self._range_display_points()
        handles = []
        for index, value in enumerate(points):
            if value is None:
                continue
            x = self._time_to_x(value)
            offscreen = -1 if x < self.TRACK_HEADER_WIDTH else 1 if x > self._content_right() else 0
            label = ('I ' + tr('入点')) if index == 0 else ('O ' + tr('出点'))
            if offscreen:
                label = ('‹ ' if offscreen < 0 else '') + label + ' ' + clock_text(value) + (' ›' if offscreen > 0 else '')
            font = QFont(self.font()); font.setPointSize(8); font.setBold(True)
            width = min(165, QFontMetrics(font).horizontalAdvance(label) + 12)
            left = x if index == 0 else x - width
            left = min(self._content_right() - width, max(self.TRACK_HEADER_WIDTH, left))
            rect = QRectF(left, 0, width, 18)
            if handles and rect.intersects(handles[0][3]):
                rect.moveTop(18)
            handles.append((index, value, x, rect, label, offscreen))
        return handles

    def _range_handle_at(self, point):
        if not self.project or point.y() < 0 or point.y() > self.RULER_HEIGHT or point.x() < self.TRACK_HEADER_WIDTH:
            return None
        hits = []
        for index, value, x, rect, label, offscreen in self._range_handles():
            # Offscreen badges are informative; dragging them must not teleport I/O.
            if offscreen:
                continue
            if rect.contains(point) or abs(point.x() - x) <= 9:
                hits.append((0 if rect.contains(point) else 1, abs(point.x() - x), index))
        return min(hits)[2] if hits else None

    def _update_range_hover(self, point):
        index = self._range_handle_at(point)
        if index != getattr(self, '_range_hover', None):
            self._range_hover = index
            QWidget.update(self, QRect(self.TRACK_HEADER_WIDTH, 0,
                                       self._content_right()-self.TRACK_HEADER_WIDTH, self.RULER_HEIGHT))
        return index

    def _range_press(self, point):
        index = self._range_handle_at(point)
        if index is None:
            return False
        self.setFocus(Qt.MouseFocusReason)
        self._range_drag = dict(index=index, before=range_points(self.project), origin=QPointF(point),
                                origin_time=self._x_to_time(point.x()), pointer=QPointF(point))
        self._range_preview = self._range_drag['before']
        self._clear_razor_preview(); self._clear_media_razor()
        self.interaction_changed.emit(True); self.setCursor(Qt.SizeHorCursor)
        return True

    def _range_move(self, point, modifiers):
        drag = getattr(self, '_range_drag', None)
        if not drag:
            return False
        drag['pointer'], drag['modifiers'] = QPointF(point), modifiers
        value = drag['before'][drag['index']] + self._x_to_time(point.x()) - drag['origin_time']
        if self.snap_enabled and not modifiers & Qt.AltModifier:
            width = max(1, self._content_right() - self.TRACK_HEADER_WIDTH)
            candidates = [(abs(t - value), t) for t, label in self._cut_candidates()
                          if label not in ('I', 'O') and abs(t - value) <= self.visible_duration_ms * 8 / width]
            if candidates:
                value = min(candidates)[1]
        self._range_preview = range_point(drag['before'], drag['index'], value, self._project_duration_ms)
        # A cheap raster blit and two lines; no cue projection or base rebuild.
        QWidget.update(self, QRegion(self.rect()))
        near = point.x() < self.TRACK_HEADER_WIDTH + 24 or point.x() > self._content_right() - 24
        if near:
            self._clip_scroll_timer.start()
        return True

    def _range_release(self, cancel=False):
        drag = getattr(self, '_range_drag', None)
        if not drag:
            return False
        points = self._range_preview
        self._range_drag = self._range_preview = None
        self._clip_scroll_timer.stop()
        self.interaction_changed.emit(False)
        if not cancel and points != drag['before']:
            self.range_edit_committed.emit(*points)
        QWidget.update(self, QRegion(self.rect()))
        return True

    def _paint_range_feedback(self, painter, palette):
        if self.project is None:
            return
        points = self._range_display_points()
        if points == (None, None):
            return
        colors = _colors(palette)
        start = 0 if points[0] is None else points[0]
        end = self._project_duration_ms if points[1] is None else points[1]
        painter.save(); painter.setClipRegion(self._feedback_region())
        left, right = max(self.TRACK_HEADER_WIDTH, self._time_to_x(start)), min(self._content_right(), self._time_to_x(end))
        if right > left:
            tint = QColor(colors[0]); tint.setAlpha(26 if palette.dark else 20)
            painter.fillRect(QRectF(left, self.RULER_HEIGHT, right-left, self._canvas_bottom()-self.RULER_HEIGHT), tint)
            tint.setAlpha(105 if palette.dark else 74)
            painter.fillRect(QRectF(left, self.RULER_HEIGHT-9, right-left, 9), tint)
            painter.setPen(QPen(colors[0], 2))
            painter.drawLine(QPointF(left, self.RULER_HEIGHT-2), QPointF(right, self.RULER_HEIGHT-2))
        font = QFont(self.font()); font.setPointSize(8); font.setBold(True); painter.setFont(font)
        for index, value, x, rect, label, offscreen in self._range_handles():
            color = colors[index]
            if index == getattr(self, '_range_hover', None):
                color = color.lighter(120)
            if not offscreen:
                painter.setPen(QPen(QColor('#17131B' if palette.dark else '#FFFFFF'), 4))
                painter.drawLine(QPointF(x, 0), QPointF(x, self._canvas_bottom()))
                painter.setPen(QPen(color, 2))
                painter.drawLine(QPointF(x, 0), QPointF(x, self._canvas_bottom()))
            painter.setBrush(color); painter.setPen(Qt.NoPen); painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor('#17131B' if palette.dark else '#FFFFFF'))
            painter.drawText(rect, Qt.AlignCenter, label)
        painter.setClipping(False)
        if not getattr(self, '_media_cut', None) and self._razor_resolution() is None:
            header = QRectF(0, 0, self.TRACK_HEADER_WIDTH, self.RULER_HEIGHT)
            painter.fillRect(header, QColor(palette.header)); painter.setPen(QColor(palette.clip_text))
            label = 'I ' + (clock_text(points[0]) if points[0] is not None else '—') + '  ·  O ' + (clock_text(points[1]) if points[1] is not None else '—')
            label += '\nΔ ' + clock_text(max(0, end-start))
            painter.drawText(header.adjusted(6, 0, -4, 0), Qt.AlignVCenter, label)
        painter.restore()
        self._last_range_paint = (points, perf_counter())
