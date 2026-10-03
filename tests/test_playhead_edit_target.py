from types import SimpleNamespace
import pytest
from twobyteasr.studio_canvas_edit import StudioCanvasEditMixin
from twobyteasr.studio_cue_controller import StudioCueController
from twobyteasr.studio_session import StudioSession
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio_runtime_state import state_for


def page_at(position=10500):
    project = SubtitleProject(media=StudioMedia('synthetic.mp4', duration_ms=30000),
        speakers=[StudioSpeaker('S1', 'One'), StudioSpeaker('S2', 'Two')], cues=[
        StudioCue('a', 10000, 12000, '字幕A', 'S1'), StudioCue('b', 15000, 17000, '字幕B', 'S2')])
    project.validate()
    session = StudioSession(project=project, _cue_lookup=state_for(project).cue_by_id)
    calls = []
    page = SimpleNamespace(project=project, session=session, selected_cue_id='',
        _review_mode=False, _canvas_editor=None, _subtitle_track_visibility={},
        timeline=SimpleNamespace(playhead_ms=position, hidden_speakers=set(), locked_speakers=set(),
            selected_track_header=None, _speaker_ids=['S1', 'S2']),
        video=SimpleNamespace(playback_position_snapshot=lambda: SimpleNamespace(
            presentation_media_ms=page.timeline.playhead_ms)),
        save_state=SimpleNamespace(setText=lambda text: calls.append(('status', text))))
    class Controller(StudioCueController):
        def _mirror_clock_selection(self, cue_id):
            page.selected_cue_id = session.selected_cue_id = cue_id
            page._manual_selection_hold = False
            calls.append(('mirror', cue_id))
    page.cue_controller = Controller(page, session)
    page.select_cue = lambda cue_id: setattr(page, 'selected_cue_id', cue_id)
    page._begin_canvas_inline_edit = lambda: calls.append(('edit', page.selected_cue_id))
    return page, calls


def test_continuous_a_gap_b_gap_overrides_stale_manual_selection():
    page, calls = page_at()
    for position, expected in [(10500,'a'),(12400,'a'),(15100,'b'),(17300,'b')]:
        page.timeline.playhead_ms = position
        if expected == 'b':
            page.selected_cue_id = page.session.selected_cue_id = 'a'
            page._manual_selection_hold = True
        page.cue_controller.sync_playhead_target(position)
        StudioCanvasEditMixin._edit_subtitle_at_playhead(page)
        assert calls[-1] == ('edit', expected)
        assert page.session.playhead_target_id == expected


@pytest.mark.parametrize('position,expected', [(0,''),(9999,''),(10000,'a'),(12000,'a'),
    (14999,'a'),(15000,'b'),(17000,'b'),(29000,'b')])
def test_paused_seek_resolves_destination_not_history(position, expected):
    page, calls = page_at(29000)
    page.cue_controller.sync_playhead_target(29000)
    page.timeline.playhead_ms = position
    StudioCanvasEditMixin._edit_subtitle_at_playhead(page)
    assert page.session.playhead_target_id == expected
    assert calls[-1][0] == ('edit' if expected else 'status')


def test_cancel_suppresses_same_target_but_e_or_next_target_restores():
    page, calls = page_at(); c = page.cue_controller
    c.sync_playhead_target(10500); c.cancel_selection()
    for position in (10501,11000,12400,14999):
        c.sync_playhead_target(position)
        assert page.selected_cue_id == page.session.playhead_target_id == ''
    page.timeline.playhead_ms=12400
    StudioCanvasEditMixin._edit_subtitle_at_playhead(page)
    assert calls[-1] == ('edit','a')
    c.cancel_selection(); c.sync_playhead_target(15100)
    assert page.selected_cue_id == 'b'


def test_overlap_priority_stable_with_reorder_visibility_locks_and_track_choice():
    page, _ = page_at()
    page.project.cues.append(StudioCue('overlap',10000,12000,'Overlap','S2'))
    state_for(page.project).reindex_cues(page.project); c = page.cue_controller
    page.session.preferred_subtitle_speaker='S2'
    assert c.resolve_playhead_target(11000).id=='overlap'
    page.timeline.selected_track_header=('subtitle','S1')
    assert c.resolve_playhead_target(11000).id=='a'
    page.timeline.locked_speakers.add('S1')
    assert c.resolve_playhead_target(11000).id=='overlap'
    page.timeline.hidden_speakers.add('S2')
    assert c.resolve_playhead_target(12400) is None
    page.timeline.hidden_speakers.clear(); page.timeline.locked_speakers.clear()
    page.timeline.selected_track_header=None; page.session.preferred_subtitle_speaker=''
    page.timeline._speaker_ids=['S2','S1']
    page.project.cues.reverse(); state_for(page.project).reindex_cues(page.project)
    assert {c.resolve_playhead_target(t).id for t in (11000,11001,12000,12400)}=={'overlap'}


