"""Measure nontransparent pixels without unpacking the RGB channels."""
from PySide6.QtGui import QImage


def alpha_metrics(image: QImage) -> tuple[tuple[int, int, int, int] | None, int]:
    """Return exact alpha bounds and nonzero count in image pixels.

    Qt's Alpha8 conversion preserves alpha for premultiplied and straight
    images alike.  Its scanlines may be padded, so keep the real row stride.
    The temporary one-byte plane is local to this call and never cached.
    """
    import numpy as np

    if image.isNull():
        return None, 0
    plane = image.convertToFormat(QImage.Format_Alpha8)
    alpha = np.ndarray((plane.height(), plane.width()), dtype=np.uint8,
                       buffer=plane.constBits(), strides=(plane.bytesPerLine(), 1))
    rows = np.flatnonzero(np.any(alpha, axis=1))
    if not rows.size:
        return None, 0
    # Rows outside this band are proved transparent. Text normally occupies
    # only a small part of the canvas; do not rescan all empty rows for X/count.
    band=alpha[int(rows[0]):int(rows[-1])+1]
    cols = np.flatnonzero(np.any(band, axis=0))
    bounds = (int(cols[0]), int(rows[0]), int(cols[-1]-cols[0]+1), int(rows[-1]-rows[0]+1))
    return bounds, int(np.count_nonzero(band[:,int(cols[0]):int(cols[-1])+1]))
