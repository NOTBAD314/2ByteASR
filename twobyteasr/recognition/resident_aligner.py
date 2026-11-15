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
        self.loaded_signature = None

    def _reader(self, pipe, kind, incoming, stopping):
        try:
            for line in iter(pipe.readline, ''):
                while not stopping.is_set():
                    try:
                        incoming.put((kind, line), timeout=.1)
                        break
                    except queue.Full:
                        pass
                if stopping.is_set():
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
            from .alignment_backend import fingerprint
            request = json.loads(Path(manifest).read_text(encoding='utf-8'))
            command_identity = [str(value) for value in command]
            for flag in ('--manifest', '--output'):
                index = command_identity.index(flag)
                command_identity[index+1] = '<request-file>'
            signature = fingerprint(dict(command=command_identity, identity=request.get('policy', {}).get('alignment_identity')))
            reuse = self.process is not None and self.process.poll() is None and signature == self.loaded_signature
            if not reuse:
                self._close_locked()
                self.stopping = threading.Event()
                self.lines = queue.Queue(maxsize=256)
                self.process = popen_hidden_subprocess([*command, '--resident'],
                    purpose='Qwen3 resident forced aligner', process_factory=subprocess.Popen, own_process_tree=True,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace', bufsize=1)
                self.loaded_signature = signature
                self.readers = [threading.Thread(target=self._reader, args=(pipe, kind, self.lines, self.stopping), daemon=True)
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
                record_run_event('alignment_progress', engine='QWEN3-ALIGNER',
                    label='Qwen3 词级对齐' if detail.get('pass_id')=='word' else 'Qwen3 字级对齐',
                    worker_pid=self.process.pid, worker_state=detail.get('event'),
                    **{key:value for key,value in detail.items() if key not in ('event','output')})
                if detail.get('event') == 'request_completed' and Path(detail['output']) == Path(output):
                    payload = json.loads(Path(output).read_text(encoding='utf-8'))
                    payload['resident_session_request'] = self.requests
                    payload['model_load_count'] = 0 if reuse else 1
                    return payload
        except BaseException:
            self._close_locked(force=True)
            raise
        finally:
            self.lock.release()

    def _close_locked(self, *, force=False):
        from ..system.processes import stop_process_tree
        process = self.process
        self.loaded_signature = None
        if process is None:
            return
        owned_job = getattr(process, '_request_job', None)
        # Windows Python venv redirectors can exit before their actual model
        # child releases mmap handles. The existing Job owns every descendant.
        if force and owned_job is not None:
            owned_job.close(timeout=3)
            process.wait(timeout=3)
        elif process.poll() is None:
            try:
                if force:
                    stop_process_tree(process)
                else:
                    process.stdin.write('{"shutdown":true}\n')
                    process.stdin.flush()
                    process.stdin.close()
                    process.wait(timeout=5)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                stop_process_tree(process)
        if owned_job is not None:
            owned_job.close(timeout=3)  # also after redirector/root exit
        self.stopping.set()
        for reader in self.readers:
            reader.join(timeout=2)
        from .cache import record_run_event
        record_run_event('asr_worker_exited', model_id='qwen_aligner', backend='qwen3-aligner',
            pid=process.pid, returncode=process.poll(), resident=True, forced=force,
            owned_descendants_released=owned_job is not None,
            readers_stopped=not any(reader.is_alive() for reader in self.readers))
        self.process = None
        self.readers = []

    def close(self):
        with self.lock:
            self._close_locked()


def run_resident(command, manifest, output, *, check):
    from .run_context import get_runtime_context
    context = get_runtime_context()
    # The queue owns this dictionary/lock, including contexts of local shards.
    key = ('qwen3',)
    with context.media_identity_lock:
        session = context.aligner_sessions.setdefault(key, ResidentAligner())
    return session.run(command, manifest, output, check=check)
