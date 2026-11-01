"""Ready-frame priority, latest sample ownership and lossless compact staging."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import time
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QObject,Qt
from PySide6.QtGui import QColor,QImage
from PySide6.QtWidgets import QApplication
from tests.test_caption_scene_handoff import _page,_until
from twobyteasr.rendering.caption_scene import CaptionScene
from twobyteasr.rendering.caption_pixel_cache import PreparedPixels,prepared_pixels

@pytest.fixture(scope='module',autouse=True)
def app():yield QApplication.instance() or QApplication([])

def test_ready_current_frame_coalesces_before_queued_metadata():
    order=[]
    class Metadata(QObject):
        def event(self,event):
            if event.type()==QEvent.Type.User:order.append('metadata');return True
            return super().event(event)
    receiver=Metadata();scene=CaptionScene(_page());token=('owner',);scene.token=token
    scene.accept=lambda t,p,tr:order.append(tr['sample_ms'])
    try:
        QCoreApplication.postEvent(receiver,QEvent(QEvent.Type.User))
        scene._notify_ready(token,object(),dict(sample_ms=10,request_kind='current'))
        scene._notify_ready(token,object(),dict(sample_ms=20,request_kind='current'))
        assert _until(lambda:len(order)==2)
        assert order==[20,'metadata']
    finally:scene.close();scene.thread.join(3)

def test_late_same_scene_motion_sample_cannot_overwrite_newer_one():
    page=_page();page.now_ms=300
    scene=CaptionScene(page);scene.active=True
    token=scene.scene_token((page.project.cues[0],),page.position_overlay._content_rect().toRect(),1)
    scene.token=token
    image=QImage(320,180,QImage.Format_ARGB32_Premultiplied);image.fill(0)
    pixels=PreparedPixels(image,None,0,0,raw_geometry={'alpha_nonzero':1})
    trace=dict(expected_cue_ids=['a'],cue_pixels=[dict(cue_id='a',status='rendered')],
               geometry_complete=True,animated=True,duration_ms=1)
    try:
        scene.accept(token,pixels,dict(trace,sample_ms=300))
        count=len(page.video.calls)
        scene.accept(token,pixels,dict(trace,sample_ms=200))
        assert len(page.video.calls)==count and scene._last_published_sample_ms==300
    finally:scene.close();scene.thread.join(3)

def test_compact_final_frame_retains_full_upload_coordinates(tmp_path):
    image=QImage(40,24,QImage.Format_ARGB32_Premultiplied);image.fill(0)
    for x in range(7,19):
        for y in range(5,13):image.setPixelColor(x,y,QColor(240,70,30,127))
    result=prepared_pixels(image,None,time.perf_counter(),tmp_path,compact_image=True)
    assert result.image.size().width()==12 and result.image.size().height()==8
    assert result.raw_geometry['source_width']==40 and result.raw_geometry['source_height']==24
    assert result.raw_geometry['bounds']==(7,5,12,8)
    assert result.raw_path.read_bytes()==bytes(image.copy(7,5,12,8).constBits())

def test_animation_cache_keys_include_frame_and_prepared_text_identity():
    page=_page();page.project.render_settings['fps']=30
    scene=CaptionScene(page)
    token=scene.scene_token((page.project.cues[0],),page.position_overlay._content_rect().toRect(),1)
    p=page._prepared['a'];items=(('a',p),)
    try:
        assert scene.animation_key(token,items,0)!=scene.animation_key(token,items,1000/30)
        newer=replace(p,snapshot_hash='new-text-snapshot')
        assert scene.animation_key(token,items,1000/30)!=scene.animation_key(token,(('a',newer),),1000/30)
    finally:scene.close();scene.thread.join(3)


def test_double_speed_boundary_retires_expired_bitmap_before_new_raster():
    page=_page();page.video._playback_rate=2
    scene=CaptionScene(page);scene.active=True
    try:
        from tests.test_caption_scene_handoff import _present
        _present(scene,page,100)
        assert _until(lambda:scene.published is not None)
        page.video.calls.clear()
        _present(scene,page,1000)
        assert any(call[0]=='remove' for call in page.video.calls)
        assert scene._hold is None
    finally:scene.close();scene.thread.join(3)
