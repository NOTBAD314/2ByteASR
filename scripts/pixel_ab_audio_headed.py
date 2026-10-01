"""Pixel-truth A/B on the audio-only project (black background).

Samples mpv screenshots every ~300ms through the whole cue:
A = default style, B = font size bumped via the real spinbox then played.
The black backdrop makes subtitle pixels unambiguous.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE_PROJECT = Path(
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\8月30日\8月30日.2byteproj"
)
WORK = ROOT / "tmp" / "pixel_ab"

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.style_recipe import recipe_payload_for_style, route_recipe
import os

CUE_ID = "2"
CUE_START, CUE_END = 3750, 5533


def bright_pixels(image: QImage, *, threshold: 200) -> int:
    if image.isNull():
        return -1
    count = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            pixel = image.pixel(x, y)
            r = (pixel >> 16) & 0xFF
            g = (pixel >> 8) & 0xFF
            b = pixel & 0xFF
            if r > threshold and g > threshold and b > threshold:
                count += 1
    return count


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    for entry in WORK.iterdir():
        entry.unlink() if entry.is_file() else shutil.rmtree(entry)
    project_copy = WORK / "ab.2byteproj"
    payload = json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))
    payload["project_id"] = "pixelab00000000000000000000000deadbeef"
    project_copy.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    page.open_project(project_copy)

    def wait_ready(deadline_s: float = 10.0) -> None:
        deadline = time.monotonic() + deadline_s
        while time.monotonic() < deadline:
            app.processEvents()
            controller = page.video.controller
            if controller is not None and controller.running:
                try:
                    if controller.get_property("sid", None):
                        return
                except RuntimeError:
                    pass
            time.sleep(0.05)

    wait_ready()

    steps: list[tuple[str, object]] = []
    state = {"index": 0}

    def log(message):
        print(f"[PX] {message}", flush=True)

    def advance():
        if state["index"] >= len(steps):
            try:
                page.close_page()
            except Exception:
                traceback.print_exc()
            app.quit()
            return
        name, fn = steps[state["index"]]
        state["index"] += 1
        log(f"RUN {name}")
        try:
            chained = fn()
        except Exception:
            traceback.print_exc()
            chained = None
        if chained != "async":
            QTimer.singleShot(300, advance)

    def play_and_shoot(label: str, mutate: bool):
        page.select_cue(CUE_ID)
        page._seek(max(0, CUE_START - 300) / 1000.0)
        if mutate:
            page.style_font_size.setValue(int(page.style_font_size.value()) + 1)
        page._toggle_playback()
        records: list[dict] = []
        shot = 0
        deadline = time.monotonic() + 12.0

        def tick():
            nonlocal shot
            controller = page.video.controller
            entry = {"t_ms": int(page.timeline.playhead_ms), "bright": -1,
                     "overlay": 0 in page.video.active_compositor_overlay_ids()}
            if controller is not None and controller.running:
                path = WORK / f"{label}-{shot:03d}.png"
                shot += 1
                try:
                    controller.screenshot_to_file(str(path), mode="subtitles")
                    entry["bright"] = bright_pixels(QImage(str(path)), threshold=200)
                except RuntimeError:
                    pass
            records.append(entry)
            if page.timeline.playhead_ms > CUE_END + 350 or time.monotonic() > deadline:
                page._toggle_playback()
                evaluate(label, records)
                QTimer.singleShot(300, advance)
                return
            QTimer.singleShot(300, tick)

        tick()
        return "async"

    def evaluate(label: str, records: list[dict]):
        inside = [r for r in records if CUE_START <= r["t_ms"] < CUE_END]
        missing = [r for r in inside if r["bright"] >= 0 and r["bright"] < 40]
        overlay_true = sum(1 for r in inside if r["overlay"])
        log(f"{label}: inside={len(inside)} pixels_missing={len(missing)} "
            f"overlay_true={overlay_true}/{len(inside)} "
            f"bright_range={min((r['bright'] for r in inside if r['bright'] >= 0), default=-1)}"
            f"..{max((r['bright'] for r in inside), default=-1)}")
        for r in missing[:6]:
            log(f"  missing t={r['t_ms']} bright={r['bright']} overlay={r['overlay']}")

    steps = [
        ("A_default", lambda: play_and_shoot("A", mutate=False)),
        ("B_fontsize", lambda: play_and_shoot("B", mutate=True)),
    ]
    QTimer.singleShot(400, advance)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
