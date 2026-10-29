"""Responsive completion surface for the existing export workspace."""
from PySide6.QtCore import QEvent, Qt, QRectF, QSize
from PySide6.QtGui import QPainter, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QBoxLayout, QGridLayout, QSizePolicy, QApplication, QStackedWidget, QScrollArea)

from ..i18n import bind_text


def elapsed_text(seconds):
    from .export_validation import positive_number
    value = positive_number(seconds)
    if value is None:
        return '—'
    tenths = round(value * 10)
    minutes, remainder = divmod(tenths, 600)
    return f'{minutes} 分 {remainder / 10:.1f} 秒' if minutes else f'{remainder / 10:.1f} 秒'


def report_unpainted_success(workspace, panel, output) -> None:
    """Diagnostics only: the result page was shown 3 s ago but never painted.

    2026-10-27 user report: the 压制完成 notification arrived while the window
    kept showing the progress page (97%). Not reproduced locally; this records
    the window's state in the export trace for the next support bundle."""
    if workspace.pages.currentWidget() is not panel or getattr(panel, 'painted', True):
        return
    window = panel.window()
    workspace._export_trace('success_page_not_painted', {
        'output': str(output), 'page_visible': panel.isVisible(), 'window_visible': window.isVisible(),
        'minimized': window.isMinimized(), 'active': window.isActiveWindow(),
        'updates_enabled': window.updatesEnabled() and panel.updatesEnabled()})


class ExportPages(QStackedWidget):
    """The setup panel's width must not constrain the responsive result page."""
    def minimumSizeHint(self):
        if self.currentWidget() and self.currentWidget().objectName() == 'exportSuccessPage':
            return QSize(540, 480)
        return super().minimumSizeHint()

    def sizeHint(self):
        if self.currentWidget() and self.currentWidget().objectName() == 'exportSuccessPage':
            return QSize(1008, 700)
        return super().sizeHint()


