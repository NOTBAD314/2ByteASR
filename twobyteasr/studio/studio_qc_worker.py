"""One page-owned QC process, one running request and one latest waiting request."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from PySide6.QtCore import QObject,Signal
from ..rendering.latest_work import LatestWork
from ..subtitle_rules.qc_process import read_packet,write_packet

class StudioQCWorker(QObject):
    ready=Signal(object,object,object)
    failed=Signal(object,str)
    def __init__(self,parent=None):
        super().__init__(parent)
        self._work=LatestWork('studio-qc-ipc')
        self._process=None
        self._closed=False
        self._lock=threading.Lock()
        self.submitted=self.completed=self.discarded=0
        self._serial=0

    def submit(self,snapshot,config,terminology,token):
        self._serial+=1;serial=self._serial;self.submitted+=1
        with self._work.condition:
            if self._work.pending is not None:self.discarded+=1
        submitted=time.perf_counter()
        self._work.submit(lambda:self._execute(snapshot,config,terminology,token,serial,submitted))

    def _execute(self,snapshot,config,terminology,token,serial,submitted):
        if self._closed or serial!=self._serial:self.discarded+=1;return
        try:
            with self._lock:
                if self._closed:return
                process=self._process
            if process is None or process.poll() is not None:
                from ..system.processes import popen_hidden_subprocess
                command=([sys.executable,'--studio-qc-worker'] if getattr(sys,'frozen',False)
                         else [sys.executable,'-B',str(Path(__file__).resolve().parents[2]/'quick_start.py'),'--studio-qc-worker'])
                process=popen_hidden_subprocess(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    purpose='bounded Studio QC computation; no model/provider work')
                with self._lock:
                    if self._closed or serial!=self._serial:
                        process.terminate();return
                    self._process=process
            begin=time.perf_counter()
            write_packet(process.stdin,(snapshot,config,terminology))
            reply=read_packet(process.stdout)
            if self._closed or serial!=self._serial:self.discarded+=1;return
            if 'error' in reply:raise RuntimeError(reply['error'])
            self.completed+=1
            self.ready.emit(token,reply['result'],{'queue_ms':(begin-submitted)*1000,
                'roundtrip_ms':(time.perf_counter()-begin)*1000,'compute_ms':reply['compute_ms'],'pid':process.pid})
        except Exception as error:
            with self._lock:
                process,self._process=self._process,None
            if process is not None and process.poll() is None:
                try:process.terminate()
                except OSError:pass
            if not self._closed and serial==self._serial:self.failed.emit(token,str(error))

    def cancel(self):
        self._serial+=1
        with self._work.condition:self._work.pending=None
        with self._lock:
            process,self._process=self._process,None
        if process is not None and process.poll() is None:
            try:process.terminate()
            except OSError:pass
        # No join/wait on the GUI thread. The actor's pipe read unwinds.

    def close(self):
        self._closed=True;self.cancel();self._work.close()

    def snapshot(self):
        process=self._process
        return {'submitted':self.submitted,'completed':self.completed,'discarded':self.discarded,
                'pending':self._work.pending is not None,'pid':process.pid if process else None,
                'alive':bool(process and process.poll() is None)}
