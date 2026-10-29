from types import SimpleNamespace
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_find_replace import PreviewBinding, apply_occurrences
from twobyteasr.studio.studio_text_tools import TextOccurrence


def page():
    p = SubtitleProject(media=StudioMedia(path='isolated.mp4'),
        cues=[StudioCue('a', 100, 1000, 'Borlin也没有接住', speaker_id='S01')])
    p.validate()
    return SimpleNamespace(session=SimpleNamespace(project=p, undo_stack=QUndoStack()), _changed=lambda: None)


def hits():
    return [TextOccurrence('a', 100, 'Borlin', 'BerLIN', (0, 6), reason='已确认纠错')]


def test_preview_rejects_same_id_different_project_object():
    a = page(); token = PreviewBinding.capture(a.session.project)
    b = page(); b.session.project.project_id = a.session.project.project_id
    assert apply_occurrences(b, hits(), title='应用术语库', binding=token) == (0, 0)
    assert b.session.project.cues[0].text.startswith('Borlin')


def test_preview_rejects_new_manual_text_and_preserves_it():
    a = page(); token = PreviewBinding.capture(a.session.project)
    a.session.project.cues[0].text = '人工修改'
    assert apply_occurrences(a, hits(), title='应用术语库', binding=token) == (0, 0)
    assert a.session.project.cues[0].text == '人工修改'


def test_apply_is_one_undo_and_preserves_timing_speaker_and_original():
    a = page(); p = a.session.project; token = PreviewBinding.capture(p)
    before = p.cues[0].__dict__.copy()
    assert apply_occurrences(a, hits(), title='应用术语库', binding=token) == (1, 1)
    assert p.cues[0].text == 'BerLIN也没有接住'

    assert (p.cues[0].start_ms,p.cues[0].end_ms,p.cues[0].speaker_id) == (100,1000,'S01')
    a.session.undo_stack.undo()
    assert p.cues[0].__dict__ == before
    a.session.undo_stack.redo()
    assert p.cues[0].text == 'BerLIN也没有接住'


def test_word_mapping_is_derived_and_undo_restores_evidence(tmp_path):
    import copy
    from twobyteasr.projects.studio_project import save_project, load_project
    from twobyteasr.recognition.cue_word_alignment import cue_words
    a = page(); p = a.session.project
    p.asr_evidence = {'r': {'words': [
        {'text':'Borlin','start_ms':100,'end_ms':500},
        {'text':'也没有接住','start_ms':500,'end_ms':1000}]}}
    p.cues[0].evidence_refs = ['r']
    original = copy.deepcopy(p.asr_evidence)
    token = PreviewBinding.capture(p)
    assert apply_occurrences(a, hits(), title='应用术语库', binding=token, glossary_ids=['valorant-id']) == (1,1)
    assert p.asr_evidence == original
    mapped = p.studio_state['term_word_overrides']['a']
    assert ''.join(w['text'] for w in mapped['words']) == p.cues[0].text
    assert mapped['alignment_provenance'] == 'term_local_mapping'
    # The remap itself is never used; the replaced spelling keeps the whole
    # heard span of the original token and cannot be cut inside.
    words, reason = cue_words(p, p.cues[0])
    assert reason == 'derived_term_source_span'
    assert [(w.start_ms, w.end_ms) for w in words] == [(100, 500), (500, 1000)]
    target = tmp_path/'term.2byteproj'; save_project(p, target)
    reopened = load_project(target)
    assert reopened.cues[0].text == 'BerLIN也没有接住'
    assert reopened.glossary_ids == ['valorant-id']
    assert reopened.studio_state['term_word_overrides'] == p.studio_state['term_word_overrides']
    a.session.undo_stack.undo()
    assert 'term_word_overrides' not in p.studio_state and p.glossary_ids == []
    assert p.asr_evidence == original
    a.session.undo_stack.redo()
    assert p.cues[0].text == 'BerLIN也没有接住'


def test_case_only_keeps_exact_word_times():
    from twobyteasr.recognition.cue_word_alignment import cue_words
    a = page(); p = a.session.project; p.cues[0].text = 'berlin也没有接住'
    p.asr_evidence = {'r': {'words':[{'text':'berlin','start_ms':100,'end_ms':500},
                                    {'text':'也没有接住','start_ms':500,'end_ms':1000}]}}
    p.cues[0].evidence_refs = ['r']
    rows = [TextOccurrence('a',100,'berlin','BerLIN',(0,6))]
    assert apply_occurrences(a,rows,title='应用术语库',binding=PreviewBinding.capture(p),glossary_ids=['v']) == (1,1)
    words, reason = cue_words(p,p.cues[0])
    assert reason == 'exact_token_text'
    assert [(w.start_ms,w.end_ms) for w in words] == [(100,500),(500,1000)]


