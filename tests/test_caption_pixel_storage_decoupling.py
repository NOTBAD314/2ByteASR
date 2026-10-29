import queue
import time
from PySide6.QtGui import QImage, QColor
from twobyteasr.rendering import overlay_session
from twobyteasr.rendering.caption_pixel_cache import prepared_pixels


def test_pixel_publication_does_not_wait_for_storage_and_release_cancels_old_work(tmp_path, monkeypatch):
    jobs=queue.Queue();calls=[]
    monkeypatch.setattr(overlay_session,'_storage_queue',lambda:jobs)
    monkeypatch.setattr(overlay_session,'lease_overlay',lambda *args:calls.append(args))
    image=QImage(32,32,QImage.Format_ARGB32);image.fill(QColor('red'))
    pixels=prepared_pixels(image,None,time.perf_counter(),tmp_path/'caption-scenes')
    path=pixels.raw_path
    assert path.exists() and pixels.raw_geometry['alpha_nonzero']==1024
    assert not calls and jobs.qsize()==1
    pixels.__del__()
    assert not path.exists()
    job,args=jobs.get_nowait();job(*args)
    assert not calls


def test_acquired_lease_releases_once_after_pixel_consumption(tmp_path, monkeypatch):
    jobs=queue.Queue();released=[]
    class Lease:
        def __exit__(self,*args):released.append(True)
    monkeypatch.setattr(overlay_session,'_storage_queue',lambda:jobs)
    monkeypatch.setattr(overlay_session,'lease_overlay',lambda *args:Lease())
    path=tmp_path/'frame.rgba';path.write_bytes(b'1234')
    lease=overlay_session.lease_overlay_deferred(path,'test')
    job,args=jobs.get_nowait();job(*args)
    lease.__exit__(None,None,None);lease.__exit__(None,None,None)
    assert jobs.qsize()==1
    job,args=jobs.get_nowait();job(*args)
    assert released==[True]
