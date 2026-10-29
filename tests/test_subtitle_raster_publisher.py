import time
from pathlib import Path
from PySide6.QtCore import QRect,Qt
from PySide6.QtGui import QImage,QColor
from twobyteasr.rendering.subtitle_raster_publisher import SubtitleRasterPublisher


def until(predicate):
    end=time.monotonic()+2
    while not predicate() and time.monotonic()<end:time.sleep(.005)
    assert predicate()


class Controller:
    running=True
    def __init__(self):self.calls=[]
    def post_raw_overlay(self,overlay,path,**kw):
        self.calls.append((overlay,Path(path),kw))
        return True


def test_cropped_geometry_alpha_and_revoke(tmp_path):
    publisher=SubtitleRasterPublisher(tmp_path);controller=Controller()
    image=QImage(8,8,QImage.Format_ARGB32);image.fill(Qt.transparent);image.setPixelColor(2,3,QColor(200,100,50,255))
    try:
        assert publisher.submit(9,image,QRect(30,40,80,80),.5,controller)
        until(lambda:len(controller.calls)==1)
        overlay,path,kw=controller.calls[0]
        assert (kw['x'],kw['y'],kw['width'],kw['height'],kw['display_width'],kw['display_height'])==(50,70,1,1,10,10)
        pixel=path.read_bytes()[:4]
        assert pixel[0] in (24,25) and pixel[1] in (49,50) and pixel[2] in (99,100) and pixel[3] in (127,128)
        assert kw['valid_when']()
        publisher.revoke(9)
        assert not kw['valid_when']()
        kw['on_applied'](False)
    finally:publisher.close();publisher.thread.join(2)


def test_close_revokes_but_retains_inflight_buffer_until_ack(tmp_path):
    publisher=SubtitleRasterPublisher(tmp_path);controller=Controller()
    image=QImage(2,2,QImage.Format_ARGB32);image.fill(Qt.white)
    publisher.submit(9,image,QRect(0,0,2,2),1,controller)
    until(lambda:len(controller.calls)==1)
    _,path,kw=controller.calls[0];publisher.close()
    assert not kw['valid_when']() and publisher.thread.is_alive()
    assert path.read_bytes()[:4]==b'\xff'*4
    kw['on_applied'](False);publisher.thread.join(2)
    assert not publisher.thread.is_alive()


def test_latest_pending_frame_does_not_overwrite_inflight_buffer(tmp_path):
    publisher=SubtitleRasterPublisher(tmp_path);controller=Controller()
    def frame(red):
        image=QImage(2,2,QImage.Format_ARGB32);image.fill(QColor(red,0,0));return image
    try:
        publisher.submit(9,frame(30),QRect(0,0,2,2),1,controller)
        until(lambda:len(controller.calls)==1)
        first=controller.calls[0];original=first[1].read_bytes()
        publisher.submit(9,frame(90),QRect(0,0,2,2),1,controller)
        publisher.submit(9,frame(210),QRect(0,0,2,2),1,controller)
        assert first[1].read_bytes()==original and len(publisher.pending)==1
        first[2]['on_applied'](True)
        until(lambda:len(controller.calls)==2)
        assert controller.calls[1][1].read_bytes()[2]==210
        controller.calls[1][2]['on_applied'](True)
    finally:publisher.close();publisher.thread.join(2)
