from types import SimpleNamespace
import copy
import pytest
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtGui import QUndoStack

from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project, load_project
from twobyteasr.timeline.studio_edit_sequence import sequence_of, HighlightCandidate, VideoSegment
from twobyteasr.timeline.studio_edit_commands import replace_candidates_command, generate_edit_command
from twobyteasr.studio.highlight_workflow import timeline_range, apply_range
from twobyteasr.studio.studio_highlight_ui import HighlightAssistantPanel, HighlightCandidateCard


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def make_candidate(index=0, ready=True):
    return HighlightCandidate(id=f'candidate-{index}',title='观众接连询问「真的假的」',
         source_path='record.flv',source_duration_ms=100000,source_in_ms=20000+index*1000,
         source_out_ms=30000+index*1000,clip_reason='「真的假的」与「？？？」接连出现，可以先看这一轮反应。',
         range_status='suggested' if ready else 'unconfirmed',context_in_ms=10000,context_out_ms=60000,
         signal_in_ms=25000,signal_out_ms=30000,
         evidence=[dict(id='d:1',kind='danmaku',start_ms=25000,end_ms=25000,text='真的假的')])


def test_cards_show_actions_and_evidence_without_score_or_automatic_play(app):
    panel=HighlightAssistantPanel()
    panel.resize(360,780);panel.show()
    events=[];panel.preview_requested.connect(events.append)
    panel.reload_candidates([make_candidate(i,i%2==0) for i in range(8)])
    app.processEvents()
    assert panel.results.count()==5 and panel.more_candidates.isVisible()
    assert not events
    first=panel.results.itemWidget(panel.results.item(0))
    assert first.preview_button.text()=='预览片段'
    assert first.accept_button.text()=='加入待生成'
    assert not any(label.objectName()=='highlightScore' for label in first.findChildren(QLabel))
    first.toggle_details();app.processEvents()
    assert first.details_body.isVisible() and not events
    first.preview_button.click()
    assert events==[1]
    pending=panel.results.itemWidget(panel.results.item(1))
    assert pending.preview_button.text()=='查看现场' and pending.accept_button.text()=='设置起止'
    assert pending.range_label.text()=='待确认剪辑范围'
    panel.more_candidates.click();app.processEvents()
    assert panel.results.count()==8
    panel.close();panel.deleteLater();app.processEvents()


def test_mapping_checks_source_identity_and_rate_and_removed_intervals():
    p=SubtitleProject(media=StudioMedia(path='old.flv',duration_ms=100000))
    seq=sequence_of(p)
    seq.segments=[VideoSegment('a','record.flv',20000,40000,0,10000),
                  VideoSegment('b','record.flv',60000,80000,10000,30000)]
    assert timeline_range(p,'record.flv',24000,30000)==(2000,5000)
    assert timeline_range(p,'old.flv',24000,30000) is None
    assert timeline_range(p,'record.flv',30000,65000) is None


def test_adjust_undo_generate_and_saved_range_are_identical(app,tmp_path):
    p=SubtitleProject(media=StudioMedia(path='record.flv',duration_ms=100000))
    seq=sequence_of(p);seq.clip_candidates=[make_candidate()]
    page=SimpleNamespace(project=p,undo_stack=QUndoStack(),_sequence_changed=lambda *a,**kw:None,
                         _refresh_danmaku_status=lambda:None,timeline=SimpleNamespace(update=lambda:None))
    assert apply_range(page,'candidate-0',19000,32000)
    c=sequence_of(p).clip_candidates[0]
    assert c.clip_range==(19000,32000) and c.user_adjusted
    page.undo_stack.undo();assert sequence_of(p).clip_candidates[0].clip_range==(20000,30000)
    page.undo_stack.redo()
    c=copy.deepcopy(sequence_of(p).clip_candidates[0]);c.status='accepted'
    page.undo_stack.push(replace_candidates_command(p,[c]))
    command=generate_edit_command(p)
    page.undo_stack.push(command)
    segment=sequence_of(p).segments[0]
    assert (segment.source_path,segment.source_in_ms,segment.source_out_ms)==('record.flv',19000,32000)
    assert generate_edit_command(p) is None
    target=tmp_path/'actual.2byteproj';save_project(p,target)
    restored=load_project(target)
    assert sequence_of(restored).clip_candidates[0].clip_range==(19000,32000)
    assert sequence_of(restored).segments[0].source_out_ms==32000


def test_pending_candidate_cannot_generate_cut(app):
    p=SubtitleProject(media=StudioMedia(path='record.flv',duration_ms=100000))
    c=make_candidate(ready=False);c.status='accepted'
    sequence_of(p).clip_candidates=[c]
    with pytest.raises(ValueError):generate_edit_command(p)


def test_repeated_io_add_reuses_source_range_instead_of_duplicating(app):
    from twobyteasr.studio.studio_edit_assembly import StudioEditAssemblyMixin
    class Page(StudioEditAssemblyMixin):
        def _sequence_changed(self,*args,**kwargs):pass
    page=Page()
    page.project=SubtitleProject(media=StudioMedia(path='record.flv',duration_ms=100000))
    page.undo_stack=QUndoStack()
    seq=sequence_of(page.project);seq.in_point_ms=1000;seq.out_point_ms=6000
    page._add_io_candidate()
    assert len(sequence_of(page.project).clip_candidates)==1
    assert sequence_of(page.project).clip_candidates[0].clip_range==(1000,6000)
    before=page.undo_stack.index()
    page._add_io_candidate()
    assert len(sequence_of(page.project).clip_candidates)==1
    assert page.undo_stack.index()==before
