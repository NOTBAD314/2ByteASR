import pytest
from twobyteasr.acceptance.loading_native_probe import select_output


def test_desktop_crop_uses_verified_physical_monitor_origin():
    displays=[{'adapter_index':0,'output_index':1,'name':'left','rect':[-1920,0,0,1080],
               'attached':True,'rotation':1,'monitor':4},
              {'adapter_index':0,'output_index':0,'name':'main','rect':[0,0,3840,2160],
               'attached':True,'rotation':1,'monitor':5}]
    selected=select_output(displays,[-1800,100,-400,1000])
    assert selected['output_index']==1
    assert selected['crop']==[120,100,1400,900]


def test_capture_refuses_cross_monitor_and_unhandled_rotated_bounds():
    displays=[{'adapter_index':0,'output_index':0,'name':'main','rect':[0,0,3840,2160],
               'attached':True,'rotation':1,'monitor':5}]
    with pytest.raises(ValueError,match='exactly one'):
        select_output(displays,[-2,0,1400,900])
    displays[0]['rotation']=2
    with pytest.raises(ValueError,match='rotated'):
        select_output(displays,[2,2,1400,900])


def test_handle_observation_cannot_create_or_recreate_a_window():
    from twobyteasr.acceptance.loading_native_probe import existing_widget_handle
    class Widget:
        def internalWinId(self): return 123
        def winId(self): raise AssertionError('observer created a native window')
    assert existing_widget_handle(Widget()) == 123
    class Deleted(Widget):
        def internalWinId(self): raise RuntimeError('C++ object deleted')
    assert existing_widget_handle(Deleted()) == 0


def test_retired_root_is_not_enumerated_or_inspected():
    from types import SimpleNamespace
    from twobyteasr.acceptance.loading_native_probe import NativeLoadingProbe
    class Window:
        def internalWinId(self): return 0
        def winId(self): raise AssertionError('observer recreated window')
        def findChildren(self, _type): raise AssertionError('retired widgets inspected')
    probe=object.__new__(NativeLoadingProbe)
    probe.user=SimpleNamespace()
    result=probe.snapshot(Window(),None,'closed')
    assert result['target_retired'] and result['native_windows']==[]


def test_waiting_for_foreground_cannot_exhaust_native_capture_capacity(tmp_path,monkeypatch):
    from PySide6.QtCore import QCoreApplication,QEvent
    from PySide6.QtWidgets import QApplication,QWidget
    from twobyteasr.acceptance import loading_native_probe,studio_loading_audit
    app=QApplication.instance() or QApplication([])
    monkeypatch.setenv('TWOBYTEASR_LOADING_NATIVE_FORENSICS','1')
    class Probe:
        calls=0
        def snapshot(self,*args):
            self.calls+=1
            return {'desktop_coverage':{'foreground_owned':True,'all_points_owned':True}}
    monkeypatch.setattr(loading_native_probe,'NativeLoadingProbe',Probe)
    window=QWidget()
    studio_loading_audit.start(window,tmp_path)
    audit=window._studio_loading_audit
    audit.timer.stop();audit.native_timer.stop()
    try:
        for _ in range(3000):audit.native_sample('foreground-wait')
        assert audit.native_samples==[] and audit.native_probe.calls==0
        audit.native_capture_active=True
        audit.native_sample('capture-start')
        assert len(audit.native_samples)==1 and audit.native_probe.calls==1
        audit.closing=True
        audit.native_sample('close')
        assert len(audit.native_samples)==1 and audit.native_probe.calls==1
        audit.closing=False
        audit.native_samples=[{}]*2500
        audit.native_sample('over-capacity')
        assert audit.result['native_samples_truncated'] is True
        assert len(audit.native_samples)==2500
    finally:
        audit.finished=True
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
