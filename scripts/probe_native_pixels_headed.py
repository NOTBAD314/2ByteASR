"""Pixel-truth probe: does libass really stop rendering native subtitles?

Fresh copy, clean session (no preset apply). Plays a native cue through its
end while grabbing mpv screenshots ("subtitles" mode) every ~90ms, then
counts bright text pixels in the subtitle band. Also measures the
reload_subtitle (sub-remove+sub-add) swap gap mid-cue by pixels.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE_PROJECT = Path(
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects"
    r"\2026-08-28 19-23-22 一起看绝区零前瞻！"
    r"\2026-08-28 19-23-22 一起看绝区零前瞻！.2byteproj"
)
WORK = ROOT / "tmp" / "native_pixel_probe"

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
import os


def band_text_pixels(image: QImage) -> int:
    """Count near-white pixels in the bottom third (subtitle band)."""
    band = image.height() * 2 // 3
    count = 0
    for y in range(band, image.height(), 2):
        for x in range(0, image.width(), 2):
            pixel = image.pixel(x, y)
            r = (pixel >> 16) & 0xFF
            g = (pixel >> 8) & 0xFF
            b = pixel & 0xFF
            if r > 215 and g > 215 and b > 215:
                count += 1
    return count


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    for entry in WORK.iterdir():
        entry.unlink() if entry.is_file() else shutil.rmtree(entry)
    project_copy = WORK / "probe.2byteproj"
    shutil.copy2(SOURCE_PROJECT, project_copy)

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    page.open_project(project_copy)

    cue_start, cue_end = 15883, 17033  # cue 6 "哦哈哈" default native
    frames: list[dict] = []

    def grab(label: str):
        controller = page.video.controller
        if controller is None or not controller.running:
            print(f"[PROBE] {label} controller-not-ready t={int(page.timeline.playhead_ms)}ms", flush=True)
            return
        path = WORK / f"shot-{len(frames):03d}.png"
        try:
            controller.screenshot_to_file(str(path), mode="subtitles")
        except RuntimeError:
            return
        image = QImage(str(path))
        frames.append({
            "label": label,
            "wall": round(time.monotonic(), 3),
            "t_ms": int(page.timeline.playhead_ms),
            "pixels": band_text_pixels(image) if not image.isNull() else -1,
        })
        print(f"[PROBE] {label} t={frames[-1]['t_ms']}ms local={frames[-1]['t_ms'] - cue_start}ms "
              f"text_pixels={frames[-1]['pixels']}", flush=True)

    def phase_clean():
        page._seek((cue_start - 900) / 1000.0)
        page._toggle_playback()
        state = {"stop": False, "deadline": time.monotonic() + 18.0}

        def tick():
            grab("clean")
            if page.timeline.playhead_ms > cue_end + 250 or state["stop"] or time.monotonic() > state["deadline"]:
                page._toggle_playback()
                QTimer.singleShot(400, phase_swap)
                return
            QTimer.singleShot(90, tick)

        tick()

    def phase_swap():
        # mid-cue reload_subtitle: measures the sub-remove+sub-add swap gap
        page._seek((cue_start + 200) / 1000.0)
        page._toggle_playback()
        reloaded_at = {"wall": None, "deadline": time.monotonic() + 18.0}

        def do_reload():
            reloaded_at["wall"] = time.monotonic()
            page.video.reload_subtitle(str(page._preview_path))

        def tick():
            grab("swap")
            if page.timeline.playhead_ms > cue_end + 100 or time.monotonic() > reloaded_at["deadline"]:
                page._toggle_playback()
                finish()
                return
            if reloaded_at["wall"] is None and page.timeline.playhead_ms > cue_start + 600:
                do_reload()
            QTimer.singleShot(70, tick)

        tick()

    def finish():
        clean = [f for f in frames if f["label"] == "clean" and cue_start <= f["t_ms"] < cue_end]
        blank_clean = [f for f in clean if f["pixels"] <= 12]
        swap = [f for f in frames if f["label"] == "swap" and cue_start <= f["t_ms"] < cue_end]
        blank_swap = [f for f in swap if f["pixels"] <= 12]
        print(f"[PROBE] clean: inside={len(clean)} blank={len(blank_blank := blank_clean)} "
              f"({[f['t_ms'] for f in blank_clean]})", flush=True)
        print(f"[PROBE] swap: inside={len(swap)} blank={len(blank_swap)} "
              f"({[f['t_ms'] for f in blank_swap]})", flush=True)
        page.close_page()
        app.quit()

    QTimer.singleShot(900, phase_clean)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
