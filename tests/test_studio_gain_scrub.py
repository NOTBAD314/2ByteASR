import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import QEvent,QPointF,Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_widgets import ScrubDoubleSpinBox


@pytest.mark.parametrize('pixels,modifiers,expected',[
    (24,Qt.KeyboardModifier.NoModifier,6.),
    (24,Qt.KeyboardModifier.ShiftModifier,1.5),
    (12,Qt.KeyboardModifier.ControlModifier,15.),
    (800,Qt.KeyboardModifier.ControlModifier,24.),
    (-800,Qt.KeyboardModifier.NoModifier,-60.),
])
def test_gain_pointer_precision_clamp_and_single_release(pixels,modifiers,expected):
    app=QApplication.instance() or QApplication([])
    spin=ScrubDoubleSpinBox();spin.setRange(-60,24);spin.setSingleStep(1);spin.setDecimals(1)
    spin.show();app.processEvents()
    started=[];finished=[]
    spin.scrubStarted.connect(lambda:started.append(1))
    spin.scrubFinished.connect(lambda:finished.append(1))
    edit=spin.lineEdit();origin=QPointF(edit.rect().center())
    def send(kind,point):
        QApplication.sendEvent(edit,QMouseEvent(kind,point,QPointF(edit.mapToGlobal(point.toPoint())),
            Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,modifiers))
    try:
        send(QEvent.Type.MouseButtonPress,origin)
        send(QEvent.Type.MouseMove,origin+QPointF(pixels,0))
        assert spin.value()==expected
        assert len(started)==1 and not finished
        send(QEvent.Type.MouseButtonRelease,origin+QPointF(pixels,0))
        assert len(finished)==1
        edit.selectAll();QTest.keyClicks(edit,'-12.5');QTest.keyClick(edit,Qt.Key.Key_Return)
        assert spin.value()==-12.5
        QTest.keyClick(spin,Qt.Key.Key_Up)
        assert spin.value()==-11.5
    finally:
        spin.close();spin.deleteLater();app.processEvents()
