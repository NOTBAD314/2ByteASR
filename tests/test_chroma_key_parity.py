"""The in-place/banded chroma key stays bit-identical to the original formulation."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from twobyteasr.playback.video_compositor import apply_chroma_key


def reference_chroma_key(image, chroma):
    """The pre-2026-11-19 implementation, kept verbatim as the oracle."""
    similarity = max(0.0, min(1.0, float(chroma.get("similarity", 0.32) or 0.0)))
    smoothness = max(0.0, min(1.0, float(chroma.get("smoothness", 0.10) or 0.0)))
    key = QColor(str(chroma.get("color") or "#00FF00"))
    key_r, key_g, key_b = key.red(), key.green(), key.blue()
    spill = bool(chroma.get("spillSuppression", True))
    width, height = image.width(), image.height()
    source = image.convertToFormat(QImage.Format.Format_ARGB32)
    pixels = np.frombuffer(source.constBits(), dtype=np.uint8, count=source.sizeInBytes()
                           ).reshape(source.height(), source.bytesPerLine() // 4, 4)[:, :width, :].copy()
    bgr = pixels[:, :, :3].astype(np.float32)
    blue, green, red = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
    distance = np.sqrt((red - key_r) ** 2 + (green - key_g) ** 2 + (blue - key_b) ** 2) / 441.673
    mask = np.clip((distance - similarity) / max(smoothness, 1e-3), 0.0, 1.0)
    if spill:
        edge = mask < 1.0
        green[edge] = np.minimum(green[edge], np.maximum(red[edge], blue[edge]) + 30.0)
        pixels[:, :, 1] = green.astype(np.uint8)
    pixels[:, :, 3] = (pixels[:, :, 3].astype(np.float32) * mask).astype(np.uint8)
    return QImage(pixels.tobytes(), width, height, source.bytesPerLine(), QImage.Format.Format_ARGB32).copy()


@pytest.mark.parametrize("size", [(1920, 1080), (333, 177), (1, 1)])
@pytest.mark.parametrize("chroma", [
    {"color": "#00FF00", "similarity": .2, "smoothness": .1, "spillSuppression": True},
    {"color": "#2040F0", "similarity": .05, "smoothness": 0, "spillSuppression": False},
    {"color": "#00FF00", "similarity": .5, "smoothness": .5},
])
def test_chroma_key_matches_reference_bit_for_bit(size, chroma):
    width, height = size
    rng = np.random.default_rng(width * 7 + height)
    data = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
    data[: max(1, height // 3), :, 1] = 250
    image = QImage(data.tobytes(), width, height, width * 4, QImage.Format.Format_ARGB32).copy()
    assert bytes(apply_chroma_key(image, chroma).constBits()) == bytes(reference_chroma_key(image, chroma).constBits())