def test_delete_and_project_close_invalidate_target():
    page,_=page_at(15100); c=page.cue_controller; c.sync_playhead_target(15100)
    page.project.cues.pop(); state_for(page.project).reindex_cues(page.project)
    c.sync_playhead_target(15100)
    assert page.session.playhead_target_id=='a'
    page.session.close()
    assert c.resolve_playhead_target(15100) is None
    assert page.session.playhead_target_id==page.session.preferred_subtitle_speaker==''


def test_open_editor_keeps_original_identity_even_when_clock_changes():
    page,calls=page_at(15100)
    page._canvas_editor=SimpleNamespace(setFocus=lambda *_:calls.append(('focus','a')))
    page._review_edit_lock={'cue_id':'a'}
    StudioCanvasEditMixin._edit_subtitle_at_playhead(page)
    assert calls==[('focus','a')] and page._review_edit_lock['cue_id']=='a'


def test_cut_sequence_resolves_project_time_to_stable_source_id():
    from twobyteasr.studio_edit_sequence import delete_timeline_range, ensure_edit_sequence, replace_runtime_sequence, source_cue_id_of
    page,calls=page_at(500); sequence=ensure_edit_sequence(page.project)
    replace_runtime_sequence(page.project,delete_timeline_range(sequence,0,10000))
    state_for(page.project).reindex_cues(page.project)
    StudioCanvasEditMixin._edit_subtitle_at_playhead(page)
    assert source_cue_id_of(calls[-1][1])=='a'


@pytest.mark.parametrize('timeline_ms,source_ms,expected', [
    (10500, 641657, 'a'), (15100, 646257, 'b'),
])
def test_e_maps_deep_source_clock_into_cut_timeline(timeline_ms, source_ms, expected):
    from twobyteasr.studio_edit_sequence import ensure_edit_sequence, replace_runtime_sequence
    page, calls = page_at(timeline_ms)
    for cue in page.project.cues:
        cue.start_ms += 631157
        cue.end_ms += 631157
    page.project.media.duration_ms += 631157
    sequence = ensure_edit_sequence(page.project)
    sequence.segments[0].source_in_ms = 631157
    sequence.segments[0].source_out_ms = 661157
    sequence.segments[0].timeline_out_ms = 30000
    replace_runtime_sequence(page.project, sequence)
    state_for(page.project).reindex_cues(page.project)
    page._playback_mode = 'mapped'
    page._mapped_sequence_segment = lambda: sequence.segments[0]
    page.video.playback_position_snapshot = lambda: SimpleNamespace(presentation_media_ms=source_ms)
    StudioCanvasEditMixin._edit_subtitle_at_playhead(page)
    from twobyteasr.studio_edit_sequence import source_cue_id_of
    assert source_cue_id_of(calls[-1][1]) == expected


def test_e_maps_rate_and_repeated_source_using_active_segment():
    from twobyteasr.studio_edit_sequence import ensure_edit_sequence, replace_runtime_sequence, VideoSegment
    page, calls = page_at(15500)
    sequence = ensure_edit_sequence(page.project)
    sequence.segments = [VideoSegment('first', sequence.source_path, 10000, 12000, 0, 1000),
                         VideoSegment('repeat', sequence.source_path, 10000, 12000, 15000, 16000)]
    replace_runtime_sequence(page.project, sequence)
    state_for(page.project).reindex_cues(page.project)
    page._playback_mode = 'mapped'
    page._mapped_sequence_segment = lambda: sequence.segments[1]
    page.video.playback_position_snapshot = lambda: SimpleNamespace(presentation_media_ms=11000)
    StudioCanvasEditMixin._edit_subtitle_at_playhead(page)
    assert 'repeat' in calls[-1][1]


def test_e_outside_mapped_segment_does_not_edit_unrelated_tail():
    page, calls = page_at(15100)
    from twobyteasr.studio_edit_sequence import ensure_edit_sequence
    sequence = ensure_edit_sequence(page.project)
    page._playback_mode = 'mapped'
    page._mapped_sequence_segment = lambda: sequence.segments[0]
    page.video.playback_position_snapshot = lambda: SimpleNamespace(presentation_media_ms=1000000)
    StudioCanvasEditMixin._edit_subtitle_at_playhead(page)
    assert calls[-1][0] == 'status'
