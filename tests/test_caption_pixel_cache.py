"""Real image readiness, stale revisions and cancellation at the handoff boundary."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading
import time
from types import SimpleNamespace
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from twobyteasr.rendering.caption_pixel_cache import CaptionPixelCache
from twobyteasr.playback.playback_clock import PlaybackClock

APP=QApplication.instance() or QApplication([])


def pump_until(predicate):
    deadline=time.monotonic()+3
    while not predicate() and time.monotonic()<deadline:
        APP.processEvents();time.sleep(.002)
    assert predicate()


def test_pixels_are_prepared_off_gui_and_revision_keys_never_alias(monkeypatch):
    gui=threading.get_ident();threads=[]
    def render(snapshot,**kwargs):
        threads.append(threading.get_ident())
        image=QImage(20,10,QImage.Format_ARGB32);image.fill(snapshot.color)
        return image
    monkeypatch.setattr('twobyteasr.rendering.advanced_live_renderer.render_live_snapshot',render)
    cache=CaptionPixelCache(budget_bytes=1200)
    old=('project',1,'A');new=('project',2,'A');ready=[]
    cache.ready.connect(ready.append)
    try:
        cache.request(old,SimpleNamespace(cue_id='A',color=0xffff0000),None,20,10,1)
        pump_until(lambda:old in ready)
        assert cache.get(old).image.pixel(0,0)==0xffff0000
        cache.request(new,SimpleNamespace(cue_id='A',color=0xff00ff00),None,20,10,1)
        pump_until(lambda:new in ready)
        assert cache.get(new).image.pixel(0,0)==0xff00ff00
        assert cache.get(old) is None  # byte budget evicts the old frame
        assert all(thread!=gui for thread in threads)
    finally:cache.close();cache._thread.join(3)


def test_close_discards_an_inflight_frame(monkeypatch):
    entered=threading.Event();release=threading.Event()
    def render(*args,**kwargs):
        entered.set();release.wait(2)
        image=QImage(2,2,QImage.Format_ARGB32);image.fill(0xffffffff);return image
    monkeypatch.setattr('twobyteasr.rendering.advanced_live_renderer.render_live_snapshot',render)
    cache=CaptionPixelCache();ready=[];cache.ready.connect(ready.append)
    cache.request('old',SimpleNamespace(cue_id='A'),None,2,2,1)
    assert entered.wait(2)
    cache.close();release.set();cache._thread.join(3);APP.processEvents()
    assert not ready and cache.get('old') is None


def test_packed_file_is_ready_before_handoff_and_has_explicit_teardown(monkeypatch,tmp_path):
    import gc
    def render(*args,**kwargs):
        image=QImage(40,20,QImage.Format_ARGB32);image.fill(0)
        for y in range(4,12):
            for x in range(7,25):image.setPixel(x,y,0xffffffff)
        return image
    monkeypatch.setattr('twobyteasr.rendering.advanced_live_renderer.render_live_snapshot',render)
    cache=CaptionPixelCache(raw_folder=tmp_path);ready=[];cache.ready.connect(ready.append)
    cache.request('B',SimpleNamespace(cue_id='B'),None,40,20,1)
    pump_until(lambda:ready)
    prepared=cache.get('B');path=prepared.raw_path
    assert prepared.raw_geometry['bounds']==(7,4,18,8)
    assert prepared.raw_geometry['alpha_nonzero']==144 and path.stat().st_size==18*8*4
    cache.close();cache._thread.join(3)
    assert path.exists()  # An in-flight actor may retain this prepared object.
    del prepared;gc.collect()
    assert not path.exists()


def test_fresh_frame_anchor_crosses_boundary_without_filling_a_real_gap():
    clock=PlaybackClock(now=0)
    clock.force_position(970,paused=False,now=1,reason='fixture')
    snapshot,accepted,reason=clock.observe(1000,source_generation=0,actor_sequence=1,
        observed_monotonic_ts=1.001,playback_rate=1,paused=False,seeking=False,now=1.001,align_forward=True)
    assert accepted and reason=='forward_frame_anchor' and snapshot.presentation_media_ms==1000
    cues=[('A',0,1000),('B',1001,2000)]
    assert not [name for name,start,end in cues if start<=snapshot.presentation_media_ms<end]
    snapshot,accepted,_=clock.observe(1001,source_generation=0,actor_sequence=2,
        observed_monotonic_ts=1.002,playback_rate=1,paused=False,seeking=False,now=1.002,align_forward=True)
    assert accepted
    assert [name for name,start,end in cues if start<=snapshot.presentation_media_ms<end]==['B']


def test_caption_identity_waits_for_observed_frame_while_ui_predicts_progress():
    from fractions import Fraction
    clock=PlaybackClock(now=0)
    clock.force_position(1000,paused=False,now=1,reason='fixture')
    clock.observe(1000,source_generation=0,actor_sequence=1,observed_monotonic_ts=1,
        observed_perf_counter_ts=10,playback_rate=1,paused=False,seeking=False,now=1)
    assert clock.media_frame_ms(Fraction(60),now_perf=10.015)==1000
    assert clock.media_frame_ms(Fraction(60),now_perf=10.018)==1000
    assert clock.media_frame_ms(Fraction(60),now_perf=10.250)==1000
    assert 1<clock.milliseconds_until_media_frame(Fraction(3050,3),Fraction(60),now_perf=10.015)<2
    clock.observe(1016.667,source_generation=0,actor_sequence=2,observed_monotonic_ts=1.251,
        observed_perf_counter_ts=10.251,playback_rate=1,paused=False,seeking=False,now=1.251)
    assert abs(clock.media_frame_ms(Fraction(60))-1016.667)<.001


def test_background_preparation_keeps_native_cues_native_and_authored_advanced(monkeypatch):
    from twobyteasr.rendering.caption_playback_cache import PlaybackCaptionCache
    from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioSpeaker,SubtitleStyle,StudioMedia
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    project=SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=3000),speakers=[StudioSpeaker('one'),StudioSpeaker('two')],
        styles=[SubtitleStyle(id='default',name='default'),SubtitleStyle(id='plain',name='plain')],cues=[
            StudioCue('A',0,1000,'甲甲甲甲','one',style_id='plain'),
            StudioCue('B',1000,2000,'乙乙乙乙','two',style_id='plain'),
            StudioCue('C',2000,3000,'高级字幕','two',style_id='advanced')])
    project.style_recipes['advanced']=StyleRecipe('advanced',engine='remotion',motion={}).to_dict()
    store=StudioRevisionStore(project);cache=PlaybackCaptionCache();errors=[]
    cache.failed.connect(errors.append)
    try:
        cache.prepare(store.render,('A','B','C'),840,472)
        pump_until(lambda:errors or cache.prepared(store.render,'C',840,472) is not None)
        assert not errors
        assert [cache.prepared(store.render,cue,840,472).route.engine for cue in ('A','B','C')]==['native','native','remotion']
        assert cache.prepared(store.render,'A',840,472).snapshot.style_recipe['layout']['fitLocked']
    finally:cache.close()
