"""Runtime (offscreen) checks: timeline waveform painting follows zoom.

Builds a real waveform cache, then drives WaveformTimeline paint directly:
READY paint, partial-cache zoom responsiveness, LOADING message visibility,
and LOD switching across zoom levels. Usage:

    python scripts/verify_flv_waveform_timeline.py
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"

OUT = ROOT / "tmp" / "flv-waveform-timeline"


def run(command):
    return subprocess.run([str(part) for part in command], capture_output=True, text=True)


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    failures: list[str] = []

    def check(name, ok, detail=""):
        print(("[PASS] " if ok else "[FAIL] ") + name + (f" :: {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    seconds = 60
    media = OUT / "tone.wav"
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"aevalsrc='0.6*sin(660*2*PI*t)*abs(sin(0.5*t))':d={seconds}:s=44100",
         str(media)])
    optimized = OUT / "optimized.mp4"
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(media),
         "-c", "copy", str(optimized)])

    from twobyteasr.waveform_cache import (
        WaveformCache, generate_progressive_waveform_cache,
    )
    stages = []
    final = generate_progressive_waveform_cache(
        str(media), FFMPEG, cache_root=OUT / "waveform",
        on_ready=lambda stage, path: stages.append(stage),
        decode_source_resolver=lambda: str(optimized),
        duration_ms=seconds * 1000,
    )
    check("waveform_stages", stages[0] == "coarse" and stages[-1] == "full", str(stages))

    partial_dir = OUT / "partial"
    shutil.copytree(final, partial_dir)
    metadata = json.loads((partial_dir / "metadata.json").read_text(encoding="utf-8"))
    trimmed = copy.deepcopy(metadata)
    for level in trimmed["levels"]:
        if level["file"].startswith("lod"):
            level["frames"] = max(1, level["frames"] // 5)
    trimmed["coverage_end_ms"] = seconds * 1000 // 5
    trimmed["duration_ms"] = trimmed["coverage_end_ms"]
    trimmed["incomplete"] = True
    (partial_dir / "metadata.json").write_text(json.dumps(trimmed))

    # ---------------------------------------------------------------- widget
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio_project import (
        AudioClip, AudioTrack, AVTrackGroup, MediaAsset, StudioMedia,
        SubtitleProject, VideoClip, VideoTrack,
    )
    from twobyteasr.studio_timeline import WaveformTimeline
    from twobyteasr.timeline_theme import timeline_palette

    asset = MediaAsset(
        asset_id="asset-1", canonical_source=str(media.resolve()),
        duration_ms=seconds * 1000,
        audio_metadata={"has_audio": True},
        video_metadata={"has_video": True},
    )
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=seconds * 1000))
    project.media_pool = [asset]
    video = VideoTrack(id="V1", name="V1")
    video.clips = [VideoClip(id="vc1", asset_id="asset-1", source_in_ms=0,
                             source_out_ms=seconds * 1000, timeline_in_ms=0,
                             timeline_out_ms=seconds * 1000)]
    audio = AudioTrack(id="A1", name="A1")
    audio.clips = [AudioClip(id="ac1", asset_id="asset-1", source_in_ms=0,
                             source_out_ms=seconds * 1000, timeline_in_ms=0,
                             timeline_out_ms=seconds * 1000)]
    project.video_tracks = [video]
    project.audio_tracks = [audio]
    project.av_track_groups = [AVTrackGroup(id="g1", video_track_id="V1",
                                            audio_track_id="A1")]
    project.validate()

    timeline = WaveformTimeline()
    timeline.resize(1200, 640)
    timeline.set_project(project)

    def lane_waveform_pixels(cache_obj) -> tuple[int, int]:
        from PySide6.QtGui import QColor
        timeline.set_cache(cache_obj)
        image = timeline.grab().toImage()
        palette = timeline._timeline_palette()
        rect = timeline._audio_track_rects().get("A1")
        background = QColor(palette.waveform_background)
        left = int(timeline.TRACK_HEADER_WIDTH) + 40
        right = int(timeline._content_right()) - 20
        colored = 0
        textish = 0
        for x in range(left, min(right, int(image.width()))):
            for y in range(int(rect.top()) + 6, int(rect.bottom()) - 6):
                color = image.pixelColor(x, y)
                if abs(color.red() - background.red()) > 12 or \
                   abs(color.green() - background.green()) > 12 or \
                   abs(color.blue() - background.blue()) > 12:
                    colored += 1
        return colored, int(rect.height())

    # 1) READY paint with a full cache.
    full_pixels, lane_height = lane_waveform_pixels(WaveformCache(final))
    check("ready_paint_waveform_visible", full_pixels > 400,
          f"{full_pixels} colored pixels in A1 lane (height {lane_height})")

    # 2) Partial cache (20 % coverage): zoom must re-shape immediately.
    timeline.set_visible_window(0, seconds * 1000)
    whole_pixels, _ = lane_waveform_pixels(WaveformCache(partial_dir))
    time.sleep(0.05)
    app.processEvents()
    t0 = time.perf_counter()
    timeline.set_visible_window(0, 10_000)
    zoom_image = timeline.grab().toImage()
    zoom_ms = (time.perf_counter() - t0) * 1000
    rect = timeline._audio_track_rects().get("A1")
    palette = timeline._timeline_palette()
    from PySide6.QtGui import QColor
    background = QColor(palette.waveform_background)
    zoom_pixels = 0
    for x in range(int(timeline.TRACK_HEADER_WIDTH) + 40, int(timeline._content_right()) - 20):
        for y in range(int(rect.top()) + 6, int(rect.bottom()) - 6):
            color = zoom_image.pixelColor(x, y)
            if abs(color.red() - background.red()) > 12 or \
               abs(color.green() - background.green()) > 12 or \
               abs(color.blue() - background.blue()) > 12:
                zoom_pixels += 1
    check("partial_zoom_repaints_immediately",
          zoom_pixels > 400 and zoom_ms < 250,
          f"pixels whole={whole_pixels} zoomed={zoom_pixels} repaint={zoom_ms:.1f}ms")

    stats = getattr(timeline, "_last_waveform_envelope_stats", {})
    check("partial_zoom_envelope_rebuilt", bool(stats), str(stats))

    # 3) LOD switching across zoom levels with the full cache.
    levels_seen = []
    for span in (1_000, 10_000, 60_000, seconds * 1000):
        timeline.set_visible_window(0, span)
        timeline.grab()
        stats = getattr(timeline, "_last_waveform_envelope_stats", {}) or {}
        levels_seen.append((span, stats.get("level"), stats.get("render_ms")))
    check("lod_switches_with_zoom", len({item[1] for item in levels_seen}) >= 2,
          str(levels_seen))
    slow = [item for item in levels_seen if (item[2] or 0) > 30]
    check("zoom_envelope_rebuild_under_30ms", not slow, str(levels_seen))

    # 4) LOADING progress message paints inside the audio lane.
    timeline.set_cache(None)
    timeline.waveform_caches.clear()
    timeline.set_waveform_state("LOADING", "正在生成音频波形… 42%")
    image = timeline.grab().toImage()
    rect = timeline._audio_track_rects().get("A1")
    from PySide6.QtGui import QColor
    background = QColor(palette.waveform_background)
    text_pixels = 0
    for x in range(int(timeline.TRACK_HEADER_WIDTH) + 10,
                   int(timeline.TRACK_HEADER_WIDTH) + 420):
        for y in range(int(rect.top()), int(rect.bottom())):
            color = image.pixelColor(x, y)
            if abs(color.red() - background.red()) > 20 or \
               abs(color.green() - background.green()) > 20 or \
               abs(color.blue() - background.blue()) > 20:
                text_pixels += 1
    check("loading_message_visible", text_pixels > 50, f"{text_pixels} text pixels")

    timeline.close()
    timeline.deleteLater()
    app.processEvents()

    if failures:
        print("FAILURES:", ", ".join(failures))
        return 1
    print("all runtime checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
