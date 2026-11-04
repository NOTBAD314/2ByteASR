"""Autosave timing contract with idle debounce and a hard dirty-age bound."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AutosaveDeadline:
    interval_seconds: float = 60.0
    idle_seconds: float = 3.0
    dirty_since: float | None = None
    last_edit_at: float | None = None
    saving: bool = False

    def configure(self, interval_seconds: float, idle_seconds: float | None = None) -> None:
        self.interval_seconds = max(5.0, float(interval_seconds))
        if idle_seconds is not None:
            self.idle_seconds = max(0.1, min(float(idle_seconds), self.interval_seconds))

    def mark_dirty(self, now: float) -> float:
        timestamp = float(now)
        if self.dirty_since is None:
            self.dirty_since = timestamp
        self.last_edit_at = timestamp
        return self.delay_seconds(timestamp)

    def delay_seconds(self, now: float) -> float:
        if self.dirty_since is None:
            return self.interval_seconds
        timestamp = float(now)
        idle_due = (self.last_edit_at if self.last_edit_at is not None else timestamp) + self.idle_seconds
        hard_due = self.dirty_since + self.interval_seconds
        return max(0.0, min(idle_due, hard_due) - timestamp)

    def due(self, now: float) -> bool:
        return self.dirty_since is not None and self.delay_seconds(now) <= 0.0

    def mark_started(self) -> None:
        self.saving = True

    def mark_succeeded(self) -> None:
        self.saving = False
        self.dirty_since = None
        self.last_edit_at = None

    def mark_failed(self, now: float) -> float:
        self.saving = False
        timestamp = float(now)
        if self.dirty_since is None:
            self.dirty_since = timestamp
        self.last_edit_at = timestamp
        return min(5.0, self.interval_seconds)
