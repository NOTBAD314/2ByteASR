"""Decisive probe: does mpv actually PAINT the compositor overlay?

Pause inside an advanced cue (after a font-size mutation routes it there),
screenshot the window with the overlay present, force-remove overlay 0,
screenshot again, and diff. Zero diff = mpv accepts overlay-add but never
paints it (the disappearance). Positive diff = overlay renders.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\8月30日\8月30日.2byteproj"
WORK = ROOT / "tmp" / "overlay_diff"

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
import os

CUE_ID, CUE_START, CUE_END = "2", 3750, 5533


def diff_pixels(a: QImage, b: QImage) -> int:
    if a.isNull() or b.isNull() or a.size() != b.size():
        return -1
    count = 0
    for y in range(0, a.height(), 2):
        for x in range(0, a.width(), 2):
            pa, pb = a.pixel(x, y), b.pixel(x, y)
            if abs(((pa >> 16) & 255) - ((pb >> 16) & 255)) > 24 or \
               abs(((pa >> 8) & 255) - ((pb >> 8) & 255)) > 24 or \
               abs((pa & 255) - (pb & 255)) > 24:
                count += 1
    return count


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    for entry in WORK.iterdir():
        entry.unlink() if entry.is_file() else shutil.rmtree(entry)
    project_copy = WORK / "probe.2byteproj"
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload["project_id"] = "ovdiff0000000000000000000000000deadbeef"
    project_copy.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    page.open_project(project_copy)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        app.processEvents()
        controller = page.video.controller
        if controller is not None and controller.running:
            try:
                if controller.get_property("sid", None):
                    break
            except RuntimeError:
                pass
        time.sleep(0.05)

    def shoot(name: str) -> QImage:
        path = WORK / f"{name}.png"
        page.video.controller.screenshot_to_file(str(path), mode="window")
        time.sleep(0.15)
        app.processEvents()
        return QImage(str(path))

    def run():
        page.select_cue(CUE_ID)
        page.style_font_size.setValue(int(page.style_font_size.value()) + 1)
        time.sleep(0.8)
        app.processEvents()
        page._seek((CUE_START + 900) / 1000.0)
        time.sleep(0.6)
        app.processEvents()

        overlays = page.video.active_compositor_overlay_ids()
        print(f"[OD] overlay_ids={overlays} owner={page._visual_ownership.current.owner.value}", flush=True)
        with_overlay = shoot("with")
        page.video.remove_compositor_overlay(0, force=True)
        time.sleep(0.3)
        app.processEvents()
        without_overlay = shoot("without")
        delta = diff_pixels(with_overlay, without_overlay)
        print(f"[OD] diff_pixels={delta} size={with_overlay.size()}", flush=True)
        if delta == 0:
            print("[OD] VERDICT: overlay-add accepted but NOT painted by mpv", flush=True)
        elif delta > 0:
            print(f"[OD] VERDICT: overlay IS painted ({delta} changed samples)", flush=True)
        page.close_page()
        app.quit()

    QTimer.singleShot(400, run)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
