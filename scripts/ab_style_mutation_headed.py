"""Minimal A/B: default style vs one font-size bump on the same cue.

Drives the REAL commit path (style_font_size spinbox -> debounced
_style_control_changed -> _apply_style) and samples every ~40ms through the
whole cue. All publish/remove overlay calls are journaled with caller
context so the transition between the last healthy frame and the first
missing frame can be read directly.
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
WORK = ROOT / "tmp" / "ab_style"
PROJECT_COPY = WORK / "ab.2byteproj"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.style_recipe import recipe_payload_for_style, route_recipe
import os

CUE_ID = "2"          # default style on the audio-only project, 3750-5533
CUE_START, CUE_END = 3750, 5533

SAMPLES: list[dict] = []
JOURNAL: list[dict] = []


def log(message: str) -> None:
    print(f"[AB] {message}", flush=True)


def route_of(page, cue) -> str:
    if page.project is None or cue is None:
        return "none"
    payload = recipe_payload_for_style(page.project.style_recipes, cue.style_id)
    if payload and route_recipe(payload).engine == "remotion":
        return "advanced"
    return "native"


def install_journal(page) -> None:
    video = page.video
    original_publish = video.publish_compositor_overlay
    original_remove = video.remove_compositor_overlay

    def publish(overlay_id, *args, **kwargs):
        context = kwargs.get("context") or {}
        JOURNAL.append({
            "wall": round(time.monotonic(), 3), "op": "PUBLISH", "id": int(overlay_id),
            "reason": str(context.get("reason") or ""), "caller": str(context.get("caller") or ""),
            "cue_id": str(context.get("cue_id") or ""),
        })
        return original_publish(overlay_id, *args, **kwargs)

    def remove(overlay_id, *args, **kwargs):
        context = kwargs.get("context") or {}
        JOURNAL.append({
            "wall": round(time.monotonic(), 3), "op": "REMOVE", "id": int(overlay_id),
            "reason": str(context.get("reason") or ""), "caller": str(context.get("caller") or ""),
            "cue_id": str(context.get("cue_id") or ""),
        })
        return original_remove(overlay_id, *args, **kwargs)

    video.publish_compositor_overlay = publish
    video.remove_compositor_overlay = remove


def sample(page, label: str) -> dict:
    cue = page._renderer_cue_at_playhead()
    canvas = page.advanced_cue_overlay
    ownership = page._visual_ownership.current
    overlays = page.video.active_compositor_overlay_ids()
    playhead = int(page.timeline.playhead_ms)
    controller = page.video.controller
    sub_text = ""
    if controller is not None and controller.running:
        try:
            sub_text = str(controller.get_property("sub-text", "") or "")
        except RuntimeError:
            pass
    recipe = page.project.style_recipes.get(cue.style_id) if cue else None
    record = {
        "label": label,
        "wall": round(time.monotonic(), 3),
        "t_ms": playhead,
        "inside": bool(cue is not None and cue.id == CUE_ID and cue.start_ms <= playhead < cue.end_ms),
        "route": route_of(page, cue),
        "style_id": cue.style_id if cue else "",
        "recipe_engine": str(recipe.get("engine", "")) if isinstance(recipe, dict) else "",
        "owner": ownership.owner.value,
        "owner_cue": ownership.cue_id,
        "canvas_visible": bool(canvas.isVisible()),
        "overlay_present": 0 in overlays,
        "layers": len(canvas._layer_images),
        "scene": str(getattr(canvas._compiled_scene, "graph_hash", "") or "")[:8],
        "native_vis": bool(page.video._native_subtitle_visible),
        "sub_text": sub_text[:16],
        "preview_state": str(page._advanced_preview_state.phase.value),
        "preview_gen": int(page._advanced_preview_state.generation),
    }
    SAMPLES.append(record)
    return record


def visual_present(record: dict) -> bool:
    if record["route"] == "advanced":
        return record["overlay_present"]
    return record["native_vis"] and bool(record["sub_text"]) or record["native_vis"]


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    for entry in WORK.iterdir():
        entry.unlink() if entry.is_file() else shutil.rmtree(entry)
    shutil.copy2(SOURCE_PROJECT, PROJECT_COPY)
    # Re-key the copy so workspace autosave recovery (keyed by project_id)
    # can neither restore stale harness state nor touch the user's entry.
    payload = json.loads(PROJECT_COPY.read_text(encoding="utf-8"))
    payload["project_id"] = "abstyle0000000000000000000000000deadbeef"
    PROJECT_COPY.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    page.open_project(PROJECT_COPY)
    install_journal(page)

    def wait_ready(deadline_s: float = 8.0) -> None:
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
    state = {"index": 0, "records": []}

    def advance():
        if state["index"] >= len(steps):
            finish()
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

    def play_window(label: str, start_ms: int, end_ms: int, post_ms: int = 400):
        page._seek(max(0, start_ms - 350) / 1000.0)
        page._toggle_playback()
        records: list[dict] = []
        timer = QTimer(page)
        timer.setInterval(40)
        deadline = time.monotonic() + (end_ms - start_ms + post_ms) / 1000.0 + 8.0

        def tick():
            records.append(sample(page, label))
            if page.timeline.playhead_ms > end_ms + post_ms or time.monotonic() > deadline:
                timer.stop()
                page._toggle_playback()
                evaluate(label, records)
                QTimer.singleShot(300, advance)
                return

        timer.timeout.connect(tick)
        timer.start()
        return "async"

    def evaluate(label: str, records: list[dict]):
        inside = [r for r in records if r["inside"]]
        bad = [r for r in inside if not r["overlay_present"] and not (r["native_vis"] and r["sub_text"])]
        log(f"{label}: inside={len(inside)} absent={len(bad)} "
            f"first_absent={bad[0]['t_ms'] if bad else '-'} route={inside[0]['route'] if inside else '?'}")
        if bad:
            first = bad[0]
            log(f"  first absent detail: {json.dumps(first, ensure_ascii=False)}")
            # show the transition: last healthy frames before it
            index = records.index(first)
            for r in records[max(0, index - 4):index + 2]:
                log(f"  [{r['label']}] t={r['t_ms']} route={r['route']} owner={r['owner']}/{r['owner_cue']} "
                    f"canvas={r['canvas_visible']} overlay={r['overlay_present']} layers={r['layers']} "
                    f"native={r['native_vis']} text={bool(r['sub_text'])} state={r['preview_state']}/{r['preview_gen']}")

    def scenario_a():
        return play_window("A_default", CUE_START, CUE_END)

    def scenario_b():
        # User's exact repro shape: pause inside the cue, bump font size,
        # then IMMEDIATELY play from the cue head — no settle wait, so the
        # debounced commit, ASS recompile and route flip all race playback.
        page.select_cue(CUE_ID)
        page._seek((CUE_START + 500) / 1000.0)
        before = page.style_font_size.value()
        page.style_font_size.setValue(int(before) + 1)
        log(f"B: font size {before} -> {page.style_font_size.value()}, playing immediately")
        return play_window("B_immediate", CUE_START, CUE_END)

    def scenario_d():
        # Pause mid-cue, mutate, stay PAUSED and sample: does the canvas
        # vanish 1-2 frames after the LIVE publish?
        page.select_cue(CUE_ID)
        page._seek((CUE_START + 1200) / 1000.0)
        before = page.style_font_size.value()
        page.style_font_size.setValue(int(before) + 1)
        log(f"D: paused font size {before} -> {page.style_font_size.value()}")
        records: list[dict] = []
        timer = QTimer(page)
        timer.setInterval(40)
        state_d = {"deadline": time.monotonic() + 5.0}

        def tick():
            records.append(sample(page, "D_paused"))
            if time.monotonic() > state_d["deadline"]:
                timer.stop()
                evaluate("D_paused", records)
                log("D journal tail: " + json.dumps(JOURNAL[-12:], ensure_ascii=False))
                QTimer.singleShot(300, advance)
                return

        timer.timeout.connect(tick)
        timer.start()
        return "async"

    def finish():
        with (WORK / "samples.jsonl").open("w", encoding="utf-8") as stream:
            for record in SAMPLES:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        with (WORK / "journal.jsonl").open("w", encoding="utf-8") as stream:
            for entry in JOURNAL:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log(f"journal ops={len(JOURNAL)} samples={len(SAMPLES)}")
        try:
            page.close_page()
        except Exception:
            traceback.print_exc()
        app.quit()

    steps = [
        ("scenario_a_default", scenario_a),
        ("scenario_b_immediate", scenario_b),
        ("scenario_d_paused_mutation", scenario_d),
    ]
    QTimer.singleShot(400, advance)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
