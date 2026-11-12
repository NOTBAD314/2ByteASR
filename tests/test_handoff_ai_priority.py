"""User-visible invariants for the ace6 handoff and accepted AI boundaries."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication
import subtitle_core as core
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project, load_project
from twobyteasr.subtitle_rules.display_timing import protect_project_display_tails, project_display_tail_plan
from twobyteasr.subtitle_rules.grouping_quality import quality_for_segments
from twobyteasr.subtitle_rules.ai_boundary_policy import inspect, minimal_fallback
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context


@pytest.fixture(autouse=True)
def scope():
    app=QApplication.instance() or QApplication([])
    with language_scope('zh'),activate_runtime_context(RuntimeContext(task_language='zh',enable_domain_terms=False),legacy=core):
        yield app


def project():
    return SubtitleProject(media=StudioMedia('',duration_ms=200000),speakers=[StudioSpeaker('A'),StudioSpeaker('B')],
        cues=[StudioCue('a',109200,111150,'和这个月光合作的一个博弈了',speaker_id='A'),
              StudioCue('b',111033,113117,'我真觉得可以开香槟了',speaker_id='B')])


def test_117ms_unknown_handoff_closes_before_fixed_layout(tmp_path):
    from twobyteasr.caption_style.collision_layout import project_layout_schedule
    from twobyteasr.rendering.ass_compiler import compile_ass
    p=project();evidence=deepcopy(p.asr_evidence)
    before=project_layout_schedule(p)
    assert before['b'][0][2]!=0
    audit=protect_project_display_tails(p)
    assert p.cues[0].end_ms==p.cues[1].start_ms==111033
    assert audit[0]['classification']=='editorial_handoff'
    assert audit[0]['source_classification']=='uncertain'
    assert audit[0]['display_adjustment_ms']==-117
    assert p.cues[0].transform['display_handoff']['acoustic_overlap_claim']=='unchanged'
    plan=project_layout_schedule(p)
    assert plan['b']==[(111033,113117,0.)]
    assert project_display_tail_plan(p)[0]=={}
    assert p.asr_evidence==evidence
    path=save_project(p,tmp_path/'handoff.2byteproj');again=load_project(path)
    assert project_layout_schedule(again)==plan
    assert compile_ass(again)==compile_ass(p)


@pytest.mark.parametrize('case',['reply','contained','long','third','locked','manual_position','protected'])
def test_real_multiline_or_manual_overlap_is_preserved(case):
    p=project()
    if case=='reply':p.cues[1].text='好'
    if case=='contained':p.cues[1].end_ms=111100
    if case=='long':p.cues[1].start_ms=110800
    if case=='third':p.cues.append(StudioCue('c',111000,111100,'第三人插话',speaker_id='C'))
    if case=='locked':p.cues[0].transform['timing_locked']=True
    if case=='manual_position':p.cues[1].transform['position_locked']=True
    if case=='protected':p.cues[0].transform['preserve_overlap']=True
    before=deepcopy(p.cues);protect_project_display_tails(p)
    assert p.cues==before


def test_one_bad_ai_piece_never_borrows_accepted_neighbour():
    from twobyteasr.subtitle_rules.grouping_quality import cues_from_quality
    pieces=['哎其实广东工业大学这边','每次抓前期续航的机会都非常好啊']
    rows=[core.SpeechSegment(i+1,i*2,(i+1)*2,text,.9,[],speaker='A') for i,text in enumerate(pieces)]
    boundaries=[len(pieces[0]),sum(map(len,pieces))]
    q=quality_for_segments(rows)
    assert inspect(q,boundaries)==[dict(kind='length',start=11,end=26,length=15)]
    cuts,receipts=minimal_fallback(q,boundaries)
    assert 11 in cuts and all(r['content_start']==11 for r in receipts)
    cues,actual,issues=cues_from_quality(rows,cuts,repair=False)
    assert cues[0].text==pieces[0] and actual==cuts and not issues
    assert not any('这边每次抓' in c.text for c in cues)


@pytest.mark.parametrize('text',['吃得下去吗','叠的太舒服了','让我们把最热烈的掌声送给他们'])
def test_valid_ai_piece_is_constructed_without_repair(text):
    from twobyteasr.subtitle_rules.grouping_quality import cues_from_quality
    row=core.SpeechSegment(1,0,2,text,.9,[],speaker='A')
    with patch('twobyteasr.subtitle_rules.grouping_quality.BoundaryQuality.repair',side_effect=AssertionError('hidden repair')):
        cues,cuts,issues=cues_from_quality([row],[len(text)],repair=False)
    assert [c.text for c in cues]==[text] and cuts==[len(text)] and not issues


def test_current_is_not_independent_and_duplicate_model_does_not_vote():
    from twobyteasr.subtitle_rules.studio_qc import ASREvidenceRule, SubtitleQCEngine, QCEvidence
    p=project();p.cues=p.cues[:1];c=p.cues[0]
    row=dict(model='firered',text='和这个月光合奏的一个博弈了',comparison_text=c.text,
             start_ms=c.start_ms,end_ms=c.end_ms,speaker_id='A',reference='one')
    with patch('twobyteasr.recognition.asr_source_evidence.cue_source_hypotheses',return_value=(row,row)):
        qc=SubtitleQCEngine(rules=(ASREvidenceRule(),)).analyze(p)
    assert len(qc.issues)==1 and qc.issues[0].severity.value=='warning'


def test_short_response_not_an_error():
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine, TimelineRule
    p=project();p.cues=[StudioCue('reply',0,317,'好',speaker_id='A')]
    qc=SubtitleQCEngine(rules=(TimelineRule(),)).analyze(p)
    assert all(r.severity.value=='info' for r in qc.issues)


def test_bounded_hold_does_not_reclassify_preexisting_speech_overlap():
    from twobyteasr.subtitle_rules.display_continuity import VERSION
    p=project();a,b=p.cues
    a.start_ms,a.end_ms=0,2117;b.start_ms,b.end_ms=1000,3000
    a.transform['display_handoff']=dict(version=VERSION,base_display_interval_ms=[0,2000],display_interval_ms=[0,2117])
    p.cues.append(StudioCue('next',2117,4000,'同一轨道的完整后继字幕',speaker_id='A'))
    ends,report=project_display_tail_plan(p)
    pair=next(r for r in report['pairs_before'] if r['left']=='a' and r['right']=='b')
    assert pair['has_bounded_display_hold'] and not pair['hold_only_overlap']
    assert pair['classification']!='bounded_display_hold'
    assert 'a' not in ends


def test_preview_calls_editorial_choice_and_undo_keeps_original_words():
    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio.display_handoff_ui import DisplayHandoffPreview
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    p=project();ensure_independent_captions(p)
    p.generation_metadata['display_overlap_audit']={'status':'user_undone'}
    words_before=deepcopy(p.studio_state.get('caption_timeline',{}))
    class Page(QWidget):
        def __init__(self):
            super().__init__();self.project=p;self.undo_stack=QUndoStack(self)
        def _changed(self):pass
        def _show_studio_hint(self,text):pass
    page=Page();dialog=DisplayHandoffPreview(page)
    assert '编辑显示顺接' in dialog.table.item(0,4).text()
    with patch('twobyteasr.timeline.studio_caption_timeline.sync_caption_interval_words',side_effect=AssertionError('display choice changed word clock')):
        dialog.apply()
        assert p.cues[0].end_ms==111033
        assert p.cues[0].transform['display_handoff']['acoustic_overlap_claim']=='unchanged'
        page.undo_stack.undo();assert p.cues[0].end_ms==111150
        page.undo_stack.redo();assert p.cues[0].end_ms==111033
    assert p.studio_state.get('caption_timeline',{})==words_before
    page.close()


def test_rejected_blue_proposal_stays_diagnostic_without_suggestion():
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine,ASREvidenceRule
    from twobyteasr.subtitle_rules.current_issues import current_issue_view
    p=project();p.cues=p.cues[:1];p.cues[0].text='算无策步步为营';p.cues[0].evidence_refs=['r']
    p.asr_evidence={'r':{'speaker_id':'A','text':'算无策步步为营','caption_arbitration':{
        'terminology_polish':{'quality_state':'pending_rejected_edit_review','rejected_edits':[
            {'from':'步步','to':'Blue','rule_id':'catalog_without_local_support'}]}}}}
    p._qc_result=SubtitleQCEngine(rules=(ASREvidenceRule(),)).analyze(p)
    view=current_issue_view(p)
    assert not view.by_cue
    assert any(r.kind=='rejected_model_proposal' and not r.suggestions for r in view.diagnostics[p.cues[0].id])


def test_final_counts_use_same_hold_classification():
    from twobyteasr.subtitle_rules.timing import refresh_final_cue_reviews
    from twobyteasr.recognition.run_context import get_runtime_context
    context=get_runtime_context();context._display_overlap_audit=[dict(classification='bounded_display_hold')]
    cues=[core.SubtitleCue(1,0,1,'保留文字',speaker='A')];segments=[]
    from twobyteasr.subtitle_rules.display_timing import runtime_display_signature
    context._display_overlap_signature=runtime_display_signature(cues,segments)
    events=[]
    with patch.object(core,'record_run_event',side_effect=lambda event,**kw:events.append((event,kw))):
        refresh_final_cue_reviews(cues,segments,legacy=core)
    assert next(kw for event,kw in events if event=='final_subtitle_validation')['overlap_classification_counts']=={'bounded_display_hold':1}


def test_hide_delete_and_undo_replan_only_local_display_state():
    from twobyteasr.projects.studio_runtime_state import state_for,DirtyDomain
    from twobyteasr.subtitle_rules.display_timing import reconcile_editorial_handoffs
    p=project();protect_project_display_tails(p)
    runtime=state_for(p)
    # A separate caption must keep its unrelated confirmation and interval.
    p.studio_state['current_issue_decisions']={'unrelated':{'status':'resolved','input_version':'same'}}
    before=deepcopy(p.studio_state['current_issue_decisions'])
    with runtime.transaction(p,action_id='hide',dirty=DirtyDomain.CUE_MODEL,affected_cue_ids=('b',)):
        p.cues[1].transform['hidden']=True
    assert p.cues[0].end_ms==111150
    with runtime.transaction(p,action_id='show',dirty=DirtyDomain.CUE_MODEL,affected_cue_ids=('b',)):
        p.cues[1].transform.pop('hidden')
    assert p.cues[0].end_ms==111033
    incoming=p.cues[1]
    with runtime.transaction(p,action_id='delete',dirty=DirtyDomain.CUE_MODEL,affected_cue_ids=('b',)):
        p.cues.remove(incoming)
    assert p.cues[0].end_ms==111150
    with runtime.transaction(p,action_id='undo delete',dirty=DirtyDomain.CUE_MODEL,affected_cue_ids=('b',)):
        p.cues.append(incoming)
    assert p.cues[0].end_ms==111033
    assert p.studio_state['current_issue_decisions']==before
    assert reconcile_editorial_handoffs(p,('b',))==set()


def test_local_fallback_avoids_inferred_quantity_noun_seam_without_changing_ai_policy():
    from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
    text='七层的寒音蛇加上非常多连击的月光合作'
    q=BoundaryQuality(text)
    final,receipt=minimal_fallback(q,[len(text)])
    pieces=q.index.pieces(final)
    assert ''.join(pieces)==text and all(len(p)<=14 for p in pieces)
    assert not any(a.endswith('非常多') and b.startswith('连击') for a,b in zip(pieces,pieces[1:]))
    assert all(r['content_start']==0 and r['content_end']==len(text) for r in receipt)


def test_previous_rule_confirmation_survives_rename_but_real_evidence_changes_reopen(tmp_path):
    from twobyteasr.subtitle_rules.current_issues import (digest,DECISIONS,prepare_legacy_scopes,current_issue_view,invalidate)
    from twobyteasr.subtitle_rules.studio_qc import (QCEvidence,QCIssue,QCResult,QCCategory,QCSeverity,model_evidence,_compact,normalize_spoken_text)
    p=project();p.cues=p.cues[:1];c=p.cues[0];c.evidence_refs=['r']
    p.asr_evidence={'r':dict(start_ms=c.start_ms,end_ms=c.end_ms,speaker_id='A',
        moss_text=c.text,qwen_asr_text='和这个月光合奏的一个博弈了')}
    evidence=model_evidence(p,c)
    distinct={_compact(c.text):QCEvidence('Current',c.text,'project')}
    for e in evidence:
        if not e.context_only and normalize_spoken_text(e.text)!=normalize_spoken_text(c.text):distinct.setdefault(_compact(e.text),e)
    key=digest([p.project_id,c.id,c.speaker_id,'original','zh','model_disagreement','asr_evidence',()])
    p.studio_state[DECISIONS]={key:dict(status='resolved',input_version=digest([c.text]),
        evidence_version=digest([(e.label,e.source,e.text,e.context_only) for e in distinct.values()]))}
    p.generation_metadata['language']={'code':'zh'}
    prepare_legacy_scopes(p)
    issue=QCIssue('local_model_correction',QCSeverity.WARNING,QCCategory.ASR,c.id,'候选','局部候选',
        tuple(e for e in evidence if e.source=='qwen3-asr'),source='asr_evidence')
    p._qc_result=QCResult({c.id:(issue,)})
    assert not current_issue_view(p).for_cue(c.id)
    p=load_project(save_project(p,tmp_path/'legacy-confirmed.2byteproj'))
    p._qc_result=QCResult({c.id:(issue,)})
    assert not current_issue_view(p).for_cue(c.id)
    before=deepcopy(p.studio_state[DECISIONS])
    invalidate(p);assert not current_issue_view(p).for_cue(c.id)
    p.asr_evidence['r']['end_ms']-=100
    invalidate(p);assert current_issue_view(p).for_cue(c.id)
    assert p.studio_state[DECISIONS]==before
