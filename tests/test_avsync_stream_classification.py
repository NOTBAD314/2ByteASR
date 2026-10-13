"""AV sync scan classifies FLV streams by codec type, not by stream index."""
from __future__ import annotations

import os
import subprocess

import pytest

from twobyteasr.audio_engine import studio_ffmpeg_path
from twobyteasr.avsync import AVSyncMap, probe_av_stream_indices, scan_timestamp_gaps


def _tools():
    ffmpeg = studio_ffmpeg_path()
    ffprobe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not ffmpeg.is_file() or not ffprobe.is_file():
        pytest.skip("bundled ffmpeg/ffprobe not available")
    return ffmpeg, ffprobe


def _flv_with_video_only_hole(ffmpeg, target, *, audio_first: bool):
    """Video timestamps jump 2 s at t=5 s; audio stays continuous."""
    maps = ["-map", "1:a", "-map", "0:v"] if audio_first else ["-map", "0:v", "-map", "1:a"]
    subprocess.run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=10",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
        "-vf", "setpts=PTS+if(gte(T\\,5)\\,2/TB\\,0)", *maps,
        "-c:v", "libx264", "-g", "30", "-c:a", "aac", "-f", "flv", str(target)], check=True)


@pytest.mark.parametrize("audio_first", [False, True])
def test_video_only_hole_never_moves_the_audio_content_clock(tmp_path, audio_first):
    ffmpeg, ffprobe = _tools()
    flv = tmp_path / "hole.flv"
    _flv_with_video_only_hole(ffmpeg, flv, audio_first=audio_first)
    assert probe_av_stream_indices(flv, ffprobe) == ((1, 0) if audio_first else (0, 1))
    result = scan_timestamp_gaps(flv, ffprobe, source_duration_ms=12_000)
    sync_map = result.map
    assert sync_map.stream_indices == ({"video": 1, "audio": 0} if audio_first else {"video": 0, "audio": 1})
    assert result.video_only_gaps == 1
    assert sync_map.total_gap_ms == 0 and sync_map.is_identity
    assert sync_map.video_holes and not sync_map.audio_holes
    # The classification survives saving and overrides.
    again = AVSyncMap.from_dict(sync_map.to_dict()).with_overrides(())
    assert again.stream_indices == sync_map.stream_indices
    assert again.video_holes == sync_map.video_holes
