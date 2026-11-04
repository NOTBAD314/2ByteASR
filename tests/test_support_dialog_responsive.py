import threading
import time
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest
from shiboken6 import isValid


def test_slow_collection_is_interactive_deduplicated_and_close_cancels(tmp_path,monkeypatch):
    from twobyteasr.diagnostics import editor_diagnostics,support_bundle
    from twobyteasr.diagnostics.event_log import EventStore
    from twobyteasr.diagnostics.support_dialog import open_support_dialog
    app=QApplication.instance() or QApplication([])
    store=EventStore(tmp_path/'logs')
    monkeypatch.setattr(editor_diagnostics,'_INSTANCE',store)
    calls=[];stopped=threading.Event()
    def slow(*args,cancelled=None,**kwargs):
        calls.append(1)
        while not cancelled():
            time.sleep(.01)
        stopped.set()
        raise InterruptedError('closed')
    monkeypatch.setattr(support_bundle,'collect',slow)
    owner=QWidget();owner.show()
    try:
        dialog=open_support_dialog(owner)
        QTest.qWait(40)
        dialog.description.setFocus();QTest.keyClicks(dialog.description,'Still responsive')
        assert dialog.description.text()=='Still responsive'
        assert not dialog.export.isEnabled()
        for _ in range(5):assert open_support_dialog(owner) is dialog
        QTest.qWait(50)
        assert len(calls)==1 and dialog._jobs==1
        dialog.close()
        deadline=time.monotonic()+2
        while isValid(dialog) and time.monotonic()<deadline:QTest.qWait(10)
        assert stopped.is_set()
        assert not isValid(dialog)
        assert owner._support_dialog is None
    finally:
        owner.close();store.close_store(clean=True)


def test_collection_deadline_and_cancel_are_explicit(tmp_path):
    import pytest
    from twobyteasr.diagnostics.support_bundle import collect
    with pytest.raises(InterruptedError):
        collect(tmp_path,cancelled=lambda:True)
    with pytest.raises(TimeoutError):
        collect(tmp_path,deadline=time.monotonic()-1)
