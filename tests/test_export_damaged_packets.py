# SPDX-License-Identifier: GPL-3.0-only
"""A few damaged packets in a source no longer fail the export (2026-10-23 report).

The decoder rejects them with AVERROR_INVALIDDATA from avcodec_send_packet();
the FFmpeg CLI and mpv skip such a packet and go on, and so do the full
preflight index and the export decoder, with the same frames on both sides.
"""
import bisect
import json
import os
import shutil
from fractions import Fraction
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import av
import pytest

from twobyteasr.exports import export_media, video_export
from twobyteasr.exports.export_media import ExportMediaError, MediaIndex, SequentialExportDecoder, probe_media
from twobyteasr.playback.video_decode_worker import decode_skipping_damaged, display_bgra
from twobyteasr.system.processes import run_hidden_subprocess

FFMPEG = Path(__file__).resolve().parents[1] / 'tools/ffmpeg/bin/ffmpeg.exe'
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason='bundled FFmpeg required')


def _source(path, seconds):
    run_hidden_subprocess([str(FFMPEG), '-v', 'error', '-f', 'lavfi', '-i',
        f'testsrc2=s=160x90:r=30:d={seconds}', '-c:v', 'libx264', '-threads', '2', '-bf', '2',
        '-g', '60', '-keyint_min', '60', '-sc_threshold', '0', '-pix_fmt', 'yuv420p', str(path)],
        purpose='damaged packet fixture', check=True, timeout=60)
    return path


def _packets(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        return [(p.pos, p.size, p.is_keyframe, p.pts * stream.time_base) for p in container.demux(stream) if p.size]


def _damage(path, choose, *, garbage=False):
    """Overwrite one packet as a broken download would: its NAL length, or all of it."""
    data = bytearray(path.read_bytes())
    for pos, size, key, seconds in _packets(path):
        if choose(key, seconds):
            if garbage:
                data[pos + 4:pos + size] = bytes((i * 37 + 11) % 256 for i in range(size - 4))
            else:
                data[pos:pos + 4] = (0x7FFFFFF0).to_bytes(4, 'big')
    path.write_bytes(bytes(data))
    return path


@pytest.fixture(scope='module')
def clean(tmp_path_factory):
    return _source(tmp_path_factory.mktemp('damaged') / 'clean.mp4', 20)


DAMAGE = {
    'p-frame': (dict(choose=lambda key, s: not key and 10 < s < 10.04), 599),
    'keyframe': (dict(choose=lambda key, s: key and s == 10), 599),
    'first-packet': (dict(choose=lambda key, s: s == 0), 540),
    'p-frame-garbage': (dict(choose=lambda key, s: not key and 12 < s < 12.04, garbage=True), 599),
}


def _reference(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        return {f.pts: display_bgra(f, 1., (2560, 2560)) for f in decode_skipping_damaged(container, stream, [])}


def _expected(index, seconds):
    target = (index.target(seconds) + index.origin) / index.time_base
    return index.pts[max(0, bisect.bisect_right(index.pts, target) - 1)]


@pytest.mark.parametrize('kind', DAMAGE)
def test_damaged_packet_is_skipped_and_reads_match_the_index(tmp_path, clean, kind):
    damage, frames = DAMAGE[kind]
    path = _damage(shutil.copyfile(clean, tmp_path / f'{kind}.mp4'), **damage)
    # Same failure the user saw, from the strict container.decode() loop.
    with av.open(str(path)) as container, pytest.raises(av.error.InvalidDataError, match='avcodec_send_packet'):
        for _ in container.decode(video=0):
            pass
    index = probe_media(FFMPEG, path)
    assert len(index.pts) == frames and index.rejected_packets and index.corrupt_frames == 0
    assert index.damaged_head == (kind == 'first-packet')
    reference = _reference(path)
    decoder = SequentialExportDecoder(index)
    try:
        for step in range(0, 600, 3):
            seconds = Fraction(step, 30)
            pixels, receipt = decoder.read(seconds)
            assert receipt['frame_pts'] == _expected(index, seconds)
            assert pixels == reference[receipt['frame_pts']]
    finally:
        decoder.close()


def test_damaged_start_holds_the_first_decodable_picture(tmp_path, clean):
    path = _damage(shutil.copyfile(clean, tmp_path / 'head.mp4'), **DAMAGE['first-packet'][0])
    index = probe_media(FFMPEG, path)
    first = index.pts[0] * index.time_base - index.origin
    assert first == 2 and index.target(0) == first
    decoder = SequentialExportDecoder(index)
    try:
        _, receipt = decoder.read(Fraction(0))
        assert receipt['frame_pts'] == index.pts[0] and receipt['boundary_clamped']
    finally:
        decoder.close()
    # Without recorded damage the existing start contract is unchanged.
    late = MediaIndex(str(path), Fraction(0), Fraction(1, 60), tuple(range(60, 120)), Fraction(60), '{}', 0)
    with pytest.raises(ValueError, match='outside decodable interval'):
        late.target(0)
    assert MediaIndex(*[getattr(late, k) for k in ('path', 'origin', 'time_base', 'pts', 'fps', 'probe_json', 'elapsed')],
                      rejected_packets=(5,), damaged_head=True).target(0) == 1


def test_clip_starting_behind_a_damaged_keyframe_restarts_shortly_before(tmp_path):
    path = _damage(_source(tmp_path / 'long.mp4', 50), lambda key, s: key and s == 40)
    index = probe_media(FFMPEG, path)
    reference = _reference(path)
    decoder = SequentialExportDecoder(index)
    try:
        seconds = Fraction(4051, 100)
        pixels, receipt = decoder.read(seconds)
        # Half a minute back, not the head of the file.
        assert receipt['seek_fallback']
        assert receipt['restart_pts'] == receipt['expected_frame_pts'] - round(30 / index.time_base) > 0
        assert receipt['frame_pts'] == _expected(index, seconds) and pixels == reference[receipt['frame_pts']]
    finally:
        decoder.close()


def test_video_without_any_decodable_picture_still_fails(tmp_path, clean):
    path = _damage(shutil.copyfile(clean, tmp_path / 'all.mp4'), lambda key, s: True)
    with pytest.raises(ExportMediaError, match='NO_VIDEO_FRAMES.*damaged packets'):
        export_media._build_probe(FFMPEG, str(path), None)


@pytest.mark.parametrize('kind,start', [('p-frame', 9.5), ('keyframe', 9.5), ('first-packet', 0.)])
def test_studio_export_route_finishes_over_the_damage(tmp_path, clean, kind, start):
    """run_render_job with a V2 overlay, so the export composes (not the direct FFmpeg route)."""
    from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, VideoTransform
    from twobyteasr.rendering.ass_compiler import compile_ass
    from twobyteasr.timeline.studio_media_pool import add_media_asset, add_video_clip, create_video_track
    source = _damage(shutil.copyfile(clean, tmp_path / f'{kind}.mp4'), **DAMAGE[kind][0])
    overlay = tmp_path / 'overlay.mkv'
    run_hidden_subprocess([str(FFMPEG), '-v', 'error', '-f', 'lavfi', '-i', 'color=blue:s=160x90:r=30:d=20',
                           '-c:v', 'ffv1', str(overlay)], purpose='overlay fixture', check=True, timeout=30)
    project = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=20000, width=160, height=90))
    project.validate()
    asset = add_media_asset(project, overlay, duration_ms=20000,
                            video_metadata={'width': 160, 'height': 90, 'has_video': True},
                            audio_metadata={'has_audio': False})
    track = create_video_track(project, 'V2')
    add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=0).transform = VideoTransform(scale_x=.25, scale_y=.25)
    ass = tmp_path / 'empty.ass'
    ass.write_text(compile_ass(project), encoding='utf-8-sig')
    job = RenderJob(str(source), str(ass), str(tmp_path / 'result.mkv'),
                    RenderSettings(container='mkv', encoder='libx264', preset='ultrafast', audio_codec='none', fps=30, quality=0),
                    start_seconds=start, duration_seconds=3, video_graph=capture_video_graph(project))
    output = run_render_job(FFMPEG, job)
    probe = json.loads(run_hidden_subprocess([str(FFMPEG.with_name('ffprobe.exe')), '-v', 'error', '-count_frames',
        '-show_streams', '-of', 'json', str(output)], purpose='damaged export check', capture_output=True,
        check=True, timeout=30).stdout)
    assert probe['streams'][0]['nb_read_frames'] == '90'
    rows = json.loads((tmp_path / 'result.preflight.json').read_text('utf8'))
    assert [r['rejected_packets'] for r in rows if r.get('status') == 'damaged_source'] == [1]


