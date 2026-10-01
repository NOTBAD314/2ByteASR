"""Headed subtitle-lifecycle verifier for the post-split Studio (real mpv).

For each scenario (native default preset / advanced legacy preset / AI graph)
this drives real playback through a full cue and samples, every ~120 ms:
cue local time, renderer owner, scene generation, overlay presence, opacity,
layer-image state, native sub visibility and mpv sub-text. A sample taken
while the playhead is inside a cue whose subtitle is not presented by any
channel is a violation. Also verifies pause->resume, mid-cue seek, and a
five-cue consecutive run for overlay leaks.

Runs on a copy of the project so the user's real project is never mutated.
Exit code 0 = all pass, 2 = violations found.
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

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.style_recipe import recipe_payload_for_style, route_recipe
import os

SOURCE_PROJECT = Path(
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects"
    r"\2026-08-28 19-23-22 一起看绝区零前瞻！"
    r"\2026-08-28 19-23-22 一起看绝区零前瞻！.2byteproj"
)
WORK_DIR = ROOT / "tmp" / "subtitle_lifecycle"
PROJECT_COPY = WORK_DIR / "verify.2byteproj"
ARTIFACT = WORK_DIR / "lifecycle.jsonl"

SAMPLE_INTERVAL_MS = 120
SAMPLES: list[dict] = []
VIOLATIONS: list[str] = []


def log(message: str) -> None:
    print(f"[LIFE] {message}", flush=True)


def route_of(page, cue) -> str:
    if page.project is None or cue is None:
        return "none"
    payload = recipe_payload_for_style(page.project.style_recipes, cue.style_id)
    if payload and route_recipe(payload).engine == "remotion":
        return "advanced"
    return "native"


def presented(record: dict) -> bool:
    if record["route"] == "advanced":
        return record["overlay_present"]
    if not record["native_visible"]:
        return False
    # mpv's sub-text observation clears within ~1 frame + ASS centisecond
    # rounding of the event end; the 25ms tail probe proved pixels persist
    # to cue end. Only count as absent when empty earlier than that window.
    if not record["mpv_sub_text"]:
        return record["cue_end"] - record["t_ms"] <= 80
    return True


def sample(page, label: str) -> dict:
    cue = page._renderer_cue_at_playhead()
    canvas = page.advanced_cue_overlay
    ownership = page._visual_ownership.current
    overlays = page.video.active_compositor_overlay_ids()
    playhead = int(page.timeline.playhead_ms)
    inside = bool(cue is not None and cue.start_ms <= playhead < cue.end_ms)
    sub_text = ""
    controller = page.video.controller
    if controller is not None and controller.running:
        try:
            sub_text = str(controller.get_property("sub-text", "") or "")
        except RuntimeError:
            sub_text = ""
    mpv_sub_vis = None
    mpv_sid = None
    mpv_sub_start = None
    applied_sub_vis = None
    track_summary = ""
    if controller is not None and controller.running:
        try:
            mpv_sub_vis = controller.get_property("sub-visibility", None)
            mpv_sid = controller.get_property("sid", None)
            mpv_sub_start = controller.get_property("sub-start", None)
        except RuntimeError:
            pass
        try:
            tracks = controller.get_property("track-list", []) or []
            track_summary = ";".join(
                f"{t.get('id')}:{t.get('type')}{'x' if t.get('selected') else ''}"
                f"{'/ext' if t.get('external') else ''}"
                for t in tracks if str(t.get("type")) == "sub"
            )
        except RuntimeError:
            pass
        try:
            applied = controller.applied_visual_state().get("subtitle", {})
            applied_sub_vis = applied.get("visible")
        except Exception:
            pass
    snapshot = getattr(canvas, "_snapshot", None)
    scene = getattr(canvas, "_compiled_scene", None)
    record = {
        "label": label,
        "wall": round(time.monotonic(), 3),
        "t_ms": playhead,
        "cue_id": cue.id if cue is not None else "",
        "cue_start": int(cue.start_ms) if cue is not None else 0,
        "cue_end": int(cue.end_ms) if cue is not None else 0,
        "cue_local_ms": playhead - int(cue.start_ms) if cue is not None else -1,
        "inside": inside,
        "route": route_of(page, cue) if cue is not None else "none",
        "owner": ownership.owner.value,
        "owner_cue": ownership.cue_id,
        "owner_count": ownership.foreground_owner_count,
        "canvas_visible": bool(canvas.isVisible()),
        "overlay_present": 0 in overlays,
        "overlay_ids": list(overlays),
        "canvas_opacity": round(float(canvas._display_opacity), 3),
        "layer_generation": int(canvas._layer_generation),
        "layer_images": sorted(canvas._layer_images.keys()) if canvas._layer_images else [],
        "scene_hash": str(getattr(scene, "graph_hash", "") or "")[:10],
        "canvas_cue": str(getattr(snapshot, "cue_id", "") or ""),
        "native_visible": bool(page.video._native_subtitle_visible),
        "mpv_sub_text": sub_text[:40],
        "mpv_sub_vis": mpv_sub_vis,
        "mpv_sid": mpv_sid,
        "mpv_sub_start": mpv_sub_start,
        "track_summary": track_summary,
        "applied_sub_vis": applied_sub_vis,
        "paused": bool(getattr(page.video, "_paused", True)),
    }
    SAMPLES.append(record)
    with ARTIFACT.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def judge_inside(records: list[dict], scenario: str) -> None:
    for record in records:
        if not record["inside"]:
            continue
        if not presented(record):
            VIOLATIONS.append(
                f"{scenario}: t={record['t_ms']}ms local={record['cue_local_ms']}ms "
                f"route={record['route']} owner={record['owner']}/{record['owner_cue']} "
                f"overlay={record['overlay_present']} canvas={record['canvas_visible']} "
                f"native={record['native_visible']} sub_text={bool(record['mpv_sub_text'])} "
                f"mpv_vis={record.get('mpv_sub_vis')} sid={record.get('mpv_sid')} "
                f"sub_start={record.get('mpv_sub_start')} tracks={record.get('track_summary')} "
                f"applied={record.get('applied_sub_vis')} "
                f"layers={record['layer_images']}"
            )


def main() -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    if WORK_DIR.exists():
        for entry in WORK_DIR.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
    shutil.copy2(SOURCE_PROJECT, PROJECT_COPY)
    ARTIFACT.write_text("", encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()

    picked: dict[str, object] = {}
    capture_records: list[dict] = []
    capture_label = ""

    capture_timer = QTimer(page)
    capture_timer.setInterval(SAMPLE_INTERVAL_MS)

    def capture():
        if capture_label:
            capture_records.append(sample(page, capture_label))

    capture_timer.timeout.connect(capture)

    def open_project():
        page.open_project(PROJECT_COPY)

        def ready():
            controller = page.video.controller
            if controller is None or not controller.running:
                return False
            try:
                return bool(controller.get_property("sid", None))
            except RuntimeError:
                return False

        deadline = time.monotonic() + 8.0
        while not ready() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)
        for cue in page.project.cues:
            route = route_of(page, cue)
            span = cue.end_ms - cue.start_ms
            recipe = page.project.style_recipes.get(cue.style_id)
            has_graph = bool(isinstance(recipe, dict) and recipe.get("visualGraph"))
            if span < 1500:
                continue
            if route == "native" and "native" not in picked:
                picked["native"] = cue
            if route == "advanced" and not has_graph and "advanced" not in picked:
                picked["advanced"] = cue
            if route == "advanced" and has_graph and "ai" not in picked:
                picked["ai"] = cue
        cues = list(page.project.cues)
        for index in range(len(cues) - 5):
            run = cues[index:index + 5]
            if all(800 <= c.end_ms - c.start_ms <= 6000 for c in run):
                picked["run5"] = run
                break
        for key in ("native", "advanced", "ai"):
            cue = picked.get(key)
            log(f"cue[{key}]={cue.id if cue else None} "
                f"span={(cue.end_ms - cue.start_ms) if cue else 0}ms")
        log(f"cue[run5]={[c.id for c in picked.get('run5', [])]}")

    def play_through(scenario: str):
        cue = picked.get(scenario)
        if scenario == "run5":
            run = picked.get("run5")
            if not run:
                VIOLATIONS.append("run5: no cue run picked")
                return None
            start_ms, end_ms = run[0].start_ms, run[-1].end_ms
        elif cue is None:
            VIOLATIONS.append(f"{scenario}: no cue picked")
            return None
        else:
            start_ms, end_ms = cue.start_ms, cue.end_ms

        nonlocal capture_records, capture_label
        page._seek(max(0, start_ms - 350) / 1000.0)
        page._toggle_playback()
        capture_records = []
        capture_label = scenario
        capture_timer.start()

        budget_s = (end_ms - start_ms) / 1000.0 + 1.0
        deadline = time.monotonic() + budget_s + 6.0

        def tick():
            if time.monotonic() > deadline:
                capture_timer.stop()
                capture_label = ""
                page._toggle_playback()
                judge_inside(capture_records, scenario)
                inside = [r for r in capture_records if r["inside"]]
                if not inside:
                    VIOLATIONS.append(f"{scenario}: no inside-cue samples captured")
                else:
                    log(
                        f"{scenario}: inside={len(inside)} "
                        f"span=[{inside[0]['t_ms']}..{inside[-1]['t_ms']}]ms "
                        f"present={sum(1 for r in inside if presented(r))}"
                    )
                QTimer.singleShot(300, advance_holder["next"])
                return
            QTimer.singleShot(120, tick)

        tick()
        return "async"

    advance_holder: dict[str, object] = {}

    def pause_resume():
        cue = picked.get("ai") or picked.get("advanced")
        if cue is None:
            return None
        mid = (cue.start_ms + cue.end_ms) // 2
        page._seek(mid / 1000.0)
        page._toggle_playback()  # play
        records: list[dict] = []

        def take(label):
            records.append(sample(page, label))

        take("resume_init")
        QTimer.singleShot(250, page._toggle_playback)  # pause
        for delay in (450, 650, 850):
            QTimer.singleShot(delay, lambda: take("paused"))
        QTimer.singleShot(1000, page._toggle_playback)  # resume
        for delay in (1200, 1400, 1600):
            QTimer.singleShot(delay, lambda: take("resumed"))

        def settle():
            page._toggle_playback()  # pause for the next step
            inside = [r for r in records if r["inside"]]
            paused_bad = [r for r in records if r["label"] == "paused" and r["inside"] and not presented(r)]
            resumed_bad = [r for r in records if r["label"] == "resumed" and r["inside"] and not presented(r)]
            log(f"pause_resume: inside={len(inside)} paused_bad={len(paused_bad)} resumed_bad={len(resumed_bad)}")
            VIOLATIONS.extend(f"pause_resume({r['label']}): absent t={r['t_ms']}" for r in paused_bad + resumed_bad)
            QTimer.singleShot(300, advance_holder["next"])

        QTimer.singleShot(1900, settle)
        return "async"

    def seek_mid():
        target = picked.get("advanced") or picked.get("ai")
        if target is None:
            return None
        mid = target.start_ms + (target.end_ms - target.start_ms) * 2 // 5
        page._seek(mid / 1000.0)
        records = [sample(page, "seek_mid")]

        def settle():
            records.extend(sample(page, "seek_mid") for _ in range(4))
            inside = [r for r in records if r["inside"]]
            bad = [r for r in inside if not presented(r)]
            log(f"seek_mid: inside={len(inside)} absent={len(bad)}")
            VIOLATIONS.extend(f"seek_mid: absent t={r['t_ms']}ms" for r in bad)
            QTimer.singleShot(300, advance_holder["next"])

        QTimer.singleShot(600, settle)
        return "async"

    def apply_preset_midplay():
        """User's exact repro: apply a complex preset while a cue is playing."""
        cue = picked.get("native")
        if cue is None:
            return None
        page.select_cue(cue.id)
        page._seek((cue.start_ms + max(400, (cue.end_ms - cue.start_ms) // 4)) / 1000.0)
        page._toggle_playback()
        complex_index = -1
        for index in range(page.style_preset.count()):
            text = page.style_preset.itemText(index)
            if "北极熊" in text or "游戏" in text:
                complex_index = index
                break
        if complex_index < 0:
            VIOLATIONS.append("apply_preset: no complex preset in combo")
            page._toggle_playback()
            return None

        state = {"applied_wall": 0.0, "records": []}

        def collect():
            state["records"].append(sample(page, "apply_after"))

        def do_apply():
            sample(page, "apply_before")
            page.style_preset.setCurrentIndex(complex_index)
            page.style_controller._preset_activated(complex_index)
            state["applied_wall"] = time.monotonic()

        def settle():
            capture_timer.stop()
            page._toggle_playback()
            after = [
                r for r in state["records"]
                if r["inside"] and r["wall"] > state["applied_wall"] + 0.05
            ]
            bad = [r for r in after if not presented(r)]
            streak = longest = 0
            for r in after:
                streak = streak + 1 if not presented(r) else 0
                longest = max(longest, streak)
            log(f"apply_preset: inside_after={len(after)} absent={len(bad)} "
                f"longest_absent_streak={longest} samples(~{longest * SAMPLE_INTERVAL_MS}ms)")
            VIOLATIONS.extend(
                f"apply_preset: absent t={r['t_ms']}ms local={r['cue_local_ms']}ms "
                f"route={r['route']} owner={r['owner']}" for r in bad[:6]
            )
            QTimer.singleShot(300, advance_holder["next"])

        capture_timer.timeout.connect(collect)
        QTimer.singleShot(900, do_apply)
        capture_timer.start()
        QTimer.singleShot(4200, lambda: (capture_timer.timeout.disconnect(collect), settle()))
        return "async"

    def finish():
        leak = check_overlay_leak()
        log(f"summary samples={len(SAMPLES)} violations={len(VIOLATIONS)} leak={leak}")
        for violation in VIOLATIONS:
            log(f"VIOLATION {violation}")
        try:
            page.close_page()
        except Exception:
            traceback.print_exc()
        (WORK_DIR / "lifecycle-summary.json").write_text(
            json.dumps({"samples": len(SAMPLES), "violations": VIOLATIONS, "overlay_leak": leak},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        app.quit()

    steps = [
        ("open_project", open_project),
        ("scenario_native", lambda: play_through("native")),
        ("scenario_advanced", lambda: play_through("advanced")),
        ("scenario_ai", lambda: play_through("ai")),
        ("pause_resume", pause_resume),
        ("seek_mid", seek_mid),
        ("apply_preset_midplay", apply_preset_midplay),
        ("run5", lambda: play_through("run5")),
    ]
    index_box = [0]

    def advance():
        if index_box[0] >= len(steps):
            finish()
            return
        name, fn = steps[index_box[0]]
        index_box[0] += 1
        log(f"RUN {name}")
        try:
            chained = fn()
        except Exception:
            traceback.print_exc()
            VIOLATIONS.append(f"step:{name}: exception")
            chained = None
        if chained != "async":
            QTimer.singleShot(300, advance)

    advance_holder["next"] = advance
    QTimer.singleShot(400, advance)
    app.exec()
    return 0 if not VIOLATIONS else 2


def check_overlay_leak() -> bool:
    """Overlay 0 must not persist >1s after the playhead left the cue.

    Evaluated inside each scenario's own monotonic wall window so seeks that
    jump the playhead across the timeline cannot connect two scenarios.
    """
    clean = True
    windows: dict[str, list[dict]] = {}
    for record in SAMPLES:
        windows.setdefault(record["label"], []).append(record)
    for label, records in windows.items():
        left_at = None
        for record in records:
            if record["inside"]:
                left_at = None
                continue
            if left_at is None:
                left_at = record["wall"]
                continue
            if record["wall"] - left_at > 1.0 and record["overlay_present"]:
                clean = False
                VIOLATIONS.append(
                    f"overlay_leak: label={label} t={record['t_ms']}ms "
                    f"overlay still present >1s after leaving cue"
                )
    return clean


if __name__ == "__main__":
    code = main()
    log(f"exit={code}")
    sys.exit(code)
