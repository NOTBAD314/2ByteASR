"""One owned Qwen aligner process per queue, serialized across ready shards."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

MARKER = '[2BYTEASR_QWEN3_ALIGNER] '


class ResidentAligner:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.lines = queue.Queue(maxsize=256)
        self.readers = []
        self.stopping = threading.Event()
        self.requests = 0

    def _reader(self, pipe, kind):
        try:
            for line in iter(pipe.readline, ''):
                while not self.stopping.is_set():
                    try:
                        self.lines.put((kind, line), timeout=.1)
                        break
                    except queue.Full:
                        pass
                if self.stopping.is_set():
                    break
        finally:
            pipe.close()

    def run(self, command, manifest, output, *, check):
        from .cache import record_run_event
        from ..system.processes import popen_hidden_subprocess
        queued = time.perf_counter()
        while not self.lock.acquire(timeout=.1):
            check()
        try:
            check()
            reuse = self.process is not None and self.process.poll() is None
            if not reuse:
                self._close_locked()
                self.stopping.clear()
                self.lines = queue.Queue(maxsize=256)
                self.process = popen_hidden_subprocess([*command, '--resident'],
                    purpose='Qwen3 resident forced aligner', process_factory=subprocess.Popen,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace', bufsize=1)
                self.readers = [threading.Thread(target=self._reader, args=(pipe, kind), daemon=True)
                    for pipe, kind in ((self.process.stdout, 'stdout'), (self.process.stderr, 'stderr'))]
                for reader in self.readers:
                    reader.start()
                record_run_event('asr_worker_started', model_id='qwen_aligner', backend='qwen3-aligner',
                    pid=self.process.pid, worker='qwen_aligner_worker.py', runtime=command[0],
                    role='forced_alignment', resident=True)
            else:
                self.process.stdin.write(json.dumps(dict(manifest=str(manifest), output=str(output)), ensure_ascii=False)+'\n')
                self.process.stdin.flush()
            self.requests += 1
            record_run_event('alignment_resource_acquired', worker_pid=self.process.pid,
                queue_seconds=round(time.perf_counter()-queued,6), model_reused=reuse,
                session_request=self.requests)
            started = time.perf_counter()
            recent = deque(maxlen=12)
            deadline = started + 3600.
            last_output=last_heartbeat=started
            while True:
                check()
                if time.perf_counter() >= deadline:
                    raise TimeoutError('Qwen3 对齐任务超过安全时限')
                try:
                    kind, line = self.lines.get(timeout=.1)
                except queue.Empty:
                    if self.process.poll() is not None:
                        raise RuntimeError('Qwen3 对齐进程退出：'+''.join(recent)[-1800:])
                    if time.perf_counter()-last_heartbeat>=5:
                        last_heartbeat=time.perf_counter()
                        record_run_event('alignment_progress',engine='QWEN3-ALIGNER',label='Qwen3 字级对齐',
                            worker_pid=self.process.pid,worker_state='running',heartbeat=True,
                            process_alive=True,last_output_seconds=round(last_heartbeat-last_output,1))
                    continue
                last_output=time.perf_counter()
                recent.append(line)
                if not line.startswith(MARKER):
                    continue
                detail = json.loads(line[len(MARKER):])
                record_run_event('alignment_progress', engine='QWEN3-ALIGNER', label='Qwen3 字级对齐',
                    worker_pid=self.process.pid, worker_state=detail.get('event'),
                    **{key:value for key,value in detail.items() if key not in ('event','output')})
                if detail.get('event') == 'request_completed' and Path(detail['output']) == Path(output):
                    payload = json.loads(Path(output).read_text(encoding='utf-8'))
                    payload['resident_session_request'] = self.requests
                    payload['model_load_count'] = 0 if reuse else 1
                    return payload
        except BaseException:
            self._close_locked()
            raise
        finally:
            self.lock.release()

    def _close_locked(self):
        from ..system.processes import stop_process_tree
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                try:
                    process.stdin.write('{"shutdown":true}\n')
                    process.stdin.flush()
                    process.stdin.close()
                    process.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    stop_process_tree(process)
            self.stopping.set()
            for reader in self.readers:
                reader.join(timeout=2)
            from .cache import record_run_event
            record_run_event('asr_worker_exited', model_id='qwen_aligner', backend='qwen3-aligner',
                pid=process.pid, returncode=process.poll(), resident=True,
                readers_stopped=not any(reader.is_alive() for reader in self.readers))
        self.readers = []

    def close(self):
        with self.lock:
            self._close_locked()


def run_resident(command, manifest, output, *, check):
    from .run_context import get_runtime_context
    context = get_runtime_context()
    # The queue owns this dictionary/lock, including contexts of local shards.
    key = ('qwen3', str(command[0]), str(command[-1]))
    with context.media_identity_lock:
        session = context.aligner_sessions.setdefault(key, ResidentAligner())
    return session.run(command, manifest, output, check=check)
