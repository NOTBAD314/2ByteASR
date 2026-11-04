from types import SimpleNamespace as NS

from twobyteasr.rendering.caption_scene import complete_scene_for_seek
from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin


def fixture():
    token=('project',1,2,8,('a','b'))
    rows=[dict(cue_id=key,status='rendered') for key in ('a','a#tr','b','b#tr')]
    scene=NS(active=True,closed=False,published=object(),token=token,last_result_token=token,
        still_current=lambda t:t==token,
        trace=lambda:dict(expected_cue_ids=['a','b'],expected_display_cue_ids=['a','a#tr','b','b#tr'],cue_pixels=rows))
    return scene,rows


def test_scene_receipt_requires_current_generation_and_all_language_layers():
    scene,rows=fixture()
    assert complete_scene_for_seek(scene,'a',8)
    assert not complete_scene_for_seek(scene,'a',7)
    assert not complete_scene_for_seek(scene,'other',8)
    rows[-1]['status']='pending'
    assert not complete_scene_for_seek(scene,'a',8)
    rows[-1]['status']='rendered';scene.published=None
    assert not complete_scene_for_seek(scene,'a',8)


def test_scene_owner_satisfies_seek_receipt_without_a_separate_qt_canvas():
    scene,_=fixture()
    for authored_route in ('native','advanced'):
        trace=dict(generation=8,visual_expectation=dict(cue_id='a',renderer_route=authored_route))
        marks=[]
        page=NS(_close_requested=False,_caption_scene=scene,
            video=NS(_active_seek_trace=trace,mark_seek_stage=lambda *a,**k:marks.append(a),_finish_seek_trace=lambda g:True),
            subtitle_visibility_trace=lambda **k:dict(cue_id='a',renderer_route='advanced',
                foreground_owner='advanced_live',foreground_owner_cue_id='scene:hash',foreground_owner_count=1,
                visible=True,native_overlay_visible=False,advanced_canvas_visible=False))
        StudioPlaybackFlowMixin._schedule_seek_trace_settlement(page,1)
        assert trace['T8_passed'] and trace['T8_observed']['complete_current_scene']
        assert marks==[('T8_active_cue_visual_owner_correct',)]
