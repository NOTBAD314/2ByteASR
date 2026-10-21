from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_video_canvas import MpvCanvas
from twobyteasr.playback.studio_mpv import ADVANCED_OVERLAY_ID
from twobyteasr.rendering.studio_live_canvas import AdvancedLiveCanvas
from PySide6.QtGui import QPixmap, QImage


def test_unload_removes_boundary_pixels_even_without_gui_registration(monkeypatch):
    app=QApplication.instance() or QApplication([])
    canvas=MpvCanvas()
    removed=[]
    boundary=SimpleNamespace(closed=False)
    boundary.close=lambda:setattr(boundary,'closed',True)
    controller=SimpleNamespace(running=True,source_epoch=3,_caption_boundary_publisher=boundary,
        post_remove_overlay=lambda ident,**kwargs:removed.append(ident) or True,
        post_clear_media=lambda:True)
    canvas.controller=controller
    canvas._media_attached=True
    canvas._active_compositor_overlays.clear()
    old_web=canvas._web_live_epoch;old_video=canvas._video_overlay_epoch
    try:
        canvas.unload_project_media()
        assert boundary.closed
        assert ADVANCED_OVERLAY_ID in removed
        assert canvas._web_live_epoch>old_web and canvas._video_overlay_epoch>old_video
        assert not canvas._media_attached and not canvas._web_live_overlay_active
    finally:
        canvas.controller=None;canvas.close();canvas.deleteLater();app.processEvents()


def test_force_remove_cleans_native_slot_when_gui_set_is_empty():
    app=QApplication.instance() or QApplication([])
    canvas=MpvCanvas();removed=[]
    canvas.controller=SimpleNamespace(running=True,post_remove_overlay=lambda n,**kw:removed.append(n) or True)
    try:
        assert canvas.remove_compositor_overlay(ADVANCED_OVERLAY_ID,force=True)
        assert removed==[ADVANCED_OVERLAY_ID]
    finally:
        canvas.controller=None;canvas.close();canvas.deleteLater();app.processEvents()


def test_clear_discards_retained_canvas_source_and_snapshot():
    app = QApplication.instance() or QApplication([])
    owner = MpvCanvas()
    canvas = AdvancedLiveCanvas(owner)
    canvas._source = QPixmap(16, 16)
    canvas._source.fill()
    canvas._display_source = QPixmap(canvas._source)
    canvas._source_image = canvas._source.toImage()
    canvas._snapshot = SimpleNamespace(cue_id='reused-cue', text='PROJECT A')
    generation = canvas._layer_generation
    try:
        canvas.clear()
        assert canvas._snapshot is None
        assert canvas._source.isNull() and canvas._display_source.isNull()
        assert canvas._source_image.isNull()
        assert canvas._layer_generation > generation
    finally:
        owner.close();owner.deleteLater();app.processEvents()

