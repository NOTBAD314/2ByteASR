"""Empty rendered movies must not become selectable successful directions."""
from io import BytesIO

import pytest
from PIL import Image

from twobyteasr.caption_design.theme_direction_preview import render_motion_preview


def test_fully_transparent_movie_is_rejected_before_encoding(tmp_path):
    image = Image.new('RGBA', (16, 9), (255, 255, 255, 0))
    data = BytesIO()
    image.save(data, format='PNG')

    class Renderer:
        pauses = 0

        def live_set(self, html, **kwargs):
            pass

        def live_pause(self, **kwargs):
            self.pauses += 1
            return data.getvalue()

    renderer = Renderer()
    with pytest.raises(ValueError, match='144帧均为空白'):
        render_motion_preview(renderer, '<html/>', tmp_path, 'C')
    assert renderer.pauses == 144
    assert not (tmp_path / 'C-motion.json').exists()
    assert not (tmp_path / 'C-motion.mp4').exists()
