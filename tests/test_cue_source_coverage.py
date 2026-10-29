from copy import deepcopy
from types import SimpleNamespace

from twobyteasr.recognition.asr_source_evidence import cue_source_hypotheses, coverage_summary
from twobyteasr.design.components import format_model_evidence_coverage
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine, review_candidates
from twobyteasr.subtitle_rules.studio_review import ReviewEvidenceAggregator, review_evidence_coverage


def project(row, cue=None):
    return SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=2000),
        cues=[cue or StudioCue('cue', 0, 1000, '一起走', evidence_refs=['r'])],
        asr_evidence={'r': row})


def evidence(text='一起走'):
    return dict(start_ms=0, end_ms=1000, text=text, moss_text=text, firered_text=text,
        qwen_asr_text=text, qwen_text=text, alternate_text=text, firered_llm_text=text,
        primary_source='moss-host')


def test_one_unique_candidate_keeps_three_independent_sources_and_roundtrip(tmp_path):
    p = project(evidence())
    candidates = review_candidates(p, p.cues[0])
    assert len(candidates) == 1
    assert set(candidates[0].sources) == {'Current', 'MOSS', 'FireRed', 'Qwen'}
    assert coverage_summary(cue_source_hypotheses(p, p.cues[0]))['known_count'] == 3
    reopened = load_project(save_project(p, tmp_path/'saved.2byteproj'))
    assert cue_source_hypotheses(reopened, reopened.cues[0]) == cue_source_hypotheses(p, p.cues[0])
    assert reopened.asr_evidence == p.asr_evidence


def test_conflict_is_not_hidden_by_three_model_count():
    row = evidence(); row['qwen_asr_text'] = '分开走'; row['qwen_text'] = '一起走'
    p = project(row)
    aggregate = ReviewEvidenceAggregator().aggregate(p, p.cues[0])
    assert aggregate.requires_review and not aggregate.models_agree_text
    coverage = format_model_evidence_coverage(aggregate.hypotheses)
    assert coverage['known_count'] == 3 and coverage['conflict']
    assert '分歧' in coverage['headline']


def test_small_real_conflict_still_requires_review_and_keeps_separate_card():
    row = evidence('这一整条很长的字幕里有一个词需要注意')
    row['qwen_asr_text'] = '这一整条很长的字幕里有一个字需要注意'
    p = project(row,StudioCue('cue',0,1000,row['moss_text'],evidence_refs=['r']))
    assert len(review_candidates(p,p.cues[0])) == 2
    assert ReviewEvidenceAggregator().aggregate(p,p.cues[0]).requires_review


def test_real_single_source_and_missing_information_are_distinct():
    p = project(dict(start_ms=0, end_ms=1000, moss_text='一起走'))
    one = coverage_summary(cue_source_hypotheses(p, p.cues[0]))
    assert one['single_source'] and not one['missing']
    p.asr_evidence = {}
    missing = format_model_evidence_coverage(cue_source_hypotheses(p, p.cues[0]))
    assert missing['missing'] and not missing['single_source']
    assert missing['headline'] == '来源信息缺失／待恢复'


def test_partial_qwen_coverage_does_not_claim_three_sources_everywhere():
    row = evidence('前半后半')
    row['words'] = [dict(text=c, start_ms=i*250, end_ms=(i+1)*250) for i, c in enumerate('前半后半')]
    row['caption_arbitration'] = dict(source_coverage={'qwen3-asr': [dict(start_ms=0, end_ms=500)]})
    p = project(row, StudioCue('cue', 0, 1000, '前半后半', evidence_refs=['r']))
    observations = cue_source_hypotheses(p, p.cues[0])
    qwen = [r for r in observations if r['model'] == 'qwen3-asr']
    assert [r['text'] for r in qwen] == ['前半']
    coverage = coverage_summary(observations)
    assert coverage['partial'] and (coverage['minimum_count'], coverage['maximum_count']) == (2, 3)
    assert coverage['spans'][-1]['models'] == ['firered', 'moss']
    aggregate = ReviewEvidenceAggregator().aggregate(p, p.cues[0])
    assert aggregate.models_agree_text and aggregate.requires_review


