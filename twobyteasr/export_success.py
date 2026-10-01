"""Responsive completion surface for the existing export workspace."""
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPainter, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QBoxLayout, QGridLayout, QSizePolicy, QApplication, QStackedWidget, QScrollArea)

from .i18n import bind_text


def elapsed_text(seconds):
    from .export_validation import positive_number
    value = positive_number(seconds)
    if value is None:
        return '—'
    tenths = round(value * 10)
    minutes, remainder = divmod(tenths, 600)
    return f'{minutes} 分 {remainder / 10:.1f} 秒' if minutes else f'{remainder / 10:.1f} 秒'


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
    def __init__(self):
        super().__init__()
        self.image = QPixmap()
        self.setObjectName('exportResultPreview')
        bind_text(self, '播放成片预览', property='accessibleName')
        bind_text(self, '播放成片', property='toolTip')
        self.setMinimumSize(260, 146)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter=QPainter(self)
        if not self.image.isNull():
            size=self.image.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            rect=QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(rect,self.image,QRectF(self.image.rect()))
        else:
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'成片已就绪')

    def resizeEvent(self,event):
        super().resizeEvent(event)
        height=round(self.width()*9/16)
        if height!=self.height():self.setFixedHeight(height)


class ExportSuccessPanel(QWidget):
    def __init__(self, play, reveal, back, again):
        super().__init__()
        self.setObjectName('exportSuccessPage')
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body=QWidget();body.setObjectName('exportSuccessBody');self.scroll.setWidget(body);outer.addWidget(self.scroll)
        root=QVBoxLayout(body); root.setContentsMargins(24,24,24,24)
        root.addStretch()
        self.card=QFrame(); self.card.setObjectName('exportResultCard')
        self.card.setMaximumWidth(1160)
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        layout=QVBoxLayout(self.card);layout.setContentsMargins(28,28,28,24);layout.setSpacing(16)
        self.content=QBoxLayout(QBoxLayout.Direction.LeftToRight);self.content.setSpacing(28)
        self.preview=ResultPreview();self.preview.clicked.connect(play)
        self.content.addWidget(self.preview,5,Qt.AlignmentFlag.AlignBottom)
        self.info=QWidget(); detail=QVBoxLayout(self.info);detail.setContentsMargins(0,0,0,0);detail.setSpacing(10)
        status=QHBoxLayout();status.setSpacing(10)
        icon=QLabel('✓');icon.setObjectName('exportSuccessIcon');icon.setFixedSize(30,30);icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title=QLabel('压制完成');title.setObjectName('exportSuccessTitle')
        status.addWidget(icon);status.addWidget(title);status.addStretch();detail.addLayout(status)
        self.name=ElidedLabel();self.name.setObjectName('exportSuccessName');detail.addWidget(self.name)
        self.metrics=QGridLayout();self.metrics.setHorizontalSpacing(20);self.metrics.setVerticalSpacing(10)
        self.values={}
        for index,key in enumerate(('格式','分辨率','帧率','时长','大小','平均码率')):
            field=QVBoxLayout();field.setSpacing(4)
            label=QLabel(key);label.setObjectName('exportSuccessMeta')
            value=QLabel('—');value.setObjectName('exportResultValue');self.values[key]=value
            field.addWidget(label);field.addWidget(value);self.metrics.addLayout(field,index//3,index%3)
            self.metrics.setColumnStretch(index%3,1)
        detail.addLayout(self.metrics)
        bind_text(self.values['平均码率'], '最终文件的容器平均码率（含视频、音频及封装开销），以文件字节数 × 8 ÷ 实际媒体时长校验。', property='toolTip')
        self.elapsed=QLabel();self.elapsed.setObjectName('exportSuccessMeta');detail.addWidget(self.elapsed)
        detail.addStretch(1)
        label=QLabel('输出位置');label.setObjectName('exportSuccessMeta');detail.addWidget(label)
        pathrow=QHBoxLayout();pathrow.setSpacing(8)
        self.path=ElidedLabel();self.path.setObjectName('exportSuccessMeta')
        self.copy=QPushButton('复制');self.copy.setObjectName('exportSuccessTertiary');self.copy.setMinimumHeight(32)
        self.copy.clicked.connect(lambda:QApplication.clipboard().setText(self.path.full_text))
        pathrow.addWidget(self.path,1,Qt.AlignmentFlag.AlignBottom);pathrow.addWidget(self.copy);detail.addLayout(pathrow)
        self.content.addWidget(self.info,5);layout.addLayout(self.content)
        self.primary_actions=QBoxLayout(QBoxLayout.Direction.LeftToRight);self.primary_actions.setSpacing(12)
        self.play=QPushButton('播放成片');self.play.setObjectName('successOpenVideo');self.play.clicked.connect(play)
        self.reveal=QPushButton('在文件夹中显示');self.reveal.setObjectName('successOpenFolder');self.reveal.clicked.connect(reveal)
        for button in (self.play,self.reveal):
            button.setFixedHeight(60)
            button.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            self.primary_actions.addWidget(button,1)
        layout.addLayout(self.primary_actions)
        self.error=QLabel();self.error.setWordWrap(True);self.error.setObjectName('exportFailureTitle');self.error.hide();layout.addWidget(self.error)
        footer=QHBoxLayout()
        self.back=QPushButton('返回剪辑');self.back.setObjectName('exportSuccessTertiary');self.back.clicked.connect(back)
        self.again=QPushButton('再次导出');self.again.setObjectName('exportSuccessTertiary');self.again.clicked.connect(again)
        self.back.setMinimumHeight(36);self.again.setMinimumHeight(36)
        footer.addWidget(self.back);footer.addStretch();footer.addWidget(self.again);layout.addLayout(footer)
        row=QHBoxLayout();row.addStretch();row.addWidget(self.card,1);row.addStretch();root.addLayout(row);root.addStretch()
        for key,callback in ((Qt.Key.Key_Return,play),(Qt.Key.Key_Enter,play),(Qt.Key.Key_Escape,back)):
            shortcut=QShortcut(QKeySequence(key),self);shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);shortcut.activated.connect(callback)
        self.setTabOrder(self.play,self.reveal);self.setTabOrder(self.reveal,self.copy);self.setTabOrder(self.copy,self.back);self.setTabOrder(self.back,self.again)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        narrow=self.width()<1000
        self.content.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        self.primary_actions.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
