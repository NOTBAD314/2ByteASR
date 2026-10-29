import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.rendering.studio_live_canvas import AdvancedLiveCanvas
from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin


def test_repeated_binding_does_not_restore_initial_frame_after_animation():
    app=QApplication.instance() or QApplication([])
    owner=QWidget()
    canvas=AdvancedLiveCanvas(owner)
    canvas.set_base_geometry(QRect(0,0,200,100))
    initial=QPixmap(200,100); initial.fill(QColor('red'))
    canvas.set_visual(initial,None)
    generation=canvas._layer_generation
    animated=QPixmap(200,100); animated.fill(QColor('blue'))
    canvas._source=animated
    canvas._rescale()
    canvas.set_visual(initial,None)
    assert canvas._layer_generation==generation
    assert canvas._display_source.toImage().pixelColor(20,20)==QColor('blue')
    owner.deleteLater()


def test_old_generation_cannot_win_when_request_key_is_reused():
    page=SimpleNamespace(_advanced_live_render_generation=3,_advanced_live_inflight_key='same')
    # An A→B→A edit may reuse the hash but cannot reuse its generation.
    StudioAdvancedFlowMixin._on_advanced_live_render_ready(page,'same',None,None,None,1)
    assert page._advanced_live_inflight_key=='same'


def test_geometry_refresh_never_rebinds_the_visual():
    calls=[]
    overlay=SimpleNamespace(_base_rect=QRect(0,0,100,50),set_base_geometry=lambda r:calls.append('geometry'),
                            set_visual=lambda *a,**kw:calls.append('rebound'))
    page=SimpleNamespace(advanced_cue_overlay=overlay,
        position_overlay=SimpleNamespace(_content_rect=lambda:SimpleNamespace(toRect=lambda:QRect(0,0,100,50))),
        ensure_active_subtitle_renderer=lambda **kw:calls.append('owner'),
        _advanced_cue_pixmap=SimpleNamespace(isNull=lambda:False),_advanced_preview_snapshot=object())
    StudioAdvancedFlowMixin._sync_advanced_cue_overlay(page)
    assert calls==['geometry','owner']
