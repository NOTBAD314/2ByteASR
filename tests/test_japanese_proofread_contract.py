import copy,json
from types import SimpleNamespace
import pytest
import subtitle_core
from twobyteasr.subtitle_rules.polishing import _validate_new_suspects,_validate_polish_response,CueValidationFailures
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia
from twobyteasr.studio.subtitle_text_targets import text_entries
from twobyteasr.glossary.recognition_review_import import existing_review
from twobyteasr.glossary.terminology import GlossarySnapshot

def test_suspect_id_and_cue_id_have_separate_types_and_exact_repair():
    row={'id':'n433-1','start':0,'end':4,'surface':'あ寝具せ','evidence':'独立参考缺少后半，需要试听'}
    scoped,unassigned=_validate_new_suspects([row],{22:'別の句',433:'あ寝具せ'})
    assert not unassigned and scoped[433][0]['cue_id']==433
    assert scoped[433][0]['suspect_id']=='n433-1'
    assert scoped[433][0]['association_basis']=='unique_exact_primary_span'
    scoped,unassigned=_validate_new_suspects([row],{433:'あ寝具せ',22:'あ寝具せ'})
    assert not scoped and unassigned[0]['validation_state']=='invalid'
    scoped,unassigned=_validate_new_suspects([dict(row,cue_id=22)],{433:'あ寝具せ',22:'あ寝具せ'})
    assert not unassigned and scoped[22][0]['cue_id']==22

def test_reference_edit_already_satisfied_only_at_requested_primary_location():
    edit={'from':'一門打人','to':'一網打尽','start':0,'end':4,'type':'asr_correction'}
    q=CueValidationFailures()
    value={'checked_ids':[326],'cues':[{'id':326,'edits':[edit]}]}
    result=_validate_polish_response(value,[SpeechSegment(326,0,2,'一網打尽にするぞ',.78,[])],1,q)
    assert not q and result['cues'][0]['edits']==[]
    assert q.completed[326][0]['rule_id']=='current_span_already_satisfied'
    q=CueValidationFailures()
    result=_validate_polish_response(value,[SpeechSegment(326,0,2,'後で一網打尽にするぞ',.78,[])],1,q)
    assert not q.completed and q.protected[326][0]['rule_id']=='source_quote_not_found'
    q=CueValidationFailures()
    shortened={'checked_ids':[326],'cues':[{'id':326,'edits':[dict(edit,to='一網')]}]}
    _validate_polish_response(shortened,[SpeechSegment(326,0,2,'一網打尽にするぞ',.78,[])],1,q)
    assert not q.completed  # a target prefix alone does not satisfy the submitted span

def project():
    p=SubtitleProject(StudioMedia('missing.mp4',duration_ms=5000),cues=[
        StudioCue('final-a',100,1400,'あ寝具せ','S1'),StudioCue('final-b',1500,2900,'もう行くよ','S2')])
    p.generation_metadata['language']={'code':'ja'}
    p.generation_metadata['segmentation_source_spans']={'cues':{'final-a':{'parts':[
        {'source_id':433,'char_start':0,'char_end':4,'raw_text':'あ寝具せ','index_unit':'python_unicode_codepoint'}]}}}
    p.asr_evidence={'segment:433':{'caption_arbitration':{'terminology_polish':{
        'input_text':'あ寝具せ','final_text':'あ寝具せ','new_suspects':[]},
        'independent_input_evidence':{'primary':'あ寝具せ','qwen':'あ寝癖'}}}}
    p.generation_metadata['polishing_summary']={'term_context':{'unassigned_new_suspects':[{'batch_index':17,'rows':[
        {'id':'n433-1','start':0,'end':4,'surface':'あ寝具せ','evidence':'独立参考と異なり、试听确认'}]}]}}
    return p

def test_recognition_pending_projects_by_source_span_not_final_array_index():
    p=project();before=copy.deepcopy(p)
    result=existing_review(p,text_entries(p,mode='original'))
    assert result.receipt['pending_rows'][0]['cue_id']=='final-a'
    assert result.receipt['pending_rows'][0]['source_segment_id']==433
    assert not result.hits and p.cues==before.cues
    p.cues[0].text='用户改过的正文'
    result=existing_review(p,text_entries(p,mode='original'))
    assert not result.receipt['pending_rows'] and result.receipt['unassigned']

