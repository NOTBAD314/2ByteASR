"""Real FFmpeg coverage for scoped holds when video is shorter than a clip."""
import json
import subprocess
from pathlib import Path

import pytest

from twobyteasr.exports.export_filtergraph import compile_video_filtergraph
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.exports.studio_render import RenderJob, RenderSettings


FFMPEG = Path(__file__).resolve().parents[1] / 'tools/ffmpeg/bin/ffmpeg.exe'
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason='bundled ffmpeg required')


def run(command):
    return run_hidden_subprocess(command, purpose='short video export regression',
                                 capture_output=True, check=True, timeout=15)


@pytest.fixture
def sources(tmp_path):
    changing = tmp_path / 'red then yellow.mkv'
    blue = tmp_path / 'blue.mkv'
    audio = tmp_path / 'no video.wav'
    run([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
         'color=red:s=16x16:r=10:d=0.2', '-f', 'lavfi', '-i',
         'color=yellow:s=16x16:r=10:d=0.2', '-filter_complex',
         '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]', '-c:v', 'ffv1', str(changing)])
    run([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
         'color=blue:s=16x16:r=10:d=0.2', '-c:v', 'ffv1', str(blue)])
    run([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i',
         'sine=duration=1', str(audio)])
    return changing, blue, audio


def clip(id, asset, start, end, *, source_start=0, rate=1):
    return dict(id=id, asset_id=asset, timeline_in_ms=start, timeline_out_ms=end,
                source_in_ms=source_start, source_out_ms=source_start+round((end-start)*rate),
                playback_rate=rate)


def command(tmp_path, sources, clips, *, start=0, duration=1):
    graph = dict(width=16, height=16, fps=10, duration_ms=2400, audio_mix={},
                 media_pool=[dict(asset_id=str(i), canonical_source=str(path),
                                  video_metadata={'has_video': True})
                             for i, path in enumerate(sources)],
                 video_tracks=[dict(enabled=True, clips=clips)])
    output = tmp_path / 'result.mkv'
    job = RenderJob(str(sources[0]), '', str(output),
                    RenderSettings(width=16, height=16, fps=10, audio_codec='none'),
                    start_seconds=start, duration_seconds=duration, direct_video_graph=graph)
    args = compile_video_filtergraph(FFMPEG, job, 'null')
    return [str(FFMPEG), '-v', 'error', '-y', *args, '-c:v', 'ffv1', str(output)], output


def pixels(output):
    raw = run([str(FFMPEG), '-v', 'error', '-i', str(output), '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', '-']).stdout
    return [tuple(raw[i:i+3]) for i in range(0, len(raw), 16*16*3)]


def assert_color(pixel, color):
    expected = {'red': (255, 0, 0), 'yellow': (255, 255, 0),
                'blue': (0, 0, 255), 'black': (0, 0, 0)}[color]
    assert all(abs(a-b) < 8 for a, b in zip(pixel, expected)), pixel


@pytest.mark.parametrize('start,rate', [(0, 1), (.6, 1), (.6, .5), (.6, 2)])
def test_last_decoded_frame_survives_tail_only_trim_and_rate(sources, tmp_path, start, rate):
    cmd, output = command(tmp_path, sources, [clip('a', '0', 0, 1000, rate=rate)],
                          start=start, duration=.3)
    run(cmd)
    frames = pixels(output)
    assert len(frames) == 3
    assert_color(frames[-1], 'yellow' if start or rate == 1 else 'red')
    if start == 0:
        assert_color(frames[0], 'red')
    probe = run([str(FFMPEG.with_name('ffprobe.exe')), '-v', 'error', '-show_format',
                 '-show_streams', '-count_frames', '-of', 'json', str(output)])
    video = json.loads(probe.stdout)['streams'][0]
    assert video['nb_read_frames'] == '3'


def test_hold_is_bounded_by_each_clip_gap_and_next_source(sources, tmp_path):
    cmd, output = command(tmp_path, sources,
                          [clip('a', '0', 0, 1000), clip('b', '1', 1200, 2200)], duration=2.4)
    run(cmd)
    frames = pixels(output)
    assert len(frames) == 24
    for index, color in [(0, 'red'), (2, 'yellow'), (9, 'yellow'),
                         (10, 'black'), (11, 'black'), (12, 'blue'),
                         (21, 'blue'), (22, 'black'), (23, 'black')]:
        assert_color(frames[index], color)


def test_missing_video_cannot_borrow_previous_clips_frame(sources, tmp_path):
    cmd, output = command(tmp_path, sources,
                          [clip('a', '0', 0, 1000), clip('empty', '2', 1000, 2000)], duration=2)
    with pytest.raises(subprocess.CalledProcessError):
        run(cmd)
    assert not output.exists() or output.stat().st_size == 0
