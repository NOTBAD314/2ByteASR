"""Local, out-of-process crash capture and resource samples for an owned queue."""
from __future__ import annotations
import json,os,time
from pathlib import Path

from ..storage.atomic_files import write_text_atomic


class QueueDiagnostics:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.pid=None;self.probe=None;self.created=None
        self.last_sample=0.;self.started=time.monotonic()
        self.samples=[];self.peak_rss=0

    def identify(self,payload):
        import psutil
        self.pid=int(payload['pid'])
        process=psutil.Process(self.pid);self.created=process.create_time()
        write_text_atomic(self.directory/f'worker-{self.pid}.json',json.dumps(payload,ensure_ascii=False))
        if os.name!='nt' or os.environ.get('TWOBYTEASR_NATIVE_CRASH_CAPTURE')=='0':return
        probe=Path(__file__).resolve().parents[2]/'tools/diagnostics/native_crash_probe.exe'
        if not probe.is_file():return
        try:
            from ..system.processes import popen_hidden_subprocess
            output=self.directory/'native-faults'/str(self.pid)
            self.probe=popen_hidden_subprocess([str(probe),str(self.pid),str(output)],purpose='recognition native crash observer')
        except OSError as exc:
            write_text_atomic(self.directory/'native-observer-error.json',json.dumps({'error':str(exc)}))

    def sample(self):
        if self.pid is None or time.monotonic()-self.last_sample<1:return
        self.last_sample=time.monotonic()
        try:
            import psutil
            parent=psutil.Process(self.pid)
            if parent.create_time()!=self.created:return
            rss=0;count=0
            for child in [parent,*parent.children(recursive=True)]:
                try:rss+=child.memory_info().rss;count+=1
                except psutil.Error:pass
            self.peak_rss=max(self.peak_rss,rss)
            self.samples.append({'seconds':round(self.last_sample-self.started,2),'tree_rss_bytes':rss,'processes':count})
        except Exception:pass

    def close(self):
        if self.probe is not None:
            try:self.probe.wait(timeout=3)
            except Exception:
                from ..system.processes import stop_process_tree
                stop_process_tree(self.probe)
        if self.pid is not None:
            write_text_atomic(self.directory/f'resources-{self.pid}.json',json.dumps({'pid':self.pid,
                'peak_tree_rss_bytes':self.peak_rss,'sampling_seconds':1,'samples':self.samples},ensure_ascii=False))
