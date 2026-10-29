"""Pending cleanup policy, async results, selection scope and plain term rows."""
import copy
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage, _StandalonePage, _issue, _StutterThread
from twobyteasr.glossary.proofread_policy import repetition_cleanup, issue_enabled
from twobyteasr.glossary.terminology import snapshot_from_pairs
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, save_project, load_project
from twobyteasr.studio.studio_text_tools import TextOccurrence

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def review(tmp_path):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,str(tmp_path/'qt'))
    p = SubtitleProject(StudioMedia('',duration_ms=20000),cues=[
        StudioCue('you',0,2000,'啊 这 有点 有点'),
        StudioCue('it',3000,5000,'它 它有什么很厉害的草系技能吗'),
        StudioCue('then',6000,8000,'那 那就很赚'),
        StudioCue('mixed',9000,11000,'那 那古龙很赚'),
    ])
    p.validate()
    w = GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    w._project = p
    w._project_path = str(tmp_path/'work.2byteproj')
    w._standalone = _StandalonePage(p)
    w._bind_stack(w._standalone.session.undo_stack)
    w._build_rows(p,start_checks=False)
    w.stutter_toggle.setChecked(True)
    for identity,span,original in [('you',(5,7),'有点'),('it',(0,1),'它'),('then',(0,1),'那'),('mixed',(0,1),'那')]:
        w._by_id[identity]['issues'] = [_issue('merge',span,original,'',checked=False)]
    w._by_id['mixed']['issues'].append(_issue('term',(3,5),'古龙','骨龙',checked=False))
    w._snapshot = snapshot_from_pairs([('古龙','骨龙')])
    w._apply_filter()
    yield w,p
    w._save_timer.stop();w._rematch_timer.stop()
    if hasattr(w,'_local_timer'):w._local_timer.stop()
    w.shutdown();w.close();w.deleteLater();APP.processEvents()


def test_disable_removes_repeats_from_every_effective_view_and_selection(review):
    w,p = review
    before = copy.deepcopy((p.cues,p.studio_state))
    w.filter_buttons['suggested'].setChecked(True);w._apply_filter();w._batch_select_all()
    assert w._batch_selected == {'you','it','then','mixed'}
    w.stutter_toggle.setChecked(False)
    assert w._batch_selected == {'mixed'}
    assert [w._rows[i]['cue_id'] for i in w.list.visible] == ['mixed']
    assert len(w._groups(w._by_id['mixed'])) == 1
    assert w._unresolved(w._by_id['mixed'])[0]['kind'] == 'term'
    assert '1' in w.batch_count.text() and w.proposal_counts()['proposals'] == 1
    assert w.list._visible_issues(w._by_id['you']) == []
    assert (p.cues,p.studio_state) == before
    w._batch_adopt()
    assert [c.text for c in p.cues] == [c.text for c in before[0]][:3]+['那 那骨龙很赚']
    w._undo()
    w._set_all(True)
    assert p.cues[0].text == before[0][0].text and p.cues[3].text == '那 那骨龙很赚'
    w.filter_buttons['all'].setChecked(True);w._apply_filter()
    assert len(w.list.visible) == 4


def test_toggle_is_preference_not_review_decision_and_reenable_does_not_revive_ignored(review):
    w,p = review
    w._batch_selected = {'then'};w._batch_ignore()
    decisions = copy.deepcopy(p.studio_state)
    w.stutter_toggle.setChecked(False)
    assert not w._stored_stutter()
    w.stutter_toggle.setChecked(True)
    assert w._stored_stutter() and p.studio_state == decisions
    assert w._unresolved(w._by_id['you'])
    assert not w._unresolved(w._by_id['then'])
    path = __import__('pathlib').Path(w._project_path)
    save_project(p,path);w._project=load_project(path)
    w._add_stutter_issues(w._project,{'then'}, {'then':[TextOccurrence('then',6000,'那','',(0,1),source='merge_suspect')]})
    w._apply_decisions(w._by_id['then'],{})
    assert not w._unresolved(w._by_id['then'])


def test_applied_cleanup_stays_in_text_after_disable(review):
    w,p = review
    issue = w._by_id['then']['issues'][0]
    issue['kind']='stutter';issue['default']=True
    w._toggle_issue('then',0)
    text = p.cues[2].text
    assert text != '那 那就很赚'
    w.stutter_toggle.setChecked(False)
    assert p.cues[2].text == text


@pytest.mark.parametrize('text,span,old,new,kind,expected',[
    ('啊 这 有点 有点',(5,7),'有点','','merge',True),
    ('它 它有什么很厉害的草系技能吗',(0,1),'它','','ai',True),
    ('那 那就很赚',(0,1),'那','','ai_review',True),
    ('有点有点强',(0,4),'有点有点','有点','ai',True),
    ('古龙古龙来了',(0,2),'古龙','骨龙','ai',False),
    ('卡卡西出场',(0,3),'卡卡西','卡西','term',False),
    ('它 它要来了',(0,1),'它','她','ai',False),
    ('这句话有点长',(3,5),'有点','','ai',False),
])
def test_policy_classifies_the_actual_edit(text,span,old,new,kind,expected):
    issue = _issue(kind,span,old,new,checked=False)
    assert repetition_cleanup(issue,text) is expected
    assert issue_enabled(issue,False,text) is (not expected)


def test_late_local_callback_cannot_add_cleanup_while_disabled(review):
    w,p = review
    w.stutter_toggle.setChecked(False)
    w._by_id['then']['issues'] = []
    w._add_stutter_issues(p,{'then'},{'then':[TextOccurrence('then',6000,'那','',(0,1),source='merge_suspect')]})
    assert not w._by_id['then']['issues']