def test_case_only_after_spelling_change_keeps_derived_alignment_through_undo_redo():
    import copy
    from twobyteasr.recognition.cue_word_alignment import cue_words
    a = page(); p = a.session.project
    p.asr_evidence = {'r': {'words': [
        {'text': 'Borlin', 'start_ms': 100, 'end_ms': 500},
        {'text': '也没有接住', 'start_ms': 500, 'end_ms': 1000}]}}
    p.cues[0].evidence_refs = ['r']
    original = copy.deepcopy(p.asr_evidence)
    apply_occurrences(a, hits(), title='应用术语库', binding=PreviewBinding.capture(p), glossary_ids=['v'])
    first = copy.deepcopy(p.studio_state['term_word_overrides'])
    rows = [TextOccurrence('a', 100, 'BerLIN', 'BERLIN', (0, 6))]
    apply_occurrences(a, rows, title='应用术语库', binding=PreviewBinding.capture(p), glossary_ids=['v'])
    assert p.studio_state['term_word_overrides']['a']['alignment_provenance'] == 'term_local_mapping'
    assert cue_words(p, p.cues[0])[1] == 'derived_term_source_span'
    second = copy.deepcopy(p.studio_state['term_word_overrides'])
    a.session.undo_stack.undo()
    assert p.studio_state['term_word_overrides'] == first
    a.session.undo_stack.redo()
    assert p.studio_state['term_word_overrides'] == second
    assert p.asr_evidence == original


def test_case_only_cannot_promote_degraded_original_timing():
    from twobyteasr.recognition.cue_word_alignment import cue_words
    for owner in ('estimated', 'proportional', 'degraded', '估算', '均分'):
        a = page(); p = a.session.project; p.cues[0].text = 'berlin也没有接住'
        p.asr_evidence = {'r': {'final_timing_owner': owner, 'words': [
            {'text': 'berlin', 'start_ms': 100, 'end_ms': 500},
            {'text': '也没有接住', 'start_ms': 500, 'end_ms': 1000}]}}
        p.cues[0].evidence_refs = ['r']
        rows = [TextOccurrence('a', 100, 'berlin', 'BerLIN', (0, 6))]
        apply_occurrences(a, rows, title='应用术语库', binding=PreviewBinding.capture(p), glossary_ids=['v'])
        assert p.studio_state['term_word_overrides']['a']['alignment_provenance'] == 'term_local_mapping', owner
        assert cue_words(p, p.cues[0])[1] == 'term_local_mapping_requires_acoustic_alignment', owner


def test_production_saved_term_mapping_keeps_alignment_provenance(tmp_path):
    from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue, WordUnit
    from twobyteasr.glossary.terminology import apply_to_segments, snapshot_from_pairs
    from twobyteasr.projects.studio_project import create_studio_outputs, load_project
    from twobyteasr.recognition.cue_word_alignment import cue_words
    for original, replacement, owner, has_words, expected in (
        ('Borlin', 'BerLIN', 'MOSS', True, 'derived_term_source_span'),
        ('berlin', 'BerLIN', 'MOSS', True, 'exact_token_text'),
        ('berlin', 'BerLIN', 'estimated', True, 'missing_word_timestamps'),
        ('berlin', 'BerLIN', 'MOSS', False, 'term_local_mapping_requires_acoustic_alignment'),
    ):
        source = original + '也没有接住'
        segment = SpeechSegment(1, .1, 1, source, .9,
            [WordUnit(.1, .5, original, .9), WordUnit(.5, 1, '也没有接住', .9)] if has_words else [],
            speaker='S01', final_timing_owner=owner)
        apply_to_segments([segment], snapshot_from_pairs([(original, replacement)]))
        outputs = create_studio_outputs(tmp_path / 'missing.mp4',
            [SubtitleCue(1, .1, 1, segment.text, speaker='S01')],
            txt_path='', segments=[segment],
            target_project_path=tmp_path / (original + owner + str(has_words)) / 'p.2byteproj')
        saved = load_project(outputs['project'])
        assert saved.cues[0].text == replacement + '也没有接住'
        words, reason = cue_words(saved, saved.cues[0])
        assert reason == expected
        if expected in ('exact_token_text', 'derived_term_source_span'):
            assert [(w.start_ms, w.end_ms) for w in words] == [(100, 500), (500, 1000)]
        else:
            assert words == ()


def independent_page(original='Borlin', *, has_aligned_words=True):
    """Freeze a real source-to-timeline projection, with unrelated clocks."""
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions, KEY
    from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence
    p = SubtitleProject(media=StudioMedia(path='isolated.mp4', duration_ms=20000),
        cues=[StudioCue('source',10000,12000,original+'也没有接住',speaker_id='S01',evidence_refs=['r'])],
        asr_evidence={'r': {'words': [
            {'text': original,'start_ms':10000,'end_ms':10600},
            {'text': '也没有接住','start_ms':10600,'end_ms':12000}]}})
    p.validate()
    store_sequence(p,EditSequence(source_path=p.media.path,source_duration_ms=20000,
        segments=[VideoSegment('cut',p.media.path,10000,12000,1000,3000)]))
    assert ensure_independent_captions(p)
    cue = p.cues[0]
    assert (cue.start_ms,cue.end_ms) == (1000,3000)
    receipt = p.studio_state[KEY]['instances'][cue.id]
    assert (receipt['source_start_ms'],receipt['source_end_ms']) == (10000,12000)
    if not has_aligned_words:
        # A manually retimed caption has no certified local words, even though
        # immutable original ASR words remain available in source time.
        receipt['words'] = []
        receipt['word_alignment'] = 'manual_interval_changed_requires_acoustic_alignment'
        # Nor any known evidence clock to re-derive them on (a receipt from
        # an older build): the caption stays explicitly pending.
        receipt.pop('evidence_clock_offset_ms', None)
    return SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=QUndoStack()),_changed=lambda:None)


