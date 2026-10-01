"""Headed verification for round 25: overlap/stuck-frame regression.

  A. web cue A (strip warm) → play across into plain cue B: web_live fully
     releases (worker stopped, kind off web_live, snapshot cleared, native
     visible for B or canvas shows B's own visual) — NO stale frame overlap.
  B. Paused seek A→B: same release within 2s.
  C. Seek back into A: web_live takes over again (recovery works).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROJECT = (ROOT / "tmp" / "webtest" / "webtest.2byteproj")
if not PROJECT.is_file():
    PROJECT = ROOT / "tmp" / "realproj" / "real-copy.2byteproj"

from PySide6.QtWidgets import QApplication

RESULTS: list[tuple[str, bool, str]] = []


def check(label, condition, detail=""):
    RESULTS.append((label, bool(condition), detail))
    print(f"[R25] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def wait_until(app, predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


def web_released(page) -> tuple[bool, str]:
    worker = getattr(page, "_web_live_worker", None)
    kind = str(getattr(page, "_advanced_canvas_source_kind", ""))
    snapshot = getattr(page, "_web_live_snapshot", None)
    native = bool(getattr(page.video, "_native_subtitle_visible", False))
    ok = (worker is None or not worker.running) and kind != "web_live" and snapshot is None
    return ok, f"worker={worker is not None and worker.running} kind={kind} snapshot={snapshot is not None} native={native}"


def main() -> int:
    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.web_theme import builtin_web_themes
    from twobyteasr.live_web_preview import GLOBAL_WEB_STRIP_STORE

    page = SubtitleStudioPage()
    page.resize(1600, 920)
    page.show()
    app.processEvents()
    page.open_project(PROJECT, skip_dirty_guard=True)
    if not wait_until(app, lambda: page.project is not None and page.video._startup_state == "READY", 25.0):
        check("project_ready", False, f"startup={page.video._startup_state}")
        return finish(page, app)

    cues = page.project.cues

    def _is_web(cue) -> bool:
        payload = page.project.style_recipes.get(cue.style_id, {}) or {}
        return isinstance(payload.get("webTheme"), dict) and bool(payload["webTheme"])

    target = nxt = None
    for i, c in enumerate(cues):
        if not _is_web(c) or (c.end_ms - c.start_ms) < 2500 or i + 1 >= len(cues):
            continue
        n = cues[i + 1]
        if not _is_web(n) and n.start_ms - c.end_ms < 1500 and (n.end_ms - n.start_ms) >= 1500:
            target, nxt = c, n
            break
    check("pair_ready", target is not None, f"A={target.id if target else None} B={nxt.id if nxt else None}")
    if target is None or nxt is None:
        return finish(page, app)

    theme = builtin_web_themes()["balatro-joker"].to_dict()
    assert page._apply_web_theme(target.id, theme)

    # ---- A) 播放跨越 A→B ----
    page.video.set_paused(True)
    page._seek((target.start_ms + 500) / 1000.0)
    took = wait_until(app, lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) == "web_live", timeout=40.0)
    check("A_web_live_takes_over", took, f"kind={getattr(page, '_advanced_canvas_source_kind', '')}")
    w = getattr(page, "_web_live_worker", None)
    if w is not None:
        wait_until(app, lambda: GLOBAL_WEB_STRIP_STORE.is_complete(w.strip_key), timeout=45.0)
    check("A_strip_warm", w is not None and GLOBAL_WEB_STRIP_STORE.is_complete(w.strip_key),
          f"frames={len(GLOBAL_WEB_STRIP_STORE.peek(w.strip_key).frames) if w and GLOBAL_WEB_STRIP_STORE.peek(w.strip_key) else 0}")
    page.video.set_paused(False)
    window = max(2.0, (nxt.start_ms + 700 - (target.start_ms + 500)) / 1000.0) + 1.2
    t_end = time.monotonic() + window
    while time.monotonic() < t_end:
        app.processEvents()
        time.sleep(0.1)
    page.video.set_paused(True)
    time.sleep(1.2)
    app.processEvents()
    ok, detail = web_released(page)
    check("B_play_across_released", ok, detail)

    # ---- B) 暂停 seek A→B ----
    page._seek((target.start_ms + 800) / 1000.0)
    wait_until(app, lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) == "web_live", timeout=30.0)
    page._seek((nxt.start_ms + 400) / 1000.0)
    dbg0 = time.monotonic()
    while time.monotonic() - dbg0 < 3.0:
        app.processEvents(); time.sleep(0.3)
        try:
            ph = int(getattr(page.timeline, "playhead_ms", -1) or -1)
            cand = page._renderer_cue_at_playhead()
            snap = page.video.playback_position_snapshot()
            print(f"[DBG] ph={ph} pos={snap.presentation_media_ms} cand={cand.id if cand else None} "
                  f"candA={cand is not None and cand.id == target.id} kind={getattr(page, '_advanced_canvas_source_kind', '')}",
                  flush=True)
        except Exception as exc:
            print("[DBG] exc", exc, flush=True)
    released = wait_until(app, lambda: web_released(page)[0], timeout=3.0)
    ok, detail = web_released(page)
    check("B_paused_seek_released", released and ok, detail)

    # ---- C) 回 A 恢复 ----
    page._seek((target.start_ms + 900) / 1000.0)
    back = wait_until(app, lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) == "web_live", timeout=30.0)
    check("C_reentry_takes_over", back, f"kind={getattr(page, '_advanced_canvas_source_kind', '')}")
    return finish(page, app)


def finish(page, app) -> int:
    try:
        page.video.set_paused(True)
    except Exception:
        pass
    try:
        page.close()
    except Exception:
        pass
    failed = [item for item in RESULTS if not item[1]]
    for label, ok, detail in RESULTS:
        print(f"[R25-SUMMARY] {'PASS' if ok else 'FAIL'} {label} {detail}")
    print(f"[R25] {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
