"""Visible signed dB entry, horizontal scrub, slider and zero marker."""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QSlider, QHBoxLayout, QVBoxLayout, QPushButton, QLabel
from .studio_widgets import ScrubDoubleSpinBox


class GainSlider(QSlider):
    editFinished = Signal()
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(-600, 240)
        self.setSingleStep(1)
        self.setPageStep(10)
        self.setMinimumWidth(200)
        self.setMinimumHeight(44)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        x = 8 + (self.width()-16)*600/840
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawLine(round(x), self.height()-14, round(x), self.height()-10)
        painter.drawText(QRectF(x-22,self.height()-13,44,13),Qt.AlignCenter,'0 dB')

    def mousePressEvent(self, event):
        if event.button()!=Qt.LeftButton: return super().mousePressEvent(event)
        self.setFocus(Qt.MouseFocusReason);self.setSliderDown(True)
        handle=8+(self.width()-16)*(self.value()-self.minimum())/(self.maximum()-self.minimum())
        if abs(event.position().x()-handle)>12:
            self.setValue(round(self.minimum()+(event.position().x()-8)/max(1,self.width()-16)*(self.maximum()-self.minimum())))
        self._gain_origin=(event.position().x(),self.value());self.grabMouse();event.accept()

    def mouseMoveEvent(self, event):
        origin=getattr(self,'_gain_origin',None)
        if origin is None:return super().mouseMoveEvent(event)
        multiplier=.25 if event.modifiers()&Qt.ShiftModifier else 5. if event.modifiers()&Qt.ControlModifier else 1.
        self.setValue(round(origin[1]+(event.position().x()-origin[0])*(self.maximum()-self.minimum())/max(1,self.width()-16)*multiplier))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button()==Qt.LeftButton and getattr(self,'_gain_origin',None) is not None:
            self._gain_origin=None;self.releaseMouse();self.setSliderDown(False);event.accept();return
        super().mouseReleaseEvent(event)

    def keyReleaseEvent(self,event):
        super().keyReleaseEvent(event);self.editFinished.emit()


class SignedDbSpin(ScrubDoubleSpinBox):
    def textFromValue(self, value):
        return f'{value:+.1f}' if value > 0 else f'{value:.1f}'


class GainControl(QWidget):
    valueChanged = Signal(float)

    def __init__(self, parent=None, *, name='gainDb'):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(3)
        row = QHBoxLayout(); layout.addLayout(row)
        self.minus = QPushButton('−'); self.plus = QPushButton('+')
        for button in (self.minus, self.plus): button.setFixedWidth(32)
        self.slider = GainSlider(self); self.slider.setObjectName(name+'Slider')
        self.gain = SignedDbSpin(self); self.gain.setObjectName(name)
        self.gain.setRange(-60., 24.); self.gain.setDecimals(1); self.gain.setSingleStep(.4)
        self.gain.setSuffix(' dB'); self.gain.setMinimumWidth(150)
        self.gain.setToolTip(''); self.slider.setToolTip('')
        # Local padding avoids the app's generous form-field rules consuming
        # the spin box editor, leaving only a selected suffix visible.
        self.gain.setStyleSheet('QDoubleSpinBox { padding: 4px 24px 4px 8px; min-width: 120px; }'
                               'QDoubleSpinBox QLineEdit { padding: 0px; border: none; background: transparent; }')
        row.addWidget(self.minus); row.addWidget(self.slider, 1); row.addWidget(self.plus); row.addWidget(self.gain)
        marks = QHBoxLayout(); layout.addLayout(marks)
        marks.addWidget(QLabel('范围 −60…+24 dB')); marks.addStretch(1)
        self.slider.valueChanged.connect(lambda value: self.gain.setValue(value/10.))
        self.gain.valueChanged.connect(self._changed)
        self.minus.clicked.connect(lambda: self.gain.setValue(self.value()-1.))
        self.plus.clicked.connect(lambda: self.gain.setValue(self.value()+1.))

    def _changed(self, value):
        self.slider.blockSignals(True); self.slider.setValue(round(value*10)); self.slider.blockSignals(False)
        self.valueChanged.emit(value)

    def value(self): return self.gain.value()
    def setValue(self, value): self.gain.setValue(value)
