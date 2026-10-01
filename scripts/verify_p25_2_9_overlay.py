"""Headed Windows acceptance for the P25.2.9 Transform visual overlay."""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p25.2.9-overlay"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(OUTPUT / "local-app-data")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitlePositionOverlay, SubtitleStudioPage


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


def nontransparent_pixels(image) -> int:
    return sum(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_p25_2_9_overlay.py PROJECT.2byteproj")
    project_path = Path(sys.argv[1]).resolve()
    if not project_path.is_file():
        raise FileNotFoundError(project_path)

    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.move(40, 40)
    page.show()
    page.open_project(project_path)
    pump(app, 1.5)

    controller = page.video.controller
    if controller is not None:
        controller.set_paused(False)
    pump(app, 0.5)

    cues = list(page.project.cues if page.project else [])
    if len(cues) < 10:
        raise RuntimeError(f"real-project acceptance requires at least 10 cues, got {len(cues)}")
    selected = random.Random(2529).sample(cues, 10)
    checks = []
    visual = page.position_overlay_visual
    source = page.position_overlay

    for index, cue in enumerate(selected, start=1):
        page.select_cue(cue.id)
        pump(app, 0.08)
        visual.sync_from_source()
        pump(app, 0.03)
        image = visual.grab().toImage()
        target = OUTPUT / f"cue-{index:02d}-{cue.id}.png"
        image.save(str(target))

        original_position = (source.position_x, source.position_y)
        original_font_size = source.font_size
        original_geometry = visual.geometry()
        source.set_video_position(
            min(source.play_res_x, source.position_x + 20),
            max(0, source.position_y - 12),
            source.play_res_x,
            source.play_res_y,
        )
        visual.sync_from_source()
        moved_geometry = visual.geometry()
        source.set_font_size(original_font_size + 8)
        visual.sync_from_source()
        resized_geometry = visual.geometry()
        source.set_video_position(
            original_position[0], original_position[1],
            source.play_res_x, source.play_res_y,
        )
        source.set_font_size(original_font_size)
        visual.sync_from_source()

        checks.append({
            "cue_id": cue.id,
            "visible": visual.isVisible(),
            "nontransparent_pixels": nontransparent_pixels(image),
            "box_geometry": list(original_geometry.getRect()),
            "position_updates_box": moved_geometry.topLeft() != original_geometry.topLeft(),
            "font_size_updates_box": moved_geometry.size() != resized_geometry.size(),
            "screenshot": str(target),
        })

    mpv = {}
    if controller is not None:
        for name in (
            "wid", "idle-active", "pause", "time-pos", "duration",
            "video-format", "video-codec", "aid", "sid", "sub-text",
        ):
            try:
                mpv[name] = controller.get_property(name)
            except RuntimeError as exc:
                mpv[name] = {"unavailable": str(exc)}

    report = {
        "project": str(project_path),
        "cue_count": len(cues),
        "checked_cues": checks,
        "interaction_overlay_count": len(page.findChildren(SubtitlePositionOverlay)),
        "visual_overlay_count": sum(
            type(widget).__name__ == "SubtitleTransformVisualOverlay"
            for widget in QApplication.topLevelWidgets()
        ),
        "interaction_overlay_native": source.testAttribute(
            Qt.WidgetAttribute.WA_NativeWindow
        ),
        "visual_is_full_canvas": visual.size() == source.size(),
        "mpv": mpv,
    }
    report_path = OUTPUT / "acceptance-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    page.close_page()
    page.close()
    app.quit()

    passed = (
        report["interaction_overlay_count"] == 1
        and report["visual_overlay_count"] == 1
        and not report["interaction_overlay_native"]
        and not report["visual_is_full_canvas"]
        and all(
            item["visible"]
            and item["nontransparent_pixels"] > 0
            and item["position_updates_box"]
            and item["font_size_updates_box"]
            for item in checks
        )
        and bool(mpv.get("video-format"))
        and mpv.get("sid") not in {None, False, "no"}
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
