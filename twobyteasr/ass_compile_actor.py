"""Persistent process actor for authoritative ASS compilation."""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Callable

from .studio_revisions import SubtitleRenderRevision


@dataclass(frozen=True, slots=True)
class AssCompileResult:
    generation: int
    revision: SubtitleRenderRevision
    content: str
    compile_ms: float
    cache_hit: bool = False
    process_id: int = 0


def _compile_process(connection: Connection) -> None:
    os.environ["TWOBYTEASR_PROCESS_ROLE"] = "ass-compiler"
    from .ass_compiler import compile_ass_revision

    try:
        while True:
            try:
                request = connection.recv()
            except EOFError:
                break
            if request is None:
                break
            generation, revision = request
            started = time.perf_counter()
            try:
                content = compile_ass_revision(revision)
                try:
                    connection.send((generation, content, (time.perf_counter() - started) * 1000.0, ""))
                except (BrokenPipeError, EOFError, OSError):
                    break
            except BaseException as exc:
                try:
                    connection.send((generation, "", 0.0, f"{type(exc).__name__}: {exc}"))
                except (BrokenPipeError, EOFError, OSError):
                    break
    finally:
        connection.close()


class AssCompileActor:
    """Latest-wins request queue backed by one reusable Python process."""

    def __init__(
        self,
        on_ready: Callable[[AssCompileResult], None],
        on_failed: Callable[[int, str], None],
    ) -> None:
        self._on_ready = on_ready
        self._on_failed = on_failed
        self._condition = threading.Condition()
        self._pending: tuple[int, SubtitleRenderRevision, int] | None = None
        self._stopping = False
        self._process: multiprocessing.Process | None = None
        self._connection: Connection | None = None
        self._last_key: tuple | None = None
        self._last_content = ""
        self._cache_epoch = 0
        self._restart_count = 0
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="studio-ass-actor",
        )
        self._thread.start()

    @property
    def idle(self) -> bool:
        with self._condition:
            return self._pending is None and not bool(getattr(self, "_compiling", False))

    @property
    def process_id(self) -> int:
        process = self._process
        return int(process.pid or 0) if process is not None else 0

    @property
    def restart_count(self) -> int:
        return self._restart_count

    def submit(self, generation: int, revision: SubtitleRenderRevision) -> None:
        with self._condition:
            if self._stopping:
                return
            self._pending = (int(generation), revision, self._cache_epoch)
            self._condition.notify_all()

    def invalidate_cache(self) -> None:
        """A reopened/copied project can reuse its id and revision counters."""
        with self._condition:
            self._cache_epoch += 1
            self._pending = None
            self._last_key = None
            self._last_content = ""
            self._condition.notify_all()

    def _start_process(self) -> None:
        if self._process is not None and self._process.is_alive() and self._connection is not None:
            return
        replacing_dead_process = self._process is not None
        self._stop_process(force=False)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=_compile_process,
            args=(child,),
            daemon=True,
            name="studio-ass-compiler",
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        if replacing_dead_process:
            self._restart_count += 1

    def _stop_process(self, *, force: bool) -> None:
        process, connection = self._process, self._connection
        self._process = None
        self._connection = None
        if connection is not None:
            if not force:
                try:
                    connection.send(None)
                except (BrokenPipeError, EOFError, OSError):
                    pass
            try:
                connection.close()
            except OSError:
                pass
        if process is not None:
            process.join(timeout=1.0)
            if force and process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            if force and process.is_alive():
                process.kill()
                process.join(timeout=1.0)
            if not process.is_alive():
                try:
                    process.close()
                except ValueError:
                    pass

    def _compile(self, generation: int, revision: SubtitleRenderRevision) -> AssCompileResult:
        with self._condition:
            # Bound at submit/dequeue, before a close can race the worker's
            # call into _compile. A late old request never acquires a new epoch.
            key = (getattr(self, "_compile_cache_epoch", self._cache_epoch), revision.compile_key)
            if key == self._last_key and self._last_content:
                return AssCompileResult(
                    generation, revision, self._last_content, 0.0,
                    cache_hit=True, process_id=self.process_id,
                )
        for attempt in range(2):
            try:
                self._start_process()
                connection = self._connection
                process = self._process
                if connection is None or process is None:
                    raise RuntimeError("ASS compiler process unavailable")
                connection.send((generation, revision))
                while not connection.poll(0.05):
                    if self._stopping:
                        raise RuntimeError("ASS compiler actor stopping")
                    if not process.is_alive():
                        raise RuntimeError("ASS compiler process exited")
                response_generation, content, compile_ms, error = connection.recv()
                if error:
                    raise RuntimeError(error)
                result = AssCompileResult(
                    int(response_generation), revision, str(content), float(compile_ms),
                    process_id=int(process.pid or 0),
                )
                with self._condition:
                    if key[0] == self._cache_epoch:
                        self._last_key = key
                        self._last_content = result.content
                return result
            except (BrokenPipeError, EOFError, OSError, RuntimeError):
                self._stop_process(force=True)
                if attempt == 0 and not self._stopping:
                    self._restart_count += 1
                    continue
                raise
        raise RuntimeError("ASS compiler retry exhausted")

    def _run(self) -> None:
        self._compiling = False
        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    break
                request = self._pending
                self._pending = None
                self._compiling = True
                self._compile_cache_epoch = request[2]
            assert request is not None
            generation, revision, _epoch = request
            try:
                result = self._compile(generation, revision)
            except BaseException as exc:
                with self._condition:
                    stale = self._pending is not None and self._pending[0] > generation
                if not stale:
                    self._on_failed(generation, f"{type(exc).__name__}: {exc}")
            else:
                with self._condition:
                    stale = self._pending is not None and self._pending[0] > generation
                if not stale:
                    self._on_ready(result)
            finally:
                with self._condition:
                    self._compiling = False
                    self._condition.notify_all()
        self._stop_process(force=True)

    def wait_idle(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while (self._pending is not None or self._compiling) and time.monotonic() < deadline:
                self._condition.wait(min(0.05, deadline - time.monotonic()))
            return self._pending is None and not self._compiling

    def close(self) -> None:
        with self._condition:
            self._stopping = True
            self._pending = None
            self._condition.notify_all()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            self._stop_process(force=True)
            if threading.current_thread() is not self._thread:
                self._thread.join(timeout=1.0)
