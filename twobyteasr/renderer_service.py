"""Persistent Remotion renderer client with a versioned JSON-lines protocol."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .processes import popen_hidden_subprocess, stop_process_tree, renderer_node_command, renderer_child_environment


PROTOCOL_VERSION = 1
RENDERER_JOB_KINDS = frozenset({
    "production", "diagnostic", "thumbnail", "card_preview",
})


class RendererServiceError(RuntimeError):
    pass


class RendererLiveRequestSuperseded(RendererServiceError):
    """The owning clock or content changed while a paused frame was pending."""


@dataclass(frozen=True)
class RendererJob:
    output: str
    input_props: Mapping[str, Any]
    frame: int
    composition_id: str = "SubtitleOverlay"
    job_id: str = ""
    job_kind: str = "production"
    cue_id: str = ""
    project_id: str = ""
    appearance_generation: int = 0
    snapshot_hash: str = ""
    graph_hash: str = ""
    requested_at: float = 0.0

    def __post_init__(self) -> None:
        # Identity must survive the request serialization round-trip. In
        # particular, require_job() must be able to find a job created without
        # an explicit caller-supplied id.
        if not self.job_id:
            object.__setattr__(self, "job_id", uuid.uuid4().hex)
        if not self.requested_at:
            object.__setattr__(self, "requested_at", time.time())
        kind = str(self.job_kind or "production")
        if kind not in RENDERER_JOB_KINDS:
            raise ValueError(f"unsupported renderer job kind: {kind}")
        object.__setattr__(self, "job_kind", kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "input_props": dict(self.input_props),
            "frame": max(0, int(self.frame)),
            "composition_id": self.composition_id,
            "job_id": self.job_id,
            "job_kind": self.job_kind,
            "cue_id": str(self.cue_id or ""),
            "project_id": str(self.project_id or ""),
            "appearance_generation": max(0, int(self.appearance_generation)),
            "snapshot_hash": str(self.snapshot_hash or ""),
            "graph_hash": str(self.graph_hash or ""),
            "requested_at": float(self.requested_at),
        }


@dataclass(frozen=True)
class RendererResult:
    request_id: str
    status: str
    generation: int
    renderer_generation: int
    queue_ms: float
    render_ms: float
    total_ms: float
    outputs: tuple[str, ...]
    jobs: tuple[Mapping[str, Any], ...] = ()
    telemetry: tuple[Mapping[str, Any], ...] = ()
    error: str = ""

    def require_job(self, expected: RendererJob) -> Mapping[str, Any]:
        match = next(
            (
                item for item in self.jobs
                if str(item.get("job_id") or "") == str(expected.job_id or "")
            ),
            None,
        )
        if match is None:
            raise RendererServiceError(
                f"renderer result missing job identity: {expected.job_id}"
            )
        expected_payload = expected.to_dict()
        fields = (
            "job_kind", "cue_id", "project_id", "appearance_generation",
            "snapshot_hash", "graph_hash", "requested_at",
        )
        mismatched = [
            field for field in fields
            if match.get(field) != expected_payload.get(field)
        ]
        if mismatched:
            raise RendererServiceError(
                "renderer result identity mismatch: " + ",".join(mismatched)
            )
        return match


@dataclass
class RendererRequestHandle:
    service: "RendererService"
    request_id: str
    generation: int
    _event: threading.Event = field(default_factory=threading.Event)
    _response: dict[str, Any] | None = None
    _error: BaseException | None = None

    def cancel(self) -> None:
        self.service.cancel(self.request_id)

    def result(self, timeout: float | None = None) -> RendererResult:
        if not self._event.wait(timeout):
            self.cancel()
            raise RendererServiceError(f"renderer request timed out: {self.request_id}")
        if self._error is not None:
            raise RendererServiceError(str(self._error)) from self._error
        payload = self._response or {}
        status = str(payload.get("status") or "ERROR")
        result = RendererResult(
            request_id=self.request_id,
            status=status,
            generation=int(payload.get("generation") or self.generation),
            renderer_generation=int(payload.get("renderer_generation") or 0),
            queue_ms=float(payload.get("queue_ms") or 0.0),
            render_ms=float(payload.get("render_ms") or 0.0),
            total_ms=float(payload.get("total_ms") or 0.0),
            outputs=tuple(
                str(item.get("output") or "")
                for item in payload.get("results", ())
                if isinstance(item, Mapping)
            ),
            jobs=tuple(
                dict(item) for item in payload.get("results", ())
                if isinstance(item, Mapping)
            ),
            telemetry=tuple(
                item for item in payload.get("telemetry", ()) if isinstance(item, Mapping)
            ),
            error=str(payload.get("error") or ""),
        )
        if status != "OK":
            raise RendererServiceError(result.error or f"renderer returned {status}")
        return result


class RendererService:
    """Own one lazy Node service and recover one broken service generation."""

    def __init__(self, renderer_root: str | Path | None = None) -> None:
        self.root = Path(renderer_root or Path(__file__).resolve().parent.parent / "renderer").resolve()
        self._process: Any | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: dict[str, RendererRequestHandle] = {}
        self._telemetry: list[dict[str, Any]] = []
        self._generation = 0
        self._service_generation = 0
        self._shutdown_generation = 0
        self._closing = False
        self._stderr_tail: queue.Queue[str] = queue.Queue(maxsize=80)

    @property
    def process_id(self) -> int | None:
        with self._lock:
            process = self._process
            return int(process.pid) if process is not None and process.poll() is None else None

    @property
    def service_generation(self) -> int:
        with self._lock:
            return self._service_generation

    def telemetry(self) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            return tuple(self._telemetry)

    def _node_binary(self) -> str:
        try:return renderer_node_command(self.root)[0]
        except RuntimeError as exc:raise RendererServiceError(str(exc)) from exc

    def _start_locked(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        service_path = self.root / "service.mjs"
        if not service_path.is_file():
            raise RendererServiceError(f"renderer service entry is missing: {service_path}")
        self._closing = False
        process = popen_hidden_subprocess(
            renderer_node_command(self.root,service_path),
            purpose="persistent advanced renderer service",
            cwd=self.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=renderer_child_environment(),
        )
        self._process = process
        self._service_generation += 1
        self._reader = threading.Thread(
            target=self._read_stdout,
            args=(process, self._service_generation),
            daemon=True,
            name="renderer-service-reader",
        )
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            args=(process,),
            daemon=True,
            name="renderer-service-stderr",
        )
        self._reader.start()
        self._stderr_reader.start()

    def _read_stderr(self, process: Any) -> None:
        stream = process.stderr
        if stream is None:
            return
        for line in stream:
            clean = line.rstrip()
            if not clean:
                continue
            if self._stderr_tail.full():
                try:
                    self._stderr_tail.get_nowait()
                except queue.Empty:
                    pass
            self._stderr_tail.put_nowait(clean[-1000:])

    def _read_stdout(self, process: Any, service_generation: int) -> None:
        stream = process.stdout
        if stream is None:
            self._fail_generation(process, RendererServiceError("renderer stdout is unavailable"))
            return
        malformed = False
        for line in stream:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                malformed = True
                self._fail_generation(process, RendererServiceError(f"malformed renderer response: {exc}"))
                break
            if not isinstance(payload, dict) or int(payload.get("version") or 0) != PROTOCOL_VERSION:
                malformed = True
                self._fail_generation(process, RendererServiceError("invalid renderer protocol response"))
                break
            request_id = str(payload.get("request_id") or "")
            with self._lock:
                for item in payload.get("telemetry", ()):
                    if isinstance(item, dict):
                        self._telemetry.append(item)
                if len(self._telemetry) > 800:
                    del self._telemetry[:-800]
                handle = self._pending.pop(request_id, None) if request_id else None
            if handle is not None:
                handle._response = payload
                handle._event.set()
        if not malformed and not self._closing:
            code = process.poll()
            self._fail_generation(
                process,
                RendererServiceError(f"renderer service exited unexpectedly ({code})"),
            )

    def _fail_generation(self, process: Any, error: BaseException) -> None:
        with self._lock:
            if process is not self._process:
                return
            self._process = None
            pending = tuple(self._pending.values())
            self._pending.clear()
        if process.poll() is None:
            try:
                stop_process_tree(process)
            except Exception:
                pass
        for handle in pending:
            handle._error = error
            handle._event.set()

    def _send(self, payload: Mapping[str, Any]) -> None:
        with self._lock:
            self._start_locked()
            process = self._process
        assert process is not None
        data = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                process.stdin.write(data)
                process.stdin.flush()
        except (AttributeError, BrokenPipeError, OSError) as exc:
            self._fail_generation(process, exc)
            raise RendererServiceError(f"renderer service pipe failed: {exc}") from exc

    def submit(
        self,
        jobs: Sequence[RendererJob],
        *,
        generation: int | None = None,
        priority: int = 0,
        snapshot_identity: str = "",
        render_type: str = "still",
        resolution: tuple[int, int] = (0, 0),
        batch_group: str = "",
        timeout: float = 120.0,
    ) -> RendererRequestHandle:
        if not jobs:
            raise ValueError("renderer jobs cannot be empty")
        with self._lock:
            self._generation = max(self._generation + 1, int(generation or 0))
            effective_generation = int(generation or self._generation)
        request_id = uuid.uuid4().hex
        handle = RendererRequestHandle(self, request_id, effective_generation)
        payload = {
            "version": PROTOCOL_VERSION,
            "type": "render",
            "request_id": request_id,
            "generation": effective_generation,
            "priority": int(priority),
            "snapshot_identity": str(snapshot_identity),
            "render_type": str(render_type),
            "resolution": [int(resolution[0]), int(resolution[1])],
            "batch_group": str(batch_group or snapshot_identity or request_id),
            "deadline_epoch_ms": int((time.time() + max(0.1, float(timeout))) * 1000),
            "jobs": [job.to_dict() for job in jobs],
        }
        with self._lock:
            self._pending[request_id] = handle
        try:
            self._send(payload)
        except Exception:
            with self._lock:
                self._pending.pop(request_id, None)
            raise
        return handle

    def render(
        self,
        jobs: Sequence[RendererJob],
        *,
        timeout: float = 120.0,
        restart_once: bool = True,
        **kwargs: Any,
    ) -> RendererResult:
        attempts = 2 if restart_once else 1
        last_error: BaseException | None = None
        with self._lock:
            shutdown_generation = self._shutdown_generation
        for attempt in range(attempts):
            try:
                return self.submit(jobs, timeout=timeout, **kwargs).result(timeout + 5.0)
            except RendererServiceError as exc:
                last_error = exc
                with self._lock:
                    shutting_down = self._shutdown_generation != shutdown_generation
                if shutting_down:
                    break
                if attempt + 1 >= attempts:
                    break
                self.restart(reason="client_retry")
        raise RendererServiceError(str(last_error or "renderer request failed"))

    def cancel(self, request_id: str) -> None:
        try:
            self._send({
                "version": PROTOCOL_VERSION,
                "type": "cancel",
                "request_id": str(request_id),
            })
        except RendererServiceError:
            return

    def warm(self, *, timeout: float = 120.0) -> RendererResult:
        request_id = uuid.uuid4().hex
        handle = RendererRequestHandle(self, request_id, 0)
        with self._lock:
            self._pending[request_id] = handle
        self._send({"version": PROTOCOL_VERSION, "type": "warm", "request_id": request_id})
        return handle.result(timeout)

    # ------------------------------------------------------------------
    # Live web preview (round 19): a persistent page rendering the ACTIVE
    # web-theme cue at the playhead; ~20Hz frame pump from the UI side.
    # ------------------------------------------------------------------

    def _live_request(self, message: Mapping[str, Any], *, timeout: float, still_current=None) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        handle = RendererRequestHandle(self, request_id, 0)
        with self._lock:
            self._pending[request_id] = handle
        self._send({
            "version": PROTOCOL_VERSION,
            **dict(message),
            "request_id": request_id,
        })
        deadline = time.monotonic() + timeout
        poll_interval = .01 if still_current is not None else timeout
        while not handle._event.wait(min(poll_interval, max(0., deadline-time.monotonic()))):
            if still_current is not None and not still_current():
                self._send({'version':PROTOCOL_VERSION, 'type':'live_cancel',
                    'session_id':message.get('session_id','default'), 'request_id':uuid.uuid4().hex})
                with self._lock:
                    self._pending.pop(request_id, None)
                raise RendererLiveRequestSuperseded('paused frame superseded by current clock/content')
            if time.monotonic() >= deadline:
                with self._lock:
                    self._pending.pop(request_id, None)
                raise RendererServiceError(f"renderer live request timed out: {message.get('type')}")
        if still_current is not None and not still_current():
            raise RendererLiveRequestSuperseded('paused frame completed after clock/content changed')
        if handle._error is not None:
            raise RendererServiceError(str(handle._error)) from handle._error
        payload = handle._response or {}
        if str(payload.get("status") or "ERROR") != "OK":
            raise RendererServiceError(
                str(payload.get("error") or f"renderer live {message.get('type')} failed")
            )
        return payload

    def live_set(self, html: str, *, width: int, height: int, timeout: float = 45.0) -> None:
        """(Re)load the live preview page (theme HTML + seek driver)."""
        self._live_request(
            {"type": "live_set", "html": str(html), "width": int(width), "height": int(height)},
            timeout=timeout,
        )

    def warm_live(self, *, timeout=10.0):
        return self._live_request({"type": "warm_live"}, timeout=timeout)

    def live_frame(self, *, cue_ms: float, stage_ms: float, timeout: float = 5.0) -> bytes:
        """Scrub the live page to (cue_ms, stage_ms) and return PNG bytes."""
        payload = self._live_request(
            {"type": "live_frame", "cue_ms": float(cue_ms), "stage_ms": float(stage_ms)},
            timeout=timeout,
        )
        data = str(payload.get("png_base64") or "")
        if not data:
            raise RendererServiceError("renderer live frame returned no image")
        import base64

        return base64.b64decode(data)

    # --- 二十轮：screencast 推帧模式（~30fps，无逐帧请求往返） ----------

    def live_play(
        self, *, cue_ms: float, stage_ms: float, rate: float = 1.0,
        every_nth_frame: int = 2, timeout: float = 8.0,
    ) -> None:
        """Scrub-sync once, then let the page run animations at ``rate``."""
        self._live_request(
            {
                "type": "live_play",
                "cue_ms": float(cue_ms),
                "stage_ms": float(stage_ms),
                "rate": float(rate),
                "every_nth_frame": int(every_nth_frame),
            },
            timeout=timeout,
        )

    def live_pause(self, *, cue_ms: float, stage_ms: float, timeout: float = 8.0, still_current=None) -> bytes | None:
        """Pause-and-scrub to the exact moment; returns a seed frame if any."""
        payload = self._live_request(
            {"type": "live_pause", "cue_ms": float(cue_ms), "stage_ms": float(stage_ms)},
            timeout=timeout, still_current=still_current,
        )
        self.last_live_pause_metrics = {key:payload.get(key) for key in ('driver_ms','settle_ms','capture_ms','total_ms')}
        data = str(payload.get("png_base64") or "")
        if not data:
            return None
        import base64

        return base64.b64decode(data)

    def live_text(self, *, text: str, speaker: str = "", duration_ms: float = 2400,
                  placement: dict | None = None,
                  prepared_cues: list | None = None,
                  timeout: float = 5.0) -> None:
        """Swap the cue text on the loaded page without a reload (~50ms)."""
        result = self._live_request(
            {"type": "live_text", "text": str(text or ""), "speaker": str(speaker or ""),
             "duration_ms": max(50, float(duration_ms)), "placement": placement or {},
             "prepared_cues": prepared_cues or []},
            timeout=timeout,
        )
        self.last_live_text_metrics = result.get('metrics', {})

    def live_latest(self, *, since_seq: int = 0, timeout: float = 3.0) -> tuple[int, bytes | None]:
        """Return (seq, png) of the newest screencast frame, or (since_seq, None)."""
        payload = self._live_request(
            {"type": "live_latest", "since_seq": int(since_seq)}, timeout=timeout,
        )
        seq = int(payload.get("seq") or 0)
        data = str(payload.get("png_base64") or "")
        if payload.get("unchanged") or not data:
            return seq, None
        self.last_live_frame_metrics = {key:payload.get(key) for key in
            ('cdp_interval_ms','cdp_ack_ms','latest_age_ms','skipped_sequences','frame_source','captured_ms')}
        import base64

        return seq, base64.b64decode(data)



    def inject_failure(self, failure: str, *, timeout: float = 5.0) -> None:
        request_id = uuid.uuid4().hex
        handle = RendererRequestHandle(self, request_id, 0)
        with self._lock:
            self._pending[request_id] = handle
        self._send({
            "version": PROTOCOL_VERSION,
            "type": "inject_failure",
            "request_id": request_id,
            "failure": str(failure),
        })
        if failure != "node_crash":
            handle.result(timeout)
        else:
            handle._event.wait(timeout)

    def restart(self, *, reason: str = "manual") -> None:
        del reason
        with self._lock:
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            stop_process_tree(process)

    def shutdown(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            process = self._process
            self._closing = True
            self._shutdown_generation += 1
            pending = tuple(self._pending.values())
            self._pending.clear()
        shutdown_error = RendererServiceError("renderer service shut down")
        for handle in pending:
            handle._error = shutdown_error
            handle._event.set()
        if process is None:
            with self._lock:
                self._closing = False
            return
        try:
            with self._write_lock:
                process.stdin.write(json.dumps({"version": PROTOCOL_VERSION, "type": "shutdown"}) + "\n")
                process.stdin.flush()
            process.wait(timeout=max(0.1, float(timeout)))
        except Exception:
            stop_process_tree(process)
        finally:
            with self._lock:
                if process is self._process:
                    self._process = None
                self._closing = False


class LiveRendererSession:
    """A page lease on the shared renderer process; no duplicate renderer."""

    def __init__(self, service: RendererService, session_id: str | None = None):
        self.service = service
        self.session_id = session_id or uuid.uuid4().hex

    def _live_request(self, message, *, timeout, still_current=None):
        options = {'timeout':timeout}
        if still_current is not None:
            options['still_current'] = still_current
        return self.service._live_request(dict(message, session_id=self.session_id), **options)

    live_set = RendererService.live_set
    live_frame = RendererService.live_frame
    live_play = RendererService.live_play
    live_pause = RendererService.live_pause
    live_text = RendererService.live_text
    live_latest = RendererService.live_latest

    def close(self):
        self._live_request({"type": "live_close"}, timeout=3)


GLOBAL_RENDERER_SERVICE = RendererService()


__all__ = [
    "GLOBAL_RENDERER_SERVICE",
    "PROTOCOL_VERSION",
    "RENDERER_JOB_KINDS",
    "RendererJob",
    "RendererRequestHandle",
    "RendererResult",
    "RendererService",
    "RendererServiceError",
]
