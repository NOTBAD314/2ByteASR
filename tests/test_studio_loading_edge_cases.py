"""Loading ownership, save continuation and external intake without native UI."""
from __future__ import annotations
from contextlib import nullcontext
from pathlib import Path
from types import MethodType, SimpleNamespace as NS
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal
from PySide6.QtGui import QUndoStack

from twobyteasr.studio.studio_readiness import StudioReadiness
from twobyteasr.app.desktop_intake import DesktopIntake


@pytest.fixture(scope='module', autouse=True)
def app():
    return QCoreApplication.instance() or QCoreApplication([])


class Loading(QObject):
    changed = Signal()
    def __init__(self, path='A', generation=1):
        super().__init__()
        self.path, self.generation = str(Path(path).resolve()), generation
        self.active, self.state, self.deliveries = True, 'preparing', 0
    def abort(self):
        self.generation += 1
        self.active, self.state = False, 'cancelled'
        self.changed.emit()
    def deliver(self, generation):
        if not self.active or generation != self.generation: return False
        self.active, self.state = False, 'ready'
        self.deliveries += 1
        self.changed.emit()
        return True
    def snapshot(self): return dict(state=self.state, generation=self.generation)
    def resume_ready(self,path):
        self.generation+=1;self.path=path;self.active=False;self.state='ready'
        self.completed=set(StudioReadiness.TASKS);self.changed.emit()
        return self.generation


class Timer:
    def __init__(self): self.running = True
    def stop(self): self.running = False
    def start(self): self.running = True
    def isActive(self): return self.running


def gate_fixture():
    loading = Loading()
    calls = []
    page = NS(project=object(), _project_view_state='loading',
              timeline=NS(setUpdatesEnabled=lambda _:None),
              video=NS(controller=object(), set_paused=lambda _:None,
                       resume_requested_playback=lambda:calls.append('play')),
              _studio_trace=lambda *a,**k:None)
    owner = NS(_reject_studio_loading=loading.abort)
    page.window = lambda:owner
    page.project_controller = NS(dirty_guard=NS(confirm=lambda _:False),
        _open_project_steps=lambda *a,**k:calls.append('hydrate') or iter(()))
    gate = NS(page=page,loading=loading,active=True,ready=False,path=loading.path,
              generation=1,loading_generation=1,timer=Timer(),steps=None,
              on_ready=lambda:calls.append('callback'),expected_result_ref=None,
              mark=lambda _:None,profile={},finished=NS(emit=lambda:calls.append('finished')))
    for name in ('_owns_request','_retire_preparation','_loaded','_player_loaded','_tick','_finish',
                 'begin','confirmation_wait','user_wait'):
        setattr(gate,name,MethodType(getattr(StudioReadiness,name),gate))
    return gate, calls


def test_reject_B_revokes_A_reader_player_tick_and_finish():
    gate,calls=gate_fixture()
    original=gate.page.project
    gate.loading.generation=2
    gate.loading.path=str(Path('B').resolve())
    gate.begin('B')
    assert not gate.active and not gate.timer.running
    gate._loaded(1,object(),'')
    closed=threading.Event()
    gate._player_loaded(1,NS(close=closed.set),'')
    gate._tick();gate.ready=True;gate._finish()
    assert closed.wait(1) and not calls and gate.steps is None
    assert gate.page.project is original and gate.loading.state=='cancelled'


def test_new_C_during_B_confirmation_keeps_C_callback_and_identity():
    gate,calls=gate_fixture()
    gate.loading.generation=2;gate.loading.path=str(Path('B').resolve())
    def prompt(_):
        gate.loading.generation=3;gate.loading.path=str(Path('C').resolve())
        gate.generation=gate.loading_generation=3;gate.path=gate.loading.path;gate.active=True
        gate.on_ready=lambda:calls.append('C')
        return False
    gate.page.project_controller.dirty_guard.confirm=prompt
    gate.begin('B')
    assert gate.active and gate.loading.active and gate.path==str(Path('C').resolve())
    gate.on_ready();assert calls==['C']


@pytest.mark.parametrize('change',['generation','path','cancelled','closed_page'])
def test_unified_identity_rejects_late_callbacks(change):
    gate,calls=gate_fixture()
    if change=='generation':gate.loading.generation+=1
    elif change=='path':gate.loading.path+='-new'
    elif change=='cancelled':gate.loading.active=False;gate.loading.state='cancelled'
    else:gate.page._close_requested=True
    gate._loaded(1,object(),'late error')
    gate._tick();gate.ready=True;gate._finish()
    assert not calls and gate.steps is None and not gate.active


