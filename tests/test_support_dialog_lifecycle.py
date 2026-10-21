import threading
import time
import zipfile

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import isValid

from twobyteasr.diagnostics.event_log import EventStore
from twobyteasr.diagnostics.support_dialog import open_support_dialog


def pump_until(predicate, seconds=4):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        QTest.qWait(10)
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        if predicate():
            return
    assert predicate(), "report lifecycle did not settle"


@pytest.fixture
def environment(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    from twobyteasr.diagnostics import editor_diagnostics
    store=EventStore(tmp_path/"logs")
    store.record("fixture",{})
    monkeypatch.setattr(editor_diagnostics,"_INSTANCE",store)
    monkeypatch.setattr(editor_diagnostics,"install_early",lambda:store)
    owner=QWidget()
    yield app,owner,store
    pump_until(lambda:not any(t.name in {"diagnostic-view","diagnostic-export","diagnostic-cleanup"} and t.is_alive()
                              for t in threading.enumerate()))
    owner.close();owner.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    store.close_store(clean=True)


def test_closed_reports_release_widgets_and_reopen_with_new_marker(environment):
    app,owner,store=environment
    markers=[]
    for _ in range(3):
        dialog=open_support_dialog(owner)
        markers.append(dialog.identity.text())
        pump_until(lambda:hasattr(dialog,"_data"))
        dialog.accept()
        pump_until(lambda:not isValid(dialog))
        assert not owner.findChildren(QDialog,"diagnosticsDialog")
    assert len(set(markers))==3
    assert sum(r["event_name"]=="problem.marked" for r in store.recent)==3


def test_close_during_load_disposes_after_worker_and_drops_queued_refreshes(environment,monkeypatch):
    app,owner,store=environment
    from twobyteasr.diagnostics import support_bundle
    original=support_bundle.collect;gate=threading.Event();entered=threading.Event();calls=[]
    def delayed(*args,**kwargs):
        calls.append(1);entered.set()
        assert gate.wait(4)
        return original(*args,**kwargs)
    monkeypatch.setattr(support_bundle,"collect",delayed)
    dialog=open_support_dialog(owner)
    try:
        pump_until(entered.is_set)
        dialog._load();dialog._load()
        dialog.close()
        assert not dialog.isVisible()
        gate.set()
        pump_until(lambda:not isValid(dialog))
        assert len(calls)==1
    finally:
        gate.set()


def test_settings_owner_can_close_while_authorized_zip_finishes(environment,monkeypatch,tmp_path):
    app,owner,store=environment
    from twobyteasr.diagnostics import support_bundle
    original=support_bundle.export_report;gate=threading.Event();entered=threading.Event()
    def delayed(*args,**kwargs):
        entered.set()
        assert gate.wait(4)
        return original(*args,**kwargs)
    monkeypatch.setattr(support_bundle,"export_report",delayed)
    settings=QDialog(owner)
    dialog=open_support_dialog(settings)
    pump_until(lambda:hasattr(dialog,"_data"))
    target=tmp_path/"closed-export.zip"
    try:
        assert dialog.parentWidget() is owner
        assert open_support_dialog(owner) is dialog
        dialog._export_to(target)
        pump_until(entered.is_set)
        settings.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert isValid(dialog)
        dialog.close()
        gate.set()
        pump_until(lambda:not isValid(dialog))
        with zipfile.ZipFile(target) as archive:
            assert archive.testzip() is None and "events.jsonl" in archive.namelist()
    finally:
        gate.set()


def test_failed_worker_start_does_not_keep_closed_dialog_alive(environment,monkeypatch):
    app,owner,store=environment
    original=threading.Thread.start
    def failed(thread):
        if thread.name=="diagnostic-view":
            raise RuntimeError("controlled unavailable worker")
        return original(thread)
    monkeypatch.setattr(threading.Thread,"start",failed)
    dialog=open_support_dialog(owner)
    assert "读取诊断记录失败" in dialog.note.text()
    dialog.close()
    pump_until(lambda:not isValid(dialog))
