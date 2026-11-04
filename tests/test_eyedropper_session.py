import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QTimer, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QDialog
from twobyteasr.design.color_picker import SimpleColorDialog, _EyedropOverlay


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('kind',['simple','fill'])
def test_screen_pick_does_not_end_modal_session_and_confirm_returns_picked_color(app,kind):
    if kind=='fill':
        from twobyteasr.caption_style.studio_fill_editors import FillEditorDialog
        dialog=FillEditorDialog('#80445566')
    else:
        dialog=SimpleColorDialog(QColor('#80445566'))
    events=[]
    QTimer.singleShot(10,dialog.picker._start_eyedrop)
    def finish():
        events.append('sample')
        dialog.picker._dropper.picked.emit(QColor('#12ab34'))
        dialog.accept()
    QTimer.singleShot(60,finish)
    result=dialog.exec()
    assert result==QDialog.Accepted and events==['sample']
    assert dialog.picker.color().name()=='#12ab34' and dialog.picker.color().alpha()==128
    dialog.deleteLater();app.processEvents()


@pytest.mark.parametrize('kind',['simple','fill'])
def test_cancel_sampling_restores_dialog_and_preserves_original_color(app,kind):
    if kind=='fill':
        from twobyteasr.caption_style.studio_fill_editors import FillEditorDialog
        dialog=FillEditorDialog('#aa336699')
    else:
        dialog=SimpleColorDialog(QColor('#aa336699'))
    QTimer.singleShot(10,dialog.picker._start_eyedrop)
    def cancel():
        dialog.picker._dropper.cancelled.emit()
        assert dialog.isVisible()
        dialog.accept()
    QTimer.singleShot(60,cancel)
    assert dialog.exec()==QDialog.Accepted
    assert dialog.picker.color().name(QColor.HexArgb)=='#aa336699'
    dialog.deleteLater();app.processEvents()


@pytest.mark.parametrize('ratio',[1,1.25,1.5,1.75,2])
def test_screen_sample_handles_dpr_and_negative_screen_origin(app,monkeypatch,ratio):
    from twobyteasr.design import color_picker
    image=QImage(round(200*ratio),round(120*ratio),QImage.Format_ARGB32)
    image.fill(QColor('#cc3322'));image.setDevicePixelRatio(ratio)
    image.setPixelColor(int(30*ratio),int(20*ratio),QColor('#21ae64'))
    fake=SimpleNamespace(geometry=lambda:SimpleNamespace(topLeft=lambda:QPoint(-200,0)),
                         grabWindow=lambda *a:SimpleNamespace(toImage=lambda:image))
    monkeypatch.setattr(color_picker.QGuiApplication,'screenAt',lambda p:fake)
    overlay=_EyedropOverlay(); picked=[];overlay.picked.connect(picked.append)
    event=SimpleNamespace(button=lambda:Qt.LeftButton,
        globalPosition=lambda:SimpleNamespace(toPoint=lambda:QPoint(-170,20)))
    overlay.mousePressEvent(event)
    assert picked[0].name()=='#21ae64'
    overlay.deleteLater();app.processEvents()
