"""Production validation must accept normal limited-range video with a JPEG cover."""
from pathlib import Path

import pytest

from twobyteasr.exports.export_validation import validate_output
from twobyteasr.system.processes import run_hidden_subprocess


@pytest.mark.parametrize('pixel_format', ['yuv420p', 'yuvj420p'])
def test_real_decode_and_completion_cover_pixel_range(tmp_path, pixel_format):
    ffmpeg = Path(__file__).resolve().parents[1] / 'tools/ffmpeg/bin/ffmpeg.exe'
    video, cover = tmp_path / 'source.mp4', tmp_path / 'cover.jpg'
    run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
        'color=c=blue:s=320x180:r=30:d=1.2', '-c:v', 'libx264',
        '-pix_fmt', pixel_format, str(video)], purpose='export range fixture',
        check=True, timeout=20)
    metadata = validate_output(ffmpeg, video, duration=1.2, fps=30, preview_path=str(cover))
    assert metadata['streams'][0]['nb_frames'] == '36'
    assert cover.is_file() and cover.stat().st_size > 100
    run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-xerror', '-i', str(cover),
        '-f', 'null', '-'], purpose='decode completion JPEG', check=True, timeout=15)
