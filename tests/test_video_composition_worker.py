import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from twobyteasr.playback.video_composition_worker import VideoCompositionWorker
from twobyteasr.playback.video_decode_pipe import PipeFrame


def test_worker_pixels_match_gui_compositor_and_reject_old_generation():
    from types import SimpleNamespace
    from twobyteasr.playback.video_compositor import VideoCompositionScene
    app=QApplication.instance() or QApplication([])
    image=QImage(320,180,QImage.Format_ARGB32);image.fill(0xff35a872)
    layer=dict(clip_id='clip',path='fixture',generation=4,decode_epoch=2,source_ms=1000,transform=dict(scale_x=.45,scale_y=.45,
        position_x=.7,position_y=.3,opacity=.6,rotation=12),effects={})
    scene=VideoCompositionScene();scene.resize(640,360)
    scene._layers=[layer];scene._players={'clip':SimpleNamespace(image=image,pts_ms=1000,generation=4,frame_age_ms=0)}
    scene._render_composition();expected=bytes(scene._rendered_frames[0].constBits())
    scene._players={};scene.close()
    delivered=[];ready=threading.Event()
    def publish(image,rect,context):delivered.append((bytes(image.constBits()),context));ready.set()
    worker=VideoCompositionWorker(publish)
    try:
        worker.configure(dict(size=(640,360),display_rect=(0,0,640,360),base=False,project_ms=1000,layers=[layer]))
        def frame(generation,epoch=2):return PipeFrame(epoch,generation,'fixture',1000,1000,320,180,memoryview(bytes(image.constBits())))
        worker.receive('clip',frame(3));time.sleep(.04);assert not delivered
        worker.receive('clip',frame(4,1));time.sleep(.04);assert not delivered
        worker.receive('clip',frame(4));assert ready.wait(2)
        assert delivered[-1][0]==expected
        worker.configure(None);count=len(delivered);worker.receive('clip',frame(4));time.sleep(.03)
        assert len(delivered)==count
    finally:worker.close();worker.thread.join(2)


def test_single_plain_follower_keeps_owned_pixels_for_native_gpu_scaling():
    image=QImage(160,90,QImage.Format_ARGB32);image.fill(0xff2468ac)
    payload=memoryview(bytes(image.constBits()));delivered=[];ready=threading.Event()
    def publish(image,rect,context):delivered.append((QImage(image),rect,context));ready.set()
    worker=VideoCompositionWorker(publish)
    try:
        layer=dict(clip_id='v2',path='fixture',generation=1,decode_epoch=3,transform={},effects={})
        worker.configure(dict(size=(320,180),display_rect=(4,8,640,360),base=False,project_ms=1000,publication_epoch=5,layers=[layer]))
        worker.receive('v2',PipeFrame(3,1,'fixture',1000,1000,160,90,payload))
        assert ready.wait(2)
        frame,rect,context=delivered[-1]
        assert context['direct_gpu_scale'] and frame.size()==image.size()
        assert rect.getRect()==(4,8,640,360) and bytes(frame.constBits())==bytes(payload)
        assert context['raster']==dict(width=160,height=90,stride=640,bytes=160*90*4,
                                      display_rect=(4,8,640,360))
        assert context['submitted_at'] >= context['compose_end']
        worker.configure(None);del payload
        assert frame.pixelColor(10,10).blue()==172
    finally:worker.close();worker.thread.join(2)
