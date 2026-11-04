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

_PREFIX = "twobyteasr."


class ResidentJobCancelled(Exception):
    """A caller retired its in-flight request."""


def _worker_main(connection: Connection) -> None:
    os.environ["TWOBYTEASR_PROCESS_ROLE"] = "resident-worker"
    try:
        while True:
            try:
                request = connection.recv()
            except EOFError:
                break
            if request is None:
                break
            token, job, payload = request
            started = time.perf_counter()
            try:
                module_name, function_name = job.split(":", 1)
                if not module_name.startswith(_PREFIX):
                    raise ValueError(f"not a 2ByteASR job: {job}")
                function = getattr(importlib.import_module(module_name), function_name)
                reply = (token, function(payload), (time.perf_counter() - started) * 1000.0, "")
            except BaseException as exc:  # noqa: BLE001 - reported; the caller falls back
                reply = (token, None, 0.0, f"{type(exc).__name__}: {exc}")
            try:
                connection.send(reply)
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
        if wait and cancel_check is not None:
            while True:
                if cancel_check():
                    return None
                if self._lock.acquire(timeout=0.05):
                    break
        elif not self._lock.acquire(blocking=wait):
            return None
        try:
            if cancel_check is not None and cancel_check():
                return None
            if not self._ensure_process():
                return None
            self._token += 1
            token = self._token
            connection, process = self._connection, self._process
            try:
                if cancel_check is None:
                    self._send(connection, process, (token, job, payload), time.monotonic() + self.SEND_TIMEOUT_S)
                else:
                    self._send(connection, process, (token, job, payload), time.monotonic() + self.SEND_TIMEOUT_S,
                               cancel_check=cancel_check)
                deadline = time.monotonic() + self.CALL_TIMEOUT_S
                while not connection.poll(0.05):
                    if cancel_check is not None and cancel_check():
                        raise ResidentJobCancelled()
                    if self._closed or not process.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError("resident worker unavailable")
                reply_token, result, elapsed_ms, error = connection.recv()
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
        failure = []

        def send():
            try:
                connection.send(message)
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
