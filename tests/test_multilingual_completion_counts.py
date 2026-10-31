from twobyteasr.recognition.recognition_outcome import normalize_recognition_outcome


def test_review_counts_are_stable_cue_and_category_not_event_count():
    items=[{'cue_id':'6','category':'校对回退','severity':'warning','detail':'bad patch'},
           {'cue_id':'6','category':'校对回退','severity':'warning','detail':'same issue later'},
           {'segment_id':2,'category':'术语召回缺口','severity':'review'},
           {'cue_id':'8','category':'翻译未完成','severity':'warning','resolved':True}]
    outcome=normalize_recognition_outcome({'status':'degraded_success','review_items':items,
        'review_severity_counts':{'review':9119,'warning':100},
        'result':{'cue_count':1392,'outputs':{'project':'saved.2byteproj'}},
        'polishing_summary':{'success_cues':650,'fallback_cues':0}})
    assert outcome.review_issue_count==1 and outcome.review_affected_cues==1
    assert outcome.accepted_edits==0


def test_missing_glossary_candidates_do_not_become_foreign_word_errors():
    from types import SimpleNamespace
    from subtitle_core import SpeechSegment
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.glossary.terminology_support import recall_gaps
    library=SimpleNamespace(id='example',revision=1,terms=[SimpleNamespace(canonical='Ferrari',aliases=(),confirmed=True)])
    snapshot=SimpleNamespace(libraries=[library])
    with activate_runtime_context(RuntimeContext(task_language='it')):
        gaps=recall_gaps([SpeechSegment(1,0,2,'la vettura è molto veloce',.9,[])],[],snapshot)
    assert gaps==[]
def test_invalid_optional_metadata_without_cue_ownership_is_diagnostic():
    from twobyteasr.recognition.recognition_outcome import review_severity
    item={'review_scope':'unassigned_batch_metadata','text':'','unassigned_new_suspects':[
        {'validation_state':'invalid','validation_errors':['invalid_cue_id_type']}]}
    assert review_severity(item)=='info'
    assert review_severity({'category':'说话人需要确认','cue_id':'c1','severity':'review'})=='review'


def test_resolved_stage_attempt_is_not_a_current_failure_diagnosis():
    from twobyteasr.recognition.run_diagnosis import diagnose_run
    payload={'status':'success','result':{'cue_count':1},'polishing_summary':{'success_cues':1,'fallback_cues':0},
        'events':[{'event':'polishing_api_fallback','category':'semantic_validation'}]}
    assert any(item.issue.id=='ai_bad_output' for item in diagnose_run(payload).findings)
    payload['_stage_recovery']={'failed_tasks':0}
    assert not any(item.issue.id in {'ai_bad_output','ai_partial_fallback'} for item in diagnose_run(payload).findings)

