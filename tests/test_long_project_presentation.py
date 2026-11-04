"""Real paint handoff, flat-table contracts, and view-only track expansion."""
import time

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QTest, QAbstractItemModelTester
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio.studio_loading import StudioLoadingSession, TASKS
from twobyteasr.studio.studio_cue_table import CueTableModel

APP = QApplication.instance() or QApplication([])


def spin_until(condition, seconds=2):
    end=time.perf_counter()+seconds
    while not condition() and time.perf_counter()<end:
        QTest.qWait(10)
    assert condition()


def test_complete_waits_for_final_paint_and_animation_then_reveals_once(tmp_path):
    host=QWidget();host.resize(1400,900);host.show()
    session=StudioLoadingSession(host)
    epoch=session.begin(str(tmp_path/'project.2byteproj'))
    before=session.view.card.geometry()
    QTest.qWait(30)
    assert session.view.card.geometry()==before
    assert session.view.steps_view._timer.interval()==16
    calls=[]
    session.on_reveal=lambda:calls.append('reveal')
    for stage in TASKS:session.mark(stage)
    assert session.complete(epoch,lambda:calls.append('callback'))
    assert session.view.isVisible() and calls==[]
    spin_until(lambda:session.state=='ready')
    names=[e['event'] for e in session.events]
    assert names.index('resources_ready') < names.index('completion_painted')
    assert names.index('completion_painted') < names.index('completion_animation_finished') < names.index('delivered')
    assert calls==['reveal','callback'] and session.deliveries==1
    assert session.view.bar._shown == 1.
    assert not session.view.isVisible()
    host.close()


def test_cover_progress_finishes_by_elapsed_time_after_delayed_timer(monkeypatch):
    import twobyteasr.studio.loading_faces as faces
    now=[100.]
    monkeypatch.setattr(faces.time,'perf_counter',lambda:now[0])
    bar=faces.CoverScrubber();bar.setRange(0,7);bar.setValue(7)
    now[0]+=.25
    bar._ease()
    assert bar._shown==1. and not bar._timer.isActive()
    bar.reset_progress()
    assert bar._shown==0. and not bar._timer.isActive()
    bar.close()


def test_cancelled_completion_cannot_reveal_successor(tmp_path):
    host=QWidget();host.resize(1400,900);host.show()
    session=StudioLoadingSession(host);calls=[]
    old=session.begin(str(tmp_path/'old.2byteproj'))
    for stage in TASKS:session.mark(stage)
    assert session.complete(old,lambda:calls.append('old'))
    QTest.qWait(50)
    new=session.begin(str(tmp_path/'new.2byteproj'))
    assert not session.complete(old)
    QTest.qWait(400)
    assert session.generation==new and session.active and not calls
    assert session.view.isVisible() and session.deliveries==0
    session.abort();host.close()


def test_cached_stage_is_presented_as_reused_and_retry_clears_it(tmp_path):
    host=QWidget();host.resize(1400,900);host.show()
    session=StudioLoadingSession(host)
    session.begin(str(tmp_path/'cached.2byteproj'))
    session.reuse('读取工程','复用已载入工程')
    assert session.view.steps_view.state_of('读取工程')=='reused'
    assert any(row['event']=='reused' for row in session.events)
    session.begin(str(tmp_path/'other.2byteproj'))
    assert not session.view.steps_view.reused
    session.abort();host.close()


def test_flat_read_only_model_survives_reset_and_accessibility_queries(monkeypatch):
    project=SubtitleProject(media=StudioMedia('',duration_ms=22000000),
        cues=[StudioCue(str(i),i*3000,i*3000+1000,'line',speaker_id='one') for i in range(6962)],
        speakers=[StudioSpeaker('one')])
    model=CueTableModel(project)
    tester=QAbstractItemModelTester(model,QAbstractItemModelTester.FailureReportingMode.Warning)
    old=model.index(3041,3)
    assert model.rowCount(old)==0 and model.columnCount(old)==0
    assert 'flags' not in CueTableModel.__dict__
    for row in (0,3041,6961):
        index=model.index(row,3)
        assert model.flags(index)&Qt.ItemFlag.ItemIsSelectable
        assert not model.flags(index)&Qt.ItemFlag.ItemIsEditable
    # Decoration/size/accessibility roles cannot trigger whole-document QC.
    import twobyteasr.studio.studio_cue_table as table
    def forbidden(*a,**k):raise AssertionError('unrelated role requested QC')
    monkeypatch.setattr(table,'_cue_status',forbidden)
    assert model.data(old,Qt.ItemDataRole.DecorationRole) is None
    assert model.data(old,Qt.ItemDataRole.DisplayRole)=='line'
    assert model.data(model.index(3041,0),Qt.ItemDataRole.DisplayRole)==3042
    monkeypatch.undo()
    model.scope_ids=('1',);model.refresh()
    assert model.data(old) is None
    assert model.data(QModelIndex()) is None
    tester.deleteLater();model.deleteLater()


def test_track_expansion_keeps_interval_and_raster_dependencies(monkeypatch):
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    from twobyteasr.recognition.speaker_roles import KEY
    project=SubtitleProject(media=StudioMedia('',duration_ms=22000000),
        speakers=[StudioSpeaker(x) for x in ('a','b','c')],
        cues=[StudioCue(str(i),i*3000,i*3000+1000,'line',speaker_id=('a','b','c')[i%3]) for i in range(6962)])
    project.studio_state[KEY]={'policy':'speaker-roles-v1','grouped':True,'expanded':False,
        'auto':{'a':'main','b':'secondary','c':'secondary'},'manual':{}}
    timeline=WaveformTimeline();timeline.resize(1400,550);timeline.set_project(project)
    timeline.set_visible_window(9000000,60000);timeline.set_playhead(9211333)
    index=timeline._cue_interval_index;rows=timeline._cues_by_start
    window=(timeline.visible_start_ms,timeline.visible_duration_ms,timeline.playhead_ms)
    def forbidden():raise AssertionError('view change rebuilt all subtitle indices')
    monkeypatch.setattr(timeline,'_rebuild_cue_index',forbidden)
    for expanded in (True,False,True,False):
        timeline.set_group_expanded(expanded)
        assert timeline._cue_interval_index is index and timeline._cues_by_start is rows
        assert (timeline.visible_start_ms,timeline.visible_duration_ms,timeline.playhead_ms)==window
        assert timeline._group_expanded==expanded
    timeline.close()
