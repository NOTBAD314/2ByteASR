"""Shared cache identity, in-flight dedupe, budgets, and telemetry."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import Counter, OrderedDict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar


T = TypeVar("T")


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class CacheIdentity:
    """Content identity shared by media, waveform, ASR, and visual caches."""

    namespace: str
    schema: int = 1
    source: Mapping[str, object] = field(default_factory=dict)
    settings: Mapping[str, object] = field(default_factory=dict)
    model: str = ""
    renderer: str = ""
    resolution: tuple[int, int] = (0, 0)
    range_ms: tuple[int, int] = (0, 0)

    @property
    def key(self) -> str:
        payload = asdict(self)
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()

    @classmethod
    def for_file(
        cls,
        namespace: str,
        path: str | os.PathLike[str],
        **kwargs: object,
    ) -> "CacheIdentity":
        source = Path(path).resolve()
        stat = source.stat()
        return cls(
            namespace=str(namespace),
            source={
                "path": str(source),
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            },
            **kwargs,
        )


class CacheTelemetry:
    EVENTS = {
        "hit", "miss", "memory_hit", "disk_hit", "generate",
        "wait_existing", "evict", "prefetch", "cancel", "stale_drop",
    }

    def __init__(self, *, event_limit: int = 1024) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._totals: Counter[str] = Counter()
        self._events: deque[dict[str, object]] = deque(maxlen=max(32, int(event_limit)))

    def record(self, event: str, **payload: object) -> None:
        name = str(event)
        with self._lock:
            self._counts[name] += 1
            for metric in ("generation_ms", "load_ms", "bytes"):
                value = payload.get(metric)
                if isinstance(value, (int, float)):
                    self._totals[metric] += value
            self._events.append({"event": name, "at": time.time(), **payload})

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counts": dict(self._counts),
                "totals": dict(self._totals),
                "events": list(self._events),
            }


@dataclass
class _MemoryEntry:
    value: object
    size: int
    pin_count: int = 0
    project_pinned: bool = False


@dataclass
class _ArtifactEntry:
    path: Path
    size: int
    project_pinned: bool = False
    pin_count: int = 0
    touched_at: float = field(default_factory=time.monotonic)


@dataclass
class _InFlight:
    event: threading.Event = field(default_factory=threading.Event)
    value: object = None
    error: BaseException | None = None


class RuntimeCacheManager:
    """Small shared coordinator; artifact formats remain owned by each module."""

    def __init__(
        self,
        *,
        memory_budget_bytes: int = 256 * 1024 * 1024,
        disk_budget_bytes: int = 4 * 1024 * 1024 * 1024,
        telemetry: CacheTelemetry | None = None,
    ) -> None:
        self.memory_budget_bytes = max(1, int(memory_budget_bytes))
        self.disk_budget_bytes = max(1, int(disk_budget_bytes))
        self.telemetry = telemetry or CacheTelemetry()
        self._lock = threading.RLock()
        self._memory: OrderedDict[str, _MemoryEntry] = OrderedDict()
        self._artifacts: OrderedDict[str, _ArtifactEntry] = OrderedDict()
        self._inflight: dict[str, _InFlight] = {}

    @staticmethod
    def _key(identity: CacheIdentity | str) -> str:
        return identity.key if isinstance(identity, CacheIdentity) else str(identity)

    def get_memory(self, identity: CacheIdentity | str) -> object | None:
        key = self._key(identity)
        with self._lock:
            entry = self._memory.get(key)
            if entry is None:
                self.telemetry.record("miss", key=key, tier="memory")
                return None
            self._memory.move_to_end(key)
            self.telemetry.record("hit", key=key, tier="memory")
            self.telemetry.record("memory_hit", key=key, bytes=entry.size)
            return entry.value

    def put_memory(
        self,
        identity: CacheIdentity | str,
        value: object,
        *,
        size_bytes: int = 0,
        project_pinned: bool = False,
    ) -> None:
        key = self._key(identity)
        with self._lock:
            previous = self._memory.pop(key, None)
            pin_count = previous.pin_count if previous else 0
            self._memory[key] = _MemoryEntry(
                value=value,
                size=max(0, int(size_bytes)),
                pin_count=pin_count,
                project_pinned=bool(project_pinned or (previous and previous.project_pinned)),
            )
            self._evict_memory_locked()

    def pin(self, identity: CacheIdentity | str, *, project: bool = False) -> None:
        key = self._key(identity)
        with self._lock:
            memory = self._memory.get(key)
            if memory is not None:
                memory.pin_count += 1
                memory.project_pinned = bool(memory.project_pinned or project)
            artifact = self._artifacts.get(key)
            if artifact is not None:
                artifact.pin_count += 1
                artifact.project_pinned = bool(artifact.project_pinned or project)

    def unpin(self, identity: CacheIdentity | str) -> None:
        key = self._key(identity)
        with self._lock:
            if key in self._memory:
                self._memory[key].pin_count = max(0, self._memory[key].pin_count - 1)
            if key in self._artifacts:
                self._artifacts[key].pin_count = max(0, self._artifacts[key].pin_count - 1)

    def register_artifact(
        self,
        identity: CacheIdentity | str,
        path: str | os.PathLike[str],
        *,
        project_pinned: bool = False,
    ) -> None:
        key = self._key(identity)
        artifact = Path(path).resolve()
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        with self._lock:
            self._artifacts.pop(key, None)
            self._artifacts[key] = _ArtifactEntry(
                path=artifact,
                size=int(artifact.stat().st_size),
                project_pinned=bool(project_pinned),
            )
            self._evict_disk_locked()

    def artifact_path(self, identity: CacheIdentity | str) -> Path | None:
        key = self._key(identity)
        started = time.perf_counter()
        with self._lock:
            entry = self._artifacts.get(key)
            if entry is None or not entry.path.is_file():
                self._artifacts.pop(key, None)
                self.telemetry.record("miss", key=key, tier="disk")
                return None
            entry.touched_at = time.monotonic()
            self._artifacts.move_to_end(key)
            self.telemetry.record("hit", key=key, tier="disk")
            self.telemetry.record(
                "disk_hit", key=key, bytes=entry.size,
                load_ms=(time.perf_counter() - started) * 1000.0,
            )
            return entry.path

    def get_or_create(
        self,
        identity: CacheIdentity | str,
        producer: Callable[[], T],
        *,
        cache_result: Callable[[T], tuple[int, bool]] | None = None,
        prefetch: bool = False,
        store_memory: bool = True,
    ) -> tuple[T, bool]:
        """Return ``(value, produced_here)`` with exactly one producer per key."""
        key = self._key(identity)
        if store_memory:
            cached = self.get_memory(key)
            if cached is not None:
                return cached, False  # type: ignore[return-value]
        with self._lock:
            # A producer may finish between the optimistic lookup and this
            # lock acquisition. Recheck so that race cannot start a duplicate.
            if store_memory:
                entry = self._memory.get(key)
                if entry is not None:
                    self._memory.move_to_end(key)
                    self.telemetry.record("hit", key=key, tier="memory")
                    self.telemetry.record("memory_hit", key=key, bytes=entry.size)
                    return entry.value, False  # type: ignore[return-value]
            flight = self._inflight.get(key)
            if flight is None:
                flight = _InFlight()
                self._inflight[key] = flight
                owner = True
                if prefetch:
                    self.telemetry.record("prefetch", key=key)
            else:
                owner = False
                self.telemetry.record("wait_existing", key=key, prefetch=bool(prefetch))
        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            return flight.value, False  # type: ignore[return-value]
        started = time.perf_counter()
        try:
            value = producer()
            size, project_pinned = cache_result(value) if cache_result else (0, False)
            if store_memory:
                self.put_memory(key, value, size_bytes=size, project_pinned=project_pinned)
            flight.value = value
            self.telemetry.record(
                "generate", key=key, completed=True,
                generation_ms=(time.perf_counter() - started) * 1000.0,
                bytes=size,
            )
            return value, True
        except BaseException as exc:
            flight.error = exc
            self.telemetry.record(
                "generate", key=key, completed=False,
                generation_ms=(time.perf_counter() - started) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)
                flight.event.set()

    def record_cancel(self, identity: CacheIdentity | str, *, stale: bool = False) -> None:
        self.telemetry.record("stale_drop" if stale else "cancel", key=self._key(identity))

    def _evict_memory_locked(self) -> None:
        total = sum(entry.size for entry in self._memory.values())
        for key in list(self._memory):
            if total <= self.memory_budget_bytes:
                break
            entry = self._memory[key]
            if entry.pin_count or entry.project_pinned:
                continue
            total -= entry.size
            self._memory.pop(key, None)
            self.telemetry.record("evict", key=key, tier="memory", bytes=entry.size)

    def _evict_disk_locked(self) -> None:
        total = sum(entry.size for entry in self._artifacts.values())
        for key in list(self._artifacts):
            if total <= self.disk_budget_bytes:
                break
            entry = self._artifacts[key]
            if entry.pin_count or entry.project_pinned:
                continue
            try:
                entry.path.unlink(missing_ok=True)
            except OSError:
                continue
            total -= entry.size
            self._artifacts.pop(key, None)
            self.telemetry.record("evict", key=key, tier="disk", bytes=entry.size)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "memory_entries": len(self._memory),
                "memory_bytes": sum(entry.size for entry in self._memory.values()),
                "artifact_entries": len(self._artifacts),
                "artifact_bytes": sum(entry.size for entry in self._artifacts.values()),
                "inflight": len(self._inflight),
                "telemetry": self.telemetry.snapshot(),
            }


GLOBAL_RUNTIME_CACHE = RuntimeCacheManager()


__all__ = [
    "CacheIdentity", "CacheTelemetry", "RuntimeCacheManager", "GLOBAL_RUNTIME_CACHE",
]