def test_merge_retains_per_reference_coverage_instead_of_source_union():
    cue = StudioCue('merged', 0, 2000, '前半后半', evidence_refs=['a', 'b'])
    p = project({}, cue)
    p.asr_evidence = {'a': dict(start_ms=0, end_ms=1000, moss_text='前半', firered_text='前半'),
        'b': dict(start_ms=1000, end_ms=2000, moss_text='后半', qwen_asr_text='后半')}
    rows = cue_source_hypotheses(p, cue)
    coverage = coverage_summary(rows)
    assert coverage['known_count'] == 3
    assert coverage['minimum_count'] == coverage['maximum_count'] == 2
    assert all(span['source_count'] == 2 for span in coverage['spans'])
    assert {row['reference'] for row in rows} == {'a', 'b'}
    totals = review_evidence_coverage(p)
    assert totals['3_SOURCE_OVERLAP'] == 0 and totals['2_SOURCE_OVERLAP'] == 1
    assert totals['PARTIAL_SOURCE_COVERAGE'] == 1


def test_model_alias_retry_receipts_do_not_duplicate_source_text():
    cue = SimpleNamespace(id='same',text='一起走',speaker_id='',start_ms=0,end_ms=1000)
    rows = [dict(model=model,text='一起走',start_ms=0,end_ms=1000)
            for model in ['MOSS','FireRed','FIRERED','firered','QWEN3-ASR','qwen3-asr']]
    aggregate = ReviewEvidenceAggregator().aggregate(cue,rows)
    assert aggregate.models_agree_text and not aggregate.requires_review
    assert aggregate.source_coverage['known_count'] == 3
    assert not aggregate.source_coverage['conflict']


def test_source_comparison_uses_same_spoken_number_normalization_as_review():
    rows = [dict(model='moss',text='还有12个人'),dict(model='firered',text='还有十二个人')]
    assert coverage_summary(rows)['agreement'] and not coverage_summary(rows)['conflict']


def test_split_projects_original_evidence_and_does_not_count_derived_copies():
    row = evidence('前半后半')
    row['words'] = [dict(text=c, start_ms=i*250, end_ms=(i+1)*250) for i, c in enumerate('前半后半')]
    row['caption_arbitration'] = dict(independent_input_evidence=dict(primary='前半后半', firered='前半后半', qwen='前半错字'))
    cue = StudioCue('split', 0, 500, '前半', evidence_refs=['r'])
    p = project(row, cue); before = deepcopy(p.asr_evidence)
    rows = cue_source_hypotheses(p, cue)
    assert len(rows) == 3 and {r['text'] for r in rows} == {'前半'}
    assert p.asr_evidence == before


def test_unknown_confidence_is_not_failed_or_zero_confidence():
    row = evidence(); row['qwen_confidence'] = 0
    p = project(row)
    qwen = next(r for r in cue_source_hypotheses(p, p.cues[0]) if r['model'] == 'qwen3-asr')
    assert qwen['confidence'] is None


def test_recorded_review_backend_keeps_cloud_asr_and_local_qwen_distinct():
    row = evidence()
    p = project(row)
    p.generation_metadata['models'] = dict(primary_asr_backend='moss',
        qwen_asr_backend='api', qwen_asr_api_model='qwen-audio-3.1-asr-flash-filetrans')
    models = {r['model'] for r in cue_source_hypotheses(p, p.cues[0])}
    assert models == {'moss', 'firered', 'asr-api:qwen-audio-3.1-asr-flash-filetrans'}
    assert 'qwen3-asr' not in models


def test_missing_review_model_identity_is_not_assumed_local_qwen():
    p = project(evidence())
    p.generation_metadata['models'] = dict(qwen_asr_backend='api', qwen_asr_api_model='')
    assert 'qwen3-asr' not in {r['model'] for r in cue_source_hypotheses(p, p.cues[0])}


