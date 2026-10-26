import json
import zipfile
from PySide6.QtWidgets import QApplication,QWidget
from twobyteasr.diagnostics import window_motion,event_log
from twobyteasr.diagnostics.support_bundle import export_report


def test_window_reason_and_generation_survive_existing_zip_export(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    w=QWidget()
    store=event_log.EventStore(tmp_path/'logs')
    monkeypatch.setattr(event_log,'recorder',lambda:store)
    monkeypatch.setattr(window_motion,'_until',0)
    try:
        window_motion.record(w,'move-request',actor='constrain',reason='fit-initial-or-dialog')
        assert not any(r['kind']=='window.motion' for r in store.recent)
        store.set_detailed(60)
        window_motion.record(w,'move-request',actor='constrain',reason='fit-initial-or-dialog',target_logical=[-500,200])
        report=export_report(tmp_path/'window.zip',root=store.root,instance=store,scope='session')
        with zipfile.ZipFile(report['target']) as z:
            rows=[json.loads(line) for line in z.read('events.jsonl').splitlines()]
        row=next(r for r in rows if r['kind']=='window.motion')
        assert row['actor']=='constrain' and row['reason']=='fit-initial-or-dialog'
        assert row['target_logical']==[-500,200] and row['operation_generation']==0
        assert 'frame_logical' in row and 'dpr' in row
    finally:
        store.close_store(clean=True)
        w.deleteLater()


def test_window_trace_expiry_and_mouse_sampling_are_bounded(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    w=QWidget()
    store=event_log.EventStore(tmp_path/'logs')
    monkeypatch.setattr(event_log,'recorder',lambda:store)
    monkeypatch.setattr(window_motion,'_until',None)
    monkeypatch.setenv('TWOBYTEASR_WINDOW_TRACE_SECONDS','2')
    clock={'time':50.0}
    monkeypatch.setattr(window_motion.time,'monotonic',lambda:clock['time'])
    try:
        for _ in range(100):
            window_motion.record(w,'move',actor='qt',reason='observed')
        assert sum(r['kind']=='window.motion' for r in store.recent)==1
        clock['time']=53.0
        window_motion.record(w,'move-request',actor='constrain',reason='expired')
        assert sum(r['kind']=='window.motion' for r in store.recent)==1
    finally:
        store.close_store(clean=True)
        w.deleteLater()