def test_ready_callback_new_navigation_prevents_old_play_and_focus():
    gate,calls=gate_fixture()
    gate.active=False;gate.ready=True
    gate.on_ready=lambda:(calls.append('callback'),setattr(gate.loading,'generation',2))
    gate._finish()
    assert calls==['callback'] and gate.loading.deliveries==1


def test_retained_ready_project_resumes_after_reject_without_second_delivery(tmp_path):
    from twobyteasr.studio.studio_readiness import project_file_identity
    gate,calls=gate_fixture()
    path=tmp_path/'A.2byteproj';path.write_text('{}','utf-8')
    gate.path=str(path.resolve());gate.page.project_path=path
    gate.loaded_file_identity=project_file_identity(path)
    gate.active=False;gate.ready=True;gate.timer.stop()
    gate._ready_project=lambda project=gate.page.project:project
    gate.page._reclaim_window_focus=lambda:None
    gate.loading.path=str(tmp_path/'B.2byteproj');gate.loading.abort()
    before=gate.loading.deliveries
    gate.begin(path)
    assert calls==['callback','finished','play']
    assert gate.loading.deliveries==before and not gate.timer.running
    assert gate._owns_request(allow_ready=True) and gate.profile['kind']=='hot'


def test_stale_hot_resume_cannot_overwrite_gate_reused_by_new_request(tmp_path):
    from twobyteasr.studio.studio_readiness import project_file_identity
    gate, calls = gate_fixture()
    path = tmp_path / 'A.2byteproj'
    path.write_text('{}', 'utf-8')
    gate.path = str(path.resolve())
    gate.page.project_path = path
    gate.loaded_file_identity = project_file_identity(path)
    gate.active, gate.ready = False, True
    gate._ready_project = lambda: gate.page.project
    gate.loading.abort()
    b_path = str((tmp_path / 'B.2byteproj').resolve())
    b_completed = {'B-stage'}
    b_profile = {'kind': 'B-preparation'}
    b_callback = lambda: calls.append('B')

    def resume_then_reenter(_path):
        resumed_epoch = gate.loading.generation + 1
        gate.loading.generation = resumed_epoch + 1
        gate.loading.path = b_path
        gate.loading.active, gate.loading.state = True, 'preparing'
        gate.loading.completed = b_completed
        gate.generation = gate.loading_generation = gate.loading.generation
        gate.path, gate.active, gate.ready = b_path, True, False
        gate.completed, gate.profile = b_completed, b_profile
        gate.on_ready = b_callback
        return resumed_epoch

    gate.loading.resume_ready = resume_then_reenter
    gate.begin(path)

    assert gate._owns_request()
    assert gate.completed is b_completed and gate.profile is b_profile
    assert gate.on_ready is b_callback and not calls


def test_retained_ready_cannot_rebind_an_active_other_load(tmp_path):
    from twobyteasr.studio.studio_readiness import project_file_identity
    gate,calls=gate_fixture()
    path=tmp_path/'A.2byteproj';path.write_text('{}','utf-8')
    gate.path=str(path.resolve());gate.page.project_path=path
    gate.loaded_file_identity=project_file_identity(path)
    gate.active=False;gate.ready=True
    gate.loading.path=str(tmp_path/'B.2byteproj');gate.loading.generation=2
    gate.loading.resume_ready=lambda _:pytest.fail('cannot resume over another active request')
    gate.begin(path)
    assert not calls and gate.loading.state=='cancelled'


def test_missing_primary_still_waits_for_actual_video_and_audio(monkeypatch):
    from twobyteasr.studio import studio_readiness
    gate,calls=gate_fixture()
    now=time.perf_counter()
    ready={'video':False,'audio':False}
    class Project: pass
    gate.page.project=Project()
    gate.page.project.media=NS(path='');gate.page.project.cues=[];gate.page.project.video_tracks=[object()]
    gate.page.audio_engine=NS(telemetry_snapshot=lambda:{'state':'BUFFERING'})
    gate.page._playback_buffers_ready=lambda:ready['audio']
    gate.page._preview_path=None
    gate.completed={'创建工作台界面','读取工程','建立时间轴'}
    gate.started=gate.last_tick=gate.last_progress=now
    gate.profile={'gui_gaps_ms':[]};gate.hydrated=True;gate.painted=True
    gate.TASKS=StudioReadiness.TASKS;gate._player_start_failure=lambda:''
    gate._set_stage_label=lambda _:None;gate.mark=gate.completed.add
    gate.requested_file_identity=None;gate._finish=lambda:calls.append('delivered')
    gate._failed_stage=lambda:'fixture';gate.fail=lambda *a:pytest.fail(str(a))
    monkeypatch.setattr(studio_readiness,'player_surface_ready',lambda _:ready['video'])
    monkeypatch.setattr(studio_readiness,'QTimer',NS(singleShot=lambda *a:None))
    gate._tick()
    assert '准备播放器' not in gate.completed and '准备音频' not in gate.completed and not calls
    ready['video']=True;gate._tick()
    assert '准备播放器' in gate.completed and '准备音频' not in gate.completed and not calls
    ready['audio']=True;gate._tick()
    assert calls==['delivered']


