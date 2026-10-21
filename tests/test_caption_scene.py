"""Every active cue contributes pixels; malformed siblings cannot erase them."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from twobyteasr.rendering.caption_scene import SceneRasterizer
from twobyteasr.rendering.caption_playback_cache import PreparedCaption
from twobyteasr.projects.studio_project import StudioMedia, StudioCue, StudioSpeaker, SubtitleStyle, SubtitleProject
from twobyteasr.caption_style.style_recipe import RecipeRoute
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def prepared(count):
    p = SubtitleProject(media=StudioMedia('', width=600, height=480, duration_ms=3000),
        render_settings={'play_res_x':600,'play_res_y':480},
        cues=[StudioCue(f'cue-{i}', 0, 2000, f'TRACK {i+1}', speaker_id=f'S{i}', style_id=f'style{i}') for i in range(count)],
        speakers=[StudioSpeaker(f'S{i}') for i in range(count)],
        styles=[SubtitleStyle(f'style{i}', f'style{i}', font_size=40, outline_width=0, shadow=0,
            position_x=300, position_y=60+65*i) for i in range(count)])
    return [(cue.id, PreparedCaption(snapshot:=build_visual_cue_snapshot(p, cue.id, width=600, height=480),
             snapshot.stable_hash(), RecipeRoute('native', ()))) for cue in p.cues]


def alpha(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return np.ndarray((image.height(), image.width(), 4), dtype=np.uint8,
        buffer=image.constBits(), strides=(image.bytesPerLine(),4,1))[:,:,3].copy()


@pytest.mark.parametrize('count', [1,2,3,4,6])
def test_authored_rows_all_have_pixels_at_original_locations(app, count):
    renderer=SceneRasterizer()
    image, rows=renderer.frame(prepared(count), 500, 600, 480)
    assert len(rows)==count and all(r['status']=='rendered' for r in rows)
    pixels=alpha(image)
    for i in range(count):
        assert np.count_nonzero(pixels[max(0,15+i*65):65+i*65]) > 100
    assert not np.any(pixels[:, :100]) and not np.any(pixels[:,500:])
    renderer.close()


def test_bad_and_unprepared_cues_do_not_suppress_healthy_peers(app, monkeypatch):
    import twobyteasr.rendering.advanced_live_renderer as live
    original=live.render_live_snapshot
    def render(snapshot, **kwargs):
        if snapshot.cue_id=='cue-1' and snapshot.style_recipe: raise ValueError('invalid style fixture')
        return original(snapshot, **kwargs)
    monkeypatch.setattr(live,'render_live_snapshot',render)
    renderer=SceneRasterizer()
    inputs=prepared(3)+[('empty-track',None)]
    image, rows=renderer.frame(inputs, 500, 600,480)
    assert [r['status'] for r in rows]==['rendered','fallback','rendered','pending']
    pixels=alpha(image)
    assert np.count_nonzero(pixels[15:65])>100
    assert np.count_nonzero(pixels[145:195])>100
    renderer.close()


def test_recognized_timeline_snapshot_is_not_projected_twice(app):
    from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.rendering.caption_playback_cache import materialize_caption_project
    p = SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=10000),
        cues=[StudioCue('8', 1500, 2400, '原有字幕')], styles=[SubtitleStyle('default','Default')])
    sequence = EditSequence(source_path='fixture.mp4', source_duration_ms=10000,
        segments=[VideoSegment('clip', 'fixture.mp4', 4000, 8000, 1000, 5000)])
    store_sequence(p, sequence)
    p.generation_metadata['timeline_recognition'] = {'sequence':sequence.to_dict()}
    revision = StudioRevisionStore(p).render
    assert revision.cues[0].id == '8#clip'
    assert revision.cues[0].start_ms == 4500
    materialized = materialize_caption_project(revision)
    snapshot = build_visual_cue_snapshot(materialized, '8')
    assert snapshot.text == '原有字幕' and snapshot.start_ms == 1500
    assert p.cues[0].id == '8' and p.cues[0].start_ms == 1500


def test_layout_failure_does_not_kill_current_or_following_scene(app, monkeypatch):
    import twobyteasr.caption_style.subtitle_stacking as stacking
    def broken(*args, **kwargs): raise ValueError('broken sibling layout')
    monkeypatch.setattr(stacking, 'compute_stack_layout', broken)
    renderer = SceneRasterizer()
    for inputs in (prepared(2), prepared(1), prepared(3)):
        image, rows = renderer.frame(inputs, 500, 600, 480)
        assert all(r['status']=='rendered' for r in rows)
        assert np.count_nonzero(alpha(image)) > 100


def test_static_visual_graph_does_not_force_continuous_animation(app):
    from dataclasses import replace
    from twobyteasr.rendering.caption_scene import animated_caption
    item=prepared(1)[0][1]
    snapshot=replace(item.snapshot,style_recipe={'visualGraph':{'motionGraph':{'tracks':[]}}})
    assert not animated_caption(replace(item,snapshot=snapshot))
    snapshot=replace(snapshot,style_recipe={'visualGraph':{'motionGraph':{'tracks':[{'target':'text'}]}}})
    assert animated_caption(replace(item,snapshot=snapshot))


def test_active_set_half_open_overlap_empty_hidden_and_authored_order():
    from twobyteasr.rendering.caption_scene import active_cues
    cues=[StudioCue('a',0,100,'A','S0'),StudioCue('b',50,150,'B','S1'),StudioCue('c',200,250,'C','S2')]
    page=SimpleNamespace(project=SimpleNamespace(cues=cues),session=SimpleNamespace(runtime=None),
        timeline=SimpleNamespace(hidden_speakers=set(),_speaker_ids=['S1','EMPTY','S0','S2']),_subtitle_track_visibility={})
    assert [c.id for c in active_cues(page,49)]==['a']
    assert [c.id for c in active_cues(page,50)]==['a','b']  # top row paints last
    assert [c.id for c in active_cues(page,100)]==['b']
    assert not active_cues(page,150)
    assert [c.id for c in active_cues(page,200)]==['c']
    page.timeline.hidden_speakers.add('S0')
    assert [c.id for c in active_cues(page,75)]==['b']
    page._subtitle_track_visibility['S1']=False
    assert not active_cues(page,75)
