"""English review evidence (2026-10-27, user report).

An English caption identical to the MOSS sentence showed "模型对「- / …」存在分歧":
the caption's own forced-alignment row (``cue-align:``) was counted as a
second MOSS reading and glued to the real one, and sliced English evidence
lost its word spaces.
"""
from types import SimpleNamespace

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.recognition.asr_source_evidence import cue_source_hypotheses
from twobyteasr.recognition.cue_evidence_slice import slice_evidence
from twobyteasr.recognition.cue_forced_alignment import evidence_row
from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine, model_evidence, review_candidates
from twobyteasr.subtitle_rules.studio_review import ReviewEvidenceAggregator

SENTENCE = "you can see that it's naturally blue in color"


def _words(text, start_ms, step_ms):
    return [dict(text=word, start_ms=start_ms + index * step_ms, end_ms=start_ms + (index + 1) * step_ms)
            for index, word in enumerate(text.split())]


def _alignment_row(cue_id, text, start_ms, end_ms):
    """What cue_forced_alignment stores for a caption: its own text, timed."""
    segments, cursor, step = [], 0, (end_ms - start_ms) // max(1, len(text.split()))
    for index, word in enumerate(text.split()):
        at = text.index(word, cursor)
        cursor = at + len(word)
        segments.append(dict(char_start=at, char_end=cursor, start_ms=start_ms + index * step,
                             end_ms=start_ms + (index + 1) * step, granularity='word'))
    alignment = dict(text=text, segments=segments, model='Qwen/Qwen3-ForcedAligner-0.6B', language='English')
    return evidence_row(cue_id, start_ms, end_ms, 'S00', alignment)


def _project(cue, evidence):
    project = SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=20_000), cues=[cue],
                              asr_evidence=evidence)
    project.generation_metadata['models'] = {'primary_asr_backend': 'moss'}
    return project


def _moss_segment(text, start_ms, end_ms, step_ms):
    return dict(start_ms=start_ms, end_ms=end_ms, text=text, moss_text=text, primary_source='moss-host',
                words=_words(text, start_ms, step_ms))


def test_caption_alignment_row_is_not_a_second_moss_reading():
    cue = StudioCue('7', 1000, 5500, SENTENCE, evidence_refs=['cue-align:7', 'segment:3'])
    project = _project(cue, {
        'cue-align:7': _alignment_row('7', SENTENCE, 1000, 5500),
        'segment:3': _moss_segment(SENTENCE, 1000, 5500, 500),
    })
    hypotheses = cue_source_hypotheses(project, cue)
    assert [(row['model'], row['reference']) for row in hypotheses] == [('moss', 'segment:3')]
    assert [row.text for row in model_evidence(project, cue)] == [SENTENCE]
    candidates = review_candidates(project, cue)
    assert len(candidates) == 1 and set(candidates[0].sources) == {'Current', 'MOSS'}
    issues = SubtitleQCEngine().analyze(project).for_cue(cue.id)
    assert not [issue for issue in issues if issue.issue_type == 'model_disagreement']
    assert ReviewEvidenceAggregator().aggregate(project, cue).models_agree_text


def test_workbench_timeline_reads_the_segment_through_the_alignment_clock():
    """Opened in the workbench, receipts carry the words of the caption's own
    alignment row; the MOSS segment is placed by that clock, once."""
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    before = "and now"
    text = f"{before} {SENTENCE} which is great"
    cue = StudioCue('7', 1000, 5500, SENTENCE, evidence_refs=['cue-align:7', 'segment:3'])
    project = _project(cue, {
        'cue-align:7': _alignment_row('7', SENTENCE, 1000, 5500),
        'segment:3': _moss_segment(text, 0, 7000, 500),
    })
    ensure_independent_captions(project)
    assert project.render_settings['_cue_domain'] == 'timeline'
    cue = project.cues[0]
    hypotheses = cue_source_hypotheses(project, cue)
    assert [(row['model'], row['reference'], row['text']) for row in hypotheses] == [('moss', 'segment:3', SENTENCE)]
    assert len(review_candidates(project, cue)) == 1
    assert 'model_disagreement' not in {issue.issue_type for issue in SubtitleQCEngine().analyze(project).for_cue(cue.id)}


def test_alignment_row_alone_gives_no_model_reading():
    """Only the caption's own text is there: nothing independent to compare."""
    cue = StudioCue('8', 0, 3000, SENTENCE, evidence_refs=['cue-align:8'])
    project = _project(cue, {'cue-align:8': _alignment_row('8', SENTENCE, 0, 3000)})
    assert cue_source_hypotheses(project, cue) == ()
    assert review_candidates(project, cue)[0].sources == ('Current',)


def test_english_slice_keeps_word_spaces():
    text = 'we are now in the S-Log3 S-Gamut3 Cine color space for this shot'
    row = _moss_segment(text, 0, 13_000, 1000)
    # words 5..9: "S-Log3 S-Gamut3 Cine color space"
    assert slice_evidence(row, SimpleNamespace(start_ms=5000, end_ms=10_000), 'moss_text') == \
        'S-Log3 S-Gamut3 Cine color space'


