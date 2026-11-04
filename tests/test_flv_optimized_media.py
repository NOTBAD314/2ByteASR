"""FLV lossless remux (optimized media) + progressive waveform coverage.

Real-ffmpeg tests for IndexedMediaCache v2 (MP4-first remux, MKV fallback,
cache reuse, cancellation) and the incremental/resumable waveform pipeline.
"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from twobyteasr.media.indexed_media import IndexedMediaCache
from twobyteasr.playback.waveform_cache import (
    WaveformCache,
    append_outline_level,
    generate_outline_from_media,
    generate_progressive_waveform_cache,
    generate_waveform_cache,
    generate_waveform_cache_incremental,
    media_cache_key,
)

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"


def run_ffmpeg(*args: str) -> None:
    subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
    )


def probe_json(path: Path) -> dict:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def flv_file(tmp_path_factory) -> Path:
    media = tmp_path_factory.mktemp("flv") / "sample.flv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc=duration=8:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        "-f", "flv", str(media),
    )
    return media


# --------------------------------------------------------------------------
# Optimized media remux


def test_flv_remux_prefers_mp4_stream_copy_and_caches(tmp_path, flv_file):
    cache = IndexedMediaCache(root=tmp_path)
    resolved = cache.resolve(str(flv_file))
    assert resolved == str(flv_file)  # non-blocking: original until ready
    target = cache.wait_optimized(str(flv_file), timeout=180)
    optimized = Path(target)
    assert optimized.is_file()
    assert optimized.suffix == ".mp4"
    payload = probe_json(optimized)
    codecs = {(s["codec_type"], s["codec_name"]) for s in payload["streams"]}
    assert ("video", "h264") in codecs and ("audio", "aac") in codecs
    original_duration = float(probe_json(flv_file)["format"]["duration"])
    assert abs(float(payload["format"]["duration"]) - original_duration) < 0.2

    # Second resolution must hit the warm cache: a failing remux proves no retry.
    def boom(self, *args, **kwargs):
        raise AssertionError("remux must not run again on a warm cache")

    cache._remux = boom.__get__(cache, type(cache))
    assert Path(cache.resolve(str(flv_file))) == optimized

    manifest = json.loads(
        (tmp_path / "v2" / _key_for(flv_file, "optimize-v2") / "ready.json").read_text()
    )
    assert manifest["container"] == "mp4"


def _key_for(source: Path, version: str) -> str:
    import hashlib
    stat = source.stat()
    return hashlib.sha256(
        f"{version}|{source}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    ).hexdigest()[:32]


def test_remux_falls_back_to_mkv_when_mp4_fails(tmp_path, flv_file):
    cache = IndexedMediaCache(root=tmp_path)
    original_remux = IndexedMediaCache._remux

    def flaky_mp4(self, ffmpeg, source, target, container, *args, **kwargs):
        if container == "mp4":
            raise RuntimeError("injected mp4 mux failure")
        return original_remux(self, ffmpeg, source, target, container, *args, **kwargs)

    cache._remux = flaky_mp4.__get__(cache, type(cache))
    cache.resolve(str(flv_file))
    target = Path(cache.wait_optimized(str(flv_file), timeout=180))
    assert target.suffix == ".mkv"
    assert target.is_file()
    assert probe_json(target)["streams"]


def test_remux_codec_gate_goes_straight_to_mkv(tmp_path, flv_file, monkeypatch):
    cache = IndexedMediaCache(root=tmp_path)
    containers = []

    def fake_probe(command, **_kwargs):
        class Result:
            returncode = 0
            stdout = json.dumps({
                "format": {"duration": "8.0", "start_time": "0"},
                "streams": [
                    {"codec_type": "video", "codec_name": "vp9", "start_time": "0"},
                    {"codec_type": "audio", "codec_name": "opus", "start_time": "0"},
                ],
            })
        return Result()

    monkeypatch.setattr("twobyteasr.media.indexed_media.run_hidden_subprocess", fake_probe)

    def record_only(self, ffmpeg, source, target, container, *args, **kwargs):
        containers.append(container)
        target.write_bytes(b"stub")

    cache._remux = record_only.__get__(cache, type(cache))
    cache.resolve(str(flv_file))
    target = Path(cache.wait_optimized(str(flv_file), timeout=30))
    assert containers == ["mkv"]
    assert target.suffix == ".mkv"


def test_cancelled_remux_falls_back_to_original_without_partial(tmp_path, flv_file):
    cache = IndexedMediaCache(root=tmp_path)

    def cancelled_remux(self, *args, **kwargs):
        raise InterruptedError("optimized media cancelled")

    cache._remux = cancelled_remux.__get__(cache, type(cache))
    cache.resolve(str(flv_file))
    assert cache.wait_optimized(str(flv_file), timeout=10) == str(flv_file)
    assert str(flv_file) in cache.errors
    partials = list(tmp_path.rglob("*.partial.*"))
    assert partials == []


def test_legacy_v1_cache_is_reused_without_new_remux(tmp_path, flv_file):
    legacy_dir = tmp_path / _key_for(flv_file, "seek-v1")
    legacy_dir.mkdir(parents=True)
    legacy_target = legacy_dir / "indexed.mkv"
    legacy_target.write_bytes(b"legacy")
    (legacy_dir / "ready.json").write_text("{}", encoding="utf-8")

    cache = IndexedMediaCache(root=tmp_path)

    def boom(self, *args, **kwargs):
        raise AssertionError("legacy cache must satisfy without remuxing")

    cache._remux = boom.__get__(cache, type(cache))
    assert cache.wait_optimized(str(flv_file), timeout=10) == str(legacy_target)


def test_wait_optimized_is_cancelled_promptly(tmp_path, flv_file):
    cache = IndexedMediaCache(root=tmp_path)
    # Never enqueue real work: hold the preparation in a blocked fake.
    release = threading.Event()

    def blocked(self, *args, **kwargs):
        release.wait(30)
        return flv_file

    cache._prepare = blocked.__get__(cache, type(cache))
    cache.resolve(str(flv_file))
    stop = threading.Event()

    def wait_and_cancel():
        cache.wait_optimized(str(flv_file), cancelled=stop.is_set, timeout=30)

    waiter = threading.Thread(target=wait_and_cancel, daemon=True)
    waiter.start()
    stop.set()
    waiter.join(timeout=3.0)
    assert not waiter.is_alive()
    release.set()


# --------------------------------------------------------------------------
# Progressive / incremental waveform


def _sine_wav(path: Path, seconds: float) -> Path:
    run_ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=16000:duration={seconds}",
        str(path),
    )
    return path


def test_incremental_full_cache_matches_legacy_bit_for_bit(tmp_path):
    media = _sine_wav(tmp_path / "tone.wav", 6)
    snaps = []
    final = generate_waveform_cache_incremental(
        media, FFMPEG, cache_root=tmp_path / "cache",
        snapshot_interval_ms=500, snapshot_min_wall_ms=0.0,
        on_snapshot=lambda path, coverage: snaps.append(coverage),
    )
    assert snaps and snaps[-1] == 6000
    metadata = json.loads((final / "metadata.json").read_text(encoding="utf-8"))
    assert not metadata.get("incomplete", False)

    import numpy as np
    legacy = generate_waveform_cache(media, FFMPEG, cache_root=tmp_path / "legacy")
    for name in ("lod0.f32", "lod1.f32", "lod3.f32"):
        produced = np.asarray(np.memmap(final / name, dtype=np.float32, mode="r"))
        expected = np.asarray(np.memmap(legacy / name, dtype=np.float32, mode="r"))
        assert produced.shape == expected.shape
        assert bool(np.array_equal(produced, expected))


def test_incremental_resume_after_cancel_matches_full_decode(tmp_path):
    media = _sine_wav(tmp_path / "long.wav", 60)
    optimized = tmp_path / "optimized.mp4"
    run_ffmpeg("-i", str(media), "-c", "copy", str(optimized))

    state = {"cancelled": False}
    with pytest.raises(InterruptedError):
        generate_waveform_cache_incremental(
            media, FFMPEG, cache_root=tmp_path / "cache",
            snapshot_interval_ms=800, snapshot_min_wall_ms=0.0,
            cancelled=lambda: state["cancelled"],
            decode_path=str(optimized),
            on_snapshot=lambda path, coverage: state.__setitem__("cancelled", True),
        )
    key = media_cache_key(media)
    partial = json.loads(
        (tmp_path / "cache" / key / "metadata.json").read_text(encoding="utf-8")
    )
    assert partial["incomplete"] is True
    assert 0 < partial["coverage_end_ms"] < 60_000

    final = generate_waveform_cache_incremental(
        media, FFMPEG, cache_root=tmp_path / "cache",
        snapshot_min_wall_ms=0.0, decode_path=str(optimized),
    )
    metadata = json.loads((final / "metadata.json").read_text(encoding="utf-8"))
    assert not metadata.get("incomplete", False)
    assert metadata["coverage_end_ms"] == 60_000

    import numpy as np
    legacy = generate_waveform_cache(media, FFMPEG, cache_root=tmp_path / "legacy")
    produced = np.asarray(np.memmap(final / "lod0.f32", dtype=np.float32, mode="r"))
    expected = np.asarray(np.memmap(legacy / "lod0.f32", dtype=np.float32, mode="r"))
    assert produced.shape == expected.shape
    assert bool(np.array_equal(produced, expected))


def test_partial_cache_zoom_reads_respond_via_outline(tmp_path):
    media = _sine_wav(tmp_path / "long.wav", 30)
    optimized = tmp_path / "optimized.mp4"
    run_ffmpeg("-i", str(media), "-c", "copy", str(optimized))
    pairs = generate_outline_from_media(optimized, FFMPEG, duration_ms=30_000)
    assert pairs is not None and len(pairs) >= 8

    final = generate_waveform_cache_incremental(
        media, FFMPEG, cache_root=tmp_path / "cache", decode_path=str(optimized),
        outline_pairs=pairs, outline_ms_per_frame=30_000 / len(pairs),
        snapshot_min_wall_ms=0.0, snapshot_interval_ms=1000,
    )
    import copy
    partial_dir = tmp_path / "partial"
    partial_dir.mkdir()
    for item in final.iterdir():
        (partial_dir / item.name).write_bytes(item.read_bytes())
    metadata = json.loads((partial_dir / "metadata.json").read_text(encoding="utf-8"))
    trimmed = copy.deepcopy(metadata)
    for level in trimmed["levels"]:
        if level["file"].startswith("lod"):
            level["frames"] = max(1, level["frames"] // 6)
    trimmed["coverage_end_ms"] = 5000
    trimmed["duration_ms"] = 5000
    trimmed["incomplete"] = True
    (partial_dir / "metadata.json").write_text(json.dumps(trimmed), encoding="utf-8")

    cache = WaveformCache(partial_dir)
    covered_level, covered = cache.read_window(0, 4_000, 1800)
    assert covered_level.file == "lod0.f32" and len(covered) > 0
    outline_level, silhouette = cache.read_window(10_000, 30_000, 1800)
    assert outline_level.file == "outline.f32"
    assert len(silhouette) > 0
    zoom_level, zoomed = cache.read_window(0, 500, 1800)
    assert zoom_level.file == "lod0.f32"


def test_append_outline_level_adds_whole_duration_silhouette(tmp_path):
    media = _sine_wav(tmp_path / "tone.wav", 12)
    coarse = generate_waveform_cache(media, FFMPEG, cache_root=tmp_path / "cache")
    pairs = generate_outline_from_media(media, FFMPEG, duration_ms=12_000)
    assert pairs is not None
    level = append_outline_level(coarse, pairs, ms_per_frame=12_000 / len(pairs))
    assert level is not None
    cache = WaveformCache(coarse)
    # Zoomed far out (12 s across a handful of pixels) the outline silhouette
    # is the level that carries the whole duration.
    chosen, data = cache.read_window(0, 12_000, 4)
    assert chosen.file == "outline.f32"
    assert len(data) == len(pairs)


def test_progressive_orchestrator_publishes_stages_and_warms(tmp_path):
    media = _sine_wav(tmp_path / "long.wav", 180)
    optimized = tmp_path / "optimized.mp4"
    run_ffmpeg("-i", str(media), "-c", "copy", str(optimized))
    stages = []

    final = generate_progressive_waveform_cache(
        media, FFMPEG, cache_root=tmp_path / "cache",
        on_ready=lambda stage, path: stages.append(stage),
        decode_source_resolver=lambda: str(optimized),
        duration_ms=180_000,
    )
    assert stages[0] == "coarse"
    assert "partial" in stages
    assert stages[-1] == "full"
    metadata = json.loads((final / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["coverage_end_ms"] == 180_000
    assert any(level["file"] == "outline.f32" for level in metadata["levels"])

    warm_stages = []
    warm = generate_progressive_waveform_cache(
        media, FFMPEG, cache_root=tmp_path / "cache",
        on_ready=lambda stage, path: warm_stages.append(stage),
        decode_source_resolver=lambda: str(optimized),
        duration_ms=180_000,
    )
    assert warm_stages == ["full"]
    assert warm == final


# --------------------------------------------------------------------------
# Page-level end to end: real FLV -> remux -> progressive waveform


def test_studio_page_flv_waveform_end_to_end(tmp_path, monkeypatch, flv_file):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from twobyteasr.projects.studio_project import (
        MediaAsset, StudioMedia, SubtitleProject,
    )
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    import twobyteasr.media.indexed_media as indexed_media

    isolated = IndexedMediaCache(root=tmp_path / "seek")
    monkeypatch.setattr(indexed_media, "GLOBAL_INDEXED_MEDIA", isolated)

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    try:
        asset = MediaAsset(
            asset_id="asset-1", canonical_source=str(flv_file.resolve()),
            duration_ms=8_000,
            audio_metadata={"has_audio": True},
            video_metadata={"has_video": True},
        )
        project = SubtitleProject(media=StudioMedia(str(flv_file), duration_ms=8_000))
        project.media_pool = [asset]
        page.project = project
        # set_cache maps caches onto media-pool assets through the timeline's
        # own project reference, mirroring the real ingest flow.
        page.timeline.set_project(project)

        page._generate_waveform(str(flv_file))
        deadline = time.monotonic() + 120
        # The coarse stage already covers this short clip; completion means the
        # background generation (optimized-source wait included) drained.
        while time.monotonic() < deadline:
            app.processEvents()
            cache = page.timeline.waveform_caches.get("asset-1")
            with page._waveform_inflight_lock:
                drained = not page._waveform_inflight
            if cache is not None and cache.metadata.coverage_end_ms >= 8_000 and drained:
                break
            time.sleep(0.05)
        else:
            pytest.fail("waveform did not complete in time")

        assert page.timeline.waveform_state == "READY"
        # Decoded audio can run a few tens of ms past the container duration
        # (AAC priming/tail samples); that is real coverage, not corruption.
        assert abs(cache.metadata.coverage_end_ms - 8_000) < 500
        # Audio extraction no longer copies the entire recording first.
        optimized = isolated.optimized_target(str(flv_file.resolve()))
        assert optimized is None
        assert isolated._requested == set()

        # A second generation must reuse the completed cache instantly.
        page._waveform_generation += 1
        page._generate_waveform(str(flv_file))
        app.processEvents()
        assert abs(
            page.timeline.waveform_caches["asset-1"].metadata.coverage_end_ms - 8_000
        ) < 500
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()