def test_preflight_receipt_and_run_log_record_the_damage(tmp_path, clean, monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.exports import export_run_log
    path = _damage(shutil.copyfile(clean, tmp_path / 'p.mp4'), **DAMAGE['p-frame'][0])
    noted = []
    monkeypatch.setattr(export_run_log, 'note_export', lambda event, payload: noted.append((event, payload)))
    clip = dict(id='C1', asset_id='A1', source_in_ms=9000, source_out_ms=11000,
                timeline_in_ms=0, timeline_out_ms=2000, playback_rate=1)
    graph = dict(media_pool=[dict(asset_id='A1', canonical_source=str(path), video_metadata=dict(has_video=True))],
                 video_tracks=[dict(id='V1', clips=[clip])], duration_ms=2000, fps=30)
    job = SimpleNamespace(settings=SimpleNamespace(fps=30), start_seconds=0, duration_seconds=2,
                          video_graph=graph, media_path=str(path), output_path=str(tmp_path / 'out.mp4'))
    video_export.preflight_video_job(FFMPEG, job)
    rows = json.loads((tmp_path / 'out.preflight.json').read_text('utf8'))
    damage = [r for r in rows if r.get('status') == 'damaged_source']
    assert len(damage) == 1 and damage[0]['rejected_packets'] == 1 and damage[0]['decoded_frames'] == 599
    assert 10 <= damage[0]['approx_seconds'][0] < 11
    assert noted == [('source_damaged_packets', damage[0])]
