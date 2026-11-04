from PySide6.QtCore import QSize
from twobyteasr.studio.video_viewport import fitted_video_rect


def test_letterbox_height_change_only_moves_native_picture():
    a=fitted_video_rect(QSize(640,800),16/9)
    b=fitted_video_rect(QSize(640,900),16/9)
    assert a.size()==b.size()==QSize(640,360)
    assert b.y()-a.y()==50


def test_width_or_height_bound_fits_without_distortion():
    assert fitted_video_rect(QSize(800,300),16/9).size()==QSize(533,300)
    assert fitted_video_rect(QSize(320,300),16/9).size()==QSize(320,180)


def test_portrait_and_empty_geometry_are_bounded():
    rect=fitted_video_rect(QSize(800,600),9/16)
    assert rect.size()==QSize(338,600) and rect.x()==231
    assert fitted_video_rect(QSize(0,0),0).size()==QSize(1,1)


def test_host_resizes_the_existing_child_at_media_aspect():
    from PySide6.QtWidgets import QApplication, QWidget
    from twobyteasr.studio.video_viewport import VideoViewportHost
    app=QApplication.instance() or QApplication([])
    host=VideoViewportHost()
    canvas=QWidget()
    host.set_canvas(canvas)
    host.resize(800,600)
    host.show()
    app.processEvents()
    assert host.grab().toImage().pixelColor(5,5).name()=="#000000"
    first=canvas.geometry()
    host.resize(400,600)
    app.processEvents()
    second=canvas.geometry()
    assert canvas.parentWidget() is host
    assert first.size()==QSize(800,450)
    assert second.size()==QSize(400,225)
    assert abs(first.width()/first.height()-second.width()/second.height())<0.01
    host.set_video_size(1080,1920)
    assert canvas.geometry().size()==QSize(338,600)
    host.close()
