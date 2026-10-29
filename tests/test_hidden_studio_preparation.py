"""Owned hidden preparation without a native player, encoder, or visible window."""
import ast
import copy
from pathlib import Path
from types import MethodType, SimpleNamespace as NS
import time

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.studio.studio_readiness import StudioReadiness, owns_hidden_preparation

APP=QApplication.instance() or QApplication([])


def owned_page():
    state={'owns':True}
    page=NS(project=object(),project_path='C:/fixture.2byteproj',_close_requested=False,isVisible=lambda:False)
    page._readiness=NS(active=True,hydrated=True,path=str(page.project_path),
                       _owns_request=lambda *a,**k:state['owns'])
    return page,state


@pytest.mark.parametrize('mutation',['cancelled','not_hydrated','closed','path','ownership'])
def test_only_hydrated_current_request_may_prepare_hidden_page(mutation):
    page,state=owned_page()
    assert owns_hidden_preparation(page)
    if mutation=='cancelled':page._readiness.active=False
    elif mutation=='not_hydrated':page._readiness.hydrated=False
    elif mutation=='closed':page._close_requested=True
    elif mutation=='path':page.project_path='C:/new.2byteproj'
    else:state['owns']=False
    assert not owns_hidden_preparation(page)


def methods(file,owner_name,names):
    path=Path(__file__).resolve().parents[1]/file
    tree=ast.parse(path.read_text('utf8'))
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==owner_name)
    body=[]
    for n in owner.body:
        if isinstance(n,ast.FunctionDef) and n.name in names:
            n=copy.deepcopy(n);n.decorator_list=[];body.append(n)
    cls=ast.ClassDef(name='Harness',bases=[],keywords=[],body=body,decorator_list=[])
    ns={'__package__':'twobyteasr.studio'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),str(path),'exec'),ns)
    return ns['Harness']


class Timer:
    def __init__(self):self.started=0;self.stopped=0
    def start(self):self.started+=1
    def stop(self):self.stopped+=1


def test_hidden_prepare_consumes_cache_without_faking_visibility_or_starting_timers():
    cls=methods('twobyteasr/studio/studio_video_canvas.py','MpvCanvas',{'prepare_loading_frame'})
    canvas=cls();page,state=owned_page();calls=[]
    clock=canvas._playback_clock=object();canvas._navigation_visible=False;canvas._paused=True
    canvas._media_attached=True;canvas._clock_only=False;canvas._studio_page=lambda:page
    canvas._timer=Timer();canvas._sync_timer=Timer();canvas._navigation_timers=[]
    canvas._reconcile_position=lambda **kw:calls.append(kw)
    assert canvas.prepare_loading_frame()
    assert calls==[{'preparing':True}]
    assert not canvas._navigation_visible and canvas._paused and canvas._playback_clock is clock
    assert canvas._navigation_timers==[canvas._timer,canvas._sync_timer]
    assert canvas._timer.started==canvas._sync_timer.started==0
    state['owns']=False
    assert not canvas.prepare_loading_frame() and len(calls)==1


def test_hidden_reconcile_privilege_requires_current_preparation():
    cls=methods('twobyteasr/studio/studio_video_canvas.py','MpvCanvas',{'_reconcile_position'})
    canvas=cls();page,state=owned_page();canvas._studio_page=lambda:page
    canvas._navigation_visible=False;canvas._sync_timer=Timer()
    class CachePumpReached(Exception):pass
    def reached():raise CachePumpReached()
    page._refresh_audio_tail_clock=reached
    canvas._reconcile_position()
    state['owns']=False;canvas._reconcile_position(preparing=True)
    assert canvas._sync_timer.stopped==2
    state['owns']=True
    with pytest.raises(CachePumpReached):canvas._reconcile_position(preparing=True)


def test_hidden_caption_cache_cannot_bypass_loading_ownership():
    cls=methods('twobyteasr/studio/studio_advanced_flow.py','StudioAdvancedFlowMixin',{'_present_caption_scene'})
    page,state=owned_page();obj=cls();obj.__dict__.update(page.__dict__)
    obj._caption_tick_time_ms=0
    obj._caption_playhead_sample={'presented_key':(id(obj.project),None,None,0)}
    assert obj._present_caption_scene()
    state['owns']=False
    assert not obj._present_caption_scene()


def test_prepared_advanced_pixels_must_belong_to_current_cue():
    cls=methods('twobyteasr/studio/studio_advanced_flow.py','StudioAdvancedFlowMixin',{'_prepare_loading_subtitles'})
    page,state=owned_page();obj=cls();obj.__dict__.update(page.__dict__)
    calls=[];obj._activate_selected_advanced_if_needed=lambda:calls.append('prepare')
    obj._advanced_active_cue_id='current'
    evidence={'foreground_owner_cue_id':'old','advanced_live_visible':True}
    obj.ensure_active_subtitle_renderer=lambda **kw:evidence
    assert not obj._prepare_loading_subtitles()
    evidence['foreground_owner_cue_id']='current'
    assert obj._prepare_loading_subtitles()
    state['owns']=False
    assert not obj._prepare_loading_subtitles() and len(calls)==2


