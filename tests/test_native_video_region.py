"""Pure HWND/HRGN and actual canvas-method tests; no QApplication or GUI."""
import ast
import copy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion

from twobyteasr.studio.native_video_region import NativeVideoRegionGate


class Process:
    def __init__(self,pid=90):self.pid=pid;self.dead=False
    def poll(self):return 0 if self.dead else None


class Api:
    def __init__(self):
        self.windows={};self.regions={};self.owned=set();self.transferred=set();self.deleted=[]
        self.sets=[];self.next=100;self.fail=False;self.finds=0
    def add(self,hwnd=11,host=10,pid=90,region=None):
        self.windows[hwnd]=(host,pid);self.regions[hwnd]=region
    def find_child(self,host,pid):
        self.finds+=1
        matches=[h for h,key in self.windows.items() if key==(host,pid)]
        if len(matches)>1:raise RuntimeError('ambiguous child')
        return matches[0] if matches else 0
    def matches(self,host,child,pid):return self.windows.get(child)==(host,pid)
    def allocate(self,value):
        self.next+=1;self.owned.add(self.next);self.regions[self.next]=value;return self.next
    def empty(self):return self.allocate(())
    def delete(self,region):
        if region:
            assert region in self.owned, 'deleted an OS-owned HRGN'
            self.owned.remove(region);self.deleted.append(region)
    def capture(self,child):
        value=self.regions[child]
        return (self.allocate(value),1 if value==() else 3) if value is not None else (0,0)
    def region_kind(self,child):
        value=self.regions[child];return 0 if value is None else 1 if value==() else 3
    def transfer(self,child,region):
        self.sets.append((child,region))
        if self.fail:return False
        if region:
            assert region in self.owned, 'used a transferred HRGN again'
            self.owned.remove(region);self.transferred.add(region)
            self.regions[child]=self.regions[region]
        else:self.regions[child]=None
        return True


def fixture(region=None):
    api=Api();api.add(region=region)
    controller=NS(_process=Process())
    return NativeVideoRegionGate(api),api,controller


def test_pending_initial_child_applies_existing_block_when_bound():
    gate,api,c=fixture();api.windows.clear()
    assert gate.sync(c,10,True)['status']=='waiting_child' and not api.sets
    api.add()
    assert gate.sync(c,10,True)['region_kind']==1 and api.regions[11]==()
    gate.sync(c,10,True)
    assert len(api.sets)==1
    assert gate.sync(c,10,False)['status']=='released' and api.regions[11] is None
    gate.close()
    assert not api.owned and not api.deleted


def test_custom_region_is_restored_and_transferred_exactly_once():
    original=((2,3,40,50),(90,80,100,90))
    gate,api,c=fixture(original)
    gate.sync(c,10,True);saved=gate.saved
    assert saved in api.owned and api.regions[11]==()
    gate.sync(c,10,False)
    assert api.regions[11]==original and saved in api.transferred
    gate.close()
    assert not api.owned and saved not in api.deleted


def test_failed_set_frees_only_untransferred_regions_and_preserves_original():
    original=((0,0,40,50),)
    gate,api,c=fixture(original);api.fail=True
    assert gate.sync(c,10,True)['status']=='error'
    saved=gate.saved
    assert saved in api.owned and api.regions[11]==original
    gate.sync(c,10,True)
    assert gate.saved==saved  # Retry cannot overwrite/leak the saved HRGN.
    gate.close()
    assert not api.owned and len(api.deleted)==3 and saved in api.deleted


def test_failed_restore_retains_ownership_until_success_or_close():
    gate,api,c=fixture(((0,0,50,50),))
    gate.sync(c,10,True);saved=gate.saved;api.fail=True
    assert gate.sync(c,10,False)['status']=='error' and saved in api.owned
    api.fail=False
    gate.sync(c,10,False)
    assert saved in api.transferred and not api.owned


def test_replaced_pid_host_or_child_never_receives_old_restore():
    for mutation in ('pid','host','child','process'):
        gate,api,c=fixture(((0,0,50,50),));gate.sync(c,10,True)
        old_saved=gate.saved;sets=len(api.sets)
        if mutation=='pid':api.windows[11]=(10,91)
        elif mutation=='host':api.windows[11]=(20,90)
        elif mutation=='child':api.windows.clear()
        else:c._process=Process(91)
        result=gate.sync(c,10,False)
        assert result['status']=='waiting_child' and len(api.sets)==sets
        assert old_saved in api.deleted and not api.owned


def test_restart_binds_new_window_without_restoring_retired_window():
    gate,api,c=fixture(((0,0,50,50),));gate.sync(c,10,True)
    c._process.dead=True;c._process=Process(91);api.windows.clear();api.add(12,pid=91)
    gate.sync(c,10,True)
    assert [h for h,_ in api.sets]==[11,12] and api.regions[12]==()
    gate.sync(c,10,False)
    assert [h for h,_ in api.sets]==[11,12,12]