class ElidedLabel(QLabel):
    def __init__(self, *args):
        super().__init__(*args)
        self.full_text = ''
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def setText(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideMiddle, max(20,self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class ResultPreview(QPushButton):
    """Clickable poster of the finished video with a play mark.

    2026-10-08 (M13): the result workspace sizes it (16:9) to the space
    left by the facts column, so the poster is the page's focal point.
    """

    def __init__(self):
        super().__init__()
        self.image = QPixmap()
        self._scaled = (None, QPixmap())
        self.setObjectName('exportResultPreview')
        bind_text(self, '播放成片预览', property='accessibleName')
        bind_text(self, '播放成片', property='toolTip')
        self.setMinimumSize(260, 146)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_poster_width(self, width):
        width = max(260, int(width))
        size = QSize(width, round(width * 9 / 16))
        if size != self.size():
            self.setFixedSize(size)

    def paintEvent(self, event):
        super().paintEvent(event)
        from PySide6.QtGui import QColor, QPainterPath, QPolygonF
        from PySide6.QtCore import QPointF
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inner = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(inner, 11, 11)
        painter.setClipPath(clip)
        if not self.image.isNull():
            size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            rect = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2, size.width(), size.height())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            poster = self._device_pixmap(size)
            painter.drawPixmap(rect, poster, QRectF(poster.rect()))
        else:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '成片已就绪')
        # Play mark: a dark disc with a light triangle, stronger on hover.
        radius = max(26.0, min(self.width(), self.height()) * 0.09)
        center = QRectF(self.rect()).center()
        disc = QColor(0, 0, 0, 150 if self.underMouse() else 110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(disc)
        painter.drawEllipse(center, radius, radius)
        side = radius * 0.9
        triangle = QPolygonF([QPointF(center.x() - side * 0.35, center.y() - side * 0.5),
                              QPointF(center.x() - side * 0.35, center.y() + side * 0.5),
                              QPointF(center.x() + side * 0.55, center.y())])
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawPolygon(triangle)
        painter.end()

    def _device_pixmap(self, size):
        """The poster resampled once to the screen's own pixels (2026-10-15).

        Drawing the full-resolution frame with SmoothPixmapTransform is a
        bilinear downscale on every paint; a cached area-averaged copy at
        devicePixelRatio stays sharp on 125–175 % screens."""
        ratio = max(1.0, float(self.devicePixelRatioF()))
        key = (self.image.cacheKey(), size.width(), size.height(), ratio)
        if self._scaled[0] != key:
            target = QSize(max(1, round(size.width() * ratio)), max(1, round(size.height() * ratio)))
            scaled = (QPixmap(self.image) if self.image.size() == target else
                      self.image.scaled(target, Qt.AspectRatioMode.IgnoreAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
            scaled.setDevicePixelRatio(ratio)
            self._scaled = (key, scaled)
        return self._scaled[1]

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class ExportSuccessPanel(QWidget):
    """Export result workspace (2026-10-08, M13, user: a real result page,
    not an enlarged dialog card).

    Header: back to editing (left), title and file name, export again
    (right) — both navigation actions full-size and equal. Body: a large
    poster and a facts column ending in the two result actions — play
    (primary) above show-in-folder (secondary).
    """

    INFO_SHARE = 0.38
    INFO_MIN = 340

    def __init__(self, play, reveal, back, again):
        super().__init__()
        from ..design.themed_icons import install_themed_icon
        self.setObjectName('exportSuccessPage')
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); body.setObjectName('exportSuccessBody'); self.scroll.setWidget(body); outer.addWidget(self.scroll)
        self.painted = False
        body.installEventFilter(self)   # the scrolled body covers the whole page
        root = QVBoxLayout(body); root.setContentsMargins(32, 22, 32, 24); root.setSpacing(18)
        self.body = body

        header = QHBoxLayout(); header.setSpacing(16)
        self.back = QPushButton('返回剪辑'); self.back.setObjectName('exportSuccessNav'); self.back.clicked.connect(back)
        install_themed_icon(self.back, 'fa5s.arrow-left', 'secondary')
        header.addWidget(self.back, 0, Qt.AlignmentFlag.AlignVCenter)
        heading = QVBoxLayout(); heading.setSpacing(2)
        status = QHBoxLayout(); status.setSpacing(10)
        icon = QLabel('✓'); icon.setObjectName('exportSuccessIcon'); icon.setFixedSize(30, 30); icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = self.title = QLabel('压制完成'); title.setObjectName('exportSuccessTitle')
        status.addWidget(icon); status.addWidget(title); status.addStretch(); heading.addLayout(status)
        self.name = ElidedLabel(); self.name.setObjectName('exportSuccessName'); heading.addWidget(self.name)
        header.addLayout(heading, 1)
        self.again = QPushButton('再次导出'); self.again.setObjectName('exportSuccessNav'); self.again.clicked.connect(again)
        install_themed_icon(self.again, 'fa5s.redo-alt', 'secondary')
        header.addWidget(self.again, 0, Qt.AlignmentFlag.AlignVCenter)
        for button in (self.back, self.again):
            button.setFixedHeight(44)
            button.setMinimumWidth(140)
        root.addLayout(header)

        self.card = QFrame(); self.card.setObjectName('exportResultCard')
        # Wraps its content (M14): no tall empty surface below the result.
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self.card); layout.setContentsMargins(24, 24, 24, 24); layout.setSpacing(0)
        self.content = QBoxLayout(QBoxLayout.Direction.LeftToRight); self.content.setSpacing(32)
        self.preview_host = QWidget()
        preview_layout = QVBoxLayout(self.preview_host); preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = ResultPreview(); self.preview.clicked.connect(play)
        preview_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        preview_layout.addStretch(1)
        self.content.addWidget(self.preview_host, 1)

        self.info = QWidget(); self.info.setObjectName('exportResultInfo')
        detail = QVBoxLayout(self.info); detail.setContentsMargins(0, 0, 0, 0); detail.setSpacing(12)
        section = self.section_label = QLabel('成片信息'); section.setObjectName('exportSectionLabel'); detail.addWidget(section)
        self.metrics = QGridLayout(); self.metrics.setHorizontalSpacing(24); self.metrics.setVerticalSpacing(22)
        self.values = {};self.metric_labels={}
        for index, key in enumerate(('格式', '分辨率', '帧率', '时长', '大小', '平均码率')):
            field = QVBoxLayout(); field.setSpacing(3)
            label = QLabel(key); label.setObjectName('exportSuccessMeta')
            self.metric_labels[key]=label
            value = QLabel('—'); value.setObjectName('exportResultValue'); self.values[key] = value
            field.addWidget(label); field.addWidget(value); self.metrics.addLayout(field, index // 2, index % 2)
            self.metrics.setColumnStretch(index % 2, 1)
        detail.addLayout(self.metrics)
        # 2026-10-09 (M15, user): the column spans the poster's height and
        # its two actions end on the poster's bottom edge; spare height is
        # shared between the fact groups instead of pooling in one gap.
        detail.addStretch(1)
        bind_text(self.values['平均码率'], '最终文件的容器平均码率（含视频、音频及封装开销），以文件字节数 × 8 ÷ 实际媒体时长校验。', property='toolTip')
        self.elapsed = QLabel(); self.elapsed.setObjectName('exportSuccessMeta'); self.elapsed.setWordWrap(True)
        detail.addWidget(self.elapsed)
        rule = QFrame(); rule.setObjectName('exportResultRule'); rule.setFixedHeight(1); detail.addWidget(rule)
        label = QLabel('输出位置'); label.setObjectName('exportSectionLabel'); detail.addWidget(label)
        pathrow = QHBoxLayout(); pathrow.setSpacing(8)
        self.path = ElidedLabel(); self.path.setObjectName('exportResultPath')
        self.copy = QPushButton('复制'); self.copy.setObjectName('exportSuccessTertiary'); self.copy.setMinimumHeight(32)
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.path.full_text))
        pathrow.addWidget(self.path, 1, Qt.AlignmentFlag.AlignVCenter); pathrow.addWidget(self.copy); detail.addLayout(pathrow)
        detail.addStretch(1)
        detail.addSpacing(6)
        self.error = QLabel(); self.error.setWordWrap(True); self.error.setObjectName('exportFailureTitle'); self.error.hide()
        detail.addWidget(self.error)
        self.primary_actions = QBoxLayout(QBoxLayout.Direction.TopToBottom); self.primary_actions.setSpacing(10)
        self.play = QPushButton('播放成片'); self.play.setObjectName('successOpenVideo'); self.play.clicked.connect(play)
        install_themed_icon(self.play, 'fa5s.play', 'on_accent')
        self.reveal = QPushButton('在文件夹中显示'); self.reveal.setObjectName('successOpenFolder'); self.reveal.clicked.connect(reveal)
        install_themed_icon(self.reveal, 'fa5s.folder-open', 'secondary')
        self.play.setFixedHeight(58); self.reveal.setFixedHeight(48)
        for button in (self.play, self.reveal):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.primary_actions.addWidget(button)
        detail.addLayout(self.primary_actions)
        self.content.addWidget(self.info, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(self.content)
        root.addWidget(self.card, 0)
        root.addStretch(1)

        for key, callback in ((Qt.Key.Key_Return, play), (Qt.Key.Key_Enter, play), (Qt.Key.Key_Escape, back)):
            shortcut = QShortcut(QKeySequence(key), self); shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut); shortcut.activated.connect(callback)
        self.setTabOrder(self.play, self.reveal); self.setTabOrder(self.reveal, self.copy)
        self.setTabOrder(self.copy, self.back); self.setTabOrder(self.back, self.again)

    def _fit(self):
        if self.preview_host.isHidden():
            self.content.setDirection(QBoxLayout.Direction.TopToBottom)
            self.info.setMinimumSize(0,0);self.info.setMaximumSize(16777215,16777215)
            return
        narrow = self.width() < 1000
        self.content.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        margins = self.card.layout().contentsMargins()
        inner = self.card.width() - margins.left() - margins.right()
        if narrow:
            self.info.setMinimumWidth(0); self.info.setMaximumWidth(16777215)
            self.info.setMinimumHeight(0); self.info.setMaximumHeight(16777215)
            self.preview.set_poster_width(inner)
            return
        # 62 : 38 (M14, user): the poster no longer dominates; it also fits
        # the visible height so ordinary sizes need no scrolling.
        header = self.card.mapTo(self.body, self.card.rect().topLeft()).y()
        available_h = self.scroll.viewport().height() - header - margins.top() - margins.bottom() - 24
        spacing = self.content.spacing()
        info = int(max(self.INFO_MIN, round((inner - spacing) * self.INFO_SHARE)))
        self.info.setFixedWidth(info)
        poster = max(260, int(min(inner - info - spacing, available_h * 16 / 9)))
        self.preview.set_poster_width(poster)
        # Bottom edges meet: the facts column is exactly as tall as the
        # poster unless its own content needs more.
        needed = self.info.layout().minimumSize().height()
        self.info.setFixedHeight(max(round(poster * 9 / 16), needed))

    def call_after_paint(self, callback, fallback_ms=500):
        """Run ``callback`` once this page has painted, or after ``fallback_ms``
        when it cannot paint (a minimized window still needs the notification)."""
        from PySide6.QtCore import QTimer
        self._after_paint = callback
        QTimer.singleShot(fallback_ms, self, self._run_after_paint)

    def _run_after_paint(self):
        callback, self._after_paint = getattr(self, '_after_paint', None), None
        if callback is not None:
            callback()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.painted = True   # completion diagnostics (report_unpainted_success)
            if getattr(self, '_after_paint', None) is not None:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self, self._run_after_paint)   # after this frame reaches the screen
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._fit)

    def showEvent(self, event):
        super().showEvent(event)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._fit)