def test_long_english_segment_still_slices():
    """A whole-file API segment is far longer than 512 letters."""
    filler = ' '.join(f'word{index}' for index in range(150))
    text = f'{filler} {SENTENCE} {filler}'
    row = _moss_segment(text, 0, len(text.split()) * 400, 400)
    start = 150 * 400
    cue = SimpleNamespace(start_ms=start, end_ms=start + len(SENTENCE.split()) * 400)
    assert slice_evidence(row, cue, 'moss_text') == SENTENCE


def _drifted_pair(second_caption):
    """Two captions cut from one MOSS segment; the recognizer's word clock puts
    "to" (the second caption's first word) inside the first caption."""
    text = "I'm here to talk to you today about color management"
    words = [dict(text=word, start_ms=index * 500, end_ms=(index + 1) * 500)
             for index, word in enumerate(text.split())]
    first = StudioCue('1', 0, 2600, "I'm here to talk", evidence_refs=['segment:1'])
    second = StudioCue('2', 2600, 5000, second_caption, evidence_refs=['segment:1'])
    project = SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=20_000), cues=[first, second],
                              asr_evidence={'segment:1': dict(start_ms=0, end_ms=5000, text=text, moss_text=text,
                                                              primary_source='moss-host', words=words)})
    return project, first, second


def test_edge_word_drift_snaps_to_the_captions_own_words():
    project, first, second = _drifted_pair('to you today about color management')
    assert [row.text for row in model_evidence(project, first)] == ["I'm here to talk"]
    assert [row.text for row in model_evidence(project, second)] == ['to you today about color management']
    for cue in (first, second):
        assert len(review_candidates(project, cue)) == 1
        issues = {issue.issue_type for issue in SubtitleQCEngine().analyze(project).for_cue(cue.id)}
        assert not issues & {'model_disagreement', 'current_projection_difference'}


def test_one_long_api_word_does_not_strand_the_rest_of_the_caption():
    """DaVinci tutorial copy, cue 183: the API stamped one token 3.5 s long."""
    words = [('down', 0, 400), ('and', 500, 600), ('select', 700, 900), ('sgamut3.cine/slog3', 1000, 4500),
             ('And', 4600, 4700), ('once', 4700, 4800), ('we', 4800, 4900), ('do', 4900, 5000),
             ("you're", 5000, 5200), ('going', 5200, 5400), ('to', 5400, 5500), ('see', 5500, 5800)]
    text = ' '.join(word for word, _a, _b in words)
    caption = "and select sgamut3.cine/slog3 And once we do you're going"
    cue = StudioCue('183', 450, 3500, caption, evidence_refs=['segment:6'])
    project = _project(cue, {'segment:6': dict(start_ms=0, end_ms=5800, text=text, moss_text=text,
        primary_source='moss-host', words=[dict(text=w, start_ms=a, end_ms=b) for w, a, b in words])})
    assert [row.text for row in model_evidence(project, cue)] == [caption]
    issues = {issue.issue_type for issue in SubtitleQCEngine().analyze(project).for_cue(cue.id)}
    assert 'current_projection_difference' not in issues


def test_edited_caption_keeps_the_model_difference():
    project, _first, second = _drifted_pair('to you today about colour grading')
    candidates = review_candidates(project, second)
    assert [candidate.sources for candidate in candidates] == [('Current',), ('MOSS',)]
    assert ' ' in candidates[1].text


def test_two_english_pieces_of_one_model_join_with_a_space():
    cue = StudioCue('9', 0, 4000, 'we can see it naturally blue in color',
                    evidence_refs=['segment:1', 'segment:2'])
    project = _project(cue, {
        'segment:1': _moss_segment('we can see it', 0, 2000, 500),
        'segment:2': _moss_segment('naturally blue in color', 2000, 4000, 500),
    })
    assert [row.text for row in model_evidence(project, cue)] == ['we can see it naturally blue in color']


def test_chinese_pieces_still_join_directly():
    cue = StudioCue('10', 0, 2000, '一起走吧', evidence_refs=['segment:1', 'segment:2'])
    project = _project(cue, {
        'segment:1': dict(start_ms=0, end_ms=1000, text='一起', moss_text='一起', primary_source='moss-host',
                          words=[dict(text='一', start_ms=0, end_ms=500), dict(text='起', start_ms=500, end_ms=1000)]),
        'segment:2': dict(start_ms=1000, end_ms=2000, text='走吧', moss_text='走吧', primary_source='moss-host',
                          words=[dict(text='走', start_ms=1000, end_ms=1500), dict(text='吧', start_ms=1500, end_ms=2000)]),
    })
    assert [row.text for row in model_evidence(project, cue)] == ['一起走吧']
