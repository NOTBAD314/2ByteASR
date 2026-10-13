"""Real decoding stays exact while avoiding redundant prefix/index work."""
from fractions import Fraction
from pathlib import Path
import threading
import os

import av
import pytest

from twobyteasr import export_media
from twobyteasr.processes import run_hidden_subprocess

FFMPEG = Path(__file__).resolve().parents[1] / 'tools/ffmpeg/bin/ffmpeg.exe'


@pytest.fixture
def long_gop(tmp_path):
    path = tmp_path / 'long-gop.mp4'
    run_hidden_subprocess([
        str(FFMPEG), '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=s=160x90:r=30:d=30', '-c:v', 'libx264', '-threads', '2',
        '-g', '60', '-keyint_min', '60', '-sc_threshold', '0', str(path),
    ], purpose='export work regression fixture', check=True, timeout=30)
    return path


def test_probe_cache_is_media_identity_not_cancel_callback(monkeypatch, long_gop):
    opened = []
    original = av.open

    def counted(*args, **kwargs):
        opened.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(av, 'open', counted)
    first = export_media.probe_media(FFMPEG, long_gop, cancelled=threading.Event().is_set)
    second = export_media.probe_media(FFMPEG, long_gop, cancelled=threading.Event().is_set)
    assert first == second
    assert len(opened) == 1, 'A new export cancellation token must reuse the successful media index'


def test_cancelled_warm_probe_never_returns_cached_success(long_gop):
    event = threading.Event()
    callback = event.is_set
    export_media.probe_media(FFMPEG, long_gop, cancelled=callback)
    event.set()
    with pytest.raises(InterruptedError):
        export_media.probe_media(FFMPEG, long_gop, cancelled=callback)


