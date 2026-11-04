import json
from pathlib import Path

import numpy as np

from twobyteasr.playback.waveform_cache import (
    LOD_FACTOR,
    WaveformCache,
    build_lod_pyramid,
    generate_waveform_cache,
)


def test_five_hour_lod_pyramid_stays_disk_backed_and_compact(tmp_path):
    milliseconds_per_frame = 16.0
    five_hour_frames = int(5 * 60 * 60 * 1000 / milliseconds_per_frame)
    level0 = np.memmap(
        tmp_path / "lod0.f32", dtype=np.float32, mode="w+", shape=(five_hour_frames, 2)
    )
    level0[:, 0] = -0.25
    level0[:, 1] = 0.5
    level0.flush()
    del level0

    levels = build_lod_pyramid(
        tmp_path,
        five_hour_frames,
        milliseconds_per_frame=milliseconds_per_frame,
    )

    assert len(levels) >= 6
    assert levels[1].frames == (five_hour_frames + LOD_FACTOR - 1) // LOD_FACTOR
    assert sum((tmp_path / item.file).stat().st_size for item in levels) < 13 * 1024 * 1024


def test_real_ffmpeg_audio_decode_and_lod_window(tmp_path):
    root = Path(__file__).resolve().parents[1]
    ffmpeg = root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    media = tmp_path / "tone.wav"
    import subprocess

    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=2",
            str(media),
        ],
        check=True,
    )

    cache_dir = generate_waveform_cache(
        media, ffmpeg, cache_root=tmp_path / "cache"
    )
    cache = WaveformCache(cache_dir)
    level, pairs = cache.read_window(250, 1250, 300)

    assert cache.metadata.duration_ms == 2000
    assert pairs.shape[1] == 2
    assert len(pairs) > 0
    assert np.max(pairs[:, 1]) > 0.05
    assert np.min(pairs[:, 0]) < -0.05
    assert json.loads((cache_dir / "metadata.json").read_text(encoding="utf-8"))[
        "schema_version"
    ] == 1


def test_cache_reuses_valid_generation(tmp_path):
    root = Path(__file__).resolve().parents[1]
    ffmpeg = root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    media = tmp_path / "short.wav"
    import subprocess

    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            "0.25",
            str(media),
        ],
        check=True,
    )
    first = generate_waveform_cache(media, ffmpeg, cache_root=tmp_path / "cache")
    marker = first / "keep.marker"
    marker.write_text("same cache", encoding="ascii")

    second = generate_waveform_cache(media, ffmpeg, cache_root=tmp_path / "cache")

    assert second == first
    assert marker.is_file()
