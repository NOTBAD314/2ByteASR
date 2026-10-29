"""Qt audio I/O has its own event loop, independent of UI paints/saves.

The GUI submits immutable PCM and synchronous short control commands. The
sink and its QBuffer are created/read/closed on this worker thread. Keeping
only a short hardware queue bounds pause without starving during UI stalls.
"""
from PySide6.QtCore import QObject,QThread,QBuffer,QByteArray,QIODevice,Signal,Slot,Qt,QCoreApplication


class _Output(QObject):
    def __init__(self):
        super().__init__();self.sink=None;self.buffer=None;self.result=None;self.failure=None

    @Slot(str,object)
    def command(self,action,args):
        self.failure=None
        try:
            if action=="create":
                from PySide6.QtMultimedia import QAudioSink
                device,fmt=args;self.sink=QAudioSink(device,fmt,self);self.sink.setBufferSize(7680)
            elif action=="start":
                self.sink.reset();self._close_buffer()
                self.buffer=QBuffer(self);self.buffer.setData(QByteArray(args));self.buffer.open(QIODevice.ReadOnly)
                self.sink.start(self.buffer)
            elif action=="reset":
                self.sink.reset();self._close_buffer()
            elif action=="volume":self.sink.setVolume(float(args))
            elif action=="suspend":self.sink.suspend()
            elif action=="resume":self.sink.resume()
            elif action=="stop":self.sink.stop();self._close_buffer()
            elif action=="query":
                self.result=(self.sink.processedUSecs(),self.sink.state(),self.sink.error(),self.sink.bufferSize())
            elif action=="dispose":
                self.sink.reset();self._close_buffer();self.sink.deleteLater();self.sink=None
        except Exception as exc:self.failure=str(exc)

    def _close_buffer(self):
        if self.buffer is not None:
            self.buffer.close();self.buffer.deleteLater();self.buffer=None


class AudioOutputSink(QObject):
    """The QAudioSink control surface used by CuePlayer, with thread ownership."""
    operation=Signal(str,object)

    def __init__(self,device,fmt,parent):
        super().__init__(parent);self.closed=False
        self._worker_thread=QThread(self);self.worker=_Output();self.worker.moveToThread(self._worker_thread)
        self._worker_thread.finished.connect(self.worker.deleteLater)
        self.operation.connect(self.worker.command,Qt.ConnectionType.BlockingQueuedConnection)
        self._worker_thread.start()
        try:
            self._call("create",(device,fmt))
        except Exception:
            self.closed=True;self._worker_thread.quit();self._worker_thread.wait(2000)
            raise
        parent.destroyed.connect(self.shutdown)
        app=QCoreApplication.instance()
        if app is not None:app.aboutToQuit.connect(self.shutdown)

    def _call(self,action,args=None):
        if self.closed:return None
        self.operation.emit(action,args)
        if self.worker.failure:raise RuntimeError(self.worker.failure)
        return self.worker.result

    def start(self,buffer):self._call("start",bytes(buffer.data()))
    def reset(self):self._call("reset")
    def stop(self):self._call("stop")
    def suspend(self):self._call("suspend")
    def resume(self):self._call("resume")
    def setVolume(self,value):self._call("volume",value)
    def processedUSecs(self):return self._call("query")[0]
    def state(self):return self._call("query")[1]
    def error(self):return self._call("query")[2]
    def bufferSize(self):return self._call("query")[3]

    @Slot()
    def shutdown(self):
        if self.closed:return
        self._call("dispose");self.closed=True;self._worker_thread.quit();self._worker_thread.wait(2000)
