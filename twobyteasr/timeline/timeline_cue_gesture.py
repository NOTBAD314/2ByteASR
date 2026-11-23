"""Ephemeral cue intervals: pointer preview never mutates the project."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CueInterval:
    start_ms: int
    end_ms: int
    speaker_id: str


def preview_intervals(
    originals: Mapping[str, CueInterval], anchor_id: str, mode: str,
    delta_ms: int, *, target_speaker: str = "", minimum_ms: int = 50,
    speaker_rows=(), locked_speakers=(),
) -> dict[str, CueInterval]:
    """Apply one bounded delta to the selection, preserving relative spacing.

    Overlaps are permitted by Studio's cue contract (including speakers talking
    simultaneously); do not silently push adjacent, unselected cues.
    """
    if not originals or anchor_id not in originals:
        return {}
    delta = int(delta_ms)
    if mode in {"move", "left"}:
        delta = max(delta, -min(v.start_ms for v in originals.values()))
    if mode == "left":
        delta = min(delta, min(v.end_ms-v.start_ms-minimum_ms for v in originals.values()))
    elif mode == "right":
        delta = max(delta, max(minimum_ms-(v.end_ms-v.start_ms) for v in originals.values()))
    if mode == "move" and len(originals) > 1 and target_speaker and speaker_rows:
        # 2026-11-20 (user): several selected lines move up or down between tracks together,
        # each by the rows the dragged one moved.
        from .subtitle_track_drag import shifted_speakers
        moved = shifted_speakers({key: v.speaker_id for key, v in originals.items()}, speaker_rows,
                                 originals[anchor_id].speaker_id, target_speaker, locked_speakers)
        return {key: CueInterval(v.start_ms + delta, v.end_ms + delta, moved.get(key, v.speaker_id))
                for key, v in originals.items()}
    return {
        key: CueInterval(
            v.start_ms + (delta if mode != "right" else 0),
            v.end_ms + (delta if mode != "left" else 0),
            target_speaker if mode == "move" and len(originals) == 1 and target_speaker else v.speaker_id,
        ) for key, v in originals.items()
    }
