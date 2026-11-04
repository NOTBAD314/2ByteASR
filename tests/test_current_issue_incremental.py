"""Local review refreshes reuse other cues but equal a complete rebuild."""
from dataclasses import replace
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.subtitle_rules.studio_qc import QCResult,QCIssue,QCCategory,QCSeverity
from twobyteasr.subtitle_rules import current_issues as issues

def project(count=1000):
    p=SubtitleProject(StudioMedia('',duration_ms=count*4000),
        cues=[StudioCue(str(i),i*4000,i*4000+3000,'第'+str(i)+'条已有字幕',speaker_id='A') for i in range(count)])
    p.validate();p.generation_metadata={'language':{'code':'ja'},'translations':{c.id:'A distinct translation '+c.id for c in p.cues}}
    p._qc_result=QCResult({c.id:(QCIssue('high_cps',QCSeverity.WARNING,QCCategory.READABILITY,c.id,
        '阅读速度','请检查',source='timing'),) for c in p.cues})
    return p

def same(a,b):
    assert a.by_cue==b.by_cue and a.diagnostics==b.diagnostics
    assert a.records==b.records and a.levels==b.levels and a.counts()==b.counts()

def test_one_text_edit_does_not_reclassify_screen_off_issues(monkeypatch):
    p=project();before=issues.current_issue_view(p)
    calls=[];original=issues._language
    def language(*args):calls.append(args[1].id);return original(*args)
    monkeypatch.setattr(issues,'_language',language)
    p.cues[3].text='这条正文改过了';issues.invalidate(p,{'3'})
    after=issues.current_issue_view(p)
    assert len(calls)<=4 and set(calls)<={'3'}
    assert after.for_cue('999')==before.for_cue('999')
    old=next(r for r in before.records if r.cue_id=='999')
    assert next(r for r in after.records if r.cue_id=='999') is old
    issues.invalidate(p);same(after,issues.current_issue_view(p))

def test_incremental_qc_result_and_translation_refresh_equal_full_view():
    p=project(30);issues.current_issue_view(p)
    rows=dict(p._qc_result.issues_by_cue)
    rows['7']=(QCIssue('invalid_time',QCSeverity.CRITICAL,QCCategory.TIMELINE,'7','时间错误','本条新问题'),)
    p._qc_result=QCResult(rows);p.generation_metadata['translations']['7']='更新后的译文'
    issues.invalidate(p,{'7'})
    after=issues.current_issue_view(p);assert after.level('7')=='high'
    issues.invalidate(p);same(after,issues.current_issue_view(p))

def test_overlap_dependant_uses_the_current_previous_speaker():
    p=project(3);p.cues[1].speaker_id='B'
    p._qc_result=QCResult({'1':(QCIssue('overlap',QCSeverity.WARNING,QCCategory.TIMELINE,'1',
        '重叠','与前条重叠',fix_metadata={'previous_cue_id':'0'}),)})
    before=issues.current_issue_view(p)
    assert not any(r.kind=='overlap' for r in before.for_cue('1'))
    p.cues[0].speaker_id='B';issues.invalidate(p,{'0'})
    after=issues.current_issue_view(p)
    assert any(r.kind=='overlap' for r in after.for_cue('1'))
    issues.invalidate(p);same(after,issues.current_issue_view(p))

def test_boundary_diagnostics_keep_original_rule_order_after_local_edit():
    p=project(8)
    p.studio_state['caption_timeline']={'version':1,'instances':{'2':{'needs_review':'保留边界证据'},'6':{'needs_review':'另一条证据'}}}
    issues.current_issue_view(p)
    p.cues[2].text='改后的第二条';issues.invalidate(p,{'2'})
    after=issues.current_issue_view(p)
    issues.invalidate(p);same(after,issues.current_issue_view(p))


def test_worker_issue_cache_roundtrips_and_preserves_row_identity():
    import pickle,copy
    p=project(10);prepared=issues.prepare_issue_cache(p)
    qc,received=pickle.loads(pickle.dumps((p._qc_result,prepared),protocol=5))
    target=copy.deepcopy(p);target._qc_result=qc;issues.invalidate(target)
    assert issues.adopt_issue_cache(target,qc,received)
    assert issues.current_issue_view(target) is received['view']
    same(received['view'],issues.current_issue_view(p))
    assert received['rows'][('0','original','high_cps','timing',())][0] is qc.issues_by_cue['0'][0]


def test_worker_issue_cache_does_not_overwrite_new_review_decisions():
    p=project(10);prepared=issues.prepare_issue_cache(p);view=issues.current_issue_view(p)
    p.studio_state[issues.DECISIONS]={'new-decision':{'status':'ignored','input_version':'new'}}
    assert not issues.adopt_issue_cache(p,p._qc_result,prepared)
    assert p.studio_state[issues.DECISIONS]['new-decision']['status']=='ignored'
