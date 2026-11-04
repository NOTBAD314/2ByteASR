"""The retained 18.4s/25s source rows distinguish search padding from tails."""
import json
from pathlib import Path

from twobyteasr.subtitle_rules.display_timing import bounded_search_window, project_display_tail_plan
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject


def recorded_project():
    data = json.loads((Path(__file__).parent/'fixtures/ge_edg_20261006_handoff_windows.json').read_text('utf-8'))
    project = SubtitleProject(media=StudioMedia('', duration_ms=30000),
        cues=[StudioCue(**row) for row in data['cues']],
        speakers=[StudioSpeaker(**row) for row in data['speakers']])
    project.asr_evidence = data['asr_evidence']
    project.render_settings['fps'] = 60
    project.validate()
    return project


def test_recorded_disjoint_source_handoffs_are_shared_frame_ends():
    project = recorded_project()
    ends, audit = project_display_tail_plan(project)
    assert ends['9'] == 18383
    assert ends['13'] == 25117
    for left, right in (('9','10'), ('13','14')):
        pair = next(p for p in audit['pairs_before'] if p['left'] == left and p['right'] == right)
        assert pair['classification'] == 'display_compensation'
        assert not pair['independently_verified']
        assert max(b for a,b in pair['left_acoustic']) <= min(a for a,b in pair['right_acoustic'])
        assert pair['boundary_ms'] == ends[left]
    # Calculate the preview without modifying the old project.
    assert next(c for c in project.cues if c.id == '9').end_ms == 18450
    assert next(c for c in project.cues if c.id == '13').end_ms == 25217


def test_nearby_other_speaker_refs_do_not_contaminate_a_cue_source_bounds():
    from twobyteasr.subtitle_rules.display_timing import project_acoustics
    project = recorded_project()
    cue = next(c for c in project.cues if c.id == '9')
    bounds = project_acoustics(project, cue)
    assert (18380,20420) not in bounds
    assert max(b for a,b in bounds) == 18250


def test_search_window_provenance_is_not_high_confidence_acoustic_evidence():
    assert bounded_search_window(dict(moss_start=17.13, moss_end=18.25,
        firered_start=17.05, firered_end=18.33, firered_alignment_confidence=.99))
    assert not bounded_search_window(dict(moss_start=17.13, moss_end=18.25,
        firered_start=17.16, firered_end=18.20))
    assert bounded_search_window(dict(caption_arbitration={'timing_evidence':{'kind':'bounded_search_window'}}))


def test_recorded_real_source_overlap_is_retained_for_review():
    project = recorded_project()
    ends, audit = project_display_tail_plan(project)
    pair = next(p for p in audit['pairs_before'] if p['left']=='8' and p['right']=='9')
    assert pair['classification'] == 'source_overlap_unverified'
    assert pair['review_required']
    assert '8' not in ends
