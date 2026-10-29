from pathlib import Path
from types import SimpleNamespace
import json
import threading
import time
import zipfile
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.projects.editor_recovery import DraftRecovery, write_draft
from twobyteasr.diagnostics.editor_diagnostics import Recorder, export_bundle, latency_stats

@pytest.fixture(scope="module",autouse=True)
def app():
    yield QApplication.instance() or QApplication([])

def test_cancel_during_inflight_draft_cannot_publish_late(tmp_path,monkeypatch):
    import twobyteasr.projects.editor_recovery as module
    page=QWidget();page._autosave_write_lock=threading.Lock()
    recovery=DraftRecovery(page)
    event=threading.Event();event.set()
    lease=dict(valid=event,path=tmp_path/"draft.json")
    recovery.lease=lease
    entered=threading.Event();release=threading.Event()
    def slow(path,payload):
        entered.set();assert release.wait(3);write_draft(path,payload)
    monkeypatch.setattr(module,"write_draft",slow)
    def write():
        with page._autosave_write_lock:
            recovery.persist(dict(lease=lease,revision=1,payload={"text":"private"}),"saved.2byteproj")
    thread=threading.Thread(target=write);thread.start()
    assert entered.wait(3)
    start=time.perf_counter();recovery.discard()
    assert time.perf_counter()-start<.1
    release.set();thread.join(3)
    assert not thread.is_alive()
    assert not lease["path"].exists()
    page.close()

def test_draft_snapshot_is_private_and_bound_to_project(tmp_path,monkeypatch):
    from twobyteasr.studio.studio_cards import _SubtitleEditCardEditor
    page=QWidget()
    page.project=SimpleNamespace(project_id="A");page.project_path=tmp_path/"a.2byteproj"
    page.subtitle_edit_input=_SubtitleEditCardEditor(page);page._canvas_editor=page.subtitle_edit_input
    page._review_edit_lock={"cue_id":"first"}
    page.selected_cue_id="second"
    page._cue_lookup={"first":SimpleNamespace(text="原文")}
    recovery=DraftRecovery(page)
    page.subtitle_edit_input.setPlainText("日本語\n新字幕")
    recovery.changed();snapshot=recovery.snapshot()
    assert snapshot["payload"]["cue_id"]=="first"
    assert snapshot["payload"]["text"]=="日本語\n新字幕"
    assert page._cue_lookup["first"].text=="原文"
    page.project=SimpleNamespace(project_id="B")
    assert recovery.snapshot() is None
    recovery.timer.stop();page.close()

def test_dirty_guard_save_cancel_and_discard_include_unsubmitted_draft():
    from twobyteasr.projects.project_dirty_guard import ProjectDirtyGuard,DirtyGuardChoice
    calls=[]
    recovery=SimpleNamespace(snapshot=lambda:{"draft":True})
    page=SimpleNamespace(project=object(),_draft_recovery=recovery,_canvas_editor=object(),
        _cancel_canvas_inline_edit=lambda:calls.append("cancel"),undo_stack=SimpleNamespace(isClean=lambda:True))
    guard=ProjectDirtyGuard(page)
    assert guard.is_dirty()
    assert not guard.confirm("switch",choice_provider=lambda _:DirtyGuardChoice.CANCEL)
    assert calls==[]
    assert guard.confirm("switch",choice_provider=lambda _:DirtyGuardChoice.DISCARD)
    assert calls==["cancel"]

def test_default_bundle_has_no_raw_draft_or_private_fields(tmp_path,monkeypatch):
    monkeypatch.setattr(Recorder,"_environment",lambda self:None)
    import sys
    old=(sys.excepthook,threading.excepthook,sys.unraisablehook)
    recorder=Recorder(tmp_path/"sessions")
    try:
        recorder.record("EDIT",dict(current_text="PRIVATE_SUBTITLE",path="D:/SECRET/video.mp4",
            api_key="SECRET_KEY",duration_ms=19,frames=["file.py:3:func"]))
        write_draft(recorder.directory/"draft.json",{"text":"PRIVATE_SUBTITLE"})
        recorder.finish(clean=True)
        archive=tmp_path/"diagnostic.zip"
        export_bundle(archive,root=recorder.root)
        with zipfile.ZipFile(archive) as z:
            assert all("draft" not in name and not name.endswith(".dmp") for name in z.namelist())
            content=b"\n".join(z.read(name) for name in z.namelist())
            assert b"PRIVATE_SUBTITLE" not in content and b"SECRET" not in content
            assert b"duration_ms" in content
    finally:
        import faulthandler
        faulthandler.disable();recorder.fault_file.close()
        sys.excepthook,threading.excepthook,sys.unraisablehook=old

