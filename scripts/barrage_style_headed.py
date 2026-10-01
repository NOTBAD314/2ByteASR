"""Barrage repro: rapid style mutations (drag, preset switching, mid-play)
across the video project and the audio-only project, verifying that every
sampled in-cue frame presents a subtitle visual.
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

WORK = ROOT / "tmp" / "barrage"
PROJECTS = [
    ("video", Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\2026-08-28 19-23-22 一起看绝区零前瞻！\2026-08-28 19-23-22 一起看绝区零前瞻！.2byteproj", "7", 19767, 23667),
    ("audio", Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\8月30日\8月30日.2byteproj", "2", 3750, 5533),
]

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.style_recipe import recipe_payload_for_style, route_recipe
import os

TOTAL_BAD = 0


def log(message):
    print(f"[BR] {message}", flush=True)


def route_of(page, cue) -> str:
    if page.project is None or cue is None:
        return "none"
    payload = recipe_payload_for_style(page.project.style_recipes, cue.style_id)
    return "advanced" if payload and route_recipe(payload).engine == "remotion" else "native"


def frame_present(page) -> bool | None:
    """Visual presence for the cue under the playhead, or None if outside.

    The judge follows the live owner arbiter, not the recipe alone: an
    audio-only project promotes plain native cues onto the canvas overlay,
    where mpv's sub-text never populates.
    """
    cue = page._renderer_cue_at_playhead()
    playhead = int(page.timeline.playhead_ms)
    if cue is None or not (cue.start_ms <= playhead < cue.end_ms):
        return None
    owner = page._visual_ownership.current.owner.value
    if owner in {"advanced_live", "advanced_fidelity"}:
        return 0 in page.video.active_compositor_overlay_ids()
    if owner == "native":
        controller = page.video.controller
        sub_text = ""
        if controller is not None and controller.running:
            try:
                sub_text = str(controller.get_property("sub-text", "") or "")
            except RuntimeError:
                pass
        return bool(page.video._native_subtitle_visible) and bool(sub_text)
    return False


def run_project(app, kind, source, cue_id, cue_start, cue_end, on_done) -> None:
    global TOTAL_BAD
    WORK.mkdir(parents=True, exist_ok=True)
    for entry in WORK.iterdir():
        entry.unlink() if entry.is_file() else shutil.rmtree(entry)
    project_copy = WORK / f"{kind}.2byteproj"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["project_id"] = f"barrage-{kind}-00000000000000deadbeef"
    project_copy.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    page.open_project(project_copy)

    def wait_sid():
        deadline = time.monotonic() + 10.0
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

    wait_sid()
    bad_total = 0
    state = {"index": 0}

    def play_window(label, *, mutate_at=None):
        page._seek(max(0, cue_start - 300) / 1000.0)
        page._toggle_playback()
        records: list[dict] = []
        stop_at = time.monotonic() + 12.0
        mutated = {"done": mutate_at is None}

        def watch():
            if not mutated["done"] and page.timeline.playhead_ms > mutate_at:
                mutated["done"] = True
                page.style_font_size.setValue(int(page.style_font_size.value()) + 1)
                log(f"[{kind}] mutation fired at t={int(page.timeline.playhead_ms)}")
            present = frame_present(page)
            if present is not None:
                records.append(present)
            if page.timeline.playhead_ms > cue_end + 350 or time.monotonic() > stop_at:
                page._toggle_playback()
                bad = sum(1 for value in records if not value)
                log(f"[{kind}] {label}: inside={len(records)} absent={bad}"
                    + (f"  <<<< ABSENT FRAMES" if bad else ""))
                nonlocal_bad[0] += bad
                QTimer.singleShot(300, advance)
                return
            QTimer.singleShot(40, watch)

        watch()
        return "async"

    nonlocal_bad = [0]

    def scenario_drag():
        page.select_cue(cue_id)
        base = int(page.style_font_size.value())
        for offset in range(1, 11):
            page.style_font_size.setValue(base + offset)
            app.processEvents()
            time.sleep(0.03)
        time.sleep(0.5)
        app.processEvents()
        return play_window("rapid_drag")

    def scenario_presets():
        page.select_cue(cue_id)
        combo = page.style_preset
        count = min(6, combo.count())
        for index in range(count):
            combo.setCurrentIndex(index)
            page.style_controller._preset_activated(index)
            app.processEvents()
            time.sleep(0.18)
        time.sleep(0.5)
        app.processEvents()
        return play_window("preset_barrage")

    def advance():
        global TOTAL_BAD
        steps = [
            ("default", lambda: play_window("default")),
            ("rapid_drag", scenario_drag),
            ("preset_barrage", scenario_presets),
            ("mutate_during_play", lambda: play_window("mutate_play", mutate_at=cue_start + 700)),
        ]
        if state["index"] >= len(steps):
            log(f"[{kind}] project absent_total={nonlocal_bad[0]}")
            TOTAL_BAD += nonlocal_bad[0]
            try:
                page.close_page()
            except Exception:
                traceback.print_exc()
            QTimer.singleShot(500, on_done)
            return
        name, fn = steps[state["index"]]
        state["index"] += 1
        log(f"[{kind}] RUN {name}")
        try:
            chained = fn()
        except Exception:
            traceback.print_exc()
            nonlocal_bad[0] += 1
            chained = None
        if chained != "async":
            QTimer.singleShot(300, advance)

    advance()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    queue = list(PROJECTS)

    def next_project():
        if not queue:
            log(f"summary total_absent={TOTAL_BAD}")
            app.quit()
            return
        kind, source, cue_id, start, end = queue.pop(0)
        run_project(app, kind, source, cue_id, start, end, next_project)

    QTimer.singleShot(300, next_project)
    app.exec()
    return 0 if TOTAL_BAD == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