def test_no_media_subtitle_placeholder_is_ready_but_online_video_still_waits():
    from twobyteasr.studio.studio_readiness import player_surface_ready
    page=NS(project=NS(video_tracks=[]),video=NS(_media_path='',_media_attached=False,_startup_state='NEW'))
    assert player_surface_ready(page)
    page.project.video_tracks=[NS(enabled=True,clips=[NS(enabled=True)])]
    assert not player_surface_ready(page)


class Label(QObject):
    def setText(self, text): self.value=text
    def setToolTip(self, text): pass


class IntakeWindow(QObject):
    def __init__(self):
        super().__init__();self._run_in_progress=False;self.worker=None
        self.header_status=Label(self);self.page=None;self.calls=[]
        self._studio_loading_session=Loading();self._studio_loading_session.abort()
        self._studio_entry_pending=None
    @property
    def studio_page(self):raise AssertionError('lazy accessor must never be used by external intake')
    def built_page(self,_):return self.page
    def _switch_page(self,page):self.calls.append('switch')
    def open_studio_project(self,path,**options):
        self.options=options;self.calls.append(('open',path))
        self._studio_entry_pending=(path,options)
        loading=self._studio_loading_session
        loading.generation+=1;loading.active=True;loading.state='preparing';loading.changed.emit()


def test_external_subtitle_waits_for_partial_construction_without_loss():
    window=IntakeWindow();intake=DesktopIntake(window)
    try:
        intake.submit(['A.2byteproj','B.srt'])
        intake._next()
        assert len(intake.requests)==1 and window.calls==[('open','A.2byteproj')]
        window.page=NS(_readiness=NS(active=False),_import_subtitle_file=lambda p:window.calls.append(('subtitle',p)))
        window._studio_entry_pending=None
        window._studio_loading_session.deliver(window._studio_loading_session.generation)
        intake._next()
        assert not intake.requests and window.calls[-1]==('subtitle',Path('B.srt'))
    finally:intake.timer.stop()


@pytest.mark.parametrize('cancel',[False,True])
def test_cold_subtitle_uses_ready_callback_and_respects_cancel(cancel):
    window=IntakeWindow();intake=DesktopIntake(window)
    try:
        intake.submit(['B.srt'])
        assert intake.active and len(intake.requests)==1
        if cancel:
            window._studio_loading_session.abort()
            assert not intake.active and not intake.requests
        else:
            page=NS(_import_subtitle_file=lambda p:window.calls.append(('subtitle',p)))
            window._studio_loading_session.deliver(window._studio_loading_session.generation)
            window.options['on_ready'](page)
            assert not intake.active and not intake.requests and window.calls[-1]==('subtitle',Path('B.srt'))
    finally:intake.timer.stop()


@pytest.mark.parametrize('waiting',['construction','save'])
def test_cancelled_queued_files_cannot_reopen_but_new_external_request_can(waiting):
    from twobyteasr.app.ui import MainWindow
    window=IntakeWindow();intake=DesktopIntake(window)
    if waiting=='construction':
        window._studio_entry_pending=('older',{})
        window._studio_loading_session.active=True
        window._studio_loading_session.state='preparing'
    else:
        window.page=SavingPage();window.page._manual_save_in_progress=True
    try:
        intake.submit(['old.2byteproj','old.srt'])
        assert len(intake.requests)==2 and not window.calls
        MainWindow._cancel_pending_studio_entries(window)
        window._studio_entry_pending=None;window._studio_loading_session.abort()
        if window.page is not None:window.page._manual_save_in_progress=False
        intake._next()
        assert not intake.requests and not window.calls
        assert '已取消' in window.header_status.value
        intake.submit(['new.2byteproj'])
        assert window.calls==[('open','new.2byteproj')]
    finally:intake.timer.stop()


def test_queued_old_build_start_cannot_construct_a_second_page():
    from twobyteasr.app.ui import MainWindow
    page=object()
    window=NS(_studio_page_building=page,_studio_entry_pending=('new',{}),_studio_entry_start_queued=True)
    MainWindow._start_studio_construction(window)
    assert window._studio_page_building is page


class SavingPage(QObject):
    manual_save_finished=Signal()
    def __init__(self):
        super().__init__();self.session=NS(project=object(),generation=1)
        self._autosave_timer=QTimer(self);self._manual_save_in_progress=False