def test_close_deletes_own_snapshot_without_touching_foreign_window():
    gate,api,c=fixture(((0,0,50,50),));gate.sync(c,10,True)
    sets=list(api.sets);gate.close();gate.close()
    assert not api.owned and api.sets==sets
    assert gate.sync(c,10,False)['status']=='retired' and api.sets==sets


def test_resize_region_recheck_preserves_original_not_an_overwritten_region():
    original=((0,0,50,50),)
    gate,api,c=fixture(original);gate.sync(c,10,True);saved=gate.saved
    api.regions[11]=None  # A native VO/window update discarded our clip.
    gate.sync(c,10,True)
    assert api.regions[11]==() and gate.saved==saved
    gate.sync(c,10,False)
    assert api.regions[11]==original


def test_no_process_or_host_does_not_create_or_touch_a_window():
    gate,api,c=fixture()
    assert gate.sync(c,0,True)['status']=='waiting_host' and api.finds==0
    c._process.dead=True
    assert gate.sync(c,10,True)['status']=='no_live_process' and not api.sets


class Timer:
    def __init__(self):self.active=False
    def stop(self):self.active=False
    def start(self):self.active=True
    def isActive(self):return self.active


class Signal:
    def __init__(self):self.handlers=[]
    def connect(self,callback):self.handlers.append(callback)
    def disconnect(self,callback):self.handlers.remove(callback)


def canvas_harness():
    """Run the real canvas ownership methods without constructing a QWidget."""
    path=Path(__file__).resolve().parents[1]/'twobyteasr/studio/studio_video_canvas.py'
    tree=ast.parse(path.read_text('utf8'))
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MpvCanvas')
    names={'controller','presentation_blocked','_request_native_region_sync','_sync_native_region',
           '_replace_native_region_gate','_sync_parent_presentation_mask','set_presentation_blocked',
           'defer_presentation_changes','_defer_native_presentation_sync','_retire_native_presentation',
           'set_navigation_visible'}
    body=[copy.deepcopy(n) for n in owner.body if isinstance(n,ast.FunctionDef) and n.name in names]
    cls=ast.ClassDef(name='CanvasHarness',bases=[],keywords=[],body=body,decorator_list=[])
    ns={'__package__':'twobyteasr.studio','QRect':QRect,'QRegion':QRegion,
        'QThread':NS(currentThread=lambda:'gui'),'contextmanager':contextmanager}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),str(path),'exec'),ns)
    canvas=ns['CanvasHarness']();canvas._controller=None;canvas._embed_hwnd=10
    canvas._presentation_block_reasons={'loading'};canvas._native_region_timer=Timer()
    canvas._native_region_token=None;canvas._native_region_result=None;canvas._native_region_attempts=0
    canvas._presentation_parent_mask_active=False;canvas._presentation_saved_mask=None
    canvas._presentation_defer_depth=0;canvas._presentation_defer_pending=False;canvas._presentation_retired=False
    canvas._mask=QRegion();canvas._mask_changes=[]
    def set_mask(mask):
        canvas._mask=QRegion(mask);canvas._mask_changes.append(('set',QRegion(mask)))
    def clear_mask():
        canvas._mask=QRegion();canvas._mask_changes.append(('clear',QRegion()))
    canvas.mask=lambda:QRegion(canvas._mask);canvas.setMask=set_mask;canvas.clearMask=clear_mask
    canvas.thread=lambda:'gui'
    canvas.destroyed=Signal()
    canvas.internalWinId=lambda:10
    canvas.winId=lambda:(_ for _ in ()).throw(AssertionError('native window creation'))
    return canvas


