from PySide6.QtCore import QPointF
from twobyteasr.studio.media_clip_shape import media_clip_shape


def test_real_ends_round_without_time_inset_or_spill():
    rect, path = media_clip_shape(100, 300, 10, 48, 0, 500)
    assert rect.left() == 100 and rect.right() == 300
    assert not path.contains(QPointF(101, 11))
    assert path.contains(QPointF(101, 34))
    assert not path.contains(QPointF(301, 34))


def test_scrolled_edge_remains_square_and_short_clip_remains_visible():
    _, path = media_clip_shape(-5000, 5000, 10, 80, 100, 500)
    assert path.contains(QPointF(100, 10.1)) and path.contains(QPointF(500, 10.1))
    rect, tiny = media_clip_shape(200, 200.6, 10, 80, 100, 500)
    assert abs(rect.width() - .6) < 1e-6
    assert tiny.contains(QPointF(200.3, 50))