def test_no_glossary_original_and_translation_review_with_dialogue_and_pending(monkeypatch):
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual
    from twobyteasr.studio.subtitle_text_targets import review_project
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    import twobyteasr.providers.ai_providers as providers
    seen=[]
    class Provider:
        provider='test';model='test';protocol='openai';max_output_tokens=4096;supports_thinking=False
        def complete(self,messages,**kwargs):
            data=json.loads(messages[-1]['content']);seen.append(data)
            a,b=data['targets'][:2]
            return {'changes':[{'target_id':b['target_id'],'original':b['target_text'],
                'replacement':b['target_text'].replace('行く','逝く').replace('已有中文','已有译文'),
                'reason':'离线字词替换夹具，需确认'}],
                'suspects':[{'target_id':a['target_id'],'original':a['target_text'],
                    'issue_type':'proper_name','reason':'两份参考有具体分歧，需要试听'}]}
    monkeypatch.setattr(providers,'provider_for_stage',lambda *a,**k:Provider())
    p=project()
    for cue in p.cues:set_manual(p,cue.id,'已有中文'+cue.id)
    for mode in ('original','translation'):
        entries=text_entries(p,mode=mode)
        view=review_project(p,entries)
        result=preview_glossary_correction(view,[e.key for e in entries],GlossarySnapshot(),{})
        assert len(seen[-1]['dialogue_context'])==2
        assert [r['speaker_id'] for r in seen[-1]['dialogue_context']]==['S1','S2']
        assert result.receipt['successful_cues']==2 and result.receipt['run_state']=='completed'
        assert result.hits and result.receipt['pending_rows'][0]['state']=='speech_review'
    assert seen[-1]['targets'][0]['source_reference']=='あ寝具せ'

def test_context_revision_changes_with_neighbor_identity_not_input_array_order():
    from twobyteasr.glossary.translation_review import review_context_versions
    p=project();entries=text_entries(p,mode='original');before=review_context_versions(p,entries)
    p.cues.reverse();assert review_context_versions(p,entries)==before
    p.cues[0].speaker_id='other'
    assert review_context_versions(p,entries)!=before


def test_retry_or_cancel_without_libraries_preserves_existing_anchored_proposals(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage,_StandalonePage,_issue
    from twobyteasr.glossary.studio_glossary_service import GlossaryReviewPreview
    app=QApplication.instance() or QApplication([]);p=project()
    w=GlossaryProofreadPage(SimpleNamespace(studio_page=None));w._project=p
    w._project_path=str(tmp_path/'work.2byteproj');w._standalone=_StandalonePage(p)
    w._bind_stack(w._standalone.session.undo_stack);w._build_rows(p,start_checks=False)
    row=w._by_id['final-a'];row['issues']=[_issue('ai_review',(0,4),'あ寝具せ','あ寝癖',checked=False)]
    monkeypatch.setattr(w,'_persist_soon',lambda *a:None);calls=[]
    monkeypatch.setattr(w,'_run',lambda *a,**k:calls.append(a))
    try:
        w._restart_review(True)
        assert row['issues'][0]['replacement']=='あ寝癖' and calls==[(True,None)]
        failed=GlossaryReviewPreview((),{'request_errors':['offline injected failure'],'successful_cues':0,
            'fallback_cues':2,'failed_cues':[{'cue_id':'final-a'}]})
        w._show_result(failed,p,True,{e.key:e.text for e in text_entries(p,mode='original')})
        assert row['issues'][0]['replacement']=='あ寝癖' and w.retry_ai_button.isVisibleTo(w)
        assert 'final-a' in w._failed_review_targets
        from twobyteasr.studio.subtitle_text_targets import bind_occurrence
        from twobyteasr.studio.studio_text_tools import TextOccurrence
        entry=text_entries(p,mode='original')[0]
        hit=bind_occurrence(TextOccurrence(entry.key,entry.start_ms,entry.text,'あ寝癖',(0,4),source='translation_ai'),entry)
        success=GlossaryReviewPreview((hit,),{'request_errors':[],'successful_cues':2,'fallback_cues':0})
        w._show_result(success,p,True,{e.key:e.text for e in text_entries(p,mode='original')})
        assert any(i.get('ai_generated') for i in row['issues'])
        w._clear_term_issues()
        assert any(i.get('ai_generated') and i['replacement']=='あ寝癖' for i in row['issues'])
        from twobyteasr.glossary.proofread_retention import row_record,put_records,restore_row
        put_records(p,{row['cue_id']:row_record(row)})
        restored=dict(row,issues=[]);restore_row(p,restored)
        assert restored['issues'][0]['ai_generated']
        import time
        called=[]
        w._window._prepare_glossary_for_task=lambda:False
        w.ai_stand_in=lambda *args,**kw:(called.append(True) or success)
        GlossaryProofreadPage._run(w,True)
        until=time.perf_counter()+5
        while w.checks_running() and time.perf_counter()<until:app.processEvents();time.sleep(.005)
        assert called==[True]  # unrelated unsaved libraries cannot block general review
    finally:
        w._save_timer.stop();w._rematch_timer.stop();w.shutdown();w.deleteLater();app.processEvents()
