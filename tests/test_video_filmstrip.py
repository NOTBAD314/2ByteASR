import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.video_filmstrip import FilmstripCache,FilmstripView,filmstrip_tiles


def test_trim_rate_and_zoom_select_source_seconds_without_gaps():
    # Ten seconds of source occupy five seconds of timeline at 2x, scrolled into its middle.
    tiles=filmstrip_tiles(0,1000,400,800,10000,20000,40)
    assert tiles[0][2]==14000 and tiles[-1][2]==17000
    assert all(b==c for (a,b,_),(c,d,_) in zip(tiles,tiles[1:]))
    assert len(filmstrip_tiles(0,100,0,100,10000,20000,40))<len(tiles)


def test_async_decode_disk_reuse_and_viewport_cancellation(tmp_path):
    app=QApplication.instance() or QApplication([])
    from twobyteasr.system.processes import run_hidden_subprocess
    source=tmp_path/'silent.mp4'
    run_hidden_subprocess([str(Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y',
        '-f','lavfi','-i','testsrc2=s=320x180:r=30:d=4','-c:v','libx264','-preset','ultrafast',str(source)],
        purpose='small silent filmstrip test fixture',check=True,timeout=15)
    def wait(predicate):
        deadline=time.monotonic()+6
        while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        assert predicate()
    cache=FilmstripCache(cache_root=tmp_path/'cache');cache.set_view([(str(source),0,4000,0)])
    try:
        wait(lambda:len(cache.memory)==4 and len(cache.refined)==4)
        assert cache.metrics['opens']==1 and cache.metrics['decoded']<=7
        assert {r['requested_ms'] for r in cache.trace if r.get('exact')}=={0,1000,2000,3000}
        assert all(abs(r['pts_ms']-r['requested_ms'])<=34 for r in cache.trace if r.get('exact'))
        first=cache.key(str(source),1000);assert cache.get(str(source),1000) is not None
        cache.set_paused(True);cache.set_view([(str(source),90000,100000,0)])
        assert all(v[2]>=90000 for v in cache.wanted.values())
        cache.set_view([]);assert not cache.wanted
    finally:cache.close();cache.thread.join(2)
    reopened=FilmstripCache(cache_root=tmp_path/'cache')
    try:
        reopened.set_view([(str(source),0,4000,0)]);wait(lambda:len(reopened.memory)==4)
        assert reopened.metrics['disk_hits']==4 and reopened.metrics['decoded']==0
        # Replacement under the same name invalidates identity by mtime/size.
        source.write_bytes(source.read_bytes()+b'cache-invalidation')
        reopened.identities.clear()
        assert reopened.key(str(source),1000)!=first
    finally:reopened.close();reopened.thread.join(2)


def test_visible_cells_are_the_whole_foreground_demand_and_stale_delivery_is_rejected(tmp_path):
    app=QApplication.instance() or QApplication([])
    from PySide6.QtGui import QImage
    cache=FilmstripCache(cache_root=tmp_path/'cache')
    cache.set_paused(True)
    try:
        view=FilmstripView('same.mp4',(0,90000,179000),(180000,),90000,'V1:clip',0,900000)
        cache.set_view([view,FilmstripView('same.mp4',(0,90000,179000),(),90000,'V2:clip')])
        assert len(cache.wanted)==4  # duplicates share media cache, not 900 source seconds
        assert sum(v[0]==0 for v in cache.wanted.values())==3
        old=cache.generation;key=cache.key('same.mp4',0)
        cache.set_view([FilmstripView('new.mp4',(40000,))])
        image=QImage(128,72,QImage.Format_ARGB32);image.fill(0xffffffff)
        cache._accept(key,image,old)
        assert key not in cache.memory
        assert not any(v[1]=='same.mp4' for v in cache.wanted.values())
        cache.get('unseen.mp4',5000)
        assert len(cache.wanted)==1  # painting cannot resurrect off-viewport jobs
    finally:cache.close();cache.thread.join(2)


def test_idle_decode_waits_for_quiet_and_round_robins_clips(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    import psutil
    monkeypatch.setattr(psutil,'cpu_percent',lambda:0)
    cache=FilmstripCache(cache_root=tmp_path/'cache');cache.set_paused(True)
    try:
        cache.set_view([FilmstripView('one.mp4',(0,5000),owner='V1'),FilmstripView('two.mp4',(0,5000),owner='V2')])
        assert cache._idle_job() is None
        cache.view_changed-=6
        first=cache._idle_job();assert first[1][4]=='V1'
        cache.last_source='V1';cache.last_idle=0
        assert cache._idle_job()[1][4]=='V2'
        monkeypatch.setattr(psutil,'cpu_percent',lambda:90);cache.last_idle=0
        assert cache._idle_job() is None
    finally:cache.close();cache.thread.join(2)


def test_decode_failure_retries_with_backoff_before_permanent(tmp_path):
    """一次超时/EOF 不再把可视格判死刑（2026-09-18 VIII）。"""
    app=QApplication.instance() or QApplication([])
    cache=FilmstripCache(cache_root=tmp_path/'cache');cache.set_paused(True)
    try:
        cache.set_view([FilmstripView('same.mp4',(0,5000),owner='V1')])
        key=next(iter(cache.wanted))
        cache._fail(key,'eof_before_target')
        assert key not in cache.failed
        assert cache.retry_after[key]>time.perf_counter()
        assert cache.attempts[key]==1
        # 退避到期后重新可被选中；未到期时不可（视图里另一个格子不受影响）。
        def eligible():
            with cache.condition:
                return [k for k,v in cache.wanted.items() if k not in cache.completed and k not in cache.failed
                        and cache.retry_after.get(k,0.0)<=time.perf_counter()]
        cache.retry_after[key]=time.perf_counter()+30
        assert key not in eligible()
        cache.retry_after[key]=0.0
        assert key in eligible()
        # 有限次数后永久失败。
        cache._fail(key,'x');cache._fail(key,'x')
        assert key in cache.failed and cache.attempts[key]==3
        # 成功投递清空重试预算。
        cache._fail(key,'x')
        from PySide6.QtGui import QImage
        image=QImage(128,72,QImage.Format_ARGB32);image.fill(0xffffffff)
        cache.failed.discard(key)
        cache._accept(key,image,cache.generation)
        assert cache.attempts.get(key) is None and cache.retry_after.get(key) is None
        assert cache.get('same.mp4',0) is not None
    finally:cache.close();cache.thread.join(2)


def test_null_image_is_a_failure_not_a_silent_completed(tmp_path):
    """空图曾泄漏进 completed：格子整会话占位且永不重试。"""
    app=QApplication.instance() or QApplication([])
    from PySide6.QtGui import QImage
    cache=FilmstripCache(cache_root=tmp_path/'cache');cache.set_paused(True)
    try:
        cache.set_view([FilmstripView('same.mp4',(0,5000),owner='V1')])
        key=next(iter(cache.wanted))
        cache._accept(key,QImage(),cache.generation)  # null QImage
        assert key not in cache.completed
        assert cache.attempts.get(key)==1
    finally:cache.close();cache.thread.join(2)
