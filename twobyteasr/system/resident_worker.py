"""One reusable worker process for heavy pure-Python jobs (stall stage 3, 2026-10-22).

Python threads in the editor's process share the GIL with the GUI thread, so
seconds of pure-Python work on any thread stall the window (report-eb10).
Jobs that only need data in and data out (full caption rebuilds, encoding
recognition evidence rows) run here instead: the calling thread pickles the
input, waits on the pipe without the GIL and unpickles the answer.

A job is ``"twobyteasr.module:function"`` called with one picklable
argument. The process is spawned like the ASS compiler (works frozen) and
reused; ``call`` returns None on any failure and the caller does the work
itself, as it did before.
"""
from __future__ import annotations

import atexit
import importlib
import multiprocessing
import os
import threading
import time
from multiprocessing.connection import Connection
from multiprocessing.reduction import ForkingPickler
from contextlib import nullcontext

_PREFIX = "twobyteasr."


class ResidentJobCancelled(Exception):
    """A caller retired its in-flight request."""


def _worker_main(connection: Connection) -> None:
    from ..diagnostics.save_trace import SaveTrace, phase
    os.environ["TWOBYTEASR_PROCESS_ROLE"] = "resident-worker"
    ready_ns = time.perf_counter_ns()
    try:
        while True:
            try:
                connection.poll(None)
                receive_started = time.perf_counter_ns()
                raw_request = connection.recv_bytes()
                decode_started = time.perf_counter_ns()
                request = ForkingPickler.loads(raw_request)
                decoded_at = time.perf_counter_ns()
            except EOFError:
                break
            if request is None:
                break
            token, job, payload = request[:3]
            trace = SaveTrace(request[3]) if len(request) > 3 else None
            if trace:
                trace.add('ipc.request_receive', receive_started, decode_started, processed_bytes=len(raw_request))
                trace.add('ipc.request_decode', decode_started, decoded_at, processed_bytes=len(raw_request))
            started = time.perf_counter()
            try:
                with trace.activate() if trace else nullcontext():
                    with trace.observe_gc() if trace else nullcontext():
                        with phase('worker.import'):
                            module_name, function_name = job.split(":", 1)
                            if not module_name.startswith(_PREFIX):
                                raise ValueError(f"not a 2ByteASR job: {job}")
                            function = getattr(importlib.import_module(module_name), function_name)
                        with phase('worker.compute'):
                            value = function(payload)
                reply = (token, value, (time.perf_counter() - started) * 1000.0, "")
            except BaseException as exc:  # noqa: BLE001 - reported; the caller falls back
                reply = (token, None, 0.0, f"{type(exc).__name__}: {exc}")
            try:
                encoded_at = time.perf_counter_ns()
                encoded = ForkingPickler.dumps(reply)
                sent_at = time.perf_counter_ns()
                connection.send_bytes(encoded)
                ended_at = time.perf_counter_ns()
                if trace:
                    trace.add('ipc.reply_pickle', encoded_at, sent_at, processed_bytes=len(encoded))
                    trace.add('ipc.reply_send', sent_at, ended_at, processed_bytes=len(encoded))
                connection.send(dict(ready_ns=ready_ns, pid=os.getpid(), trace=trace.payload() if trace else None))
            except (BrokenPipeError, EOFError, OSError):
                break
    finally:
        connection.close()


