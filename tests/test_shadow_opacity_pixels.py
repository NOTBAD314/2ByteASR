import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
import numpy as np
from PySide6.QtWidgets import QApplication
from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot
from tests.test_caption_scene import prepared, alpha


def test_shadow_opacity_is_applied_once_and_text_is_unchanged():
    app = QApplication.instance() or QApplication([])
    base = prepared(1)[0][1].snapshot
    masks = []
    text_masks = []
    for opacity in (0, .25, .5, 1):
        shadow = dict(enabled=True, color='#FF000000', opacity=opacity,
                      offset_x=40, offset_y=35, blur=6, spread=3)
        snapshot = replace(base, shadow=shadow, strokes=(), style_recipe={})
        masks.append(alpha(render_live_snapshot(snapshot,width=600,height=480,layers={'effects'})))
        text_masks.append(alpha(render_live_snapshot(snapshot,width=600,height=480,layers={'text'})))
    assert not masks[0].any()
    for ratio, mask in zip((.25,.5),masks[1:3]):
        assert np.max(np.abs(mask.astype(float)-masks[3]*ratio)) <= 1
    assert masks[3].max() > 150
    assert all(np.array_equal(text_masks[0], mask) for mask in text_masks[1:])


def test_processed_preview_fits_small_frames_and_dpr_on_resize():
    from PySide6.QtGui import QPixmap
    from twobyteasr.exports.studio_export_ui import ProcessedFrameView
    app = QApplication.instance() or QApplication([])
    view = ProcessedFrameView()
    pixmap = QPixmap(320,180); pixmap.setDevicePixelRatio(2)
    view.setPixmap(pixmap)
    for w,h in ((960,540),(480,400),(1280,720)):
        view.resize(w,h)
        rect = view.frame_rect()
        assert abs(rect.width()/rect.height()-16/9) < .01
        assert rect.width() >= w-1 or rect.height() >= h-1
        assert abs(rect.center().x()-w/2) <= 1
        assert abs(rect.center().y()-h/2) <= 1
    view.clear()
    assert view.pixmap().isNull() and view.frame_rect().isEmpty()
