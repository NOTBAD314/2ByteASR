import threading
import time
from types import SimpleNamespace
from twobyteasr.exports.export_run_log import ProcessLog, LoggedPipe


def test_slow_log_disk_never_holds_pipe_drainer(tmp_path):
    owner=SimpleNamespace(path=tmp_path, _lock=threading.RLock(), note=lambda *a:None)
    log=ProcessLog(owner,'001',{})
    blocked=threading.Event();release=threading.Event();write=log._write_buffers
    def slow_write():
        blocked.set();release.wait(3);write()
    log._write_buffers=slow_write
    try:
        log.output('stdout','frame=1\n');assert blocked.wait(1)
        started=time.monotonic()
        for i in range(2000):log.output('stdout',f'frame={i}\n')
        assert time.monotonic()-started<.3
        assert log._queue.qsize()<=1024
        assert log.dropped_chunks>0
    finally:
        release.set();log.finish()
    assert not log._writer.is_alive()
