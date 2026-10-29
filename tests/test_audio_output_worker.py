"""Qt buffer/sink ownership and shutdown do not depend on UI refill events."""
from PySide6.QtCore import QObject,QThread,QBuffer,QByteArray,QIODevice,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
import PySide6.QtMultimedia as multimedia
from twobyteasr.playback.audio_output_worker import AudioOutputSink
import pytest

APP=QApplication.instance() or QApplication([])


def test_output_and_buffer_share_worker_thread_and_controls_are_synchronous(monkeypatch):
    calls=[]
    class Sink(QObject):
        def __init__(self,_device,_format,parent):super().__init__(parent);calls.append(("create",QThread.currentThread()))
        def setBufferSize(self,_v):pass
        def reset(self):calls.append(("reset",QThread.currentThread()))
        def start(self,buffer):
            assert buffer.thread()==self.thread()==QThread.currentThread()
            calls.append((bytes(buffer.readAll()),QThread.currentThread()))
        def setVolume(self,_v):pass
        def suspend(self):calls.append(("pause",QThread.currentThread()))
        def resume(self):calls.append(("resume",QThread.currentThread()))
        def stop(self):calls.append(("stop",QThread.currentThread()))
        def processedUSecs(self):return 10
        def state(self):return multimedia.QAudio.State.ActiveState
        def error(self):return multimedia.QAudio.Error.NoError
        def bufferSize(self):return 7680
    monkeypatch.setattr(multimedia,"QAudioSink",Sink)
    parent=QObject();output=AudioOutputSink(None,None,parent)
    buffer=QBuffer();buffer.setData(QByteArray(b"complete pcm"));buffer.open(QIODevice.ReadOnly)
    output.start(buffer);output.suspend();output.resume()
    assert [x[0] for x in calls]==["create","reset",b"complete pcm","pause","resume"]
    assert all(thread!=QThread.currentThread() for _,thread in calls)
    assert output.processedUSecs()==10 and output.bufferSize()==7680
    output.shutdown();assert output.closed and not output._worker_thread.isRunning()
    output.shutdown()


def test_destroying_owner_stops_output_thread(monkeypatch):
    class Sink(QObject):
        def __init__(self,_d,_f,parent):super().__init__(parent)
        def setBufferSize(self,_v):pass
        def reset(self):pass
    monkeypatch.setattr(multimedia,"QAudioSink",Sink)
    parent=QObject();output=AudioOutputSink(None,None,parent)
    thread=output._worker_thread;thread.setParent(None)
    parent.deleteLater();QCoreApplication.sendPostedEvents(parent,QEvent.DeferredDelete);APP.processEvents()
    assert output.closed and not thread.isRunning()
    thread.deleteLater()


def test_initialization_failure_leaves_no_running_thread(monkeypatch):
    class BadSink:
        def __init__(self,*_args):raise RuntimeError("device unavailable")
    monkeypatch.setattr(multimedia,"QAudioSink",BadSink)
    parent=QObject()
    with pytest.raises(RuntimeError,match="device unavailable"):
        AudioOutputSink(None,None,parent)
    output=next(x for x in parent.children() if isinstance(x,AudioOutputSink))
    assert output.closed and not output._worker_thread.isRunning()
