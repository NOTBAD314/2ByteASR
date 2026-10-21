"""Bbox-local raster cache for Advanced subtitle LIVE compositing layers.

Replaying or re-entering an advanced cue used to re-run the whole Qt raster
pipeline (glyph layout, stroke rings, soft-shadow halos) for every layer.
This cache stores the per-layer rasters cropped to their content bbox and
re-pastes them onto the full render canvas on hit, so only the first play of
a cue pays the rasterization cost.

The cache is content-addressed: the key hashes every static pixel input
(text, font, fill, strokes, shadow, glow, effects, resolution, dpr) through
``VisualCueSnapshot.pixel_hash`` with the LIVE renderer version. Editing a
cue produces a new key; stale entries simply age out through the LRU byte
budget instead of needing explicit invalidation.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Mapping

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QRegion

from .advanced_live_renderer import LIVE_RENDERER_VERSION, LiveLayerImages

CACHE_SCHEMA = "live-layer-cache-v1"
DEFAULT_MAX_ENTRIES = 8
# Cropped subtitle-band layer sets are a few MB each; the budget bounds the
# whole cache, never a single full-frame 1080p RGBA mirror per cue.
DEFAULT_MAX_BYTES = 160 * 1024 * 1024


def live_layer_cache_key(
    snapshot,
    *,
    width: int,
    height: int,
    device_pixel_ratio: float = 1.0,
) -> str:
    digest = hashlib.sha256()
    digest.update(CACHE_SCHEMA.encode("utf-8"))
    digest.update(LIVE_RENDERER_VERSION.encode("utf-8"))
    try:
        pixel = snapshot.pixel_hash(
            renderer_version=LIVE_RENDERER_VERSION,
            resolution=(int(width), int(height)),
            device_pixel_ratio=float(device_pixel_ratio),
        )
    except (AttributeError, TypeError, ValueError):
        pixel = str(snapshot.stable_hash())
    digest.update(str(pixel).encode("utf-8"))
    digest.update(f"{int(width)}x{int(height)}@{float(device_pixel_ratio):.3f}".encode("utf-8"))
    return digest.hexdigest()


class _CacheEntry:
    __slots__ = ("layers", "origin", "canvas_size", "weight_bytes")

    def __init__(
        self,
        layers: dict[str, QImage],
        origin: QPoint,
        canvas_size,
        weight_bytes: int,
    ) -> None:
        self.layers = layers
        self.origin = origin
        self.canvas_size = canvas_size
        self.weight_bytes = int(weight_bytes)


class LiveLayerCache:
    """Thread-safe LRU of cropped layer rasters, bounded by entries and bytes."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = int(max_entries)
        self._max_bytes = int(max_bytes)
        self._hits = 0
        self._misses = 0
        self._stores = 0

    def contains(self, key: str) -> bool:
        with self._lock:
            return str(key) in self._entries

    def store(self, key: str, layers: Mapping[str, QImage]) -> bool:
        """Crop full-canvas layer rasters to their union bbox and remember them."""
        images = {
            str(layer_id): image
            for layer_id, image in layers.items()
            if not image.isNull()
        }
        if not images:
            return False
        source = next(iter(images.values()))
        canvas_size = getattr(layers, "canvas_size", None) or source.size()
        bbox = QRect()
        for image in images.values():
            layer_bounds = QRegion(QPixmap.fromImage(image).mask()).boundingRect()
            if not layer_bounds.isEmpty():
                bbox = layer_bounds.united(bbox) if not bbox.isNull() else layer_bounds
        if bbox.isNull() or bbox.isEmpty():
            return False
        padding = max(24, round(max(bbox.width(), bbox.height()) * 0.15))
        bbox = bbox.adjusted(-padding, -padding, padding, padding).intersected(
            QRect(0, 0, canvas_size.width(), canvas_size.height())
        )
        if bbox.isEmpty():
            return False
        cropped: dict[str, QImage] = {}
        weight = 0
        for layer_id, image in images.items():
            piece = image.copy(bbox)
            if piece.isNull():
                continue
            cropped[layer_id] = piece
            weight += piece.sizeInBytes()
        if not cropped or weight > self._max_bytes:
            return False
        origin = QPoint(bbox.x(), bbox.y()) + getattr(layers, "origin", QPoint())
        with self._lock:
            self._entries[str(key)] = _CacheEntry(cropped, origin, canvas_size, weight)
            self._entries.move_to_end(str(key))
            self._stores += 1
            self._evict_locked()
        return True

    def materialize(self, key: str, *, snapshot=None) -> LiveLayerImages | None:
        """Return full-canvas layer rasters rebuilt from the cropped cache."""
        with self._lock:
            entry = self._entries.get(str(key))
            if entry is None:
                self._misses += 1
                return None
            self._entries.move_to_end(str(key))
            self._hits += 1
            cropped = dict(entry.layers)
            origin = QPoint(entry.origin)
            canvas_size = QSize(entry.canvas_size)
        if not cropped:
            return None
        layers = LiveLayerImages({}, canvas_size=canvas_size, snapshot=snapshot)
        for layer_id, image in cropped.items():
            full = QImage(
                canvas_size.width(),
                canvas_size.height(),
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            dpr = float(image.devicePixelRatio() or 1.0)
            full.fill(Qt.GlobalColor.transparent)
            # Cache bbox/origin are physical pixels. Painting them onto an
            # already DPR-tagged image multiplies the origin a second time
            # (at 175%, the lower shadow can move completely off canvas).
            piece = QImage(image)
            piece.setDevicePixelRatio(1.0)
            painter = QPainter(full)
            painter.drawImage(origin.x(), origin.y(), piece)
            painter.end()
            full.setDevicePixelRatio(dpr)
            layers[layer_id] = full
        return layers

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "bytes": sum(entry.weight_bytes for entry in self._entries.values()),
                "hits": self._hits,
                "misses": self._misses,
                "stores": self._stores,
                "max_entries": self._max_entries,
                "max_bytes": self._max_bytes,
            }

    def _evict_locked(self) -> None:
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        total = sum(entry.weight_bytes for entry in self._entries.values())
        while total > self._max_bytes and len(self._entries) > 1:
            _key, evicted = self._entries.popitem(last=False)
            total -= evicted.weight_bytes


GLOBAL_LIVE_LAYER_CACHE = LiveLayerCache()

__all__ = [
    "GLOBAL_LIVE_LAYER_CACHE",
    "LiveLayerCache",
    "live_layer_cache_key",
]
