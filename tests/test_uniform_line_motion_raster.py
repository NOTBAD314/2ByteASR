"""Whole-line affine loops reuse real glyph pixels and retain motion clocks."""
from dataclasses import replace
import numpy as np
import pytest
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.caption_style.motion_application import motion_command
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.caption_style.style_recipe import route_recipe
from twobyteasr.rendering.caption_playback_cache import PreparedCaption
from twobyteasr.rendering.caption_scene import SceneRasterizer
from twobyteasr.rendering.advanced_live_renderer import render_live_layers,composite_live_scene_layers,composition_pivot_for_snapshot
from twobyteasr.rendering.studio_live_canvas import compiled_scene_for_snapshot


@pytest.fixture(scope='module')
def qapp():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    yield app


def snapshot(text='Two readable lines\nretain their line spacing.'):
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('a',0,5000,text)])
    p.validate();p.styles[0].font_family='Arial';p.styles[0].font_size=62
    p.styles[0].position_y=700
    cmd=motion_command(p,['a'],motion={'entry':{'type':'fade','duration':180},
        'exit':{'type':'fade','duration':140},'loop':{'type':'loop_breathe','duration':1200}},language='linked')
    cmd.redo();return build_visual_cue_snapshot(p,'a',width=960,height=540)


def prepared(s):return PreparedCaption(s,s.stable_hash(),route_recipe(s.style_recipe))


@pytest.mark.parametrize('text',['A readable line','Two readable lines\nretain their line spacing.'])
def test_affine_loop_matches_direct_render_and_keeps_one_cached_glyph_set(qapp,text):
    s=snapshot(text);r=SceneRasterizer();p=prepared(s)
    for ms in (90,600,1200,2600,4900):
        fast=r.native_frame(p,ms,960,540)
        direct_layers=render_live_layers(s,width=960,height=540,word_time_ms=ms)
        direct,_=composite_live_scene_layers(direct_layers,compiled_scene_for_snapshot(s),ms,
            pivot=composition_pivot_for_snapshot(s,960,540))
        def pixels(image):return np.frombuffer(image.constBits(),dtype=np.uint8).reshape(image.height(),image.width(),4).copy()
        a,b=pixels(fast),pixels(direct)
        union=np.count_nonzero((a[:,:,3]>16)|(b[:,:,3]>16));intersection=np.count_nonzero((a[:,:,3]>16)&(b[:,:,3]>16))
        assert intersection/max(1,union)>.96
        assert np.abs(a.astype(float)-b.astype(float)).mean()<.5
    assert len(r.rasters)==1
    changed=prepared(replace(s,text='Changed text',fill={'type':'solid','color':'#FF00FF00'}))
    r.native_frame(changed,600,960,540)
    assert len(r.rasters)==2
    r.close();assert not r.rasters


def test_whole_line_loop_does_not_rebuild_paths_each_tick(qapp,monkeypatch):
    import twobyteasr.rendering.advanced_live_renderer as renderer
    calls=[];original=renderer.render_live_layers
    def layers(*a,**k):calls.append(k);return original(*a,**k)
    monkeypatch.setattr(renderer,'render_live_layers',layers)
    s=snapshot();r=SceneRasterizer();p=prepared(s)
    for ms in range(0,4000,40):r.native_frame(p,ms,960,540)
    assert len(calls)==1


def test_word_modes_do_not_enter_whole_line_cache(qapp):
    from twobyteasr.caption_style.word_animation import uniform_line_unit
    from twobyteasr.rendering.caption_motion_preheater import motion_raster_key
    s=snapshot();assert uniform_line_unit(s.word_animation)
    assert uniform_line_unit(dict(s.word_animation,mode='word_reveal')) is None
    assert uniform_line_unit(dict(s.word_animation,rich_entry={'type':'char_reveal'})) is None
    assert motion_raster_key(prepared(replace(s,word_animation=dict(s.word_animation,mode='word_reveal'))),960,540) is None


def test_preheated_affine_raster_matches_fresh_pixels_and_is_released(qapp):
    import time
    from twobyteasr.rendering.caption_motion_preheater import CaptionMotionPreheater, motion_raster_key
    p = prepared(snapshot())
    key = motion_raster_key(p, 960, 540)
    assert key is not None
    warmer = CaptionMotionPreheater()
    warmer.set_epoch(('project', 1))
    warmer.request(('project', 1), [(key, p, 1200, 960, 540)])
    try:
        end = time.monotonic()+5
        while time.monotonic() < end and not warmer.stats()['ready']:
            time.sleep(.01)
        cached = warmer.take(('project', 1), [key])
        assert len(cached) == 1
        actual, fresh = SceneRasterizer(), SceneRasterizer()
        try:
            actual.insert_raster(*cached[0])
            for ms in (90, 600, 1200, 2600, 4900):
                preheated = actual.native_frame(p, ms, 960, 540)
                original = fresh.native_frame(p, ms, 960, 540)
                assert bytes(preheated.constBits()) == bytes(original.constBits())
        finally:
            actual.close();fresh.close()
    finally:
        warmer.close()
        warmer.thread.join(3)
        assert not warmer.thread.is_alive()
