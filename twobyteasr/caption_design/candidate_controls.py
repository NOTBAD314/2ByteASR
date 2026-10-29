"""Theme-aware candidate transport with absolute mouse seeking."""
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class SeekSlider(QSlider):
    def _seek(self, event):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
        groove = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderGroove, self)
        value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
            round(event.position().x() - groove.x() - handle.width() / 2),
            max(1, groove.width() - handle.width()), option.upsideDown)
        self.setValue(value)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self.setSliderDown(True)
            self._seek(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._seek(event)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self._seek(event)
            self.setSliderDown(False)
        else:
            super().mouseReleaseEvent(event)


def playback_icon(running, color):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    if running:
        painter.drawRoundedRect(6, 5, 4, 14, 1, 1)
        painter.drawRoundedRect(14, 5, 4, 14, 1, 1)
    else:
        painter.drawPolygon(QPolygonF([QPointF(7, 4), QPointF(20, 12), QPointF(7, 20)]))
    painter.end()
    return QIcon(pixmap)


def workbench_qss(theme):
    t = theme
    return f'''
QToolButton {{ background:{t.input_surface}; color:{t.text}; border:1px solid {t.border}; border-radius:6px; padding:6px 9px; }}
QToolButton:hover {{ background:{t.selected}; border-color:{t.border_strong}; }}
QToolButton:checked {{ background:{t.accent_tint}; border-color:{t.accent}; }}
QToolButton:disabled {{ color:{t.text_muted}; background:{t.panel}; }}
QListWidget#candidateList {{ background:transparent; border:0; outline:0; color:{t.text}; }}
QListWidget#candidateList::item {{ background:{t.surface}; border:1px solid {t.border}; border-radius:8px; padding:6px; color:{t.text}; }}
QListWidget#candidateList::item:hover {{ background:{t.surface_elevated}; border-color:{t.border_strong}; }}
QListWidget#candidateList::item:selected {{ background:{t.accent_tint}; border:2px solid {t.accent}; color:{t.text}; }}
QTabWidget::pane {{ background:transparent; border:0; border-top:1px solid {t.border}; }}
QTabBar::tab {{ background:transparent; color:{t.text_secondary}; border:0; padding:7px 14px; }}
QTabBar::tab:selected {{ color:{t.text}; border-bottom:2px solid {t.accent}; }}
QPlainTextEdit {{ background:transparent; border:0; padding:5px 1px; color:{t.text_secondary}; selection-background-color:{t.selected}; selection-color:{t.text}; }}
QLabel#workTitle {{ font-size:20px; font-weight:600; color:{t.text}; }}
QLabel#workStatus, QLabel#workOverview {{ color:{t.text_secondary}; font-size:12px; }}
QSlider::groove:horizontal {{ background:{t.border}; height:5px; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{t.accent}; border-radius:2px; }}
QSlider::handle:horizontal {{ background:{t.accent}; width:13px; margin:-5px 0; border-radius:6px; }}
QSlider::handle:horizontal:disabled {{ background:{t.disabled}; }}
'''