def test_disabled_local_worker_skips_cleanup_but_keeps_independent_checks(review,monkeypatch):
    import twobyteasr.glossary.glossary_proofread as module
    import twobyteasr.recognition.transcript_evidence as evidence
    import twobyteasr.subtitle_rules.stutter_cleanup as cleanup
    w,p = review
    called=[]
    monkeypatch.setattr(module,'compute_stutter',lambda *_a,**_k:pytest.fail('cleanup disabled'))
    monkeypatch.setattr(evidence,'project_evidence',lambda *_a,**_k:called.append('evidence') or {})
    monkeypatch.setattr(cleanup,'consistency_occurrences',lambda *_a,**_k:called.append('consistency') or {})
    thread=_StutterThread(p,(),cleanup=False);thread.run()
    assert called == ['evidence','consistency']


def test_real_running_ai_thread_result_rechecks_current_setting(review,monkeypatch):
    w,p = review
    started,release = threading.Event(),threading.Event()
    result=SimpleNamespace(hits=[TextOccurrence('it',3000,'它','',(0,1),source='ai_accepted'),
        TextOccurrence('mixed',9000,'古龙','骨龙',(3,5),source='ai_accepted')],receipt={})
    def offline(*_a,**_k):
        started.set();release.wait(3);return result
    w.ai_stand_in=offline
    monkeypatch.setattr(w,'_selected_ids',lambda:('pairs',))
    monkeypatch.setattr(w,'_read_snapshot',lambda:None)
    w._run(True)
    deadline=time.monotonic()+2
    while not started.is_set() and time.monotonic()<deadline:QTest.qWait(5)
    assert started.is_set()
    w.stutter_toggle.setChecked(False);release.set()
    deadline=time.monotonic()+4
    while w._worker is not None and time.monotonic()<deadline:QTest.qWait(5)
    assert w._worker is None
    assert not w._groups(w._by_id['it'])
    assert any(i['replacement']=='骨龙' for i in w._unresolved(w._by_id['mixed']))
    w._batch_select_all();w._batch_adopt()
    assert p.cues[1].text == '它 它有什么很厉害的草系技能吗'


def test_term_rows_are_only_words_while_records_and_tooltips_keep_provenance(review):
    w,_ = review
    w._fill_terms()
    assert w.term_list.count() > 0
    for n in range(w.term_list.count()):
        item=w.term_list.item(n);record=item.data(Qt.UserRole+1)
        assert item.text() == record.canonical
        assert record.library_name in item.toolTip()
        assert item.data(Qt.UserRole) == record.canonical


def test_ai_canonical_name_correction_is_not_confused_with_cleanup(review):
    w,p=review
    p.cues[0].text='卡卡西出场';w._by_id['you']['base']=p.cues[0].text;w._by_id['you']['issues']=[]
    w._snapshot=snapshot_from_pairs([('卡西','卡西')])
    w.stutter_toggle.setChecked(False)
    result=SimpleNamespace(hits=[TextOccurrence('you',0,'卡卡西','卡西',(0,3),source='ai_accepted')],receipt={})
    w._show_result(result,p,True,{c.id:c.text for c in p.cues})
    assert any(i['replacement']=='卡西' for i in w._unresolved(w._by_id['you']))


def test_row_check_is_visible_initially_and_independent_actions_do_not_select(review):
    w,_ = review
    assert not hasattr(w,'batch_toggle') and not hasattr(w.list,'batch_mode')
    assert not any(b.text()=='批量选择' for b in w.findChildren(QPushButton))
    assert not w._batch_selected
    w.resize(1500,900);w.show();APP.processEvents();w.list.repaint()
    row='you'
    box=next(rect for rect,action,c,_ in w.list._hit_boxes if action=='rowcheck' and c==row)
    assert box.width()>30 and box.height()>=20
    QTest.mouseClick(w.list,Qt.LeftButton,pos=box.center().toPoint())
    assert w._batch_selected == {row}
    plays=[];w.list.play_requested.disconnect();w.list.play_requested.connect(plays.append)
    box=next(rect for rect,action,c,_ in w.list._hit_boxes if action=='play' and c==row)
    QTest.mouseClick(w.list,Qt.LeftButton,pos=box.center().toPoint())
    assert plays==[row] and w._batch_selected=={row}
    QTest.keyClick(w.list,Qt.Key_Space)
    assert plays==[row,row] and w._batch_selected=={row}
    w._apply_filter();w.list.repaint()
    assert any(action=='rowcheck' for _,action,_,_ in w.list._hit_boxes)


def test_leaving_cancels_local_checks_and_does_not_cancel_authorized_ai(review,monkeypatch):
    w,_ = review
    cancelled=[]
    local=SimpleNamespace(isRunning=lambda:True,requestInterruption=lambda:cancelled.append('stutter'))
    w._stutter_threads=[local]
    w._worker=SimpleNamespace(isRunning=lambda:True,token=SimpleNamespace(cancel=lambda:cancelled.append('match')),inputs=(None,['then']))
    w._worker_ai=False;w._worker_scope_all=False
    w._cancel_hidden_checks()
    assert cancelled==['stutter','match']
    assert w._match_on_show=={'then'}
    w._worker_ai=True;cancelled.clear();w._cancel_hidden_checks()
    assert cancelled==['stutter']
    w._worker=None;w._stutter_threads=[]