class ResidentWorker:
    """One worker process; ``call`` blocks only the calling (non-GUI) thread."""

    CALL_TIMEOUT_S = 180.0
    # A fresh worker reads its first request once its imports are done.
    SEND_TIMEOUT_S = 30.0

    def __init__(self, name: str = "studio-resident-worker") -> None:
        self.name = name
        self._lock = threading.Lock()
        self._process = None
        self._connection = None
        self._token = 0
        self._closed = False
        self.calls = 0
        self.failures: list[str] = []
        self.last_ms = 0.0

    def _ensure_process(self) -> bool:
        if self._closed:
            return False
        if self._process is not None and self._process.is_alive() and self._connection is not None:
            return True
        self._stop(force=True)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(target=_worker_main, args=(child,), daemon=True, name=self.name)
        process.start()
        child.close()
        self._process, self._connection = process, parent
        return True

    def call(self, job: str, payload, *, wait: bool = True, cancel_check=None):
        """``job(payload)`` in the worker, or None. ``wait=False`` gives up when busy."""
        from ..diagnostics.save_trace import current as current_save_trace, phase
        trace = current_save_trace()
        lock_started = time.perf_counter_ns()
        if wait and cancel_check is not None:
            while True:
                if cancel_check():
                    return None
                if self._lock.acquire(timeout=0.05):
                    break
        elif not self._lock.acquire(blocking=wait):
            return None
        try:
            if trace:
                trace.add('resident.queue_wait', lock_started, time.perf_counter_ns())
            if cancel_check is not None and cancel_check():
                return None
            process_started = time.perf_counter_ns() if not self.running else None
            if not self._ensure_process():
                return None
            self._token += 1
            token = self._token
            connection, process = self._connection, self._process
            try:
                request = (token, job, payload, trace.save_id) if trace else (token, job, payload)
                if cancel_check is None:
                    self._send(connection, process, request, time.monotonic() + self.SEND_TIMEOUT_S)
                else:
                    self._send(connection, process, request, time.monotonic() + self.SEND_TIMEOUT_S,
                               cancel_check=cancel_check)
                deadline = time.monotonic() + self.CALL_TIMEOUT_S
                while not connection.poll(0.05):
                    if cancel_check is not None and cancel_check():
                        raise ResidentJobCancelled()
                    if self._closed or not process.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError("resident worker unavailable")
                with phase('ipc.reply_receive'):
                    raw_reply = connection.recv_bytes()
                with phase('ipc.reply_decode'):
                    reply_token, result, elapsed_ms, error = ForkingPickler.loads(raw_reply)
                if not connection.poll(5):
                    raise RuntimeError('resident worker missing completion receipt')
                metadata = connection.recv()
                if trace:
                    if process_started is not None:
                        trace.add('resident.startup_ready', process_started, metadata['ready_ns'], worker_pid=metadata['pid'])
                    child = metadata.get('trace') or {}
                    trace.events.extend(child.get('events', ()))
                    for key, value in child.get('counters', {}).items():
                        worker_key = f"worker_{metadata['pid']}_{key}"
                        trace.counters[worker_key] = trace.counters.get(worker_key, 0) + value
            except ResidentJobCancelled:
                # This job holds the worker lock. Retire its process so a late
                # reply cannot be mistaken for a later task's response.
                self._stop(force=True)
                return None
            except (BrokenPipeError, EOFError, OSError, RuntimeError, ValueError, TypeError) as exc:
                self.failures.append(f"{job}: {type(exc).__name__}: {exc}")
                del self.failures[:-32]
                self._stop(force=True)
                return None
            if reply_token != token or error:
                self.failures.append(f"{job}: {error or 'stale reply'}")
                del self.failures[:-32]
                return None
            if cancel_check is not None and cancel_check():
                return None
            self.calls += 1
            self.last_ms = elapsed_ms
            return result
        finally:
            self._lock.release()

    def _send(self, connection, process, message, deadline, *, cancel_check=None) -> None:
        """``connection.send`` that cannot block past ``deadline``.

        A large message fills the pipe; a worker that never reads (stuck, or
        still importing a script without a ``__main__`` guard) would block
        the sender forever.
        """
        from ..diagnostics.save_trace import current as current_save_trace, phase
        failure = []
        trace = current_save_trace()

        def send():
            try:
                with trace.activate() if trace else nullcontext():
                    with phase('ipc.request_pickle'):
                        encoded = ForkingPickler.dumps(message)
                    if trace:
                        trace.counters['ipc_request_bytes'] = trace.counters.get('ipc_request_bytes', 0) + len(encoded)
                    with phase('ipc.request_send'):
                        connection.send_bytes(encoded)
            except BaseException as exc:  # noqa: BLE001
                failure.append(exc)

        sender = threading.Thread(target=send, name=f"{self.name}-send", daemon=True)
        sender.start()
        while sender.is_alive():
            sender.join(0.05)
            if sender.is_alive() and cancel_check is not None and cancel_check():
                raise ResidentJobCancelled()
            if sender.is_alive() and (self._closed or not process.is_alive() or time.monotonic() > deadline):
                raise RuntimeError("resident worker does not read its requests")
        if failure:
            raise failure[0]

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.is_alive()

    def _stop(self, *, force: bool) -> None:
        process, connection = self._process, self._connection
        self._process = self._connection = None
        if connection is not None:
            try:
                if not force:
                    connection.send(None)
            except (BrokenPipeError, EOFError, OSError):
                pass
            try:
                connection.close()
            except OSError:
                pass
        if process is not None:
            process.join(timeout=1.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)

    def close(self) -> None:
        self._closed = True
        # Never wait long for a job in flight (closing may run on the GUI thread).
        if self._lock.acquire(timeout=0.2):
            try:
                self._stop(force=False)
            finally:
                self._lock.release()
        else:
            process = self._process
            if process is not None and process.is_alive():
                process.terminate()


_shared: ResidentWorker | None = None
_shared_lock = threading.Lock()


def shared_worker() -> ResidentWorker | None:
    """The process-wide worker, or None when switched off
    (``TWOBYTEASR_RESIDENT_WORKER=0``)."""
    global _shared
    if os.environ.get("TWOBYTEASR_RESIDENT_WORKER", "1") == "0":
        return None
    with _shared_lock:
        if _shared is None or _shared._closed:
            _shared = ResidentWorker()
        return _shared


def close_shared_worker() -> None:
    global _shared
    with _shared_lock:
        worker, _shared = _shared, None
    if worker is not None:
        worker.close()


atexit.register(close_shared_worker)
