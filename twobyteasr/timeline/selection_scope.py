"""Compact canonical selection descriptors for dense Studio projects."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from time import perf_counter
from typing import Iterable, Sequence


class SelectionMode(str, Enum):
    EMPTY = "EMPTY"
    ALL = "ALL"
    ROW_RANGE = "ROW_RANGE"
    EXPLICIT_IDS = "EXPLICIT_IDS"


@dataclass(frozen=True, slots=True)
class SelectionScope:
    mode: SelectionMode = SelectionMode.EMPTY
    active_id: str = ""
    total_count: int = 0
    row_start: int = -1
    row_end: int = -1
    explicit_ids: frozenset[str] = frozenset()

    @classmethod
    def empty(cls) -> "SelectionScope":
        return cls()

    @classmethod
    def all(cls, total_count: int, active_id: str = "") -> "SelectionScope":
        return cls(
            mode=SelectionMode.ALL,
            active_id=str(active_id),
            total_count=max(0, int(total_count)),
        )

    @classmethod
    def row_range(
        cls,
        start: int,
        end: int,
        *,
        active_id: str = "",
    ) -> "SelectionScope":
        left, right = sorted((int(start), int(end)))
        return cls(
            mode=SelectionMode.ROW_RANGE,
            active_id=str(active_id),
            total_count=max(0, right - left + 1),
            row_start=left,
            row_end=right,
        )

    @classmethod
    def explicit(
        cls,
        cue_ids: Iterable[str],
        active_id: str = "",
    ) -> "SelectionScope":
        ordered = list(dict.fromkeys(str(item) for item in cue_ids if str(item)))
        values = frozenset(ordered)
        return cls(
            mode=SelectionMode.EXPLICIT_IDS if values else SelectionMode.EMPTY,
            active_id=str(active_id if active_id in values else next(iter(ordered), "")),
            total_count=len(values),
            explicit_ids=values,
        )

    def count(self) -> int:
        return max(0, int(self.total_count))

    def with_active(self, active_id: str) -> "SelectionScope":
        return replace(self, active_id=str(active_id))

    def contains(self, cue_id: str, *, row: int | None = None) -> bool:
        if self.mode == SelectionMode.ALL:
            return True
        if self.mode == SelectionMode.ROW_RANGE:
            return row is not None and self.row_start <= int(row) <= self.row_end
        if self.mode == SelectionMode.EXPLICIT_IDS:
            return str(cue_id) in self.explicit_ids
        return False

    def materialize(self, ordered_ids: Sequence[str] | Iterable[str]) -> list[str]:
        values = ordered_ids if isinstance(ordered_ids, Sequence) else tuple(ordered_ids)
        if self.mode == SelectionMode.ALL:
            return [str(item) for item in values if str(item)]
        if self.mode == SelectionMode.ROW_RANGE:
            return [
                str(item)
                for item in values[self.row_start:self.row_end + 1]
                if str(item)
            ]
        if self.mode == SelectionMode.EXPLICIT_IDS:
            return [str(item) for item in values if str(item) in self.explicit_ids]
        return []


class SelectionLatencyTrace:
    """T0-T6 marker recorder shared by headed selection acceptance."""

    def __init__(self) -> None:
        self._token = 0
        self._started = 0.0
        self._markers: dict[str, float] = {}
        self._counts: dict[str, int] = {}

    @property
    def token(self) -> int:
        return self._token

    def begin(self) -> int:
        self._token += 1
        self._started = perf_counter()
        self._markers = {"T0_keydown": self._started}
        self._counts = {}
        return self._token

    def mark(self, name: str, *, token: int | None = None) -> None:
        if self._started <= 0.0 or (token is not None and token != self._token):
            return
        self._markers.setdefault(str(name), perf_counter())

    def increment(self, name: str, amount: int = 1) -> None:
        if self._started <= 0.0:
            return
        key = str(name)
        self._counts[key] = self._counts.get(key, 0) + int(amount)

    def snapshot(self) -> dict[str, object]:
        return {
            "token": self._token,
            "markers_ms": {
                key: round((value - self._started) * 1000.0, 3)
                for key, value in self._markers.items()
            },
            "counts": dict(self._counts),
        }


__all__ = [
    "SelectionLatencyTrace",
    "SelectionMode",
    "SelectionScope",
]
