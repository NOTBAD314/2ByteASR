"""Painted parts of the two loading faces (2026-11-02 redesign).

Opening a project shows the poster face: the project's cover with a
playback-style progress bar (the bunny's face is the knob) and a subtitle-
style line, beside the real stages. Entering the project library shows the
library face: the bunny, the build stages and a fan of recent projects; a
picked card opens as soon as the workbench is ready.

Progress only advances with completed stages; the current stage is shown by
motion (hopping dots), never by an invented percentage.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QTransform)
from PySide6.QtWidgets import QProgressBar, QWidget

STAGE_ICONS = {
    '创建工作台界面': 'fa5s.th-large', '读取工程': 'fa5s.folder-open', '建立时间轴': 'fa5s.stream',
    '准备播放器': 'fa5s.play', '准备音频': 'fa5s.volume-up', '准备字幕': 'fa5s.closed-captioning',
    '首屏绘制': 'fa5s.magic',
    '搭工作台框架': 'fa5s.th-large', '装工具面板': 'fa5s.toolbox', '铺时间轴': 'fa5s.stream',
    '摆工程库': 'fa5s.book-open', '读取工程列表': 'fa5s.th',
}
STAGE_DETAILS = {
    '创建工作台界面': '第一次进入时建立界面', '读取工程': '工程文件与素材清单', '建立时间轴': '字幕与说话人轨',
    '准备播放器': '启动播放器', '准备音频': '连接音频输出', '准备字幕': '字体与样式', '首屏绘制': '画出第一屏',
    '搭工作台框架': '工具栏、字幕列表、视频区', '装工具面板': 'AI、样式、动效、剪辑、素材',
    '铺时间轴': '时间轴工具栏与轨道', '摆工程库': '工程库布局与导航', '读取工程列表': '名称、封面、字幕条数',
}
# The bunny's line for each stage (decoration; the stage names stay plain).
STAGE_LINES = {
    '创建工作台界面': '先把桌子摆好～', '读取工程': '先把工程翻开看看～', '建立时间轴': '字幕排排站好',
    '准备播放器': '播放器热身中…', '准备音频': '喂喂？试一下声音', '准备字幕': '字幕样式穿戴整齐',
    '首屏绘制': '马上就好！',
    '搭工作台框架': '先把桌子摆好～', '装工具面板': '工具一件件挂上墙', '铺时间轴': '轨道铺平啦',
    '摆工程库': '书架擦一擦', '读取工程列表': '工程马上就到！',
}
FAILED_LINE = '呜…出了点问题'
READY_LINE = '好啦，开工！'


def active_theme():
    from ..design.theme_manager import theme_definition, theme_key
    return theme_definition(theme_key())


def _tr(text: str) -> str:
    from ..i18n import current_language, translate
    language = current_language()
    return translate(text, language) if language != 'zh' else text


def _alpha(color, alpha: float) -> QColor:
    value = QColor(color)
    value.setAlphaF(alpha)
    return value


_ICON_CACHE: dict = {}


def stage_icon(name: str, color: str, size: int, ratio: float) -> QPixmap:
    key = (name, color, size, ratio)
    pixmap = _ICON_CACHE.get(key)
    if pixmap is None:
        try:
            import qtawesome as qta
            pixmap = qta.icon(name, color=color).pixmap(QSize(size, size), ratio)
        except Exception:
            pixmap = QPixmap()
        _ICON_CACHE[key] = pixmap
    return pixmap


def _draw_check(painter, center: QPointF, color, scale=1.0):
    painter.setPen(QPen(QColor(color), 2.2 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    c = center
    painter.drawPolyline([QPointF(c.x() - 4.2 * scale, c.y() + .2 * scale), QPointF(c.x() - 1.2 * scale, c.y() + 3.2 * scale),
                          QPointF(c.x() + 4.6 * scale, c.y() - 3 * scale)])


def _draw_cross(painter, center: QPointF, color, scale=1.0):
    painter.setPen(QPen(QColor(color), 2.2 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    d = 3.6 * scale
    painter.drawLine(QPointF(center.x() - d, center.y() - d), QPointF(center.x() + d, center.y() + d))
    painter.drawLine(QPointF(center.x() - d, center.y() + d), QPointF(center.x() + d, center.y() - d))


def _draw_dots(painter, right: float, cy: float, color, now: float):
    painter.setPen(Qt.PenStyle.NoPen)
    for index in range(3):
        phase = (now * 1.0 - index * .15) % 1.0
        lift = math.sin(phase / .3 * math.pi) * 4 if phase < .3 else 0.0
        painter.setBrush(_alpha(color, .45 + (.55 if lift > .5 else .0)))
        painter.drawEllipse(QPointF(right - 22 + index * 8, cy - lift), 2.6, 2.6)


class ReadinessSteps(QWidget):
    """The real opening stages: done ✓ with its time, current (hopping dots), waiting, failed ✕.

    ``compact`` is the library face's vertical list; otherwise rows with icon tiles.
    """

    ROW = 44
    completion_painted = Signal()
    completion_finished = Signal()
    FINISH_SECONDS = .28

    def __init__(self, tasks, parent=None, *, compact=False):
        super().__init__(parent)
        self.tasks = tuple(tasks)
        self.compact = compact
        self.row = 40 if compact else self.ROW
        self.completed: set[str] = set()
        self.current = ''
        self.failed = ''
        self.failed_detail = ''
        self.skipped = {}
        self.reused = {}
        self.times: dict[str, float] = {}
        self._finishing = False
        self._finish_started = None
        self.setMinimumHeight(self.row * len(self.tasks))
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._update_active_row)

    def sizeHint(self):
        return QSize(360, self.row * len(self.tasks))

    def _update_active_row(self):
        if self._finishing:
            self.update()
            return
        if self.current in self.tasks:
            index=self.tasks.index(self.current)
            self.update(QRect(0,index*self.row,self.width(),self.row))

    def set_dense(self, dense: bool):
        """Shorter rows while an error message needs the room (project face)."""
        row = (34 if self.compact else 36) if dense else (40 if self.compact else self.ROW)
        if row != self.row:
            self.row = row
            self.setMinimumHeight(self.row * len(self.tasks))
            self.updateGeometry()
            self.update()

    def set_state(self, completed, current='', failed=''):
        desired=(set(completed),str(current or ''),str(failed or ''))
        if (self.completed,self.current,self.failed)==desired:return
        self.completed,self.current,self.failed=desired
        if self.failed or set(self.tasks) - self.completed:
            self.cancel_completion()
        self._sync_timer()
        self.update()

    def _sync_timer(self):
        animate = bool((self.current or self._finishing) and not self.failed and self.isVisible())
        if animate and not self._timer.isActive():
            self._timer.start()
        elif not animate:
            self._timer.stop()

    def finish_after_paint(self):
        """Start the success gesture only when every final row is painted."""
        self._finishing = True
        self._finish_started = None
        self._sync_timer()
        self.update()

    def cancel_completion(self):
        self._finishing = False
        self._finish_started = None

    def showEvent(self, event):
        self._sync_timer()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def state_of(self, task):
        if task == self.failed:
            return 'failed'
        if task in self.completed:
            return 'reused' if task in self.reused else 'done'
        if task == self.current:
            return 'active'
        return 'waiting'

    def paintEvent(self, _event):
        theme = active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ratio = self.devicePixelRatioF()
        now = time.perf_counter()
        final = self._finishing and not self.failed and set(self.tasks) <= self.completed
        first_final_paint = final and self._finish_started is None
        if first_final_paint:
            self._finish_started = now
        finish_progress = min(1., (now-self._finish_started)/self.FINISH_SECONDS) if final else 0.
        base = QFont(self.font())
        mono = QFont('Cascadia Mono')
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPixelSize(12)
        width = self.width()
        if self.compact:
            painter.setPen(QPen(QColor(theme.border), 2))
            painter.drawLine(QPointF(15, self.row / 2), QPointF(15, self.row * (len(self.tasks) - .5)))
        clip=_event.rect() if _event is not None else self.rect()
        for index, task in enumerate(self.tasks):
            top = index * self.row
            if not clip.intersects(QRect(0,top,width,self.row)):continue
            state = self.state_of(task)
            label = _tr(task) + ((' · ' + _tr('已复用')) if task in self.reused else
                                (' · ' + _tr('无需准备')) if task in self.skipped else '')
            if self.compact:
                tile = QRectF(0, top + (self.row - 30) / 2, 30, 30)
                text_left = 44
            else:
                row = QRectF(0, top + 2, width, self.row - 4)
                if state in ('active', 'failed'):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(theme.accent_soft if state == 'active' else theme.danger_soft))
                    painter.drawRoundedRect(row, 15, 15)
                tile = QRectF(7, top + (self.row - 32) / 2, 32, 32)
                text_left = 52
            fill, ink, border = {
                'reused': (theme.accent if self.compact else _alpha(theme.success, .16), theme.text_on_accent if self.compact else theme.success, None),
                'done': (theme.accent if self.compact else _alpha(theme.success, .16), theme.text_on_accent if self.compact else theme.success, None),
                'active': (theme.accent if not self.compact else theme.accent_soft, theme.text_on_accent if not self.compact else theme.accent_text, theme.accent if self.compact else None),
                'failed': (theme.danger, '#ffffff', None),
                'waiting': (theme.panel if not self.compact else theme.app_background, theme.text_muted, theme.border_strong),
            }[state]
            painter.setBrush(QColor(fill))
            if border:
                pen = QPen(QColor(border), 1.4)
                if state == 'waiting':
                    pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
            if self.compact:
                painter.drawEllipse(tile)
            else:
                painter.drawRoundedRect(tile, 11, 11)
            center = tile.center()
            if state in ('done','reused'):
                _draw_check(painter, center, ink, 1.0 + .18*math.sin(math.pi*finish_progress))
            elif state == 'failed':
                _draw_cross(painter, center, ink)
            else:
                icon = stage_icon(STAGE_ICONS.get(task, 'fa5s.circle'), QColor(ink).name(), 15, ratio)
                painter.drawPixmap(QPointF(center.x() - 7.5, center.y() - 7.5), icon)
            font = QFont(base)
            font.setPixelSize(14 if not self.compact else 13)
            font.setWeight(QFont.Weight.Bold if state in ('active', 'failed') else QFont.Weight.Medium)
            painter.setFont(font)
            color = {'active': theme.accent_text, 'failed': theme.danger,
                     'done': theme.text_secondary, 'reused': theme.text_secondary}.get(state, theme.text_muted)
            painter.setPen(QColor(color))
            right_space = 64
            detail = ''
            if not self.compact and state in ('active', 'failed') and self.row >= 40:
                detail = self.failed_detail if state == 'failed' and self.failed_detail else _tr(STAGE_DETAILS.get(task, ''))
            if detail:
                painter.drawText(QRectF(text_left, top + 5, width - text_left - right_space, self.row / 2),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
                small = QFont(base)
                small.setPixelSize(11)
                painter.setFont(small)
                painter.setPen(_alpha(color, .78))
                metrics = QFontMetricsF(small)
                painter.drawText(QRectF(text_left, top + self.row / 2 - 2, width - text_left - right_space, self.row / 2 - 4),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                                 metrics.elidedText(detail, Qt.TextElideMode.ElideRight, width - text_left - right_space))
            else:
                painter.drawText(QRectF(text_left, top, width - text_left - right_space, self.row),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            cy = top + self.row / 2
            if state == 'done':
                seconds = self.times.get(task)
                if seconds is not None and task not in self.skipped:
                    painter.setFont(mono)
                    painter.setPen(QColor(theme.success if not self.compact else theme.text_muted))
                    painter.drawText(QRectF(width - right_space - 14, top, right_space, self.row),
                                     Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f'{seconds:.1f}s')
            elif state == 'active':
                _draw_dots(painter, width - 8, cy, theme.accent_text, now)
            elif state in ('failed', 'waiting') and not self.compact:
                small = QFont(base)
                small.setPixelSize(12)
                small.setWeight(QFont.Weight.Bold if state == 'failed' else QFont.Weight.Medium)
                painter.setFont(small)
                painter.setPen(QColor(theme.danger if state == 'failed' else theme.text_muted))
                painter.drawText(QRectF(width - right_space - 14, top, right_space, self.row),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                                 _tr('失败') if state == 'failed' else _tr('等待'))
        painter.end()
        if first_final_paint:
            self.completion_painted.emit()
        if final and finish_progress >= 1.:
            self._finishing = False
            self._sync_timer()
            self.completion_finished.emit()


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _draw_glass_chip(painter, text, anchor: QPointF, *, right=False, mono=False):
    font = QFont('Cascadia Mono') if mono else QFont(painter.font())
    font.setPixelSize(12)
    metrics = QFontMetricsF(font)
    width = metrics.horizontalAdvance(text) + 24
    rect = QRectF(anchor.x() - width if right else anchor.x(), anchor.y(), width, 28)
    painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
    painter.setBrush(QColor(20, 14, 20, 100))
    painter.drawRoundedRect(rect, 14, 14)
    painter.setFont(font)
    painter.setPen(QColor('#ffffff'))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


_outlined_rasters = {}

def _outlined_text(painter, rect: QRectF, text: str, pixel_size: int, *, scale=1.0, opacity=1.0):
    ratio=painter.device().devicePixelRatioF()
    key=(text,pixel_size,round(rect.width()),painter.font().toString(),ratio)
    image=_outlined_rasters.get(key)
    if image is None:
        from PySide6.QtGui import QImage
        font=QFont(painter.font());font.setPixelSize(pixel_size);font.setWeight(QFont.Weight.Black)
        metrics=QFontMetricsF(font)
        while metrics.horizontalAdvance(text)>rect.width() and font.pixelSize()>14:
            font.setPixelSize(font.pixelSize()-2);metrics=QFontMetricsF(font)
        path=QPainterPath();path.addText(0,0,font,text)
        stroke=max(4.0,font.pixelSize()/5.5)
        box=path.boundingRect().adjusted(-stroke,-stroke,stroke,stroke)
        image=QImage(max(1,round(box.width()*ratio)),max(1,round(box.height()*ratio)),QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
        raster=QPainter(image);raster.setRenderHint(QPainter.RenderHint.Antialiasing)
        raster.translate(-box.topLeft())
        raster.setPen(QPen(QColor('#1a1410'),stroke,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        raster.setBrush(Qt.BrushStyle.NoBrush);raster.drawPath(path);raster.fillPath(path,QColor('#ffffff'));raster.end()
        if len(_outlined_rasters)>=32:_outlined_rasters.pop(next(iter(_outlined_rasters)))
        _outlined_rasters[key]=image
    painter.save();painter.setOpacity(opacity);painter.translate(rect.center());painter.scale(scale,scale)
    painter.drawImage(QPointF(-image.width()/ratio/2,-image.height()/ratio/2),image);painter.restore()


def cover_placeholder(size: QSize) -> QPixmap:
    """No cover yet: a soft gradient in theme colours with a large CC."""
    theme = active_theme()
    pixmap = QPixmap(max(1, size.width()), max(1, size.height()))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, size.width(), size.height())
    gradient.setColorAt(0, QColor(theme.media))
    gradient.setColorAt(1, QColor(theme.accent).darker(170))
    painter.fillRect(pixmap.rect(), gradient)
    font = QFont(painter.font())
    font.setPixelSize(max(24, size.height() // 4))
    font.setWeight(QFont.Weight.Black)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 46))
    painter.drawText(QRectF(pixmap.rect()), Qt.AlignmentFlag.AlignCenter, 'CC')
    painter.end()
    return pixmap


class CoverScrubber(QProgressBar):
    """The loading progress, drawn like a player's seek bar over the cover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextVisible(False)
        # The global QSS caps progress bars at a thin line; this one is a 48 px pill.
        self.setStyleSheet('QProgressBar {min-height:48px; max-height:48px; border:0; background:transparent;}')
        self.setFixedHeight(48)
        self.glyph = 'fa5s.folder-open'
        self.failed = False
        self.finished = False
        self._shown = 0.0
        self._ease_from = 0.0
        self._ease_started = time.perf_counter()
        self._face = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._ease)
        self.valueChanged.connect(self._retarget)

    def _retarget(self, _value):
        self._ease_from = self._shown
        self._ease_started = time.perf_counter()
        self._timer.start()

    def _target(self):
        span = max(1, self.maximum() - self.minimum())
        return (self.value() - self.minimum()) / span + (.5 / span if self.failed else 0.0)

    def _ease(self):
        target = self._target()
        progress = min(1., max(0., (time.perf_counter()-self._ease_started)/.18))
        self._shown = self._ease_from + (target-self._ease_from)*(1.-(1.-progress)**3)
        if progress >= 1.:
            self._shown = target
            self._timer.stop()
        self.update()

    def reset_progress(self):
        self._timer.stop()
        self._shown = 0.0
        self._ease_from = 0.0
        self._ease_started = time.perf_counter()
        self.failed = self.finished = False
        self.update()

    def paintEvent(self, _event):
        from ..design.bunny_mascot import bunny_face_pixmap
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        ratio = self.devicePixelRatioF()
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        painter.setPen(QPen(QColor(255, 255, 255, 36), 1))
        painter.setBrush(QColor(20, 14, 20, 108))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        # Left: the current stage's icon in a white disc.
        disc = QRectF(8, (self.height() - 32) / 2, 32, 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(disc)
        if self.failed:
            _draw_cross(painter, disc.center(), '#c0362f')
        elif self.finished:
            _draw_check(painter, disc.center(), '#2f7a45')
        else:
            icon = stage_icon(self.glyph, '#2a2133', 15, ratio)
            painter.drawPixmap(QPointF(disc.center().x() - 7.5, disc.center().y() - 7.5), icon)
        painter.setPen(Qt.PenStyle.NoPen)
        count = f'{min(self.value() + (0 if self.finished or self.failed else 1), self.maximum())}/{self.maximum()}'
        mono = QFont('Cascadia Mono')
        mono.setPixelSize(12)
        count_width = QFontMetricsF(mono).horizontalAdvance(count) + 4
        track = QRectF(disc.right() + 20, self.height() / 2 - 4, self.width() - disc.right() - 40 - count_width - 16, 8)
        painter.setBrush(QColor(255, 255, 255, 56))
        painter.drawRoundedRect(track, 4, 4)
        fraction = max(0.0, min(1.0, self._shown))
        filled = QRectF(track.left(), track.top(), track.width() * fraction, track.height())
        if filled.width() > 0:
            gradient = QLinearGradient(filled.topLeft(), filled.topRight())
            gradient.setColorAt(0, QColor('#f3866b' if self.failed else '#ffd6a0'))
            gradient.setColorAt(1, QColor('#f3866b' if self.failed else '#ffffff'))
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(filled, 4, 4)
        steps = max(1, self.maximum() - self.minimum())
        painter.setBrush(QColor(20, 14, 20, 90))
        for index in range(1, steps):
            x = track.left() + track.width() * index / steps
            painter.drawRect(QRectF(x - 1, track.top(), 2, track.height()))
        knob = 34
        if self._face is None or self._face[0] != ratio:
            self._face = (ratio, bunny_face_pixmap(knob, ratio))
        center = QPointF(track.left() + track.width() * fraction, self.height() / 2)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(center, knob / 2 + 3, knob / 2 + 3)
        painter.drawPixmap(QPointF(center.x() - knob / 2, center.y() - knob / 2), self._face[1])
        painter.setFont(mono)
        painter.setPen(QColor(255, 255, 255, 230))
        painter.drawText(QRectF(self.width() - count_width - 16, 0, count_width, self.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, count)
        painter.end()


class CoverPane(QWidget):
    """The project's cover, its two info chips and the bunny's subtitle line."""

    INSET = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cover = QPixmap()
        self.left_chip = ''
        self.right_chip = ''
        self.line = ''
        self.failed = False
        self._line_at = 0.0
        self._scaled = None
        self.scrubber = CoverScrubber(self)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_cover(self, pixmap: QPixmap):
        self.cover = pixmap if pixmap is not None else QPixmap()
        self._scaled = None
        self.update()

    def set_line(self, text: str):
        if text != self.line:
            self.line = text
            self._line_at = time.perf_counter()
            self._timer.start()
            self.update()

    def set_failed(self, failed: bool):
        if failed != self.failed:
            self.failed = failed
            self._scaled = None
            self.update()

    def _tick(self):
        if time.perf_counter() - self._line_at > .45:
            self._timer.stop()
        self.update()

    def inner_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(self.INSET, self.INSET, -self.INSET, -self.INSET)

    def resizeEvent(self, event):
        inner = self.inner_rect().toRect()
        self.scrubber.setGeometry(inner.left() + 18, inner.bottom() - 18 - 48, inner.width() - 36, 48)
        self._scaled = None
        super().resizeEvent(event)

    def _cover_pixmap(self, size: QSize, ratio: float) -> QPixmap:
        key = (size.width(), size.height(), ratio, self.failed, self.cover.cacheKey())
        if self._scaled is None or self._scaled[0] != key:
            target = QSize(round(size.width() * ratio), round(size.height() * ratio))
            source = self.cover if not self.cover.isNull() else cover_placeholder(target)
            scaled = source.scaled(target, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            x, y = (scaled.width() - target.width()) // 2, (scaled.height() - target.height()) // 2
            scaled = scaled.copy(x, y, target.width(), target.height())
            if self.failed:
                image = scaled.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
                scaled = QPixmap.fromImage(image)
            scaled.setDevicePixelRatio(ratio)
            self._scaled = (key, scaled)
        return self._scaled[1]

    def paintEvent(self, _event):
        inner = self.inner_rect()
        if inner.width() <= 0 or inner.height() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipPath(_rounded(inner, 24))
        painter.drawPixmap(inner.topLeft(), self._cover_pixmap(inner.size().toSize(), self.devicePixelRatioF()))
        if self.failed:
            painter.fillRect(inner, QColor(20, 14, 20, 60))
        shade = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        shade.setColorAt(0, QColor(20, 14, 20, 64))
        shade.setColorAt(.22, QColor(20, 14, 20, 0))
        shade.setColorAt(.55, QColor(20, 14, 20, 0))
        shade.setColorAt(1, QColor(20, 14, 20, 154))
        painter.fillRect(inner, shade)
        if self.left_chip:
            _draw_glass_chip(painter, self.left_chip, QPointF(inner.left() + 16, inner.top() + 16))
        if self.right_chip:
            _draw_glass_chip(painter, self.right_chip, QPointF(inner.right() - 16, inner.top() + 16), right=True, mono=True)
        if self.line:
            age = time.perf_counter() - self._line_at
            k = min(1.0, age / .42)
            ease = 1 - (1 - k) ** 3
            overshoot = 1 + .06 * math.sin(k * math.pi) if k < 1 else 1.0
            # Full opacity from the first paint: if the GUI thread stalls the
            # line must still read; only a small bounce is animated.
            band = QRectF(inner.left() + 24, inner.bottom() - 84 - 40 + (1 - ease) * 8, inner.width() - 48, 56)
            _outlined_text(painter, band, self.line, 34, scale=(.96 + .04 * ease) * overshoot)
        painter.end()


class RecentFan(QWidget):
    """Up to five recent projects fanned out; clicking one picks it to open when ready."""

    picked = Signal(int)

    FAN = {1: [(0, 0)], 2: [(-6, 2), (6, 2)], 3: [(-10, 4), (0, 0), (10, 4)],
           4: [(-14, 8), (-5, 1), (5, 1), (14, 8)], 5: [(-16, 10), (-8, 2), (0, 0), (8, 2), (16, 10)]}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[dict] = []
        self.selected = 0
        self.armed = False
        self._covers: dict = {}
        self.setMouseTracking(True)
        self.setMinimumSize(320, 260)

    def set_entries(self, entries):
        self.entries = list(entries)[:5]
        self.selected = len(self.entries) // 2 if self.entries else 0
        self.armed = False
        self._covers.clear()
        self.update()

    def set_armed(self, armed: bool, index: int | None = None):
        if index is not None:
            self.selected = index
        self.armed = bool(armed and self.entries)
        self.update()

    def selected_entry(self):
        return self.entries[self.selected] if self.entries and 0 <= self.selected < len(self.entries) else None

    def _card_size(self):
        width = min(300.0, self.width() * .44)
        return width, width * 10 / 16 + 66

    def _transforms(self):
        width, height = self._card_size()
        angles = self.FAN.get(len(self.entries), [])
        origin = QPointF(self.width() / 2, self.height() * .52 + height * 2.1)
        result = []
        for index, (angle, drop) in enumerate(angles):
            lift = -24 if index == self.selected else 0
            transform = QTransform()
            transform.translate(origin.x(), origin.y())
            transform.rotate(angle)
            transform.translate(-origin.x(), -origin.y())
            transform.translate(self.width() / 2 - width / 2, self.height() * .52 - height / 2 + drop + lift)
            result.append((index, transform))
        centre = self.selected
        return sorted(result, key=lambda item: (item[0] == centre, -abs(item[0] - centre)))

    def _cover(self, index, size: QSize, ratio):
        key = (index, size.width(), size.height(), ratio)
        pixmap = self._covers.get(key)
        if pixmap is None:
            path = str(self.entries[index].get('cover') or '')
            source = QPixmap(path) if path and Path(path).is_file() else QPixmap()
            target = QSize(round(size.width() * ratio), round(size.height() * ratio))
            if source.isNull():
                source = cover_placeholder(target)
            scaled = source.scaled(target, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            x, y = (scaled.width() - target.width()) // 2, (scaled.height() - target.height()) // 2
            pixmap = scaled.copy(x, y, target.width(), target.height())
            pixmap.setDevicePixelRatio(ratio)
            self._covers[key] = pixmap
        return pixmap

    def paintEvent(self, _event):
        if not self.entries:
            return
        theme = active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        width, height = self._card_size()
        card = QRectF(0, 0, width, height)
        cover = QRectF(10, 10, width - 20, (width - 20) * 10 / 16)
        ratio = self.devicePixelRatioF()
        base = QFont(self.font())
        for index, transform in self._transforms():
            entry = self.entries[index]
            top = index == self.selected
            painter.save()
            painter.setTransform(transform)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(30, 18, 10, 26))
            painter.drawRoundedRect(card.translated(0, 6), 22, 22)
            painter.setBrush(QColor(theme.surface))
            painter.setPen(QPen(QColor(theme.border), 1))
            painter.drawRoundedRect(card, 22, 22)
            painter.save()
            painter.setClipPath(_rounded(cover, 15))
            painter.drawPixmap(cover.topLeft(), self._cover(index, cover.size().toSize(), ratio))
            painter.restore()
            if top:
                title = QFont(base)
                title.setPixelSize(14)
                title.setWeight(QFont.Weight.Bold)
                painter.setFont(title)
                painter.setPen(QColor(theme.text))
                text_rect = QRectF(14, cover.bottom() + 8, width - 28, 22)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 QFontMetricsF(title).elidedText(str(entry.get('name') or ''), Qt.TextElideMode.ElideRight, text_rect.width()))
                meta = QFont(base)
                meta.setPixelSize(12)
                painter.setFont(meta)
                painter.setPen(QColor(theme.text_muted))
                parts = []
                if entry.get('count'):
                    parts.append(_tr('{count} 条字幕').replace('{count}', str(entry['count'])))
                if entry.get('edited'):
                    parts.append(str(entry['edited']))
                painter.drawText(QRectF(14, cover.bottom() + 30, width - 28, 20),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, ' · '.join(parts))
            if top and self.armed:
                painter.setPen(QPen(QColor(theme.accent), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(card.adjusted(-1.5, -1.5, 1.5, 1.5), 23, 23)
                badge_font = QFont(base)
                badge_font.setPixelSize(11)
                badge_font.setWeight(QFont.Weight.Bold)
                text = _tr('就绪后打开')
                badge = QRectF(18, 18, QFontMetricsF(badge_font).horizontalAdvance(text) + 20, 24)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(theme.accent))
                painter.drawRoundedRect(badge, 12, 12)
                painter.setFont(badge_font)
                painter.setPen(QColor(theme.text_on_accent))
                painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()
        painter.end()

    def _hit(self, point):
        width, height = self._card_size()
        for index, transform in reversed(self._transforms()):
            inverse, ok = transform.inverted()
            if ok and QRectF(0, 0, width, height).contains(inverse.map(QPointF(point))):
                return index
        return None

    def mouseMoveEvent(self, event):
        hit = self._hit(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if hit is not None else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        hit = self._hit(event.position()) if event.button() == Qt.MouseButton.LeftButton else None
        if hit is None:
            return super().mousePressEvent(event)
        self.set_armed(True, hit)
        self.picked.emit(hit)
        event.accept()


__all__ = ['CoverPane', 'CoverScrubber', 'ReadinessSteps', 'RecentFan', 'STAGE_LINES', 'FAILED_LINE', 'READY_LINE',
           'STAGE_ICONS', 'active_theme', 'cover_placeholder']