def test_changed_media_identity_rebuilds_index(monkeypatch, long_gop):
    opened = []
    original = av.open

    def counted(*args, **kwargs):
        opened.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(av, 'open', counted)
    callback = threading.Event().is_set
    first = export_media.probe_media(FFMPEG, long_gop, cancelled=callback)
    info = long_gop.stat()
    os.utime(long_gop, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    second = export_media.probe_media(FFMPEG, long_gop, cancelled=callback)
    assert first.pts == second.pts
    assert len(opened) == 2, 'Changed media identity must invalidate the successful index'


def _count_decoder(monkeypatch, *, wrong_seek=False, cancel_after=None):
    from twobyteasr import video_decode_worker
    original = video_decode_worker.open_decoder
    counts = {'frames': 0, 'seeks': []}

    class CountedContainer:
        def __init__(self, container):
            self.container = container

        def seek(self, offset, **kwargs):
            counts['seeks'].append(offset)
            if wrong_seek and offset > 0:
                # Simulate a container whose index lands after the requested
                # boundary: the successful full PTS index remains authoritative.
                offset += int(Fraction(4) / kwargs['stream'].time_base)
            return self.container.seek(offset, **kwargs)

        def decode(self, stream):
            for frame in self.container.decode(stream):
                counts['frames'] += 1
                if cancel_after and counts['frames'] >= 10:
                    cancel_after.set()
                yield frame

        def close(self):
            self.container.close()

    def open_counted(*args, **kwargs):
        container, stream, backend = original(*args, **kwargs)
        return CountedContainer(container), stream, backend

    monkeypatch.setattr(video_decode_worker, 'open_decoder', open_counted)
    return counts


def test_late_first_frame_uses_keyframe_and_keeps_exact_pixels(monkeypatch, long_gop):
    index = export_media.probe_media(FFMPEG, long_gop)
    target = Fraction(27123, 1000)
    expected_pts = max(pts for pts in index.pts if pts * index.time_base - index.origin <= target)
    from twobyteasr.video_decode_worker import display_bgra
    with av.open(str(long_gop)) as reference:
        frame = next(frame for frame in reference.decode(video=0) if frame.pts == expected_pts)
        expected = display_bgra(frame, 1., (2560, 2560))
    counts = _count_decoder(monkeypatch)
    decoder = export_media.SequentialExportDecoder(index)
    try:
        pixels, receipt = decoder.read(target)
        assert receipt['frame_pts'] == expected_pts
        assert pixels == expected
        assert counts['frames'] <= 70, counts
        _, earlier = decoder.read(Fraction(10123, 1000))
        assert earlier['frame_pts'] == max(p for p in index.pts if p * index.time_base <= Fraction(10123, 1000))
    finally:
        decoder.close()


def test_bad_container_seek_falls_back_to_exact_index(monkeypatch, long_gop):
    index = export_media.probe_media(FFMPEG, long_gop)
    counts = _count_decoder(monkeypatch, wrong_seek=True)
    decoder = export_media.SequentialExportDecoder(index)
    try:
        _, receipt = decoder.read(Fraction(23123, 1000))
        assert receipt['frame_pts'] == max(p for p in index.pts if p * index.time_base <= Fraction(23123, 1000))
        assert receipt.get('seek_fallback') is True
        assert 0 in counts['seeks']
    finally:
        decoder.close()


def test_decode_prefix_can_be_cancelled(monkeypatch, long_gop):
    index = export_media.probe_media(FFMPEG, long_gop)
    cancelled = threading.Event()
    counts = _count_decoder(monkeypatch, cancel_after=cancelled)
    decoder = export_media.SequentialExportDecoder(index, cancelled=cancelled.is_set)
    try:
        with pytest.raises(InterruptedError):
            decoder.read(Fraction(27123, 1000))
        assert counts['frames'] <= 11
    finally:
        decoder.close()


@pytest.mark.parametrize('container_kind', ['flv', 'vfr_nonzero'])
def test_index_checked_seek_keeps_container_pixels(monkeypatch, tmp_path, long_gop, container_kind):
    if container_kind == 'flv':
        source = tmp_path / 'indexed.flv'
        command = ['-i', str(long_gop), '-c:v', 'copy', '-an', str(source)]
    else:
        source = tmp_path / 'nonzero-vfr.mkv'
        command = ['-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=30:d=10',
                   '-vf', "select='not(mod(n,3))+eq(mod(n,7),0)',setpts=PTS+2/TB",
                   '-fps_mode', 'vfr', '-c:v', 'libx264', '-threads', '2', '-g', '60', str(source)]
    run_hidden_subprocess([str(FFMPEG), '-v', 'error', *command],
                          purpose='container seek regression fixture', check=True, timeout=30)
    index = export_media.probe_media(FFMPEG, source)
    if container_kind == 'vfr_nonzero':
        assert index.origin > 0
        assert len({b-a for a, b in zip(index.pts, index.pts[1:])}) > 1
    chosen = [len(index.pts)-5, len(index.pts)//2, 0]
    expected_pts = [index.pts[i] for i in chosen]
    targets = [(index.pts[i]+index.pts[i+1])*index.time_base/2-index.origin for i in chosen]
    from twobyteasr.video_decode_worker import display_bgra
    with av.open(str(source)) as reference:
        expected = {frame.pts: display_bgra(frame, 1., (2560, 2560))
                    for frame in reference.decode(video=0) if frame.pts in expected_pts}
    _count_decoder(monkeypatch)
    decoder = export_media.SequentialExportDecoder(index)
    try:
        for target, pts in zip(targets, expected_pts):
            pixels, receipt = decoder.read(target)
            assert receipt['frame_pts'] == pts
            assert pixels == expected[pts]
    finally:
        decoder.close()


def test_cancelled_cold_probe_is_not_cached(monkeypatch, long_gop):
    opened = []
    original = av.open

    def counted(*args, **kwargs):
        opened.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(av, 'open', counted)
    polls = []

    def cancel_during_decode():
        polls.append(True)
        return len(polls) >= 6

    with pytest.raises(InterruptedError):
        export_media.probe_media(FFMPEG, long_gop, cancelled=cancel_during_decode)
    result = export_media.probe_media(FFMPEG, long_gop, cancelled=lambda: False)
    assert len(result.pts) == 900
    assert len(opened) == 2, 'A cancelled partial index must not become a cache hit'


def test_probe_cache_retains_only_24_successful_identities(monkeypatch, tmp_path):
    from collections import OrderedDict
    monkeypatch.setattr(export_media, '_PROBE_CACHE', OrderedDict())
    calls = []

    def build(ffmpeg, path, cancelled):
        calls.append(path)
        return export_media.MediaIndex(path, Fraction(0), Fraction(1, 30), (0, 1),
                                       Fraction(30), '{}', 0.)

    monkeypatch.setattr(export_media, '_build_probe', build)
    sources = [tmp_path / f'{i}.mp4' for i in range(25)]
    for source in sources:
        source.write_bytes(b'identity fixture; decoder stubbed')
        export_media.probe_media(FFMPEG, source)
    assert len(calls) == 25 and len(export_media._PROBE_CACHE) == 24
    export_media.probe_media(FFMPEG, sources[-1])
    assert len(calls) == 25
    export_media.probe_media(FFMPEG, sources[0])
    assert len(calls) == 26 and len(export_media._PROBE_CACHE) == 24


def test_compose_propagates_cancellation_during_first_prefix(monkeypatch, tmp_path, long_gop):
    from twobyteasr import video_export
    from twobyteasr.studio_render import RenderJob, RenderSettings

    index = export_media.probe_media(FFMPEG, long_gop)
    cancelled = threading.Event()
    counts = _count_decoder(monkeypatch, cancel_after=cancelled)
    graph = dict(media_pool=[dict(asset_id='A1', canonical_source=str(long_gop),
                                 video_metadata=dict(has_video=True))],
        video_tracks=[dict(id='V1', clips=[dict(id='late', asset_id='A1', source_in_ms=27123,
            source_out_ms=28123, timeline_in_ms=0, timeline_out_ms=1000, playback_rate=1.)])],
        width=160, height=90, fps=30, duration_ms=1000)
    output = tmp_path / 'cancelled.mkv'
    job = RenderJob(str(long_gop), str(tmp_path / 'unused.ass'), str(output),
        RenderSettings(width=160, height=90, fps=30, audio_codec='none'),
        duration_seconds=1, video_graph=graph)
    with pytest.raises(InterruptedError):
        video_export.compose_video(FFMPEG, job, output, cancelled=cancelled.is_set,
                                   indexes={str(long_gop.resolve()): index})
    assert counts['frames'] <= 11
