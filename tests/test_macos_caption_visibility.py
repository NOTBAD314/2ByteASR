"""A video QWidget must not cover subtitles already composed by the Qt surface."""
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QColor
from PySide6.QtWidgets import QApplication


def test_qt_video_layer_does_not_repaint_over_caption_pixels(tmp_path):
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    from twobyteasr.studio.studio_qt_preview import QtEmbeddedVideoController
    from twobyteasr.playback.video_compositor import VideoCompositionScene
    app=QApplication.instance() or QApplication([])
    canvas=MpvCanvas();canvas.setAttribute(Qt.WA_NativeWindow,False);canvas.resize(320,180)
    canvas.controller=QtEmbeddedVideoController(canvas);canvas.controller.start()
    canvas._media_attached=True
    video=QImage(320,180,QImage.Format_ARGB32_Premultiplied);video.fill(QColor('#00aa00'))
    canvas.controller.surface.frame=video
    caption=QImage(80,24,QImage.Format_ARGB32_Premultiplied);caption.fill(Qt.white)
    raw=tmp_path/'caption.bgra';raw.write_bytes(bytes(caption.constBits()))
    dpr=canvas.devicePixelRatioF()
    canvas.controller.set_raw_overlay(1,raw,x=30*dpr,y=30*dpr,width=80,height=24,stride=caption.bytesPerLine(),
                                      display_width=80*dpr,display_height=24*dpr)
    scene=VideoCompositionScene(canvas);scene.setGeometry(canvas.rect())
    canvas.show();scene.show();scene.raise_()
    app.processEvents()
    scene._layers=[{}];scene._paused=False
    scene._rendered_frames=(video,QImage());scene._native_frames=None
    video_raw=tmp_path/'video.bgra';video_raw.write_bytes(bytes(video.constBits()))
    canvas.controller.set_raw_overlay(0,video_raw,x=0,y=0,width=320,height=180,stride=video.bytesPerLine(),
                                      display_width=320*dpr,display_height=180*dpr)
    scene.update()
    try:
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            app.processEvents();time.sleep(.01)
        # The compositor's own native layer is present. Its QWidget must not
        # paint a second opaque copy above that surface's caption layer.
        assert 0 in canvas.controller.surface.overlays
        assert canvas.controller.surface.grab().toImage().pixelColor(round(50*dpr),round(40*dpr)).name()=='#ffffff'
        assert canvas.grab().toImage().pixelColor(round(50*dpr),round(40*dpr)).name()=='#ffffff'
        assert canvas.grab().toImage().pixelColor(round(200*dpr),round(100*dpr)).name()=='#00aa00'
        from twobyteasr.acceptance.macos_desktop_evidence import visible_caption_pixels
        evidence=visible_caption_pixels(canvas)
        assert evidence['passed'] and evidence['changed_pixels']>100
        assert 1 in canvas.controller.surface.overlays
    finally:
        scene.clear();canvas.controller.close();canvas.close();app.processEvents()
