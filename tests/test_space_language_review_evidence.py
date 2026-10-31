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


def test_legacy_neighbor_is_context_only_with_full_same_source_receipt():
    from twobyteasr.recognition.asr_source_evidence import _mark_neighbor_context
    cue = SimpleNamespace(start_ms=2000, end_ms=4000)
    rows = [dict(model='single-source', text='poco conosciuto', cue_text_start=None,
                 cue_text_end=None, cue_text_length=10, original_start_ms=1000, original_end_ms=2250,
                 projection_basis='frozen_caption_source_interval'),
            dict(model='single-source', text='Va bene', cue_text_start=0, cue_text_end=10, cue_text_length=10)]
    _mark_neighbor_context(rows, cue)
    assert rows[0]['context_only'] and rows[0]['text']=='poco conosciuto'
    # A genuinely different independent reading of the current interval is
    # not discarded, nor is a same-source observation confined to this cue.
    other = dict(rows[0], model='another-source', context_only=False)
    confined = dict(rows[0], context_only=False, original_start_ms=2000, original_end_ms=4000)
    _mark_neighbor_context([other, confined, rows[1]], cue)
    assert not other['context_only'] and not confined['context_only']


def test_neighbor_context_never_votes_against_an_exact_short_current_reading(monkeypatch):
    import twobyteasr.recognition.asr_source_evidence as source
    cue = StudioCue('c', 2000, 3000, 'Certo')
    project = _project(cue, {})
    rows = [dict(model='qwen', text='Certo', comparison_text='Certo', start_ms=2000, end_ms=3000,
                 cue_start_ms=2000, cue_end_ms=3000, cue_text_start=0,cue_text_end=5,cue_text_length=5,
                 context_only=False, reference='current'),
            dict(model='qwen', text='Ag i ardi ha fatto perdere tre secondi', comparison_text='Ag i ardi',
                 start_ms=2000,end_ms=3000,cue_start_ms=2000,cue_end_ms=3000,
                 context_only=True, reference='next')]
    monkeypatch.setattr(source, 'cue_source_hypotheses', lambda *args, **kwargs: rows)
    evidence = model_evidence(project,cue)
    assert evidence[0].text=='Certo' and not evidence[0].context_only
    assert evidence[1].context_only
    issues=SubtitleQCEngine().analyze(project).for_cue('c')
    assert not any(r.issue_type in {'model_disagreement','suspected_word'} for r in issues)


def test_independent_import_never_borrows_audio_by_time_and_uses_its_language():
    cue=StudioCue('import-id',0,1500,'这是一条用来测试中文速度的导入字幕'*2,speaker_id='srt-track')
    p=_project(cue,{'segment:1':_moss_segment('a completely different source sentence',0,1800,200)})
    p.generation_metadata.update(language={'code':'it'},subtitle_imports={'tracks':{'srt-track':{'language':'zh','role':'independent'}}})
    assert not cue_source_hypotheses(p,cue)
    issues=SubtitleQCEngine().analyze(p).for_cue(cue.id)
    assert not any(r.issue_type=='model_disagreement' for r in issues)
    speed=next(r for r in issues if r.issue_type=='high_cps')
    assert speed.severity.value=='critical'


def test_exact_native_sentence_is_not_cut_by_another_aligners_last_word():
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    sentence='皮尔波伊杜卡'
    cue=StudioCue('7',0,1200,sentence,evidence_refs=['cue-align:7','segment:3'])
    native={'start_ms':0,'end_ms':1000,'text':sentence,'moss_text':sentence,'primary_source':'moss-host',
        'words':[dict(text=char,start_ms=i*150,end_ms=(i+1)*150)for i,char in enumerate(sentence)]}
    p=_project(cue,{'cue-align:7':_alignment_row('7',sentence,23,743),'segment:3':native})
    ensure_independent_captions(p)
    reading=model_evidence(p,p.cues[0])
    assert reading and reading[0].text==sentence
    assert not any(r.issue_type=='current_projection_difference' for r in SubtitleQCEngine().analyze(p).for_cue('7'))
    assert p.asr_evidence['segment:3']==native


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
