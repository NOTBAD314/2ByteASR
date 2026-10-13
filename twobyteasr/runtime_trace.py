"""Non-blocking bounded runtime tracing for latency-sensitive GUI paths."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from contextlib import contextmanager
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Mapping


# studio-open.log is rotated to studio-open.previous.log at this size.
TRACE_LOG_MAX_BYTES = 16 * 1024 * 1024


class RuntimeTraceWriter:
    """Write diagnostics off the caller thread while retaining a bounded ring."""

    def __init__(self, *, capacity: int = 4096, ring_size: int = 2048) -> None:
        self._queue: queue.Queue[dict[str, object]] = queue.Queue(
            maxsize=max(32, int(capacity))
        )
        self._ring: deque[dict[str, object]] = deque(maxlen=max(32, int(ring_size)))
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._dropped = 0

    def emit(self, event: str, fields: Mapping[str, object]) -> None:
        now = datetime.now().astimezone()
        record: dict[str, object] = {
            "event": str(event),
            "time": now.isoformat(timespec="milliseconds"),
            "stamp": now.strftime("%H:%M:%S.%f")[:-3],
            **dict(fields),
        }
        with self._lock:
            self._ring.append(record)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    daemon=True,
                    name="studio-runtime-trace",
                )
                self._thread.start()
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            with self._lock:
                self._dropped += 1
            try:
                self._queue.put_nowait(record)
            except queue.Full:
                with self._lock:
                    self._dropped += 1

    @contextmanager
    def operation(
        self,
        name: str,
        *,
        project_id: str = "",
        media_path: str = "",
        blocking_ui_thread: bool | None = None,
        event: str = "STARTUP_OPERATION",
    ):
        """Trace one bounded operation without adding work to its caller.

        The caller can use this around a synchronous Studio-open section. The
        emitted record is deliberately self-contained so packaged traces can
        be analyzed without reconstructing timing from unrelated log lines.
        """
        started_wall_ms = time.time() * 1000.0
        started_perf = time.perf_counter()
        thread = threading.current_thread()
        if blocking_ui_thread is None:
            blocking_ui_thread = thread.name in {"MainThread", "Qt mainThread"}
        error = ""
        try:
            yield
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            ended_wall_ms = time.time() * 1000.0
            self.emit(
                event,
                {
                    "name": str(name),
                    "start_ms": round(started_wall_ms, 3),
                    "end_ms": round(ended_wall_ms, 3),
                    "duration_ms": round((time.perf_counter() - started_perf) * 1000.0, 3),
                    "thread": thread.name,
                    "blocking_ui_thread": bool(blocking_ui_thread),
                    "project_id": str(project_id or ""),
                    "media_path": str(media_path or ""),
                    "error": error,
                },
            )

    def recent(self) -> tuple[Mapping[str, object], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._ring)

    def freeze(self, reason: str = "", *, path: str | os.PathLike[str] | None = None) -> str:
        """Persist the current bounded trace buffer for rare failure evidence."""
        target = Path(path) if path else (
            Path("tmp") / "studio_debug" /
            f"trace-freeze-{int(time.time() * 1000)}.json"
        )
        payload = {
            "reason": str(reason or ""),
            "dropped": self.dropped,
            "records": list(self.recent()),
        }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            return ""
        self.emit(
            "TRACE_BUFFER_FROZEN",
            {"reason": str(reason or ""), "path": str(target), "record_count": len(payload["records"])},
        )
        return str(target)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def freeze_async(self, reason: str = "") -> str:
        """A single diagnostic write can never stall playback or form a queue."""
        with self._lock:
            if getattr(self, '_freeze_busy', False):
                return ""
            self._freeze_busy = True
        def write():
            try:
                self.freeze(reason)
            finally:
                with self._lock:
                    self._freeze_busy = False
        threading.Thread(target=write, name='studio-trace-freeze', daemon=True).start()
        return "pending"

    def flush(self, timeout: float = 1.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.005)
        return self._queue.unfinished_tasks == 0

    @staticmethod
    def _render(record: Mapping[str, object]) -> str:
        rendered = " ".join(
            f"{key}={json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, tuple)) else value}"
            for key, value in record.items()
            if key not in {"time", "stamp"}
        )
        return f"[{record.get('stamp', '')}] {rendered}\n"

    @staticmethod
    def _open_bounded(path: Path):
        """Append to ``path``; first move a full log to ``*.previous.log``.

        The file used to grow forever (1.27 GB on a daily machine). Like the
        child-process log, keep the current file plus one previous file."""
        try:
            if path.stat().st_size >= TRACE_LOG_MAX_BYTES:
                path.replace(path.with_name(path.stem + ".previous" + path.suffix))
        except OSError:
            pass
        stream = path.open("a", encoding="utf-8", buffering=1)
        return stream, stream.tell()

    def _run(self) -> None:
        local_appdata = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
        path = local_appdata / "2ByteASR" / "logs" / "studio-open.log"
        debug_enabled = os.environ.get("TWOBYTEASR_DEBUG_STUDIO") == "1"
        debug_path = Path("tmp") / "studio_debug" / "project-open-trace.jsonl"
        stream = None
        debug_stream = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream, written = self._open_bounded(path)
            if debug_enabled:
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                debug_stream = debug_path.open("a", encoding="utf-8", buffering=1)
            while True:
                record = self._queue.get()
                try:
                    line = self._render(record)
                    if written >= TRACE_LOG_MAX_BYTES:
                        stream.close()
                        stream, written = self._open_bounded(path)
                    stream.write(line)
                    written += len(line.encode("utf-8"))
                    if debug_stream is not None:
                        payload = {
                            key: value for key, value in record.items() if key != "stamp"
                        }
                        debug_stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                except OSError:
                    pass
                finally:
                    self._queue.task_done()
        except OSError:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
                else:
                    self._queue.task_done()
        finally:
            if debug_stream is not None:
                debug_stream.close()
            if stream is not None:
                stream.close()


GLOBAL_STUDIO_TRACE = RuntimeTraceWriter()


__all__ = ["GLOBAL_STUDIO_TRACE", "RuntimeTraceWriter"]