@pytest.mark.parametrize('decision',['latest','cancel','replace_session'])
def test_save_continuation_is_latest_only_and_revocable(decision):
    from twobyteasr.projects.studio_save import manual_save_scope,defer_navigation_until_saved,cancel_navigation_after_save
    page=SavingPage();calls=[]
    with manual_save_scope(page):
        assert defer_navigation_until_saved(page,lambda:calls.append('A'))
        assert defer_navigation_until_saved(page,lambda:calls.append('B'))
        QCoreApplication.processEvents()
        assert not calls
        if decision=='cancel':cancel_navigation_after_save(page)
        if decision=='replace_session':page.session.generation+=1
    page.manual_save_finished.emit();QCoreApplication.processEvents()
    page.manual_save_finished.emit();QCoreApplication.processEvents()
    assert calls==(['B'] if decision=='latest' else [])


def test_rejected_close_preserves_loading_and_its_timer():
    from twobyteasr.app.ui import MainWindow
    gate,calls=gate_fixture();gate.page._readiness=gate
    window=NS(_studio_loading_session=gate.loading,built_page=lambda _:gate.page,worker=None,
              _prepare_glossary_for_task=lambda:True,_retire_studio_loading_for_close=lambda:calls.append('retire'))
    window._confirm_application_close=MethodType(MainWindow._confirm_application_close,window)
    result=[]
    MainWindow.closeEvent(window,NS(ignore=lambda:result.append('ignored')))
    assert result==['ignored'] and not calls
    assert gate.active and gate.loading.active and gate.timer.running


def test_main_open_during_save_does_not_start_loading_and_resumes_latest():
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.projects.studio_save import manual_save_scope
    page=SavingPage();page._studio_trace=lambda *a,**k:None
    calls=[]
    window=NS(built_page=lambda _:page,_open_subtitle_studio=lambda path,**kw:calls.append(path))
    window.studio_page=page
    window.open_studio_project=MethodType(MainWindow.open_studio_project,window)
    with manual_save_scope(page):
        window.open_studio_project('A');window.open_studio_project('B')
        assert not calls and not hasattr(window,'_studio_loading_session')
    page.manual_save_finished.emit();QCoreApplication.processEvents()
    assert calls==['B']


@pytest.mark.parametrize('failed',[False,True])
def test_real_save_controller_signals_after_publication_or_error_ui(monkeypatch,tmp_path,failed):
    from twobyteasr.projects import studio_save
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.projects.studio_project_controller import StudioProjectController
    page=SavingPage();project=SubtitleProject(media=StudioMedia(''))
    page.session.project=page.project=project
    page.session.project_path=tmp_path/'save.2byteproj'
    page.session.undo_stack=QUndoStack(page)
    page.save_state=Label(page)
    page._capture_studio_state=lambda:None
    page._schedule_autosave=lambda:None
    page._autosave_deadline=NS(mark_succeeded=lambda:None)
    order=[]
    monkeypatch.setattr(studio_save,'capture_manual_save',lambda *a:NS(updated_at='saved-fixture'))
    def persist(*a,**k):
        studio_save.defer_navigation_until_saved(page,lambda:order.append('open-A'))
        studio_save.defer_navigation_until_saved(page,lambda:order.append('open-B'))
        assert page._manual_save_in_progress and not order
        if failed:raise OSError('controlled save failure')
        return page.session.project_path
    monkeypatch.setattr(studio_save,'persist_with_progress',persist)
    controller=StudioProjectController(page,page.session)
    controller.save(message_box_fn=lambda *a:order.append('error-presented'))
    assert not page._manual_save_in_progress
    assert order==(['error-presented'] if failed else [])
    QCoreApplication.processEvents()
    assert order==(['error-presented','open-B'] if failed else ['open-B'])


def test_cold_continuation_declining_proofread_save_retires_its_card():
    from twobyteasr.app.ui import MainWindow
    page=SavingPage();loading=Loading('A')
    window=NS(built_page=lambda _:page,_studio_loading_session=loading,
        glossary_proofread_page=NS(settle_writes=lambda _:False),_reject_studio_loading=loading.abort)
    MainWindow.open_studio_project(window,'A')
    assert not loading.active and loading.state=='cancelled'


def test_cold_continuation_invalid_result_fails_its_card(monkeypatch):
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.recognition import recognition_result
    loading=Loading('A');errors=[]
    loading.fail=lambda stage,error:errors.append((stage,error))
    window=NS(built_page=lambda _:object(),_studio_loading_session=loading)
    monkeypatch.setattr(recognition_result,'verify_result_reference',lambda *a,**k:(_ for _ in ()).throw(ValueError('identity mismatch')))
    MainWindow._open_subtitle_studio(window,'A',expected_result_ref={'fixture':True})
    assert errors==[('核对识别结果','identity mismatch')]
