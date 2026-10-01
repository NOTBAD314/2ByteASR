"""Headed verification for round 19: live web preview + shadow + demo strip.

  A. WEB-LIVE takeover (paused): web cue → video layer source_kind == "web_live",
     canvas pixmap carries the theme design (green HUD / bright text / red splat).
  B. PLAYBACK truth: while actually playing, web_live keeps publishing frames
     (fresh timestamp advances) and canvas pixels keep the design — the user
     sees the real theme incl. entrance/exit during editing playback.
  C. Scrub response: seek within the cue (paused) → pixmap content changes.
  D. Graph cue shadow: pause inside a plain/graph cue → LIVE pixmap contains
     dark offset shadow pixels (the "no shadow" complaint).
  E. Demo strip live pump: storyboard starts fast and animates without batch.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROJECT = ROOT / "tmp" / "realproj" / "real-copy.2byteproj"
SHOTS = ROOT / "tmp" / "r19-verify"

from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.web_theme import builtin_web_themes

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R19] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def wait_until(app, predicate, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


def pixmap_ratios(pixmap):
    image = pixmap.toImage()
    width, height = image.width(), image.height()
    top = int(height * 0.60)
    total = green = bright = red = dark = 0
    for y in range(top, height, 3):
        for x in range(0, width, 3):
            color = image.pixelColor(x, y)
            if color is None or color.alpha() < 40:
                continue
            total += 1
            r, g, b = color.red(), color.green(), color.blue()
            if g > 60 and g > r + 25 and g > b + 25:
                green += 1
            if (r + g + b) / 3 > 165:
                bright += 1
            if r > 80 and r > g + 45 and r > b + 45:
                red += 1
            if color.alpha() < 200 and r < 60 and g < 60 and b < 60:
                dark += 1
    denom = max(1, total)
    return green / denom, bright / denom, red / denom, dark / denom, total


def main() -> int:
    SHOTS.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1700, 940)
    page.show()
    app.processEvents()
    page.open_project(PROJECT, skip_dirty_guard=True)
    if not wait_until(app, lambda: page.project is not None and page.video._startup_state == "READY", 25.0):
        check("project_ready", False, f"startup={page.video._startup_state}")
        return finish(page, app)
    cues = page.project.cues
    check("project_ready", True, f"cues={len(cues)}")

    # ---- A) paused takeover ----
    target = next((c for c in cues if 30_000 <= c.start_ms <= 60_000), cues[0])
    page.select_cue(target.id)
    theme = builtin_web_themes()["doom95"].to_dict()
    assert page._apply_web_theme(target.id, theme)
    page.video.set_paused(True)
    page._seek((target.start_ms + 600) / 1000.0)
    ok = wait_until(
        app,
        lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) == "web_live",
        timeout=30.0,
    )
    check("web_live_takes_over_paused", ok,
          f"kind={getattr(page, '_advanced_canvas_source_kind', '')}")
    pixmap = getattr(page, "_advanced_cue_pixmap", None)
    if pixmap is None or pixmap.isNull():
        check("web_live_frame_design", False, "no pixmap")
    else:
        pixmap.save(str(SHOTS / "web-live-paused.png"))
        green, bright, red, _dark, total = pixmap_ratios(pixmap)
        check("web_live_frame_design",
              green > 0.0015 and bright > 0.002 and red > 0.0005,
              f"green={green:.4f} bright={bright:.4f} red={red:.4f}")

    # ---- B) playback keeps the real theme ----
    page.video.set_paused(False)
    frames_seen = [0]
    baseline = float(getattr(page, "_web_live_last_frame_at", 0.0))

    def sample_playback(seconds: float = 4.0):
        kinds: dict[str, int] = {}
        last = baseline
        green_hits = 0
        samples = 0
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.08)
            kind = str(getattr(page, "_advanced_canvas_source_kind", ""))
            kinds[kind] = kinds.get(kind, 0) + 1
            stamp = float(getattr(page, "_web_live_last_frame_at", 0.0))
            if stamp > last:
                frames_seen[0] += 1
                last = stamp
            pixmap_now = getattr(page, "_advanced_cue_pixmap", None)
            if pixmap_now is not None and not pixmap_now.isNull():
                samples += 1
                green, _b, _r, _d, _t = pixmap_ratios(pixmap_now)
                if green > 0.004:
                    green_hits += 1
        return kinds, green_hits, samples

    playhead_at_end = target.end_ms + 1500
    kinds, green_hits, samples = sample_playback(
        min(4.0, max(1.5, (playhead_at_end - (target.start_ms + 600)) / 1000.0))
    )
    page.video.set_paused(True)
    check("web_live_frames_during_playback", frames_seen[0] >= 4,
          f"frames={frames_seen[0]}")
    check("web_live_dominates_playback",
          kinds.get("web_live", 0) >= sum(kinds.values()) * 0.5, str(kinds))
    check("web_live_design_during_playback",
          samples > 0 and green_hits >= max(1, samples // 3),
          f"green_hits={green_hits}/{samples}")

    # ---- C) scrub response (paused) ----
    pixmap = getattr(page, "_advanced_cue_pixmap", None)
    before_key = pixmap.cacheKey() if pixmap is not None else 0
    inside = next((c for c in cues if c.id != target.id and not isinstance(
        (page.project.style_recipes.get(c.style_id, {}) or {}).get("webTheme"), dict
    )), None)
    page._seek((target.start_ms + (target.end_ms - target.start_ms) * 0.8) / 1000.0)
    wait_until(app, lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) == "web_live", 12.0)
    time.sleep(0.8)
    app.processEvents()
    pixmap = getattr(page, "_advanced_cue_pixmap", None)
    after_key = pixmap.cacheKey() if pixmap is not None else 0
    check("web_live_scrub_updates", after_key != 0 and after_key != before_key,
          f"{before_key}->{after_key}")

    # ---- D) graph cue shadow (plain-looking advanced cue) ----
    if inside is not None:
        page.video.set_paused(True)
        page._seek((inside.start_ms + 500) / 1000.0)
        ok = wait_until(
            app,
            lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) in {"live", "fidelity", "web_live"},
            timeout=20.0,
        )
        time.sleep(0.6)
        app.processEvents()
        pixmap = getattr(page, "_advanced_cue_pixmap", None)
        if pixmap is None or pixmap.isNull():
            check("graph_cue_shadow_pixels", False, "no pixmap")
        else:
            pixmap.save(str(SHOTS / "graph-cue-live.png"))
            _g, _b, _r, dark, total = pixmap_ratios(pixmap)
            check("graph_cue_shadow_pixels", dark > 0.001,
                  f"dark={dark:.4f} total={total}")

    # ---- E) demo strip live pump ----
    page._pending_web_theme = type("N", (), {
        "cue_id": target.id, "theme": dict(theme), "name": theme["name"], "recipe": None,
    })()
    page._start_web_theme_storyboard(dict(theme))
    demo = page.ai_web_theme_demo_label

    def demo_pixmap_key():
        pm = demo.pixmap()
        return pm.cacheKey() if pm and not pm.isNull() else 0

    first_key = wait_until(app, lambda: demo_pixmap_key() != 0, timeout=12.0)
    check("demo_live_first_frame", first_key, "")
    key1 = demo_pixmap_key()
    # 二十四轮：演示带首次需 live_set+条带录制（~4s），之后墙钟循环回放恒动。
    animated = False
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        time.sleep(0.4)
        app.processEvents()
        if demo_pixmap_key() != key1 and demo_pixmap_key() != 0:
            animated = True
            break
    check("demo_live_animates", animated,
          f"{key1}->{demo_pixmap_key()}")
    if demo.pixmap() and not demo.pixmap().isNull():
        demo.pixmap().save(str(SHOTS / "demo-live.png"))

    return finish(page, app)


def finish(page, app) -> int:
    try:
        page._stop_web_live_preview("script_end")
        page._stop_storyboard_animation()
    except Exception:
        pass
    page.close()
    app.processEvents()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n[R19] {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
