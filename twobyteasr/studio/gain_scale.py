"""Where a dB value sits on a gain fader, and how to say it in words (2026-11-14).

User (2026-11-14, track volume draft C): on the old slider 0 dB sat at 70 % and
the useful −12…+6 dB took a sliver. These anchors are spaced evenly, so 0 dB is
near the middle and the common range gets most of the travel. No Qt.
"""
from __future__ import annotations

import math

MIN_DB, MAX_DB = -60., 24.
ANCHORS = (-60., -24., -12., -6., -3., 0., 3., 6., 12., 24.)
SNAP_DB = .45   # a drag this close to 0 dB lands on 0 (Shift turns it off)


def clamp_db(value: float) -> float:
    value = float(value)
    return max(MIN_DB, min(MAX_DB, value)) if math.isfinite(value) else 0.


def position_of(db: float) -> float:
    """0…1 along the fader for ``db``."""
    db = clamp_db(db)
    last = len(ANCHORS) - 1
    for index in range(last):
        low, high = ANCHORS[index], ANCHORS[index + 1]
        if db <= high:
            return (index + (db - low) / (high - low)) / last
    return 1.


def db_at(position: float) -> float:
    last = len(ANCHORS) - 1
    scaled = max(0., min(1., float(position))) * last
    index = min(last - 1, int(scaled))
    low, high = ANCHORS[index], ANCHORS[index + 1]
    return low + (scaled - index) * (high - low)


ZERO_POSITION = position_of(0.)


def snap(db: float, *, fine: bool = False) -> float:
    value = round(clamp_db(db), 1)
    if not fine and abs(value) < SNAP_DB:
        return 0.
    return value + 0.   # no −0.0


def signed(db: float) -> str:
    """+3.0 / −3.0 / 0.0 with a real minus sign."""
    value = round(float(db), 1)
    if abs(value) < .05:
        return '0.0'
    return ('+' if value > 0 else '−') + f'{abs(value):.1f}'


def tick_label(db: float) -> str:
    return '0' if db == 0 else ('+' if db > 0 else '−') + f'{abs(db):g}'


def words(db: float) -> str:
    """A plain description of the change (a translation key)."""
    db = float(db)
    if abs(db) < .05:
        return '原音量'
    if db <= MIN_DB + .05:
        return '几乎静音'
    if db < 0:
        return '稍微小声一点' if db > -3 else '小声一些' if db > -8 else '小声很多' if db > -20 else '很轻，快听不到'
    return '稍微大声一点' if db < 3 else '大声一些' if db < 8 else '大声很多，小心爆音'