def test_ripple_edited_caption_uses_immutable_source_refs_not_current_video_clock():
    row = evidence('stu点掉了一个'); row.update(start_ms=47350, end_ms=48790)
    row['firered_text'] = 'stw点掉了一个'
    row['words'] = [dict(text=c, start_ms=47350+i*180, end_ms=47350+(i+1)*180)
                    for i,c in enumerate('stu点掉了一个')]
    cue = StudioCue('35',36491,37891,'stu点掉了一个',evidence_refs=['r','neighbor'])
    p = project(row,cue); p.render_settings['_cue_domain'] = 'timeline'
    p.asr_evidence['neighbor'] = dict(start_ms=48790,end_ms=49770,moss_text='panda也收掉了stu')
    words = [dict(text=c,char_start=i,char_end=i+1,evidence_ref='r',
        start_ms=36424+i*180,end_ms=36424+(i+1)*180) for i,c in enumerate(cue.text)]
    p.studio_state['caption_timeline'] = dict(instances={'35':dict(
        source_start_ms=47417,source_end_ms=48817,word_base_words=words)})
    observations = cue_source_hypotheses(p,cue)
    assert {o['reference'] for o in observations} == {'r'}
    assert {o['model'] for o in observations} == {'moss','firered','qwen3-asr'}
    assert all(o['source_start_ms'] >= 47350 for o in observations)
    assert all(o['start_ms'] == 36491 and o['end_ms'] == 37864 for o in observations)
    # The retained last word ends 27ms before the cue; moving the caption
    # does not turn that blank tail into additional model coverage.
    assert coverage_summary(observations)['partial']
    from twobyteasr.recognition.cue_evidence_slice import cue_evidence
    assert cue_evidence(p,cue,'firered_text') == 'stw点掉了一个'
    assert coverage_summary(observations)['conflict']


def test_real_ge_edg_saved_cues_keep_three_sources_after_cut_and_roundtrip(tmp_path):
    import json
    from pathlib import Path
    from twobyteasr.recognition.cue_evidence_slice import cue_evidence
    fixture = json.loads((Path(__file__).parent/'fixtures/ge_edg_20261005_cue_evidence.json').read_text(encoding='utf-8'))
    p = SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=60000),
        cues=[StudioCue(**row) for row in fixture['cues']], asr_evidence=fixture['asr_evidence'],
        studio_state=fixture['studio_state'], render_settings=fixture['render_settings'],
        generation_metadata=fixture['generation_metadata'])
    first, second = p.cues
    assert (first.start_ms, first.end_ms) == (36491, 37891)
    assert first.text == 'stu点掉了一个'
    assert cue_evidence(p,first,'firered_text') == 'stw点掉了一个'
    assert cue_evidence(p,second,'qwen_asr_text') == 'pandaman也收掉了'
    for cue, expected_ref in [(first,'segment:37'),(second,'segment:38')]:
        hypotheses = cue_source_hypotheses(p,cue)
        assert {row['reference'] for row in hypotheses} == {expected_ref}
        assert {row['model'] for row in hypotheses} == {'moss','firered','qwen3-asr'}
        coverage = coverage_summary(hypotheses)
        assert coverage['known_count'] == coverage['maximum_count'] == 3
        assert coverage['minimum_count'] == 0 and coverage['partial']
        assert all(row['end_ms'] == cue.end_ms-27 for row in hypotheses)
        assert all(row['source_start_ms'] > row['start_ms']+10000 for row in hypotheses)
        assert ReviewEvidenceAggregator().aggregate(p,cue).requires_review
    reopened = load_project(save_project(p,tmp_path/'ge-roundtrip.2byteproj'))
    assert reopened.asr_evidence == p.asr_evidence
    assert [cue_source_hypotheses(reopened,c) for c in reopened.cues] == [cue_source_hypotheses(p,c) for c in p.cues]


def _real_new48_tail_project():
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent/'fixtures/ge_edg_20261005_new48_tail_evidence.json').read_text(encoding='utf-8'))
    return SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=68000),
        cues=[StudioCue(**row) for row in fixture['cues']], asr_evidence=fixture['asr_evidence'])


