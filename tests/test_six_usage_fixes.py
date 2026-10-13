"""Generate-from-bin, caption remapping, Q/W target and caption-scene rules (2026-10-11)."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_scene import CaptionScene
from twobyteasr.studio_caption_timeline import KEY, STASH_KEY
from twobyteasr.studio_cue_controller import StudioCueController
from twobyteasr.studio_edit_commands import generate_edit_command, restore_full_sequence_command
from twobyteasr.studio_edit_sequence import HighlightCandidate, sequence_of, store_sequence
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio_runtime_state import state_for
from twobyteasr.studio_session import StudioSession


def _app():
    return QApplication.instance() or QApplication([])


def _words(text, start, step):
    return [dict(text=ch, char_start=i, char_end=i + 1, start_ms=start + i * step,
                 end_ms=start + (i + 1) * step, evidence_ref='e') for i, ch in enumerate(text)]


def _independent_project():
    """60 s recording; captions in project time with measured words."""
    cues = [StudioCue('a', 10_000, 12_000, '第一句话', 'S01'),
            StudioCue('b', 30_000, 32_000, '中间一句', 'S01'),
            StudioCue('c', 44_000, 46_000, '跨越剪点', 'S01')]
    project = SubtitleProject(media=StudioMedia('D:/rec.flv', duration_ms=60_000),
                              speakers=[StudioSpeaker('S01', '主播')], cues=cues)
    project.validate()
    project.render_settings['_cue_domain'] = 'timeline'
    project.studio_state[KEY] = {'version': 1, 'instances': {
        cue.id: dict(text=cue.text, words=_words(cue.text, cue.start_ms, 500), word_alignment='exact_token_text')
        for cue in cues}}
    sequence = sequence_of(project)
    sequence.video_track_locked = False
    for track in project.video_tracks:
        track.locked = False
    sequence.clip_candidates = [
        HighlightCandidate('k2', '后段', 40_000, 45_000, 0.8, status='accepted'),
        HighlightCandidate('k1', '前段', 5_000, 15_000, 0.9, status='accepted'),
        HighlightCandidate('k3', '没选', 20_000, 25_000, 0.7, status='suggested'),
    ]
    store_sequence(project, sequence)
    return project


def test_generate_uses_bin_order_and_kept_ranges_and_moves_captions_word_exact():
    _app()
    project = _independent_project()
    command = generate_edit_command(project)
    command.redo()
    segments = [(s.source_in_ms, s.source_out_ms, s.timeline_in_ms, s.timeline_out_ms)
                for s in sequence_of(project).segments]
    # Bin order (k2 then k1), kept ("建议保留") ranges, 15 s in total.
    assert segments == [(40_000, 45_000, 0, 5_000), (5_000, 15_000, 5_000, 15_000)]
    cues = {c.id: c for c in project.cues}
    # 'a' (10-12 s source) now plays at 10-12 s of the new timeline (5 s + 5 s).
    assert (cues['a'].start_ms, cues['a'].end_ms, cues['a'].text) == (10_000, 12_000, '第一句话')
    # 'c' crosses the 45 s cut: only the whole words before it survive.
    assert (cues['c'].start_ms, cues['c'].end_ms, cues['c'].text) == (4_000, 5_000, '跨越')
    # 'b' (30-32 s) is outside every kept range; it is stashed, not lost.
    assert 'b' not in cues
    assert {entry['cue']['id'] for entry in project.studio_state[STASH_KEY]['entries']} >= {'b', 'c'}
    # Linked audio follows the same cut.
    audio = [(c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms)
             for t in project.audio_tracks for c in t.clips]
    assert audio in ([], segments)
    command.undo()
    assert [c.id for c in project.cues] == ['a', 'b', 'c']
    assert STASH_KEY not in project.studio_state


def test_return_to_full_recording_restores_left_out_captions_at_source_time():
    _app()
    project = _independent_project()
    generate_edit_command(project).redo()
    restore = restore_full_sequence_command(project)
    restore.redo()
    cues = {c.id: (c.start_ms, c.end_ms, c.text) for c in project.cues}
    assert cues == {'a': (10_000, 12_000, '第一句话'), 'b': (30_000, 32_000, '中间一句'),
                    'c': (44_000, 46_000, '跨越剪点')}
    assert STASH_KEY not in project.studio_state


def test_repeated_generate_is_a_no_op_and_empty_or_locked_bins_explain_why():
    _app()
    project = _independent_project()
    generate_edit_command(project).redo()
    assert generate_edit_command(project) is None
    sequence = sequence_of(project)
    for candidate in sequence.clip_candidates:
        candidate.status = 'suggested'
    with pytest.raises(ValueError, match='候选箱是空的'):
        generate_edit_command(project)
    sequence.clip_candidates[0].status = 'accepted'
    project.video_tracks[0].locked = True
    with pytest.raises(ValueError, match='已锁定'):
        generate_edit_command(project)


def _controller(cues, playhead=0, hidden=(), locked=()):
    project = SubtitleProject(media=StudioMedia('x.mp4', duration_ms=60_000),
                              speakers=[StudioSpeaker('S1', 'A'), StudioSpeaker('S2', 'B')], cues=cues)
    project.validate()
    session = StudioSession(project=project, _cue_lookup=state_for(project).cue_by_id)
    page = SimpleNamespace(project=project, session=session, _subtitle_track_visibility={},
                           timeline=SimpleNamespace(playhead_ms=playhead, hidden_speakers=set(hidden),
                                                    locked_speakers=set(locked), selected_track_header=None,
                                                    _speaker_ids=['S1', 'S2']))
    return StudioCueController(page, session)


@pytest.mark.parametrize('playhead,expected', [
    (12_000, 'early'),     # inside the earlier caption
    (14_000, 'early'),     # 1.6 s after its end, 6.0 s before the next start
    (19_800, 'late'),      # the screenshot case: 0.2 s before the next caption
    (21_000, 'late'),      # inside the later caption
])
def test_qw_target_is_the_caption_under_or_nearest_the_playhead(playhead, expected):
    c = _controller([StudioCue('early', 10_000, 12_400, '依旧打抵抗', 'S1'),
                     StudioCue('late', 20_000, 22_000, '再来发坍缩吗', 'S1')])
    assert c.resolve_edit_target(playhead).id == expected


def test_qw_target_uses_boundary_distance_not_centres_and_skips_hidden_or_locked_tracks():
    # A long caption whose centre is far but whose end is near wins over a
    # short caption whose centre is nearer.
    c = _controller([StudioCue('long', 0, 9_000, '很长的一句', 'S1'),
                     StudioCue('short', 11_500, 11_700, '短', 'S1')])
    assert c.resolve_edit_target(9_800).id == 'long'
    c = _controller([StudioCue('hidden', 9_000, 9_900, '隐藏', 'S2'),
                     StudioCue('shown', 12_000, 13_000, '可见', 'S1')], hidden={'S2'})
    assert c.resolve_edit_target(10_000).id == 'shown'
    c = _controller([StudioCue('locked', 9_000, 9_900, '锁定', 'S2')], locked={'S2'})
    assert c.resolve_edit_target(10_000) is None


def test_qw_target_does_not_reach_a_caption_far_away():
    c = _controller([StudioCue('far', 0, 1_000, '很远', 'S1')])
    assert c.resolve_edit_target(1_000 + c.EDIT_TARGET_REACH_MS + 1) is None


def test_caption_scene_withdraws_only_when_content_or_geometry_changes():
    token = lambda cues, rect=(0, 0, 100, 50), generation=1: (1, 2, 3, generation, cues, 'r', *rect)
    previous = token(('a',))
    assert CaptionScene.shows_other_content(previous, token(('b',)))
    assert CaptionScene.shows_other_content(previous, token(('a',), rect=(0, 0, 90, 50)))
    assert not CaptionScene.shows_other_content(previous, token(('a',), generation=2))
    # The raster cache ignores the playback generation for the same content.
    assert CaptionScene.frame_key(previous) == CaptionScene.frame_key(token(('a',), generation=9))


def test_overlap_protection_keeps_cues_apart_when_recovered_cues_repeat_an_id():
    # 2026-10-11 688 s run: content recovery appended cues numbered 1 and 2
    # again; the id-keyed protection gave cue "1" at 102 s the end of the
    # first caption (102280..1067) and the project could not be saved.
    from twobyteasr.display_timing import protect_runtime_display_tails

    def seg(start, end, speaker):
        return SimpleNamespace(start=start, end=end, speaker=speaker, moss_start=start, moss_end=end,
                               words=[], final_timing_owner='moss')

    cues = [SimpleNamespace(cue_id=1, start=0.283, end=1.25, text='是啊', speaker='S01'),
            SimpleNamespace(cue_id=2, start=0.97, end=1.92, text='狼来了', speaker='S02'),
            SimpleNamespace(cue_id=1, start=102.28, end=105.28, text='一点一', speaker='S01'),
            SimpleNamespace(cue_id=2, start=104.68, end=105.9, text='对的', speaker='S02')]
    segments = [seg(0.283, 1.25, 'S01'), seg(0.97, 1.92, 'S02'),
                seg(102.28, 103.48, 'S01'), seg(104.68, 105.28, 'S02')]
    audit = protect_runtime_display_tails(cues, segments)
    assert all(cue.end > cue.start for cue in cues)
    assert (cues[1].start, cues[1].end) == (0.97, 1.92)
    assert cues[2].end <= 105.28 and cues[3].end == 105.9
    assert [(pair['left'], pair['right']) for pair in audit] == [('1', '2'), ('1', '2')]
