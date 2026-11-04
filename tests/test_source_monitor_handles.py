from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QLabel, QHBoxLayout, QPushButton
from PySide6.QtTest import QTest
from twobyteasr.studio.studio_source_monitor import SourcePointButton, SourceSelectionArea, StudioSourceMonitor

APP=QApplication.instance() or QApplication([])

@pytest.fixture
def point():
    clicks=[]; commits=[]
    field=StudioSourceMonitor.time_field(lambda:commits.append(field.text()))
    owner=SimpleNamespace(point_layouts=[],icon_button=StudioSourceMonitor.icon_button)
    button=StudioSourceMonitor.point(owner,'入点（I）',field,lambda:clicks.append(True),'设置入点')
    button.resize(420,64);button.show();APP.processEvents()
    yield button,field,clicks,commits
    button.close();button.deleteLater();APP.processEvents()

def test_every_part_of_point_frame_is_one_click(point):
    button,field,clicks,_=point
    for pos in (QPoint(5,32),QPoint(210,32),field.geometry().center(),
                button.findChild(QLabel).geometry().center(),QPoint(button.width()-22,32)):
        target=button.childAt(pos) or button
        assert target is button
        QTest.mouseClick(button,Qt.LeftButton,pos=pos)
    assert len(clicks)==5 and field.isReadOnly()

def test_point_timecode_double_click_edit_enter_once_and_escape(point):
    button,field,clicks,commits=point
    QTest.mouseDClick(button,Qt.LeftButton,pos=field.geometry().center())
    assert not field.isReadOnly() and field.hasFocus()
    QTest.keyClicks(field,'00:00:04.000');QTest.keyClick(field,Qt.Key_Return)
    assert commits==['00:00:04.000'] and field.isReadOnly()
    QTest.mouseDClick(button,Qt.LeftButton,pos=field.geometry().center())
    QTest.keyClicks(field,'00:00:09.000');QTest.keyClick(field,Qt.Key_Escape)
    assert field.text()=='00:00:04.000' and commits==['00:00:04.000']
    QTest.keyClick(button,Qt.Key_Space)
    assert len(clicks)==1

@pytest.mark.parametrize('mode',['av','video','audio'])
def test_selection_area_starts_one_drag_after_threshold(mode):
    calls=[];owner=SimpleNamespace(mode=mode,start_drag=lambda widget,value:calls.append(value))
    area=SourceSelectionArea(owner);area.resize(300,100);area.show();APP.processEvents()
    try:
        QTest.mousePress(area,Qt.LeftButton,pos=QPoint(20,20))
        def move(x):
            pos=QPointF(x,20)
            APP.sendEvent(area,QMouseEvent(QEvent.MouseMove,pos,QPointF(area.mapToGlobal(pos.toPoint())),
                Qt.NoButton,Qt.LeftButton,Qt.NoModifier))
        move(21);assert not calls
        move(20+APP.startDragDistance()+2);move(100)
        QTest.mouseRelease(area,Qt.LeftButton,pos=QPoint(100,20))
        assert calls==[mode] and area.origin is None
    finally:
        area.close();area.deleteLater();APP.processEvents()

def test_selection_controls_do_not_turn_clicks_into_drags():
    calls=[];owner=SimpleNamespace(mode='av',start_drag=lambda *args:calls.append('drag'))
    area=SourceSelectionArea(owner);layout=QHBoxLayout(area)
    button=QPushButton('试看选段');layout.addWidget(button);button.clicked.connect(lambda:calls.append('play'))
    area.show();APP.processEvents()
    try:
        QTest.mouseClick(button,Qt.LeftButton)
        assert calls==['play'] and area.origin is None
    finally:
        area.close();area.deleteLater();APP.processEvents()