def test_hidden_timeline_is_rendered_once_without_showing_it():
    parent=QWidget();timeline=QWidget(parent);timeline.resize(640,180)
    failures=[]
    gate=NS(page=NS(timeline=timeline),painted=False,generation=1,profile={},
            _owns_request=lambda epoch:epoch==1,fail=lambda *a:failures.append(a))
    class PaintObserver(QObject):
        def eventFilter(self,watched,event):
            if event.type()==QEvent.Paint:gate.painted=True
            return False
    observer=PaintObserver(timeline);timeline.installEventFilter(observer)
    try:
        assert not timeline.isVisible()
        assert StudioReadiness._prepare_timeline_surface(gate)
        assert gate.painted and gate.profile['timeline_prepared_hidden'] and not failures
        assert not parent.isVisible() and not timeline.isVisible()
    finally:parent.deleteLater()


def test_disabled_timeline_fails_preparation_instead_of_waiting_for_hidden_paint():
    timeline=QWidget();timeline.setUpdatesEnabled(False);failures=[]
    gate=NS(page=NS(timeline=timeline),painted=False,fail=lambda *a:failures.append(a))
    try:
        assert not StudioReadiness._prepare_timeline_surface(gate)
        assert failures==[('首屏绘制','时间轴尚未启用绘制')]
    finally:timeline.deleteLater()


def test_cancel_passes_reveal_after_rejecting_old_callbacks():
    order=[]
    page=NS(video=NS(set_paused=lambda _x:None),timeline=NS(setUpdatesEnabled=lambda _x:None),
            project=object(),_studio_trace=lambda *a,**k:None)
    gate=NS(page=page,generation=4,active=True,ready=False,steps=object(),timer=Timer(),on_ready=object(),path='A')
    def reveal():order.append(('reveal',gate.active,gate.generation))
    def abort(*,reveal):
        order.append(('abort',gate.active,gate.generation));reveal()
    gate.loading=NS(abort=abort)
    StudioReadiness.cancel(gate,navigate=False,reveal=reveal)
    assert order==[('abort',False,5),('reveal',False,5)] and gate.on_ready is None


def test_cancel_without_reveal_keeps_legacy_abort_signature():
    page=NS(video=NS(set_paused=lambda _x:None),timeline=NS(setUpdatesEnabled=lambda _x:None),
            project=object(),_studio_trace=lambda *a,**k:None)
    calls=[]
    gate=NS(page=page,generation=4,active=True,ready=False,steps=None,timer=Timer(),on_ready=None,path='A',
            loading=NS(abort=lambda:calls.append('abort')))
    StudioReadiness.cancel(gate,navigate=False)
    assert calls==['abort']


def caption_gate_fixture(monkeypatch, *, cue_start=None):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.studio import studio_readiness
    monkeypatch.setattr(studio_readiness,'player_surface_ready',lambda page:True)
    project=SubtitleProject(media=StudioMedia(path='',duration_ms=5000),
        cues=[] if cue_start is None else [StudioCue('current',cue_start,cue_start+1000,'字幕')])
    events=[];failures=[];now=time.perf_counter()
    class Scene:
        active=True;closed=False;token=None;valid=False
        def close(self):self.closed=True;self.active=False;events.append('scene.close')
        def deleteLater(self):events.append('scene.deleteLater')
        def trace(self):return {'expected_cue_ids':['current'],'cue_pixels':[{'cue_id':'current','status':'rendered'}]}
        def still_current(self,_):return self.valid and not self.closed
    scene=Scene()
    timeline=NS(hidden_speakers=set(),_speaker_ids=[],updatesEnabled=lambda:True,isVisible=lambda:False)
    video=NS(_paused=True,controller=None,ADVANCED_OVERLAY_ID=900,
        clear_caption_boundaries=lambda:events.append('boundaries.clear'),
        remove_compositor_overlay=lambda *a,**k:events.append(('remove',a,k)))
    page=NS(project=project,project_path='C:/current.2byteproj',video=video,timeline=timeline,
        session=NS(runtime=None),_subtitle_track_visibility={},_caption_sample_ms=lambda:0,
        _caption_scene=scene,_caption_playhead_sample={'presented_key':'old'},_advanced_active_cue_id='old',
        _preview_path=None,isVisible=lambda:False,_studio_trace=lambda *a,**k:None,
        _revoke_advanced_preview=lambda **k:events.append(('revoke',k)),
        _playback_buffers_ready=lambda:True,_prepare_loading_subtitles=lambda:True,
        _present_caption_scene=lambda:None,audio_engine=NS(telemetry_snapshot=lambda:{}))
    completed=set(StudioReadiness.TASKS)-{'准备字幕','首屏绘制'}
    loading=NS(completed=completed,skip=lambda stage,reason:(completed.add(stage),events.append(('skip',stage,reason))),
               mark=completed.add)
    gate=NS(page=page,loading=loading,active=True,ready=False,hydrated=True,painted=False,
        path=str(page.project_path),generation=9,_owns_request=lambda *a,**k:True,
        completed=completed,started=now,last_tick=now,last_progress=now,_reader=None,steps=None,
        profile={'stages_ms':{},'gui_gaps_ms':[]},TASKS=StudioReadiness.TASKS,
        _player_start_failure=lambda:'',_failed_stage=lambda:'准备字幕',
        _set_stage_label=lambda stage:events.append(('waiting',stage)),timer=Timer(),
        requested_file_identity=None,_finish=lambda:events.append('finished'),_warm_text_analysis=lambda epoch:None,
        fail=lambda *a:failures.append(a),bar=NS(setValue=lambda n:None),
        steps_view=NS(current='准备字幕',set_state=lambda *a:None))
    page._readiness=gate
    gate.mark=MethodType(StudioReadiness.mark,gate)
    timeline.grab=lambda:setattr(gate,'painted',True)
    return gate,scene,events,failures


