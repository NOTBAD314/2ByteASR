"""Headed verification for round 16: effect-subtitle closure.

  A. FIDELITY TAKEOVER: applying a web theme then seeking inside the cue
     (paused) must put the REAL HTML render on the video layer
     (_advanced_canvas_source_kind == "fidelity"), not the stroke/color
     mirror (regression: geometry parity dropped every web frame,
     bbox_center_delta≈0.32).
  B. Demo band: single big cropped strip, >=20 frames, timer running,
     pixels change between ticks.
  C. Web-adjust card: visible for web cue, opinion composition, apply-all.
  D. Screenshots for GLM (agy) visual review.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROJECT = ROOT / "tmp" / "realproj" / "real-copy.2byteproj"
SHOTS = ROOT / "tmp" / "r16-verify"

from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.web_theme import builtin_web_themes

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R16] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def wait_until(app, predicate, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


def grab_video_canvas(page, name: str) -> None:
    canvas = getattr(page, "video_canvas", None) or getattr(page, "video", None)
    widget = canvas if hasattr(canvas, "grab") else page
    widget.grab().save(str(SHOTS / name))


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
    check("project_ready", True, f"cues={len(page.project.cues)}")

    cues = page.project.cues
    target = next((c for c in cues if 30_000 <= c.start_ms <= 60_000), cues[0])
    page.select_cue(target.id)

    # ---- A) fidelity takeover (paused inside the cue) ----
    theme = builtin_web_themes()["balatro-joker"].to_dict()
    assert page._apply_web_theme(target.id, theme)
    page._seek((target.start_ms + 500) / 1000.0)
    ok = wait_until(
        app,
        lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) == "fidelity",
        timeout=45.0,
    )
    kind = str(getattr(page, "_advanced_canvas_source_kind", ""))
    check("fidelity_takes_over_video_layer", ok, f"source_kind={kind}")
    time.sleep(0.4)
    app.processEvents()
    grab_video_canvas(page, "video-layer-fidelity.png")

    # ---- B) demo band ----
    from types import SimpleNamespace

    page._pending_web_theme = SimpleNamespace(
        cue_id=target.id, theme=dict(theme), name=theme["name"], recipe=None,
    )
    page._start_web_theme_storyboard(dict(theme))
    frames = page._storyboard_frames
    ok_frames = wait_until(
        app, lambda: len(frames.get("demo", [])) >= 20, timeout=120.0,
    )
    check("demo_band_frames", ok_frames, f"frames={len(frames.get('demo', []))}")
    timer = getattr(page, "_storyboard_timer", None)
    check("demo_band_timer", timer is not None and timer.isActive())
    demo = page.ai_web_theme_demo_label

    def signature():
        pm = demo.pixmap()
        return hash(pm.toImage().cacheKey()) if pm and not pm.isNull() else -1

    before = signature()
    time.sleep(0.5)
    app.processEvents()
    check("demo_band_animates", signature() != before and signature() >= 0)
    if demo.pixmap() and not demo.pixmap().isNull():
        demo.pixmap().save(str(SHOTS / "demo-band.png"))
    check(
        "demo_band_is_strip",
        demo.pixmap() and demo.pixmap().width() > 0
        and demo.pixmap().width() / max(1, demo.pixmap().height()) > 2.2,
        f"aspect={demo.pixmap().width() / max(1, demo.pixmap().height()):.2f}",
    )

    # ---- C) web-adjust card ----
    check("web_adjust_visible", not page.web_adjust_host.isHidden())
    page.web_adjust_font.lineEdit().setText("KaiTi")
    page.web_adjust_size.setValue(96)
    page._web_adjust_color_value = "#FF3355"
    page.web_adjust_extra.setText("描边加粗一档")
    opinion = page._assemble_web_adjust_opinion()
    check(
        "web_adjust_opinion",
        all(token in opinion for token in ("KaiTi", "96", "#FF3355", "描边")),
        opinion[:80],
    )
    page.web_adjust_scope.setCurrentIndex(page.web_adjust_scope.findData("all"))
    page._apply_web_theme_to_scope()
    themed = sum(
        1 for cue in cues
        if isinstance(
            (page.project.style_recipes.get(cue.style_id, {}) or {}).get("webTheme"), dict
        )
    )
    check("apply_all_via_style_panel", themed == len(cues), f"{themed}/{len(cues)}")
    page.ai_suggestion_card.setVisible(True)
    page.ai_refine_row.setVisible(True)
    app.processEvents()
    page.ai_suggestion_card.grab().save(str(SHOTS / "ai-draft-card.png"))

    # style panel screenshot: switch the tool drawer to the style page
    drawer = getattr(page, "context_drawer", None)
    if drawer is not None:
        try:
            drawer.setCurrentIndex(1)
        except Exception:
            pass
    app.processEvents()
    advanced = getattr(page, "web_adjust_host", None)
    if advanced is not None:
        host_card = advanced.parentWidget()
        host_card.grab().save(str(SHOTS / "style-web-adjust.png"))
    page.grab().save(str(SHOTS / "window.png"))

    return finish(page, app)


def finish(page, app) -> int:
    page.close()
    app.processEvents()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n[R16] {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
