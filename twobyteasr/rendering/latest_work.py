"""One persistent worker and one replaceable waiting job for preview work."""
import threading


class LatestWork:
    def __init__(self,name):
        self.condition=threading.Condition();self.pending=None;self.closed=False
        self.thread=threading.Thread(target=self._run,name=name,daemon=True);self.thread.start()

    def submit(self,callback):
        with self.condition:
            if self.closed:return
            self.pending=callback;self.condition.notify()

    def close(self):
        with self.condition:self.closed=True;self.pending=None;self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.pending is not None or self.closed)
                if self.closed:return
                callback,self.pending=self.pending,None
            try:callback()
            except Exception:pass
