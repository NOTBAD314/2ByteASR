"""Ink-wash colour field for the style tab's colour wells (2026-11-13, user).

A well shows its colour the way a loaded brush leaves it on paper: dense at
the left, thinning out to the right, with a faint tide line where each layer
dried.  The field is a small density map built from value noise, rendered at
half resolution and scaled up smoothly by the caller, so every tone has a
soft, uneven edge.

Black and other colourless dark inks thin out towards a cool blue-black
(松烟墨) instead of a neutral grey, which read as dirt on the warm paper;
their grain and inner tide lines are mostly dropped for the same reason.
Coloured inks are not changed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtGui import QColor, QImage

#: Field resolution: one sample per ``SCALE`` logical pixels.
SCALE = 2.0
#: Width of the pool of full colour at the left, as a share of the height.
POOL_RATIO = 27.0 / 38.0
#: What a colourless dark ink thins out to.
COOL_INK = (52.0, 70.0, 96.0)

_TABLES = None


def _np():
    import numpy

    return numpy


def _tables():
    global _TABLES
    if _TABLES is None:
        np = _np()
        rng = np.random.default_rng(20261113)
        perm = rng.permutation(256).astype(np.int32)
        _TABLES = (np.concatenate([perm, perm]), rng.random(256).astype(np.float32))
    return _TABLES


def _value_noise(x, y, z):
    """Smooth 3-D value noise in 0..1 for broadcastable arrays."""
    np = _np()
    perm, grad = _tables()
    x, y, z = np.broadcast_arrays(np.asarray(x, dtype=np.float32), np.asarray(y, dtype=np.float32),
                                  np.asarray(z, dtype=np.float32))
    xi, yi, zi = np.floor(x), np.floor(y), np.floor(z)
    u, v, w = x - xi, y - yi, z - zi
    u, v, w = u * u * (3 - 2 * u), v * v * (3 - 2 * v), w * w * (3 - 2 * w)
    X, Y, Z = xi.astype(np.int32) & 255, yi.astype(np.int32) & 255, zi.astype(np.int32) & 255
    X1, Y1, Z1 = (X + 1) & 255, (Y + 1) & 255, (Z + 1) & 255
    a, b, a1, b1 = perm[X] + Y, perm[X1] + Y, perm[X] + Y1, perm[X1] + Y1
    c000, c100 = grad[perm[perm[a] + Z]], grad[perm[perm[b] + Z]]
    c010, c110 = grad[perm[perm[a1] + Z]], grad[perm[perm[b1] + Z]]
    c001, c101 = grad[perm[perm[a] + Z1]], grad[perm[perm[b] + Z1]]
    c011, c111 = grad[perm[perm[a1] + Z1]], grad[perm[perm[b1] + Z1]]
    x00, x10 = c000 + (c100 - c000) * u, c010 + (c110 - c010) * u
    x01, x11 = c001 + (c101 - c001) * u, c011 + (c111 - c011) * u
    y0, y1 = x00 + (x10 - x00) * v, x01 + (x11 - x01) * v
    return y0 + (y1 - y0) * w


def _fbm(x, y, z):
    return (_value_noise(x, y, z) * 0.52
            + _value_noise(x * 2.03 + 7.1, y * 2.03 + 3.3, z * 1.7 + 1.3) * 0.30
            + _value_noise(x * 4.1 + 1.7, y * 4.1 + 9.2, z * 2.9 + 5.1) * 0.18)


def _smooth(lo: float, hi: float, value):
    np = _np()
    t = np.clip((value - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def luminance(color: QColor) -> float:
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def neutrality(color: QColor) -> float:
    """1 for black and dark greys, 0 for anything with a hue or a light tone."""
    high, low = max(color.red(), color.green(), color.blue()), min(color.red(), color.green(), color.blue())
    saturation = (high - low) / high if high else 0.0

    def smooth(lo: float, hi: float, value: float) -> float:
        t = min(1.0, max(0.0, (value - lo) / (hi - lo)))
        return t * t * (3 - 2 * t)

    return (1.0 - smooth(0.12, 0.45, saturation)) * (1.0 - smooth(70.0, 165.0, luminance(color)))


def wash_alpha(width: float, height: float, *, level: float = 1.0, t: float = 0.0, seed: float = 0.0,
               neutral: float = 0.0, hover: tuple[float, float, float] | None = None,
               ripples: Sequence[tuple[float, float, float]] = ()):
    """Ink density (0..0.93) of a ``width`` x ``height`` well, one sample per
    ``SCALE`` pixels.  ``level`` is how far the wash has run (0: only the pool
    at the left; 1: across the well; it may overshoot while it settles).
    ``hover`` is ``(x, y, strength)``; each ripple is ``(x, y, age_seconds)``.
    """
    np = _np()
    columns, rows = max(1, math.ceil(width / SCALE)), max(1, math.ceil(height / SCALE))
    x = ((np.arange(columns, dtype=np.float32) + 0.5) * SCALE)[None, :]
    y = ((np.arange(rows, dtype=np.float32) + 0.5) * SCALE)[:, None]
    pool = max(8.0, height * POOL_RATIO)
    reach = max(pool, pool + (max(pool, width - 4.0) - pool) * float(level))
    unit = (y - height / 2.0) / (height / 2.0)
    bulge = 4.0 * (1.0 - unit * unit)
    distance = x / reach + (_fbm(x * 0.02 + seed, y * 0.045, t * 0.07) - 0.5) * 0.6
    if hover is not None and hover[2] > 0.01:
        dx, dy = x - hover[0], y - hover[1]
        distance = distance - hover[2] * 0.24 * np.exp(-(dx * dx + dy * dy) / 760.0)
    for ripple_x, ripple_y, age in ripples:
        spread = np.hypot(x - ripple_x, (y - ripple_y) * 1.4)
        distance = distance + (0.075 * np.sin(spread * 0.28 - age * 9.0) * math.exp(-age * 2.2)
                               * np.exp(-spread / 46.0))
    base = 1.0 - _smooth(0.28, 1.06, distance)
    grain = 1.0 + (0.2 * _value_noise(x * 0.11 + seed, y * 0.16, 3.1) - 0.1) * (1.0 - 0.8 * neutral)
    line = 3.4 / reach
    marks = ((0.13 * np.exp(-((distance - 0.60) / line) ** 2) + 0.10 * np.exp(-((distance - 0.86) / line) ** 2))
             * (1.0 - 0.9 * neutral)
             + 0.20 * np.exp(-((distance - 1.02) / (line * 1.15)) ** 2) * (1.0 - 0.55 * neutral))
    alpha = base * 0.82 * grain + marks * min(1.0, abs(float(level)) + 0.35)
    # The wash never meets the well's right edge as a cut line.
    alpha = alpha * (1.0 - _smooth(width - 14.0, width - 1.0, x))
    edge = pool - 3.0 + bulge + (_value_noise(y * 0.2 + seed, t * 0.5, 5.3) - 0.5) * 4.0
    alpha = np.maximum(alpha, 0.82 * (1.0 - _smooth(-3.0, 3.0, x - edge)))
    return np.clip(alpha, 0.0, 0.93)


def _column_colors(colors: Sequence[QColor], columns: int):
    np = _np()
    stops = np.array([[c.red(), c.green(), c.blue()] for c in colors], dtype=np.float32)
    if len(stops) == 1:
        return np.repeat(stops, columns, axis=0)
    position = np.linspace(0.0, len(stops) - 1.0, columns, dtype=np.float32)
    index = np.clip(np.floor(position).astype(np.int32), 0, len(stops) - 2)
    share = (position - index)[:, None]
    return stops[index] + (stops[index + 1] - stops[index]) * share


def wash_image(width: float, height: float, colors: Sequence[QColor], **field) -> QImage:
    """The wash as a premultiplied image, ``SCALE`` times smaller than the
    well; draw it stretched over the well with smooth scaling.  Several
    ``colors`` run left to right (a gradient fill, or mixed selections)."""
    np = _np()
    colors = [color for color in colors if color.isValid()] or [QColor("#000000")]
    neutral = neutrality(colors[0]) if len(colors) == 1 else 0.0
    alpha = wash_alpha(width, height, neutral=neutral, **field)
    rows, columns = alpha.shape
    ramp = _column_colors(colors, columns)[None, :, :]
    if neutral > 0.0:
        thin = ramp + (np.array(COOL_INK, dtype=np.float32) - ramp) * (0.85 * neutral)
        ramp = thin + (ramp - thin) * _smooth(0.30, 0.82, alpha)[:, :, None]
    pixels = np.empty((rows, columns, 4), dtype=np.uint8)
    pixels[:, :, 2::-1] = np.clip(ramp * alpha[:, :, None], 0, 255)  # premultiplied B, G, R
    pixels[:, :, 3] = alpha * 255.0
    data = pixels.tobytes()  # kept alive until the copy below owns its pixels
    image = QImage(data, columns, rows, columns * 4, QImage.Format.Format_ARGB32_Premultiplied)
    return image.copy()
