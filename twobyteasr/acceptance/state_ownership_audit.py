"""Cross-layer evidence for UI -> domain -> snapshot -> renderer ownership."""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class StateOwnershipSample:
    feature: str
    cue_id: str = ""
    generation: int = 0
    ui_value: Any = None
    domain_value: Any = None
    snapshot_value: Any = None
    renderer_value: Any = None
    pixel_value: Any = None
    owner: str = ""
    snapshot_hash: str = ""
    graph_hash: str = ""
    foreground_hash: str = ""
    timestamp_ns: int = field(default_factory=time.perf_counter_ns)

    def values_match(self) -> bool:
        values = (
            self.ui_value,
            self.domain_value,
            self.snapshot_value,
            self.renderer_value,
        )
        concrete = [value for value in values if value is not None]
        return not concrete or all(value == concrete[0] for value in concrete[1:])


class StateOwnershipAudit:
    """Bounded recorder shared by opacity, stroke, audio, and icon fixtures."""

    def __init__(self, *, limit: int = 10_000) -> None:
        self.limit = max(1, int(limit))
        self._samples: list[StateOwnershipSample] = []

    def record(self, feature: str, **values: Any) -> StateOwnershipSample:
        sample = StateOwnershipSample(feature=str(feature), **copy.deepcopy(values))
        self._samples.append(sample)
        if len(self._samples) > self.limit:
            del self._samples[: len(self._samples) - self.limit]
        return sample

    def samples(self, feature: str = "") -> tuple[StateOwnershipSample, ...]:
        if not feature:
            return tuple(self._samples)
        return tuple(item for item in self._samples if item.feature == str(feature))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": len(self._samples),
            "features": sorted({item.feature for item in self._samples}),
            "samples": [asdict(item) for item in self._samples],
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StateOwnershipAudit":
        audit = cls(limit=max(1, int(payload.get("sample_count", 1) or 1)))
        for raw in payload.get("samples", ()):
            if isinstance(raw, Mapping):
                values = dict(raw)
                feature = str(values.pop("feature", ""))
                values.pop("timestamp_ns", None)
                audit.record(feature, **values)
        return audit


__all__ = ["StateOwnershipAudit", "StateOwnershipSample"]
