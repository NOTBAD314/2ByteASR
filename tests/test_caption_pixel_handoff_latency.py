"""Storage registration must not block an already-rendered subtitle frame."""
import time
from PySide6.QtGui import QImage,QColor
from twobyteasr.rendering import overlay_session
from twobyteasr.rendering.caption_pixel_cache import prepared_pixels


def test_prepared_frame_does_not_wait_for_storage_and_eviction_cancels_queued_lease(tmp_path,monkeypatch):
    jobs=[]
    class Queue:
        def put(self,job):jobs.append(job)
    monkeypatch.setattr(overlay_session,'_storage_queue',lambda:Queue())
    def forbidden(*args):raise AssertionError('synchronous storage call on pixel handoff')
    monkeypatch.setattr(overlay_session,'lease_overlay',forbidden)
    image=QImage(64,32,QImage.Format_ARGB32_Premultiplied);image.fill(QColor('white'))
    pixels=prepared_pixels(image,None,time.perf_counter(),tmp_path)
    assert pixels.raw_path.is_file() and pixels.raw_geometry['alpha_nonzero']==64*32
    assert len(jobs)==1
    path=pixels.raw_path
    del pixels
    assert not path.exists()
    job,args=jobs.pop();job(*args)  # no consumer: do not register a removed file
