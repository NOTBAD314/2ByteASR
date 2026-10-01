"""Persistent, crash-recoverable background render queue for Subtitle Studio."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .studio_project import studio_data_root
from .studio_render import RenderJob, RenderSettings, run_render_job


QUEUE_SCHEMA_VERSION = 1
QUEUE_STATUSES = {"Queued", "Rendering", "Completed", "Failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class QueuedRenderJob:
    job: RenderJob
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "Queued"
    progress: dict[str, str] = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        # Completion UI receipts are ephemeral, never part of the queue contract.
        job = asdict(self.job)
        job.pop('completion_preview_path', None)
        job.pop('completion_metadata', None)
        job.pop('preview_callback', None)
        return {
            "id": self.id,
            "status": self.status,
            "progress": dict(self.progress),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "job": {
                **job,
                "settings": asdict(self.job.settings),
            },
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "QueuedRenderJob":
        job_payload = dict(payload["job"])
        job_payload["settings"] = RenderSettings(**dict(job_payload.get("settings", {})))
        status = str(payload.get("status") or "Queued")
        if status not in QUEUE_STATUSES:
            status = "Failed"
        return cls(
            id=str(payload.get("id") or uuid.uuid4().hex),
            job=RenderJob(**job_payload),
            status=status,
            progress={str(k): str(v) for k, v in dict(payload.get("progress", {})).items()},
            error=str(payload.get("error") or ""),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or _now()),
        )


class RenderQueueStore:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path else studio_data_root() / "render-queue.json"
        self._lock = threading.RLock()

    def load(self, *, recover: bool = True) -> list[QueuedRenderJob]:
        with self._lock:
            if not self.path.is_file():
                return []
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if int(payload.get("schema_version", 0)) != QUEUE_SCHEMA_VERSION:
                    raise ValueError("unsupported render queue schema")
                jobs = [QueuedRenderJob.from_dict(item) for item in payload.get("jobs", [])]
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise RuntimeError(f"could not read render queue: {exc}") from exc
            changed = False
            if recover:
                for item in jobs:
                    if item.status == "Rendering":
                        item.status = "Queued"
                        item.error = "Recovered after an interrupted application session"
                        item.updated_at = _now()
                        changed = True
            if changed:
                self.save(jobs)
            return jobs

    def save(self, jobs: list[QueuedRenderJob]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(
                prefix=".render-queue.", suffix=".tmp", dir=str(self.path.parent)
            )
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(
                        {
                            "schema_version": QUEUE_SCHEMA_VERSION,
                            "jobs": [item.to_dict() for item in jobs],
                        },
                        stream,
                        ensure_ascii=False,
                        indent=2,
                    )
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                try:
                    temporary.unlink()
                except OSError:
                    pass


class StudioRenderQueue:
    def __init__(
        self,
        ffmpeg_path: str | os.PathLike[str],
        *,
        store: RenderQueueStore | None = None,
        runner: Callable = run_render_job,
    ) -> None:
        self.ffmpeg_path = str(Path(ffmpeg_path).resolve())
        self.store = store or RenderQueueStore()
        self.runner = runner
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._cancel_current = threading.Event()
        self._thread: threading.Thread | None = None
        self._jobs = self.store.load(recover=True)

    def jobs(self) -> list[QueuedRenderJob]:
        with self._condition:
            return [QueuedRenderJob.from_dict(item.to_dict()) for item in self._jobs]

    def enqueue(self, job: RenderJob) -> QueuedRenderJob:
        queued = QueuedRenderJob(job=job)
        with self._condition:
            self._jobs.append(queued)
            self.store.save(self._jobs)
            self._ensure_worker_locked()
            self._condition.notify_all()
        return QueuedRenderJob.from_dict(queued.to_dict())

    def start(self) -> None:
        with self._condition:
            self._ensure_worker_locked()
            self._condition.notify_all()

    def stop(self, *, cancel_current: bool = False, timeout: float = 5.0) -> None:
        self._stop.set()
        if cancel_current:
            self._cancel_current.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _ensure_worker_locked(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._work, daemon=True, name="studio-render-queue"
        )
        self._thread.start()

    def _persist_progress(self, queued: QueuedRenderJob, payload: dict[str, str]) -> None:
        with self._condition:
            queued.progress = {str(key): str(value) for key, value in payload.items()}
            queued.updated_at = _now()
            self.store.save(self._jobs)

    def _work(self) -> None:
        while not self._stop.is_set():
            with self._condition:
                queued = next((item for item in self._jobs if item.status == "Queued"), None)
                if queued is None:
                    self._condition.wait(timeout=1.0)
                    continue
                queued.status = "Rendering"
                queued.error = ""
                queued.updated_at = _now()
                self._cancel_current.clear()
                self.store.save(self._jobs)
            try:
                runner = self.runner
                if queued.job.export_project_data and runner is run_render_job:
                    from .studio_project import SubtitleProject
                    from .advanced_renderer import AdvancedRendererBackend, project_requires_advanced
                    project = SubtitleProject.from_dict(queued.job.export_project_data)
                    start = (queued.job.start_seconds or 0)*1000
                    end = start+(queued.job.duration_seconds or 0)*1000
                    if project_requires_advanced(project,start_ms=start,end_ms=end):
                        runner = lambda ffmpeg, job, **kwargs: AdvancedRendererBackend().render(project,ffmpeg,job,**kwargs)
                runner(
                    self.ffmpeg_path,
                    queued.job,
                    progress=lambda payload: self._persist_progress(queued, payload),
                    cancelled=lambda: self._stop.is_set() or self._cancel_current.is_set(),
                )
            except Exception as exc:
                queued.status = "Failed"
                queued.error = str(exc)
            else:
                queued.status = "Completed"
                queued.error = ""
            queued.updated_at = _now()
            with self._condition:
                self.store.save(self._jobs)


_QUEUE: StudioRenderQueue | None = None
_QUEUE_LOCK = threading.Lock()


def get_render_queue(ffmpeg_path: str | os.PathLike[str]) -> StudioRenderQueue:
    global _QUEUE
    resolved = str(Path(ffmpeg_path).resolve())
    with _QUEUE_LOCK:
        if _QUEUE is None or _QUEUE.ffmpeg_path != resolved:
            if _QUEUE is not None:
                _QUEUE.stop(timeout=1.0)
            _QUEUE = StudioRenderQueue(resolved)
            _QUEUE.start()
        return _QUEUE
