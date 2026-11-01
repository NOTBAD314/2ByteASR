"""The faster alpha scan must preserve the original pixel-level contract."""
import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from twobyteasr.rendering.alpha_geometry import alpha_metrics


def reference(image):
    packed = image.convertToFormat(QImage.Format_RGBA8888)
    alpha = np.ndarray((packed.height(), packed.width(), 4), dtype=np.uint8,
        buffer=packed.constBits(), strides=(packed.bytesPerLine(), 4, 1))[:, :, 3]
    rows = np.flatnonzero(np.any(alpha, axis=1))
    cols = np.flatnonzero(np.any(alpha, axis=0))
    bounds = (int(cols[0]), int(rows[0]), int(cols[-1]-cols[0]+1), int(rows[-1]-rows[0]+1)) if rows.size and cols.size else None
    return bounds, int(np.count_nonzero(alpha))


@pytest.mark.parametrize('fmt', [QImage.Format_ARGB32, QImage.Format_ARGB32_Premultiplied,
    QImage.Format_RGBA8888, QImage.Format_RGBA8888_Premultiplied, QImage.Format_RGB32,
    QImage.Format_RGB888, QImage.Format_Grayscale8, QImage.Format_RGB16,
    QImage.Format_RGBA64, QImage.Format_RGBA64_Premultiplied, QImage.Format_RGBX64, QImage.Format_Alpha8])
@pytest.mark.parametrize('width', [1, 3, 7, 32])
def test_formats_padding_and_partial_alpha_match_existing_rgba_scan(fmt, width):
    image = QImage(width, 9, fmt)
    image.fill(0)
    for y in range(9):
        for x in range(width):
            alpha = (0, 1, 17, 127, 254, 255)[(x*3+y) % 6]
            image.setPixelColor(x, y, QColor((x*47) % 256, (y*31) % 256, 123, alpha))
    before = bytes(image.constBits())
    assert alpha_metrics(image) == reference(image)
    assert bytes(image.constBits()) == before


def test_transparent_and_sparse_edge_pixels():
    image = QImage(13, 11, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    assert alpha_metrics(image) == (None, 0)
    image.setPixelColor(0, 10, QColor(255, 255, 255, 1))
    image.setPixelColor(12, 0, QColor(255, 0, 255, 254))
    assert alpha_metrics(image) == ((0, 0, 13, 11), 2)


def test_null_image_has_no_bounds():
    assert alpha_metrics(QImage()) == (None, 0)


def test_indexed_transparency_palette_matches_existing_scan():
    image = QImage(7, 5, QImage.Format_Indexed8)
    image.setColorTable([0x00000000, 0x01010203, 0x80808080, 0xffffffff])
    for y in range(image.height()):
        for x in range(image.width()):
            image.setPixel(x, y, (x+y) % 4)
    assert alpha_metrics(image) == reference(image)
