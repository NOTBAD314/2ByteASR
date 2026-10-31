import copy
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.recognition.current_review import current_review, DECISIONS_KEY
from twobyteasr.recognition.processing_recovery import effective_report, failure_summary
from twobyteasr.recognition.recognition_outcome import normalize_recognition_outcome


def fixture():
    p = SubtitleProject(StudioMedia('', duration_ms=6000), speakers=[StudioSpeaker('s')],
        cues=[StudioCue('stable', 0, 3000, '这是一条需要确认的字幕', speaker_id='s', evidence_refs=['segment:7'])])
    p.asr_evidence['segment:7'] = dict(start_ms=0, end_ms=3000, text=p.cues[0].text,
        caption_arbitration={'processing_identity': {'polish_record_id': 42},
                             'terminology_polish': {'input_text': p.cues[0].text}})
    issue = dict(category='多模型争议', severity='review', segment_id=42, text=p.cues[0].text, timestamp=0)
    r = dict(job_id='job', status='degraded_success', result={'cue_count': 1, 'outputs': {'project': 'saved'}},
        review_items=[issue, dict(issue, detail='同一任务再次回调'), dict(issue, category='术语召回缺口')])
    return p, r


def test_current_items_deduplicate_by_business_identity_and_optional_suggestions_are_separate():
    p, r = fixture()
    before = copy.deepcopy(r)
    for _ in range(3):
        value = current_review(p, r)
        assert len(value['items']) == 1 and len(value['suggestions']) == 1
        assert value['items'][0]['cue_ids'] == ['stable']
    effective_report(p, r)
    assert r == before


def test_current_readability_uses_the_saved_content_language_policy():
    p,r=fixture();r['review_items']=[]
    p.cues[0].text='Che bella gara oggi.';p.cues[0].end_ms=1000
    p.generation_metadata['language']={'code':'it'}
    assert not current_review(p,r)['items']
    p.generation_metadata['language']={'code':'zh'}
    assert any(row['category']=='阅读较快' for row in current_review(p,r)['items'])


def test_decision_retires_only_its_current_input_version_without_fake_text_edit():
    p, r = fixture()
    issue = current_review(p, r)['items'][0]
    p.studio_state[DECISIONS_KEY] = {issue['issue_id']: dict(status='ignored', input_version=issue['input_version'])}
    assert not current_review(p, r)['items']
    assert not p.edit_history
    p.cues[0].text += '已变化'
    assert len(current_review(p, r)['items']) == 1
    p.cues.clear()
    assert not current_review(p, r)['items']


def test_safe_protection_is_not_retryable_but_structural_failure_survives():
    p, r = fixture()
    r['polishing_summary'] = dict(fallback_ids=[42], fallback_cues=1, failure_records={'42':'semantic_validation'})
    detail = p.asr_evidence['segment:7']['caption_arbitration']['terminology_polish']
    detail.update(response_state='fallback', validation_failure={'reason':'source_quote_not_found'})
    assert failure_summary(p, r)['failed_tasks'] == 0
    detail['validation_failure'] = {'reason':'ambiguous_source_quote'}
    assert failure_summary(p, r)['retryable_tasks'] == 1


def test_green_completion_requires_current_usable_structure_and_preserves_save_error():
    p, r = fixture()
    r['polishing_summary'] = dict(fallback_ids=[42], fallback_cues=1)
    result = effective_report(p, r)
    assert result['polishing_summary']['count_scope'] == 'current_processing_task'
    assert result['polishing_summary']['fallback_batches'] is None
    assert normalize_recognition_outcome(result).core_status == 'completed'
    assert normalize_recognition_outcome(result).result_usable
    r['events'] = [{'event':'studio_project_save_failed', 'error':'disk full'}]
    assert normalize_recognition_outcome(effective_report(p, r)).core_status == 'failed'