def test_independent_term_spelling_mapping_uses_cue_clock_or_explicit_pending(tmp_path):
    import copy
    from twobyteasr.recognition.cue_word_alignment import cue_words
    from twobyteasr.projects.studio_project import save_project,load_project
    for has_words in (True,False):
        a = independent_page(has_aligned_words=has_words)
        p = a.session.project; cue = p.cues[0]
        original_evidence = copy.deepcopy(p.asr_evidence)
        original_state = copy.deepcopy(p.studio_state)
        rows = [TextOccurrence(cue.id,cue.start_ms,'Borlin','BerLIN',(0,6))]
        assert apply_occurrences(a,rows,title='当前词库重新校对',
            binding=PreviewBinding.capture(p),glossary_ids=['valorant-id']) == (1,1)
        mapping = p.studio_state['term_word_overrides'][cue.id]
        assert mapping['text'] == 'BerLIN也没有接住'
        assert mapping['alignment_provenance'] == 'term_local_mapping'
        assert mapping['time_domain'] == 'cue'
        if has_words:
            assert ''.join(w['text'] for w in mapping['words']) == cue.text
            assert [(w['start_ms'],w['end_ms']) for w in mapping['words']] == [(1000,1600),(1600,3000)]
            assert all(cue.start_ms <= w['start_ms'] < w['end_ms'] <= cue.end_ms for w in mapping['words'])
        else:
            assert mapping['words'] == []
            assert mapping['requires_acoustic_alignment'] is True
            assert mapping['timing'] == 'segment-only-no-word-alignment'
        # A spelling remap is derived even when its input had exact word times:
        # with the caption's measured words the replaced span stays whole; a
        # caption without measured words stays explicitly pending.
        expected = (((1000, 1600), (1600, 3000)), 'derived_term_source_span') if has_words else (
            (), 'term_local_mapping_requires_acoustic_alignment')
        words, reason = cue_words(p, cue)
        assert (tuple((w.start_ms, w.end_ms) for w in words), reason) == expected
        assert p.asr_evidence == original_evidence
        reopened = load_project(save_project(p,tmp_path/f'independent-{has_words}.2byteproj'))
        assert reopened.studio_state['term_word_overrides'][cue.id] == mapping
        words, reason = cue_words(reopened, reopened.cues[0])
        assert (tuple((w.start_ms, w.end_ms) for w in words), reason) == expected
        a.session.undo_stack.undo()
        assert p.studio_state == original_state and p.cues[0].text == 'Borlin也没有接住'
        a.session.undo_stack.redo()
        assert p.studio_state['term_word_overrides'][cue.id] == mapping
        assert p.asr_evidence == original_evidence


def test_independent_case_only_term_keeps_projected_exact_times_on_reopen(tmp_path):
    import copy
    from twobyteasr.recognition.cue_word_alignment import cue_words
    from twobyteasr.projects.studio_project import save_project,load_project
    a = independent_page('berlin'); p = a.session.project; cue = p.cues[0]
    evidence_before = copy.deepcopy(p.asr_evidence)
    words_before,reason_before = cue_words(p,cue)
    assert reason_before == 'exact_token_text'
    times_before = [(w.start_ms,w.end_ms) for w in words_before]
    assert times_before == [(1000,1600),(1600,3000)]
    rows = [TextOccurrence(cue.id,cue.start_ms,'berlin','BerLIN',(0,6))]
    assert apply_occurrences(a,rows,title='当前词库重新校对',
        binding=PreviewBinding.capture(p),glossary_ids=['valorant-id']) == (1,1)
    mapping = p.studio_state['term_word_overrides'][cue.id]
    assert mapping['alignment_provenance'] == 'case_only' and mapping['time_domain'] == 'cue'
    words,reason = cue_words(p,cue)
    assert reason == 'exact_token_text'
    assert [(w.start_ms,w.end_ms) for w in words] == times_before
    assert ''.join(w.text for w in words) == cue.text
    reopened = load_project(save_project(p,tmp_path/'independent-case.2byteproj'))
    assert cue_words(reopened,reopened.cues[0]) == (words,reason)
    assert p.asr_evidence == reopened.asr_evidence == evidence_before
    a.session.undo_stack.undo()
    assert cue_words(p,p.cues[0]) == (words_before,reason_before)
    a.session.undo_stack.redo()
    assert cue_words(p,p.cues[0]) == (words,reason)