def test_real_new48_tail_current_full_text_needs_review_without_changing_accepted_text(tmp_path):
    p = _real_new48_tail_project()
    cue = next(c for c in p.cues if c.id == '48')
    p.studio_state['cue_statuses'] = {cue.id: 'done'}
    p.studio_state['review_confirmations'] = {cue.id: {'text': cue.text}}
    before = deepcopy(p.asr_evidence)
    assert cue.text == '他会遇到一个什么样的情况'
    assert all(value == cue.text for value in p.asr_evidence['segment:50']['caption_arbitration']['independent_input_evidence'].values())
    rows = cue_source_hypotheses(p, cue)
    assert {row['text'] for row in rows} == {'他会遇到一个什么样的'}
    assert {row['model'] for row in rows} == {'moss', 'firered', 'qwen3-asr'}
    aggregate = ReviewEvidenceAggregator().aggregate(p, cue)
    assert aggregate.requires_review and not aggregate.models_agree_text
    assert aggregate.source_coverage['partial']
    assert not aggregate.source_coverage['conflict'], 'Three raw model observations agree; the missing tail is a projection defect'
    assert aggregate.source_coverage['minimum_count'] < 3
    assert aggregate.source_coverage['current_text_supported'] is False
    assert '完整' not in format_model_evidence_coverage(rows)['headline']
    candidates = review_candidates(p, cue)
    assert len(candidates) == 2
    assert set(candidates[1].sources) == {'MOSS', 'FireRed', 'Qwen'}
    issues = SubtitleQCEngine().analyze(p).for_cue(cue.id)
    assert any(issue.issue_type == 'current_projection_difference' for issue in issues)
    assert not any(issue.issue_type == 'model_disagreement' for issue in issues)
    assert p.asr_evidence == before and cue.text == '他会遇到一个什么样的情况'
    reopened = load_project(save_project(p, tmp_path/'new48-tail.2byteproj'))
    assert reopened.cues[-1].text == cue.text
    assert reopened.studio_state['cue_statuses'][cue.id] == 'done'
    assert reopened.asr_evidence == before
    assert ReviewEvidenceAggregator().aggregate(reopened, reopened.cues[-1]).requires_review


def test_real_new48_one_candidate_three_supporters_remains_partial_and_needs_review():
    p = _real_new48_tail_project()
    cue = next(c for c in p.cues if c.id == '3')
    candidates = review_candidates(p, cue)
    assert len(candidates) == 1
    assert set(candidates[0].sources) == {'Current', 'MOSS', 'FireRed', 'Qwen'}
    aggregate = ReviewEvidenceAggregator().aggregate(p, cue)
    assert aggregate.models_agree_text and aggregate.requires_review
    assert aggregate.source_coverage['partial'] and aggregate.source_coverage['minimum_count'] == 0
    assert not aggregate.source_coverage['conflict']
    assert '局部来源覆盖' in format_model_evidence_coverage(aggregate.hypotheses)['headline']


def test_current_text_does_not_vote_in_model_majority_or_acoustic_confidence():
    cue = SimpleNamespace(id='vote', text='后撤', speaker_id='', start_ms=0, end_ms=1000)
    rows = [dict(model=model, text=text, start_ms=0, end_ms=1000)
        for model, text in [('MOSS', '前进'), ('FireRed', '后撤'), ('Qwen', '后撤')]]
    aggregate = ReviewEvidenceAggregator().aggregate(cue, rows)
    assert aggregate.model_majority == .667
    row = evidence(); row.pop('qwen_asr_text'); row.pop('qwen_text'); row['confidence'] = .6
    p = project(row)
    candidates = review_candidates(p, p.cues[0])
    assert set(candidates[0].sources) == {'Current', 'MOSS', 'FireRed'}
    assert any(issue.issue_type == 'low_confidence' for issue in SubtitleQCEngine().analyze(p).for_cue('cue'))


def test_real_gui_audit_selects_partial_same_text_and_actual_tail_projection_difference():
    from twobyteasr.acceptance.asr_evidence_audit import _review_cases
    p = _real_new48_tail_project()
    cases = _review_cases(p)
    assert [(name, cue.id) for name, cue in cases] == [('agreement', '3'), ('conflict', '1'), ('tail-projection', '48')]
    assert ReviewEvidenceAggregator().aggregate(p, cases[0][1]).requires_review
    assert ReviewEvidenceAggregator().aggregate(p, cases[1][1]).source_coverage['conflict']
    # The same cue ID and sentence can already have complete projected words
    # in an edited project. The audit must not invent a tail defect there.
    p.cues[-1].end_ms = 67600
    assert 'tail-projection' not in [name for name, cue in _review_cases(p)]


