"""Round surfaces and native activation must keep their actual painted extent."""
import ctypes
from ctypes import wintypes as W
from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout

APP=QApplication.instance() or QApplication([])


@pytest.mark.parametrize('message,expected',[(0x85,0),(0x86,1)])
def test_main_window_dispatches_native_frame_paint_and_activation(monkeypatch,message,expected):
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.app import window_native_frame as native,window_constraints as bounds
    calls=[]
    monkeypatch.setattr(bounds,'existing_native_handle',lambda *_a,**_kw:42)
    monkeypatch.setattr(native,'handle_message',lambda w,m,*a,**kw:calls.append(m) or expected)
    msg=W.MSG();msg.hWnd=42;msg.message=message
    window=SimpleNamespace(isFullScreen=lambda:False,isMinimized=lambda:False)
    assert MainWindow.nativeEvent(window,b'windows_generic_MSG',ctypes.addressof(msg))==(True,expected)
    assert calls==[message]


@pytest.mark.parametrize('size',[(640,360),(920,560)])
def test_shared_dialog_background_respects_all_four_corners(size):
    from twobyteasr.design.main_ui_dialogs import DialogSurface
    parent=QWidget();parent.resize(size[0]+60,size[1]+60)
    parent.setStyleSheet('QWidget#testBackdrop { background: #14365b; }');parent.setObjectName('testBackdrop')
    surface=DialogSurface(parent,title='识别字幕');surface.setGeometry(30,30,*size)
    parent.show();APP.processEvents()
    try:
        image=parent.grab().toImage();scale=parent.devicePixelRatioF()
        background=image.pixelColor(round(10*scale),round(10*scale))
        for x,y in [(30,30),(30+size[0]-1,30),(30,30+size[1]-1),(30+size[0]-1,30+size[1]-1)]:
            assert image.pixelColor(round(x*scale),round(y*scale))==background
        assert image.pixelColor(round((30+size[0]/2)*scale),round(45*scale))!=background
    finally:parent.close();parent.deleteLater()


def test_recognition_header_remeasures_control_box_after_zoom_changes(tmp_path,monkeypatch):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    from twobyteasr.app.modal_host_widgets import ModalHost
    from twobyteasr.app import ui_zoom
    from PySide6.QtTest import QTest
    host=QWidget();host.resize(1500,900)
    host.legacy=SimpleNamespace(RUNTIME_SETTINGS={})
    import wave
    audio=tmp_path/'source.wav'
    with wave.open(str(audio),'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(b'\0\0'*16000)
    page=SubtitleStudioPage()
    monkeypatch.setattr(page.video,'load',lambda *_a,**_k:None)
    monkeypatch.setattr(page,'_generate_waveform',lambda *_a,**_k:None)
    page.open_project(save_project(SubtitleProject(StudioMedia(str(audio),duration_ms=1000)),tmp_path/'fixture.2byteproj'))
    APP.processEvents();page._media_ingest_state='READY';page._empty_playback_state=False
    page.setParent(host)
    host._modal_host=ModalHost(host)
    host.show();page._open_recognition_sheet();QTest.qWait(30)
    combo=page._recognition_controls['plan'];header=combo.parentWidget()
    previous=ui_zoom.zoom_percent()
    try:
        for percent in (100,80,100,120,100):
            ui_zoom.set_zoom_percent(percent)
            ui_zoom.apply_to(host,percent/100);QTest.qWait(30)
            ui_zoom.apply_to(host,percent/100);QTest.qWait(30)
            assert header.rect().contains(combo.geometry()),(percent,header.geometry(),combo.geometry())
    finally:
        ui_zoom.set_zoom_percent(previous);page.close_page();host.close();host.deleteLater()


def test_header_reacts_before_paint_when_qss_changes_the_control_box():
    from twobyteasr.studio.recognition_role_rows import RecognitionCardHeader
    from PySide6.QtWidgets import QComboBox,QHBoxLayout,QLabel
    from PySide6.QtTest import QTest
    header=RecognitionCardHeader();box=QHBoxLayout(header);box.setContentsMargins(0,0,0,0)
    title=QLabel('识别方案');title.setObjectName('recognitionStepTitle');box.addWidget(title)
    combo=QComboBox();combo.addItem('当前主页方案');box.addWidget(combo)
    header.resize(400,31);header.show();QTest.qWait(30)
    try:
        for content_height in (29,36,43,36):
            title.setStyleSheet(f'font-size:{round(content_height*.55)}px;')
            combo.setStyleSheet(f'QComboBox {{ min-height:{content_height}px; max-height:{content_height}px; border:1px solid #777; padding:0; }}')
            combo.ensurePolished();combo.resize(combo.width(),combo.minimumHeight())
            assert header.minimumHeight()>=combo.minimumHeight()
            assert title.minimumWidth()>=title.fontMetrics().horizontalAdvance(title.text())
            QTest.qWait(10)
            assert header.rect().contains(combo.geometry())
    finally:header.close();header.deleteLater()
