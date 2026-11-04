"""Snap corresponding rectangle edges without constraining canvas overflow."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AxisSnap:
    position: float
    edge: float


def snap_axis(position, extent, boundary, scale, previous=None):
    """Use viewport logical pixels: acquire at 8 px, release beyond 12 px."""
    candidates = (AxisSnap(0., 0.), AxisSnap(boundary-extent, boundary))
    if previous in candidates and abs(position-previous.position)*scale <= 12:
        return previous
    nearest = min(candidates, key=lambda target: abs(position-target.position))
    return nearest if abs(position-nearest.position)*scale <= 8 else None