def test_legacy_serialized_confident_statistics_are_not_reused_for_tail_projection():
    from twobyteasr.subtitle_rules.studio_review import cached_review_risks, store_review_risks
    p = _real_new48_tail_project()
    legacy = {'48': {'level': 'confident', 'score': 0, 'reasons': []}}
    p.studio_state['review_risks'] = deepcopy(legacy)
    assert cached_review_risks(p) == {}
    store_review_risks(p)
    assert cached_review_risks(p)['48']['level'] != 'confident'
    assert p.studio_state['review_risks'] == legacy


def test_real_new48_normal_open_hydration_preserves_partial_word_scope_and_tail_review(tmp_path):
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    from twobyteasr.acceptance.asr_evidence_audit import _review_cases
    p = _real_new48_tail_project()
    raw = deepcopy(p.asr_evidence)
    before = {cue.id: cue_source_hypotheses(p, cue) for cue in p.cues}
    assert ensure_independent_captions(p)
    for cid in ('3', '48'):
        cue = next(c for c in p.cues if c.id == cid)
        observations = cue_source_hypotheses(p, cue)
        assert [(r['model'], r['text'], r['start_ms'], r['end_ms']) for r in observations] == [
            (r['model'], r['text'], r['start_ms'], r['end_ms']) for r in before[cid]]
        aggregate = ReviewEvidenceAggregator().aggregate(p, cue)
        assert aggregate.requires_review and aggregate.source_coverage['partial']
        assert aggregate.source_coverage['minimum_count'] == 0
    assert ('tail-projection', '48') in [(name, cue.id) for name, cue in _review_cases(p)]
    assert p.asr_evidence == raw
    reopened = load_project(save_project(p, tmp_path/'normal-open-tail.2byteproj'))
    assert [(name, cue.id) for name, cue in _review_cases(reopened)] == [(name, cue.id) for name, cue in _review_cases(p)]


def test_real_new48_missing_qwen_confidence_is_not_a_zero_percent_qc_risk():
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    p = _real_new48_tail_project()
    row = p.asr_evidence['segment:50']
    assert row['qwen_confidence'] == 0 and 'qwen_confidence_available' not in row
    ensure_independent_captions(p)
    cue = next(c for c in p.cues if c.id == '48')
    aggregate = ReviewEvidenceAggregator().aggregate(p, cue)
    assert aggregate.requires_review and aggregate.source_coverage['current_text_supported'] is False
    assert {r['model'] for r in aggregate.hypotheses} == {'moss', 'firered', 'qwen3-asr'}
    assert all(r['confidence'] is None for r in aggregate.hypotheses)
    assert not any(issue.issue_type == 'low_confidence' for issue in SubtitleQCEngine().analyze(p).for_cue(cue.id))


def test_real_new48_independent_move_and_ripple_preserve_original_tail_scope(tmp_path):
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions, shift_caption, ripple_caption_range
    p = _real_new48_tail_project()
    raw = deepcopy(p.asr_evidence)
    cue = next(c for c in p.cues if c.id == '48')
    original = cue_source_hypotheses(p, cue)
    ensure_independent_captions(p)
    cue = next(c for c in p.cues if c.id == '48')
    shift_caption(p, cue, 5000)
    ripple_caption_range(p, 10000, 10500)
    cue = next(c for c in p.cues if c.id == '48')
    moved = cue_source_hypotheses(p, cue)
    assert {row['text'] for row in moved} == {'他会遇到一个什么样的'}
    assert [(r['start_ms'], r['end_ms']) for r in moved] == [(r['start_ms']+4500, r['end_ms']+4500) for r in original]
    assert all(65817 <= r['source_start_ms'] < r['source_end_ms'] <= 67233 for r in moved)
    assert ReviewEvidenceAggregator().aggregate(p, cue).requires_review
    assert p.asr_evidence == raw
    reopened = load_project(save_project(p, tmp_path/'moved-tail.2byteproj'))
    assert cue_source_hypotheses(reopened, reopened.cues[-1]) == moved
