"""Bounded motion prefetch cannot publish stale work after seek or close."""
import threading
import time

from PySide6.QtGui import QImage

from twobyteasr.rendering.caption_motion_preheater import CaptionMotionPreheater


def wait_for(predicate, seconds=3):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.01)
    return predicate()


def test_inflight_old_epoch_is_discarded_and_close_stops_worker():
    entered, release = threading.Event(), threading.Event()
    image = QImage(10, 10, QImage.Format_ARGB32_Premultiplied)
    def build(item):
        if item[0] == 'old':
            entered.set()
            assert release.wait(3)
        return (None, None, image)
    warmer = CaptionMotionPreheater(builder=build, budget_bytes=500)
    try:
        warmer.set_epoch('old-project')
        warmer.request('old-project', [('old',)])
        assert entered.wait(2)
        warmer.set_epoch('new-project')
        warmer.request('new-project', [('new',)])
        release.set()
        assert wait_for(lambda: warmer.stats()['built'] == 1)
        assert warmer.take('old-project', ['old']) == ()
        assert [key for key, _ in warmer.take('new-project', ['new'])] == ['new']
        assert warmer.stats()['discarded'] == 1
    finally:
        release.set()
        warmer.close()
        warmer.thread.join(3)
        assert not warmer.thread.is_alive()


def test_ready_cache_has_both_item_and_byte_limits():
    image = QImage(10, 10, QImage.Format_ARGB32_Premultiplied)
    warmer = CaptionMotionPreheater(builder=lambda _: (None, None, image), budget_bytes=500)
    try:
        warmer.set_epoch('project')
        for key in ('a', 'b', 'c'):
            warmer.request('project', [(key,)])
            assert wait_for(lambda: warmer.stats()['pending'] == 0 and warmer.stats()['inflight'] == 0)
        stats = warmer.stats()
        assert stats['ready'] == 1 and stats['ready_bytes'] <= 500
        assert [key for key, _ in warmer.take('project', ['a', 'b', 'c'])] == ['c']
    finally:
        warmer.close()
        warmer.thread.join(3)


def test_overload_keeps_near_valid_short_cue_before_far_future_work():
    from types import SimpleNamespace
    entered=threading.Event();release=threading.Event()
    image=QImage(4,4,QImage.Format_ARGB32_Premultiplied);image.fill(0)
    def build(item):
        if item[0]=='busy':entered.set();assert release.wait(3)
        return None,None,image
    warmer=CaptionMotionPreheater(builder=build)
    def item(key,start,end):return (key,SimpleNamespace(snapshot=SimpleNamespace(end_ms=end)),start,4,4)
    try:
        warmer.set_epoch('epoch');warmer.request('epoch',[item('busy',0,50)])
        assert entered.wait(2)
        warmer.request('epoch',[item('short',100,200),item('near',250,500),item('next',600,900),item('later',1000,1400)])
        warmer.request('epoch',[item('far',5000,6000)],current_ms=80)
        with warmer._condition:
            assert list(warmer._pending)==['short','near','next','later']
        release.set()
        assert wait_for(lambda:warmer.stats()['pending']==0 and not warmer.stats()['inflight'])
        assert any(key=='short' for key,_ in warmer.take('epoch',['short']))
    finally:
        release.set();warmer.close();warmer.thread.join(3)
