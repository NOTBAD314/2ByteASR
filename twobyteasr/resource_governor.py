"""Central foreground/background resource policy for Studio work."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class ResourceKind(str, Enum):
    PLAYBACK = "PLAYBACK"
    DRAGGING = "DRAGGING"
    ASR = "ASR"
    PROXY = "PROXY"
    WAVEFORM = "WAVEFORM"
    ADVANCED_PREVIEW = "ADVANCED_PREVIEW"
    EXPORT = "EXPORT"
    AI = "AI"


@dataclass(frozen=True)
class ResourceSnapshot:
    playback: bool
    dragging: bool
    active: dict[str, int]
    background_limit: int
    foreground_active: dict[str, int] = field(default_factory=dict)
    yield_counts: dict[str, int] = field(default_factory=dict)


class ResourceGovernor:
    """Bound background concurrency and expose cooperative yield decisions."""

    def __init__(self, *, background_limit: int = 2) -> None:
        self.background_limit = max(1, int(background_limit))
        self._condition = threading.Condition()
        self._active: dict[ResourceKind, int] = {kind: 0 for kind in ResourceKind}
        self._active_foreground: dict[ResourceKind, int] = {
            kind: 0 for kind in ResourceKind
        }
        self._yield_counts: dict[ResourceKind, int] = {
            kind: 0 for kind in ResourceKind
        }
        self._playback = False
        self._dragging = False

    def set_playback(self, active: bool) -> None:
        with self._condition:
            self._playback = bool(active)
            self._condition.notify_all()

    def set_dragging(self, active: bool) -> None:
        with self._condition:
            self._dragging = bool(active)
            self._condition.notify_all()

    def should_yield(self, kind: ResourceKind, *, foreground: bool = False) -> bool:
        with self._condition:
            return self._should_yield_locked(kind, foreground=foreground)

    def _should_yield_locked(self, kind: ResourceKind, *, foreground: bool = False) -> bool:
        if foreground:
            return False
        if not (self._playback or self._dragging):
            return False
        if kind == ResourceKind.AI:
            active_ai_background = (
                self._active[kind] - self._active_foreground[kind]
            )
            return active_ai_background >= 1
        return kind in {
            ResourceKind.PROXY,
            ResourceKind.WAVEFORM,
            ResourceKind.ADVANCED_PREVIEW,
        }

    def wait_until_allowed(
        self,
        kind: ResourceKind,
        *,
        foreground: bool = False,
        cancelled=None,
        timeout: float | None = None,
    ) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            yielded = False
            while self._should_yield_locked(kind, foreground=foreground):
                if not yielded:
                    self._yield_counts[kind] += 1
                    yielded = True
                if cancelled and cancelled():
                    return False
                if deadline is not None and time.monotonic() >= deadline:
                    return False
                self._condition.wait(0.05)
            return True

    @contextmanager
    def lease(
        self,
        kind: ResourceKind,
        *,
        foreground: bool = False,
        cancelled=None,
    ) -> Iterator[bool]:
        allowed = self.wait_until_allowed(
            kind, foreground=foreground, cancelled=cancelled,
        )
        if not allowed:
            yield False
            return
        acquired = False
        with self._condition:
            while True:
                if cancelled and cancelled():
                    break
                if self._should_yield_locked(kind, foreground=foreground):
                    self._condition.wait(0.05)
                    continue
                active_background = sum(
                    self._active[item] - self._active_foreground[item]
                    for item in ResourceKind
                    if item not in {ResourceKind.PLAYBACK, ResourceKind.DRAGGING}
                )
                if foreground or active_background < self.background_limit:
                    self._active[kind] += 1
                    if foreground:
                        self._active_foreground[kind] += 1
                    acquired = True
                    break
                self._condition.wait(0.05)
        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            with self._condition:
                self._active[kind] = max(0, self._active[kind] - 1)
                if foreground:
                    self._active_foreground[kind] = max(
                        0, self._active_foreground[kind] - 1,
                    )
                self._condition.notify_all()

    def snapshot(self) -> ResourceSnapshot:
        with self._condition:
            return ResourceSnapshot(
                playback=self._playback,
                dragging=self._dragging,
                active={kind.value: count for kind, count in self._active.items() if count},
                background_limit=self.background_limit,
                foreground_active={
                    kind.value: count
                    for kind, count in self._active_foreground.items()
                    if count
                },
                yield_counts={
                    kind.value: count
                    for kind, count in self._yield_counts.items()
                    if count
                },
            )


GLOBAL_RESOURCE_GOVERNOR = ResourceGovernor()


__all__ = [
    "ResourceKind", "ResourceSnapshot", "ResourceGovernor", "GLOBAL_RESOURCE_GOVERNOR",
]