def test_canvas_controller_assignment_binds_late_child_without_transport(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    canvas=canvas_harness();api=Api();canvas._native_region_gate=NativeVideoRegionGate(api)
    c=NS(_process=Process());canvas.controller=c
    assert canvas._native_region_timer.active
    api.add();canvas._sync_native_region()
    assert not canvas._native_region_timer.active and api.regions[11]==()
    assert canvas.controller is c


def test_canvas_discovery_stops_after_bounded_attempts_and_rechecks_on_lifecycle(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    canvas=canvas_harness();api=Api();canvas._native_region_gate=NativeVideoRegionGate(api)
    canvas.controller=NS(_process=Process())
    for _ in range(119):canvas._sync_native_region()
    assert api.finds==120 and not canvas._native_region_timer.active
    assert canvas._native_region_result['status']=='binding_timeout'
    assert canvas._presentation_parent_mask_active
    canvas._request_native_region_sync()
    assert api.finds==120  # No repeated steady lookup for the same owner/token.
    api.add();canvas._request_native_region_sync(recheck=True)
    assert api.regions[11]==() and not canvas._native_region_timer.active


def test_reusable_canvas_gets_new_gate_after_player_close(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    canvas=canvas_harness();api=Api();api.add(region=((0,0,50,50),))
    previous=canvas._native_region_gate=NativeVideoRegionGate(api)
    canvas.destroyed.connect(previous.close)
    canvas.controller=NS(_process=Process())
    previous.close();canvas.controller=None
    assert previous.closed and not api.owned
    api.windows.clear();api.add(12,pid=91)
    canvas.controller=NS(_process=Process(91))
    assert canvas._native_region_gate is not previous and not canvas._native_region_gate.closed
    assert api.regions[12]==() and [h for h,_ in api.sets]==[11,12]
    assert previous.close not in canvas.destroyed.handlers
    assert canvas.destroyed.handlers==[canvas._native_region_gate.close]


def test_waiting_child_parent_fallback_saves_once_then_restores_exact_region(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    canvas=canvas_harness();api=Api();canvas._native_region_gate=NativeVideoRegionGate(api)
    original=QRegion(QRect(2,3,100,90))-QRegion(QRect(10,12,8,9));canvas._mask=original
    canvas.controller=NS(_process=Process())
    assert canvas._presentation_parent_mask_active and canvas._presentation_saved_mask==original
    assert len(canvas._mask_changes)==1
    canvas._sync_native_region();canvas.set_presentation_blocked('navigation',True)
    assert len(canvas._mask_changes)==1 and canvas._presentation_saved_mask==original
    api.add();canvas._sync_native_region()
    assert not canvas._presentation_parent_mask_active and canvas.mask()==original
    assert canvas._presentation_saved_mask is None and len(canvas._mask_changes)==2


def test_verified_child_transitions_never_flash_a_parent_fallback(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    canvas=canvas_harness();api=Api();api.add();canvas._native_region_gate=NativeVideoRegionGate(api)
    canvas.controller=NS(_process=Process())
    canvas.set_presentation_blocked('navigation',True)
    canvas.set_presentation_blocked('loading',False)
    canvas.set_presentation_blocked('navigation',False)
    canvas.set_presentation_blocked('loading',True)
    assert not canvas._mask_changes and not canvas._presentation_parent_mask_active


def test_error_recovery_keeps_fallback_until_child_is_verified(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    canvas=canvas_harness();api=Api();api.add();api.fail=True
    canvas._native_region_gate=NativeVideoRegionGate(api)
    original=QRegion(QRect(4,5,300,200));canvas._mask=original
    canvas.controller=NS(_process=Process())
    assert canvas._native_region_result['status']=='error' and canvas._presentation_parent_mask_active
    canvas.set_presentation_blocked('loading',True)
    assert canvas._presentation_saved_mask==original and len(canvas._mask_changes)==1
    api.fail=False;canvas.set_presentation_blocked('loading',True)
    assert canvas._native_region_result['empty_verified'] and not canvas._presentation_parent_mask_active
    assert canvas.mask()==original and len(canvas._mask_changes)==2


def test_old_success_result_cannot_claim_a_replaced_controller_or_host(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    for changed in ('controller','host'):
        canvas=canvas_harness();api=Api();api.add();canvas._native_region_gate=NativeVideoRegionGate(api)
        canvas.controller=NS(_process=Process());old=dict(canvas._native_region_result)
        if changed=='controller':canvas.controller=NS(_process=Process(91))
        else:canvas.internalWinId=lambda:20
        canvas._native_region_result=old
        canvas._sync_parent_presentation_mask()
        assert canvas._presentation_parent_mask_active
        assert not canvas.mask().isEmpty()


def test_closed_or_unsupported_gate_retains_parent_fallback(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    canvas=canvas_harness();api=Api();api.add();gate=canvas._native_region_gate=NativeVideoRegionGate(api)
    canvas.destroyed.connect(gate.close)
    canvas.controller=NS(_process=Process());gate.close()
    canvas._request_native_region_sync()
    assert canvas._presentation_parent_mask_active and canvas._native_region_result is None
    canvas.controller=NS(_process=Process(91),backend='qt-video-sink')
    assert canvas._native_region_result['status']=='unsupported_backend'
    assert canvas._presentation_parent_mask_active


def test_lost_region_readback_cannot_release_the_parent_fallback(monkeypatch):
    from twobyteasr.diagnostics import event_log
    monkeypatch.setattr(event_log,'emit',lambda *_a,**_k:None)
    canvas=canvas_harness();api=Api();api.add();gate=canvas._native_region_gate=NativeVideoRegionGate(api)
    canvas.controller=NS(_process=Process());api.regions[11]=None
    canvas._sync_parent_presentation_mask()
    assert canvas._presentation_parent_mask_active and not gate.empty_verified
    canvas._request_native_region_sync(recheck=True)
    assert not canvas._presentation_parent_mask_active and gate.empty_verified
