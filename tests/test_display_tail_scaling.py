"""Display-tail planning preserves complete pair semantics and acoustic clocks."""
from copy import deepcopy
import json
import random
from types import SimpleNamespace

import pytest

from twobyteasr import display_timing as timing


def legacy_plan(project):
    """Original all-pairs planner; public acoustic policies remain authoritative."""
    rows = [dict(id=c.id, start_ms=c.start_ms, end_ms=c.end_ms, speaker=c.speaker_id)
            for c in project.cues]
    acoustic = {c.id: timing.project_acoustics(project, c) for c in project.cues}
    boundaries = {c.id: timing.project_word_boundaries(project, c) for c in project.cues}
    verified = {(a.id, b.id) for i, a in enumerate(project.cues) for b in project.cues[i+1:]
                if min(a.end_ms, b.end_ms) > max(a.start_ms, b.start_ms)
                and timing.independent_overlap_verified(project, a, b)}
    changes, audit = timing.protect_intervals(rows, acoustic, word_boundaries=boundaries,
                                             verified_pairs=verified)
    by_id = {c.id: c for c in project.cues}
    frame = timing.project_frame_ms(project)
    for pair in audit:
        left, right = by_id[pair['left']], by_id[pair['right']]
        pair.update(raw_labels=[left.speaker_id, right.speaker_id],
                    display_labels=[next((s.name or s.id for s in project.speakers if s.id == c.speaker_id),
                                         c.speaker_id) for c in (left, right)],
                    cue_before=[[left.start_ms, left.end_ms], [right.start_ms, right.end_ms]], frame_ms=frame,
                    independently_verified=timing.independent_overlap_verified(project, left, right))
        if pair['classification'] == 'acoustic' and not pair['independently_verified']:
            pair.update(classification='source_overlap_unverified', review_required=True)
        if left.id in changes:
            pair.update(boundary_ms=changes[left.id], boundary_source='incoming_cue_or_measured_speech_end')
    report = dict(policy_version=4, status='applied', pairs_before=audit, changed_ends=changes,
                  counts={name: sum(p['classification'] == name for p in audit) for name in
                          ('display_compensation', 'acoustic', 'uncertain', 'source_overlap_unverified')},
                  source='measured cue words before coarse source intervals; unknown overlap retained')
    return changes, report


def project_fixture(count=36, *, evidence='coarse', seed=7):
    rng = random.Random(seed)
    cues = []
    records = {}
    for index in range(count):
        start = index * 800
        if index % 7 == 1:
            start -= 800  # Equal-start cues; endpoint ordering must still match.
        end = start + (9000 if index % 11 == 0 else rng.randint(500, 2200))
        key = f'c{index}'
        speaker = f'S{index % 4}'
        cue = SimpleNamespace(id=key, start_ms=start, end_ms=end, text='字幕',
                              speaker_id=speaker, evidence_refs=[key])
        cues.append(cue)
        if evidence != 'unknown':
            records[key] = dict(speaker_id=speaker, moss_start=start/1000,
                                moss_end=(min(end, start+700))/1000)
            if evidence == 'words':
                records[key].update(final_timing_owner='FireRed', words=[
                    dict(text='字', start_ms=start+10, end_ms=start+300),
                    dict(text='幕', start_ms=start+300, end_ms=start+600)])
            if index % 5 == 0:
                records[key]['speaker_independent'] = True
                records[key]['independent_speech_intervals'] = [dict(start_ms=start+50, end_ms=start+650)]
            if index % 6 == 0 and index+1 < count:
                records[key]['verified_overlap_with'] = [f'c{index+1}']
    # Mixed-speaker neighbouring refs must not contaminate word boundaries.
    for index, cue in enumerate(cues[:-1]):
        cue.evidence_refs.append(cues[index+1].id)
    rng.shuffle(cues)
    return SimpleNamespace(cues=cues, asr_evidence=records, studio_state={}, render_settings={'fps': 60},
        media_pool=[], speakers=[SimpleNamespace(id=f'S{i}', name=f'主播{i}') for i in range(4)])


