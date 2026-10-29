"""Actual canvas scopes with pure HWND/region/timer fakes; no GUI or decoder."""
from types import SimpleNamespace as NS

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion

from tests.test_native_video_region import Api, Process, Timer, canvas_harness
from twobyteasr.studio.native_video_region import NativeVideoRegionGate


@pytest.fixture(autouse=True)
def isolated_fakes(monkeypatch):
    import shiboken6
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(shiboken6,'isValid',lambda obj:getattr(obj,'_valid',True))
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)


def canvas_fixture(*,native=True):
    canvas=canvas_harness();api=Api();api.add()
    canvas._presentation_block_reasons.clear()
    canvas._native_region_gate=NativeVideoRegionGate(api) if native else None
    if native:canvas.destroyed.connect(canvas._native_region_gate.close)
    canvas.controller=NS(_process=Process())
    syncs=[]
    if native:
        original=canvas._native_region_gate.sync
        def sync(*args):syncs.append(args);return original(*args)
        canvas._native_region_gate.sync=sync
    return canvas,api,syncs


def test_nested_scope_commits_final_native_state_once():
    canvas,api,syncs=canvas_fixture()
    with canvas.defer_presentation_changes():
        canvas.set_presentation_blocked('loading',True)
        with canvas.defer_presentation_changes():
            canvas.set_presentation_blocked('navigation',True)
            canvas.set_presentation_blocked('loading',False)
        assert canvas._presentation_block_reasons=={'navigation'}
        assert not api.sets and not syncs and not canvas._mask_changes
    assert len(syncs)==1 and len(api.sets)==1 and api.regions[11]==()
    assert canvas._presentation_defer_depth==0 and not canvas._presentation_defer_pending


def test_cancelled_temporary_reason_never_changes_regions():
    canvas,api,syncs=canvas_fixture()
    with canvas.defer_presentation_changes():
        canvas.set_presentation_blocked('loading',True)
        canvas.set_presentation_blocked('loading',False)
    assert len(syncs)==1 and not api.sets and not canvas._mask_changes


def test_parent_fallback_is_deferred_and_original_region_is_kept():
    canvas,api,_=canvas_fixture(native=False)
    original=QRegion(QRect(3,7,400,210));canvas._mask=original
    with canvas.defer_presentation_changes():
        canvas.set_presentation_blocked('loading',True)
        canvas._sync_parent_presentation_mask()
        assert canvas.mask()==original and not canvas._mask_changes
    assert canvas._presentation_parent_mask_active and canvas._presentation_saved_mask==original
    with canvas.defer_presentation_changes():canvas.set_presentation_blocked('loading',False)
    assert canvas.mask()==original and len(canvas._mask_changes)==2


def test_navigation_pause_timers_and_generation_change_before_presentation_commit():
    canvas,api,syncs=canvas_fixture();clock=canvas._playback_clock=object();pauses=[]
    canvas._navigation_visible=True;canvas._navigation_generation=4;canvas._paused=False
    canvas._timer=Timer();canvas._sync_timer=Timer();canvas._buffered_play_timer=Timer()
    for timer in (canvas._timer,canvas._sync_timer,canvas._buffered_play_timer):timer.start()
    canvas._startup_play_requested=canvas._buffered_play_pending=True
    canvas.isVisible=lambda:True;canvas.parentWidget=lambda:None;canvas.geometry=lambda:QRect(0,0,640,360)
    def pause(value):pauses.append(value);canvas._paused=value
    canvas.set_paused=pause
    with canvas.defer_presentation_changes():
        canvas.set_navigation_visible(False)
        assert not canvas._navigation_visible and canvas._navigation_generation==5
        assert pauses==[True] and canvas._paused and canvas._playback_clock is clock
        assert not canvas._timer.active and not canvas._sync_timer.active and not canvas._buffered_play_timer.active
        assert not canvas._startup_play_requested and not canvas._buffered_play_pending
        assert not api.sets and not syncs
    assert len(syncs)==1 and len(api.sets)==1


def test_exception_still_commits_and_is_not_suppressed():
    canvas,api,syncs=canvas_fixture()
    with pytest.raises(ValueError,match='original'):
        with canvas.defer_presentation_changes():
            canvas.set_presentation_blocked('loading',True)
            raise ValueError('original')
    assert len(syncs)==1 and api.regions[11]==()
    assert canvas._presentation_defer_depth==0


def test_destroy_inside_scope_does_not_call_any_invalid_widget_method():
    canvas,api,syncs=canvas_fixture()
    with canvas.defer_presentation_changes():
        canvas.set_presentation_blocked('loading',True)
        canvas._valid=False
        canvas.thread=lambda:(_ for _ in ()).throw(AssertionError('invalid QObject access'))
    assert not api.sets and not syncs and not canvas._mask_changes
    assert canvas._presentation_defer_depth==0 and not canvas._presentation_defer_pending


def test_close_retires_pending_commit_and_owned_native_timer():
    canvas,api,syncs=canvas_fixture()
    with canvas.defer_presentation_changes():
        canvas.set_presentation_blocked('loading',True)
        canvas._retire_native_presentation()
        canvas.controller=None
    assert canvas._presentation_retired and canvas._native_region_gate.closed
    assert not canvas._native_region_timer.active and not canvas._presentation_defer_pending
    assert not api.sets and not syncs and not canvas._mask_changes


def test_native_bind_timer_cannot_commit_inside_scope():
    canvas,api,syncs=canvas_fixture()
    with canvas.defer_presentation_changes():
        canvas.set_presentation_blocked('loading',True)
        canvas._native_region_timer.start();canvas._sync_native_region()
        assert not canvas._native_region_timer.active and not syncs
    assert len(syncs)==1 and api.regions[11]==()


def test_worker_thread_scope_is_rejected_before_state_changes():
    canvas,api,syncs=canvas_fixture();canvas.thread=lambda:'other-thread'
    with pytest.raises(RuntimeError,match='GUI thread'):
        with canvas.defer_presentation_changes():raise AssertionError('scope entered')
    assert not api.sets and not syncs and canvas._presentation_defer_depth==0


def test_inner_exception_does_not_commit_before_outer_final_state():
    canvas,api,syncs=canvas_fixture()
    with canvas.defer_presentation_changes():
        try:
            with canvas.defer_presentation_changes():
                canvas.set_presentation_blocked('loading',True)
                raise ValueError('inner')
        except ValueError:pass
        assert not syncs and not api.sets
        canvas.set_presentation_blocked('loading',False)
    assert len(syncs)==1 and not api.sets and not canvas._mask_changes


@pytest.mark.parametrize('native',[True,False])
def test_explicit_reopen_in_scope_commits_only_the_new_process(native):
    canvas,api,_=canvas_fixture(native=native);old=canvas._native_region_gate
    with canvas.defer_presentation_changes():
        canvas.set_presentation_blocked('loading',True)
        canvas._retire_native_presentation();canvas.controller=None
        api.windows.clear();api.add(12,pid=91)
        canvas.controller=NS(_process=Process(91))
        assert (old is None or old.closed) and not canvas._presentation_retired and not api.sets
    if native:
        assert canvas._native_region_gate is not old
        assert [child for child,_ in api.sets]==[12] and api.regions[12]==()
    else:
        assert canvas._native_region_gate is None and not api.sets
        assert canvas._presentation_parent_mask_active and len(canvas._mask_changes)==1