def test_percentile_uses_tail_not_average():
    stats=latency_stats(list(range(100)))
    assert stats["p95_ms"]==94 and stats["p99_ms"]==98 and stats["max_ms"]==99


def test_input_queue_probe_time_is_counted_only_once(monkeypatch):
    from twobyteasr.diagnostics import input_latency as module
    clock = [0.0]
    monkeypatch.setattr(module, 'time', SimpleNamespace(perf_counter=lambda: clock[0]))
    def delayed_queue_probe(_event):
        clock[0] = .2
        return 200.0
    monkeypatch.setattr(module, 'queued_ms', delayed_queue_probe)
    monkeypatch.setattr(module, 'record', lambda *args, **kwargs: None)
    editor = module.InputLatencyTextEdit()
    try:
        item = editor._begin_input('key', object())
        clock[0] = .21
        total = item['queue_ms'] + (clock[0]-item['started'])*1000
        assert total == pytest.approx(210.0)
    finally:
        editor.close()


def test_detailed_recording_limit_preserves_standard_events(tmp_path, monkeypatch):
    monkeypatch.setattr(Recorder, '_environment', lambda self: None)
    monkeypatch.setattr(Recorder, '_resources', lambda self: None)
    import sys, faulthandler
    old = sys.excepthook, threading.excepthook, sys.unraisablehook
    recorder = Recorder(tmp_path/'sessions')
    try:
        recorder.record('FIRST', {'time': 999, 'kind': 'nested kind', 'sequence': 0,
                                  'session_id': 'incorrect-session', 'format_version': 999})
        first = recorder.recent[-1]
        assert first['kind'] == 'FIRST' and first['sequence'] > 0 and first['time'] != 999
        assert first['reported_sequence'] == 0
        assert first['session_id'] == recorder.session_id and first['format_version'] == 1
        assert first['reported_time'] == 999
        assert recorder.standard_recording and not recorder.recording
        previous_id = recorder.recording_id
        recorder.start_recording()
        assert recorder.recording and recorder.recording_id != previous_id
        recorder.record('NEXT', {})
        assert recorder.recent[-1]['monotonic_ms'] > first['monotonic_ms']
        assert recorder.recent[-1]['sequence'] > first['sequence']
        recorder._detail_until = time.monotonic()-1
        assert not recorder.recording
        recorder.record('AFTER_DETAIL_EXPIRED', {})
        assert recorder.recent[-1]['kind'] == 'AFTER_DETAIL_EXPIRED'
        recorder.start_recording()
        recorder.stop_recording()
        recorder.record('AFTER_DETAIL_STOPPED', {})
        assert recorder.recent[-1]['kind'] == 'AFTER_DETAIL_STOPPED'
        assert not recorder.recording and recorder.standard_recording
    finally:
        recorder.finish(clean=True)
        faulthandler.disable(); recorder.fault_file.close()
        sys.excepthook, threading.excepthook, sys.unraisablehook = old


def test_diagnostic_environment_off_creates_no_recorder(monkeypatch):
    from twobyteasr.diagnostics import editor_diagnostics as module
    monkeypatch.setenv('TWOBYTEASR_EDITOR_DIAGNOSTICS', '0')
    monkeypatch.setattr(module, '_INSTANCE', None)
    monkeypatch.setattr(module, 'Recorder', lambda *_: pytest.fail('disabled recorder created'))
    assert module.install_early() is None



def test_technical_stall_context_preserved_without_private_payload():
    from twobyteasr.diagnostics.editor_diagnostics import safe
    value = safe(dict(context_after=dict(studio=dict(editing=True, current_text="PRIVATE", media_path="D:/PRIVATE"))))
    assert value["context_after"]["studio"]["editing"] is True
    assert value["context_after"]["studio"]["current_text"] == "<omitted>"
    assert "PRIVATE" not in json.dumps(value)

def test_exited_windows_process_is_not_a_live_previous_session(monkeypatch):
    import psutil
    from datetime import datetime, timezone
    from twobyteasr.diagnostics.editor_diagnostics import _session_process_alive
    stamp=datetime.now(timezone.utc).timestamp()
    process=SimpleNamespace(is_running=lambda:False, create_time=lambda:stamp)
    monkeypatch.setattr(psutil,"Process",lambda pid:process)
    row=dict(pid=4242,started=datetime.fromtimestamp(stamp,timezone.utc).isoformat())
    assert not _session_process_alive(row)
    process.is_running=lambda:True
    assert _session_process_alive(row)
    process.create_time=lambda:stamp+60
    assert not _session_process_alive(row)