@pytest.mark.parametrize('evidence', ['unknown', 'coarse', 'words'])
@pytest.mark.parametrize('seed', [0, 7, 23])
def test_full_plan_matches_legacy_with_nested_equal_start_and_unsorted_cues(evidence, seed):
    project = project_fixture(evidence=evidence, seed=seed)
    before = deepcopy(project)
    expected = legacy_plan(project)
    actual = timing.project_display_tail_plan(project)
    assert actual == expected
    # Dict insertion order and every audit row/value remain stable too.
    assert json.dumps(actual, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False)
    assert project == before
    if evidence == 'unknown':
        assert actual[0] == {}


def test_measured_boundaries_are_computed_once_per_cue(monkeypatch):
    from twobyteasr import cue_word_alignment
    project = project_fixture(20, evidence='words')
    original = cue_word_alignment.cue_words
    observed = []

    def counted(view, cue):
        observed.append(cue.id)
        return original(view, cue)

    monkeypatch.setattr(cue_word_alignment, 'cue_words', counted)
    timing.project_display_tail_plan(project)
    assert sorted(observed) == sorted(c.id for c in project.cues)


@pytest.mark.parametrize('alignment', ['exact_token_text', 'derived_term_source_span'])
def test_independent_measured_or_non_equal_derived_span_keeps_current_clock(alignment):
    project = project_fixture(2, evidence='unknown')
    project.cues.sort(key=lambda c: c.id)
    left, right = project.cues
    left.start_ms, left.end_ms = 10000, 12000
    right.start_ms, right.end_ms = 11500, 13000
    left.text = '风暴龙' if alignment == 'derived_term_source_span' else '骨龙'
    right.text = '字幕'
    project.render_settings['_cue_domain'] = 'timeline'
    instances = {}
    for cue, start, end in ((left, 10100, 11400), (right, 11600, 12300)):
        instances[cue.id] = dict(text=cue.text, word_alignment=alignment,
            words=[dict(text=cue.text, char_start=0, char_end=len(cue.text), start_ms=start, end_ms=end,
                        evidence_ref=cue.id)], word_base_interval=[cue.start_ms, cue.end_ms])
    project.studio_state['caption_timeline'] = dict(instances=instances)
    before = deepcopy(project)
    expected = legacy_plan(project)
    actual = timing.project_display_tail_plan(project)
    assert actual == expected
    assert actual[0] == {left.id: 11500}
    assert actual[1]['pairs_before'][0]['word_boundaries_ms'] == [11400, 11600]
    assert project == before


@pytest.mark.parametrize('source_spans', [[], [{'source_start_ms': 0, 'source_end_ms': 2000}]])
def test_legacy_coarse_evidence_is_mapped_only_with_an_unambiguous_clock(source_spans):
    project = project_fixture(2, evidence='coarse')
    project.cues.sort(key=lambda c: c.id)
    left, right = project.cues
    left.start_ms, left.end_ms = 10000, 12000
    right.start_ms, right.end_ms = 11500, 13000
    project.asr_evidence = {left.id: dict(speaker_id=left.speaker_id, acoustic_start_ms=100, acoustic_end_ms=1400),
                            right.id: dict(speaker_id=right.speaker_id, acoustic_start_ms=1600, acoustic_end_ms=2300)}
    left.evidence_refs, right.evidence_refs = [left.id], [right.id]
    project.render_settings['_cue_domain'] = 'timeline'
    project.studio_state['caption_timeline'] = dict(instances={
        left.id: dict(words=[], word_alignment='missing_word_timestamps', source_spans=source_spans,
                      word_base_interval=[10000, 12000]),
        right.id: dict(words=[], word_alignment='missing_word_timestamps',
                       source_spans=[{'source_start_ms': 1500, 'source_end_ms': 3000}],
                       word_base_interval=[11500, 13000])})
    assert timing.project_display_tail_plan(project) == legacy_plan(project)
    if not source_spans:
        assert timing.project_display_tail_plan(project)[0] == {}
