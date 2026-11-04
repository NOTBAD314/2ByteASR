import pytest
from PySide6.QtCore import QPointF, QRectF

from twobyteasr.studio.studio_geometry import SubtitleCoordinateMapper


@pytest.mark.parametrize(
    ("video_size", "viewport"),
    [
        ((1920, 1080), QRectF(0, 0, 960, 540)),
        ((3840, 2160), QRectF(0, 0, 1277, 719)),
        ((2560, 1440), QRectF(0, 0, 800, 700)),
        ((1920, 800), QRectF(0, 0, 960, 540)),
        ((1080, 1920), QRectF(0, 0, 960, 540)),
    ],
)
def test_subtitle_preview_mapping_round_trips_across_video_aspects(video_size, viewport):
    mapper = SubtitleCoordinateMapper(
        viewport, 1920, 1080, video_size[0], video_size[1]
    )
    source = QPointF(960, 900)
    restored = mapper.preview_to_subtitle(mapper.subtitle_to_preview(source))
    assert restored.x() == pytest.approx(source.x(), abs=1e-7)
    assert restored.y() == pytest.approx(source.y(), abs=1e-7)


def test_video_content_rect_uses_source_aspect_not_ass_playres_aspect():
    mapper = SubtitleCoordinateMapper(
        QRectF(0, 0, 960, 540), 1920, 1080, 1920, 800
    )
    content = mapper.video_content_rect
    assert content == QRectF(0, 70, 960, 400)
    assert mapper.subtitle_to_preview(QPointF(0, 0)) == content.topLeft()
    assert mapper.subtitle_to_preview(QPointF(1920, 1080)) == content.bottomRight()


@pytest.mark.parametrize("device_scale", [1.0, 1.25, 1.5, 1.75, 2.0])
def test_mapper_stays_in_logical_pixels_at_every_device_scale(device_scale):
    logical_viewport = QRectF(0, 0, 960, 540)
    mapper = SubtitleCoordinateMapper(logical_viewport, 1920, 1080, 1920, 1080)
    logical = mapper.subtitle_to_preview(QPointF(960, 540))
    # A physical framebuffer may scale this point, but the Qt overlay must not.
    physical = QPointF(logical.x() * device_scale, logical.y() * device_scale)
    assert logical == QPointF(480, 270)
    assert physical == QPointF(480 * device_scale, 270 * device_scale)
