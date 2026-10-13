"""Indexed audio-only copy of an FLV keeps the original source time domain.

The preview audio decoder seeks an hour-long FLV in 0.3-1.5 s because FFmpeg
scans it from the head; the stream-copied Matroska copy seeks in ~20 ms. The
copy is only allowed if decoding it at source time T yields the same samples
as decoding the original at T, including when audio starts after video.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from twobyteasr.audio_engine import build_audio_decode_command, studio_ffmpeg_path
from twobyteasr.indexed_media import (
    AUDIO_SEEK_COPY_NAME,
    AUDIO_SEEK_MARKER_NAME,
    audio_seek_copy_ready,
    build_audio_seek_copy,
)


def _tools():
    ffmpeg = studio_ffmpeg_path()
    ffprobe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not ffmpeg.is_file() or not ffprobe.is_file():
        pytest.skip("bundled ffmpeg/ffprobe not available")
    return ffmpeg, ffprobe


def _make_flv(ffmpeg: Path, target: Path, *, audio_delay_s: float) -> None:
    # Video from t=0, a chirp-like tone whose samples differ every instant,
    # audio stream starting ``audio_delay_s`` later (as live recorders do).
    subprocess.run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=20",
        "-itsoffset", f"{audio_delay_s:.3f}",
        "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*(200+40*t)*t)|sin(2*PI*(310+25*t)*t):s=48000:d=19.5",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-g", "60", "-c:a", "aac", "-b:a", "128k",
        "-f", "flv", str(target)], check=True)


def _decode(ffmpeg: Path, source: Path, source_ms: int, decode_source=None) -> np.ndarray:
    command = build_audio_decode_command(
        ffmpeg, source, source_ms=source_ms, rate=1.0, sample_rate=48000, channels=2,
        pcm_format="f32le", decode_source=decode_source)
    command[-1:-1] = ["-t", "2"]  # 2 s of output is enough for the comparison
    output = subprocess.run(command, check=True, capture_output=True).stdout
    return np.frombuffer(output, dtype="<f4").reshape(-1, 2)


def _best_lag(a: np.ndarray, b: np.ndarray, window: int = 960) -> tuple[int, float]:
    n = len(a)
    def mismatch(k):
        return float(np.mean(np.abs(a[max(0, k):n + min(0, k)] - b[max(0, -k):n - max(0, k)])))
    lag = min(range(-window, window + 1), key=mismatch)
    error = float(np.max(np.abs(a[max(0, lag):n + min(0, lag)] - b[max(0, -lag):n - max(0, lag)])))
    return lag, error


@pytest.mark.parametrize("audio_delay_s", [0.0, 0.08])
def test_copy_decodes_the_same_samples_at_the_same_source_time(tmp_path, audio_delay_s):
    ffmpeg, ffprobe = _tools()
    flv = tmp_path / "live.flv"
    _make_flv(ffmpeg, flv, audio_delay_s=audio_delay_s)
    folder = tmp_path / "cache"
    folder.mkdir()
    marker = build_audio_seek_copy(str(flv), folder, ffmpeg, ffprobe)
    assert (folder / AUDIO_SEEK_COPY_NAME).is_file()
    assert (folder / AUDIO_SEEK_MARKER_NAME).is_file()
    # The copy keeps the audio stream's own start (AAC priming included); the
    # offset brings -ss back to the original container's start.
    assert marker["offset_ms"] == round(marker["container_start_ms"] - marker["copy_start_ms"])
    if audio_delay_s:
        assert marker["offset_ms"] < -40
    ready = audio_seek_copy_ready(folder, str(flv))
    assert ready == {"path": str(folder / AUDIO_SEEK_COPY_NAME), "offset_ms": marker["offset_ms"]}
    for source_ms in (260, 4_000, 11_337):
        original = _decode(ffmpeg, flv, source_ms)
        copied = _decode(ffmpeg, flv, source_ms, decode_source=ready)
        count = min(len(original), len(copied))
        assert count > 48000
        lag, error = _best_lag(original[:count, 0], copied[:count, 0])
        # FLV keeps millisecond packet times; the copy may land a few samples
        # apart (measured 8-16 samples = 0.17-0.33 ms), never a frame apart.
        assert abs(lag) <= 48, (source_ms, lag)
        assert error < 1e-4, (source_ms, lag, error)


def test_copy_is_rejected_after_the_source_changes(tmp_path):
    ffmpeg, ffprobe = _tools()
    flv = tmp_path / "live.flv"
    _make_flv(ffmpeg, flv, audio_delay_s=0.0)
    folder = tmp_path / "cache"
    folder.mkdir()
    build_audio_seek_copy(str(flv), folder, ffmpeg, ffprobe)
    assert audio_seek_copy_ready(folder, str(flv)) is not None
    stat = flv.stat()
    os.utime(flv, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert audio_seek_copy_ready(folder, str(flv)) is None


def test_decode_command_without_copy_reads_the_original(tmp_path):
    source = tmp_path / "missing.flv"
    command = build_audio_decode_command("ffmpeg", source, source_ms=5_000, rate=1.0,
                                         decode_source={"path": str(tmp_path / "gone.mka"), "offset_ms": -80})
    assert command[command.index("-i") + 1] == str(source)
    assert command[command.index("-ss") + 1] == "5.000000"


def test_media_cache_builds_copy_in_background_and_then_serves_it(tmp_path, monkeypatch):
    """Preview path: unknown -> background build -> {"path", "offset_ms"}; MP4 never."""
    import time as _time
    from twobyteasr.indexed_media import IndexedMediaCache
    ffmpeg, _ffprobe = _tools()
    flv = tmp_path / "media" / "live.flv"
    flv.parent.mkdir()
    _make_flv(ffmpeg, flv, audio_delay_s=0.08)
    cache = IndexedMediaCache(root=tmp_path / "seek")
    monkeypatch.setattr("twobyteasr.storage_service.safe_path", lambda *a, **k: True)
    assert cache.audio_seek_source(str(flv)) is None  # starts the build
    deadline = _time.monotonic() + 30
    ready = None
    while ready is None and _time.monotonic() < deadline:
        _time.sleep(0.1)
        cache._audio_seek.pop(str(flv), None)  # skip the 2 s memo for the test
        ready = cache.audio_seek_source(str(flv))
    assert ready is not None and Path(ready["path"]).is_file() and ready["offset_ms"] < 0
    assert cache.audio_seek_source(str(flv)) == ready  # memoised
    assert cache.audio_seek_source(str(tmp_path / "clip.mp4")) is None