@pytest.mark.parametrize('target',['empty','gap','hidden_track','placeholder'])
def test_no_first_frame_caption_retires_old_scene_and_explicitly_skips(monkeypatch,target):
    gate,scene,events,failures=caption_gate_fixture(monkeypatch,cue_start=None if target=='empty' else 1000 if target=='gap' else 0)
    if target=='hidden_track':
        gate.page.timeline.hidden_speakers={gate.page.project.cues[0].speaker_id}
    elif target=='placeholder':gate.page._empty_playback_state=True
    cues_before=list(gate.page.project.cues)
    StudioReadiness._tick(gate)
    assert gate.ready and not gate.active and not failures
    assert scene.closed and gate.page._caption_scene is None and not scene.still_current(('old',))
    assert 'presented_key' not in gate.page._caption_playhead_sample
    assert gate.page._advanced_active_cue_id=='' and gate.page.project.cues==cues_before
    assert events.count('scene.close')==1 and events.count('boundaries.clear')==1
    assert sum(isinstance(e,tuple) and e[0]=='remove' for e in events)==1
    reason='工程没有字幕' if target=='empty' else '首屏没有可显示字幕'
    assert ('skip','准备字幕',reason) in events


@pytest.mark.parametrize('identity',['missing_token','old_revision'])
def test_real_caption_still_requires_current_scene_token_and_revision(monkeypatch,identity):
    gate,scene,events,failures=caption_gate_fixture(monkeypatch,cue_start=0)
    gate.page._preview_path='current.ass'
    scene.token=None if identity=='missing_token' else ('old',)
    StudioReadiness._tick(gate)
    assert gate.active and not gate.ready and '准备字幕' not in gate.completed
    assert not scene.closed and not failures and 'scene.close' not in events
    scene.token=('current',);scene.valid=True
    StudioReadiness._tick(gate)
    assert gate.ready and not failures and not scene.closed


def test_ready_tick_resolves_geometry_before_consuming_old_paint(monkeypatch):
    gate,scene,events,failures=caption_gate_fixture(monkeypatch)
    gate.painted=True
    gate.completed.add('首屏绘制')
    def prepare(page):
        events.append('geometry')
        StudioReadiness.invalidate_surface_geometry(gate)
    gate.page.window=lambda:NS(_prepare_hidden_studio_geometry=prepare)
    def paint():
        events.append('paint-at-current-geometry')
        gate.painted=True
    gate.page.timeline.grab=paint
    StudioReadiness._tick(gate)
    assert gate.ready and not failures
    assert events.index('geometry') < events.index('paint-at-current-geometry') < events.index('finished')


def test_geometry_callback_that_retires_request_cannot_continue_ready_tick(monkeypatch):
    gate,scene,events,failures=caption_gate_fixture(monkeypatch)
    owns={'value':True}
    gate._owns_request=lambda *a,**k:owns['value']
    def prepare(page):
        events.append('geometry')
        owns['value']=False
    gate.page.window=lambda:NS(_prepare_hidden_studio_geometry=prepare)
    StudioReadiness._tick(gate)
    assert not gate.ready and not failures and events==['geometry']


def test_ready_tick_waits_when_owner_cannot_prepare_geometry(monkeypatch):
    gate,scene,events,failures=caption_gate_fixture(monkeypatch)
    gate.painted=True
    gate.completed.add('首屏绘制')
    gate.page.window=lambda:NS(_prepare_hidden_studio_geometry=lambda page:False)
    StudioReadiness._tick(gate)
    assert not gate.ready and not failures and not events
