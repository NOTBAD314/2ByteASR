"""Headed verification for round 24: strip pre-render (record-once → replay).

  0. Service-level strip record against the REAL node renderer: the rebuilt
     Balatro theme records 0→span+400ms, frames dense, entrance≠hold, tail
     (beyond cue end) empty, and a second recording replays identically.
  A. Paused takeover + freeze: paused inside a web cue → web_live frame; with
     the playhead frozen no new frames arrive (strip replay = exact freeze).
  B. Determinism: paused seek to the same cue offset twice → identical pixel
     grid (same strip frame served).
  C. Exit anchored to duration: near cue end the overlay is mostly empty
     (exit completes at --wt-dur), fully gone past span+400ms.
  D. Node-crash immunity: strip complete → inject node_crash → playback keeps
     publishing frames from the strip (no Chromium dependency).
  E. Scope apply + warm: apply theme to the next cues → playhead walk → every
     cue gets web_live frames.
  F. Export entrance/hold/exit frames for GLM (agy) visual review.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROJECT = (ROOT / "tmp" / "webtest" / "webtest.2byteproj")
if not PROJECT.is_file():
    PROJECT = ROOT / "tmp" / "realproj" / "real-copy.2byteproj"
SHOTS = ROOT / "tmp" / "r24-verify"

from PySide6.QtWidgets import QApplication

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R24] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def wait_until(app, predicate, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


def alpha_stats(image, band: float = 0.0):
    """Share of sampled pixels with alpha>40; band>0 时只统计下方 band 比例区（字幕带）。"""
    width, height = image.width(), image.height()
    y0 = int(height * (1.0 - band)) if band > 0 else 0
    opaque = 0
    total_px = 0
    for y in range(y0, height, 4):
        for x in range(0, width, 4):
            total_px += 1
            color = image.pixelColor(x, y)
            if color is not None and color.alpha() > 150:
                opaque += 1
    return opaque / max(1, total_px)


def grid_hash(image, step: int = 16) -> str:
    digest = hashlib.sha1()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            color = image.pixelColor(x, y)
            digest.update(
                bytes((color.red() // 8, color.green() // 8, color.blue() // 8, color.alpha() // 16))
                if color is not None else b"\0\0\0\0"
            )
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 0) Service-level strip record (real node service, no Qt widgets)
# ---------------------------------------------------------------------------


def record_strip(span_ms: float, rate: float = 1.0) -> list[tuple[float, bytes]]:
    from twobyteasr.renderer_service import GLOBAL_RENDERER_SERVICE
    from twobyteasr.web_theme import builtin_web_themes, theme_archive_html

    theme = builtin_web_themes()["balatro-joker"].to_dict()
    html = theme_archive_html(theme, sample_text="小丑筹码灯珠全屏", duration_seconds=span_ms / 1000.0, auto_replay=False)
    svc = GLOBAL_RENDERER_SERVICE
    svc.live_set(html, width=1280, height=720, timeout=60.0)
    frames: list[tuple[float, bytes]] = []
    svc.live_pause(cue_ms=0.0, stage_ms=0.0)
    svc.live_play(cue_ms=0.0, stage_ms=0.0, rate=rate, every_nth_frame=1)
    t0 = time.monotonic()
    seq = 0
    while True:
        frontier = (time.monotonic() - t0) * 1000.0 * rate
        if frontier >= span_ms + 400.0:
            break
        new_seq, png = svc.live_latest(since_seq=seq)
        if png:
            seq = new_seq
            frames.append((frontier, png))
        time.sleep(0.01)
    return frames


def part0_service_strip() -> list[tuple[float, bytes]]:
    from PySide6.QtGui import QImage

    frames = record_strip(3000.0)
    check("strip_frame_count", len(frames) >= 75, f"frames={len(frames)}（everyNth=1÷2.5x≈24动画fps）")
    times = [t for t, _ in frames]
    check("strip_times_monotonic", all(b > a for a, b in zip(times, times[1:])), "")

    def frame_near(t: float) -> tuple[float, bytes]:
        return min(frames, key=lambda item: abs(item[0] - t))

    entrance = QImage.fromData(frame_near(450.0)[1])
    hold = QImage.fromData(frame_near(1800.0)[1])
    tail = QImage.fromData(frame_near(3150.0)[1])
    entrance.save(str(SHOTS / "balatro-entrance.png"))
    hold.save(str(SHOTS / "balatro-hold.png"))
    tail.save(str(SHOTS / "balatro-exit-tail.png"))
    check("strip_frames_decode", not (entrance.isNull() or hold.isNull() or tail.isNull()))
    gh_entrance, gh_hold = grid_hash(entrance), grid_hash(hold)
    check("entrance_differs_from_hold", gh_entrance != gh_hold, "入场≠持住（动画在走）")
    hold_band = alpha_stats(hold, band=0.32)
    tail_band = alpha_stats(tail, band=0.32)
    check("exit_tail_band_emptied", tail_band < 0.6 * max(hold_band, 0.01),
          f"hold_band={hold_band:.3f} tail_band={tail_band:.3f}（cue 层在 --wt-dur 收束；舞台氛围层保留）")
    # 重录一致性：同主题再录一遍，对应时刻字幕带的不透明占比应一致（±0.2）。
    frames2 = record_strip(3000.0)
    e2 = QImage.fromData(min(frames2, key=lambda item: abs(item[0] - 1800.0))[1])
    band2 = alpha_stats(e2, band=0.32)
    check("second_record_band_consistent",
          len(frames2) >= 75 and abs(band2 - hold_band) < 0.2,
          f"frames2={len(frames2)} band2={band2:.3f} vs {hold_band:.3f}")
    return frames


# ---------------------------------------------------------------------------
# Studio-level checks
# ---------------------------------------------------------------------------


def pick_target(page):
    cues = page.project.cues
    return next(
        (c for c in cues if 30_000 <= c.start_ms <= 60_000 and (c.end_ms - c.start_ms) >= 2500),
        next((c for c in cues if (c.end_ms - c.start_ms) >= 2500), cues[0]),
    )


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])

    frames = part0_service_strip()

    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.web_theme import builtin_web_themes

    page = SubtitleStudioPage()
    page.resize(1700, 940)
    page.show()
    app.processEvents()
    page.open_project(PROJECT, skip_dirty_guard=True)
    if not wait_until(app, lambda: page.project is not None and page.video._startup_state == "READY", 25.0):
        check("project_ready", False, f"startup={page.video._startup_state}")
        return finish(page, app)
    check("project_ready", True, f"cues={len(page.project.cues)}")

    theme = builtin_web_themes()["balatro-joker"].to_dict()
    target = pick_target(page)
    span = target.end_ms - target.start_ms
    assert page._apply_web_theme(target.id, theme)

    # ---- A) paused takeover + freeze ----
    page.video.set_paused(True)
    page._seek((target.start_ms + 500) / 1000.0)
    ok = wait_until(app, lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) == "web_live", timeout=30.0)
    check("web_live_takes_over_paused", ok, f"kind={getattr(page, '_advanced_canvas_source_kind', '')}")
    pixmap = getattr(page, "_advanced_cue_pixmap", None)
    # 等条带录完（暂停时录制静默进行），随后验证"暂停=冻结"。
    from twobyteasr.live_web_preview import GLOBAL_WEB_STRIP_STORE as _STORE

    def _strip_done() -> bool:
        worker = getattr(page, "_web_live_worker", None)
        return worker is not None and _STORE.is_complete(worker.strip_key)

    wait_until(app, _strip_done, timeout=40.0)
    stamp = float(getattr(page, "_web_live_last_frame_at", 0.0))
    time.sleep(2.0)
    app.processEvents()
    stamp2 = float(getattr(page, "_web_live_last_frame_at", 0.0))
    check("paused_no_new_frames", stamp2 == stamp, f"{stamp:.2f} → {stamp2:.2f}（暂停=冻结）")

    # ---- B) determinism: same offset twice → identical pixels ----
    def snapshot_at(offset_ms: float) -> str:
        page._seek((target.start_ms + offset_ms) / 1000.0)
        wait_until(app, lambda: time.monotonic() > 0, 0.5)  # let ticks settle
        deadline = time.monotonic() + 5.0
        last = ""
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.08)
            pm = getattr(page, "_advanced_cue_pixmap", None)
            if pm is not None and not pm.isNull():
                last = grid_hash(pm.toImage())
        return last

    hash_b1 = snapshot_at(1200)
    hash_b2 = snapshot_at(1200)
    check("replay_deterministic", hash_b1 == hash_b2 and hash_b1 != "", "同偏移两次取帧逐格一致")

    # ---- C) exit anchored to cue duration ----
    pm_hold = getattr(page, "_advanced_cue_pixmap", None)
    snapshot_at(1200)  # 回持住位取参照帧
    pm_hold2 = getattr(page, "_advanced_cue_pixmap", None)
    snapshot_at(max(120, span - 40))  # 出场尾段（--wt-dur 前 40ms，≈93% 进度）
    pm_exit = getattr(page, "_advanced_cue_pixmap", None)
    hold_band = alpha_stats(pm_hold2.toImage(), band=0.32) if pm_hold2 is not None and not pm_hold2.isNull() else 0.0
    exit_band = alpha_stats(pm_exit.toImage(), band=0.32) if pm_exit is not None and not pm_exit.isNull() else 1.0
    check("exit_anchored_to_dur", exit_band < 0.65 * max(hold_band, 0.01),
          f"hold_band={hold_band:.3f} near_end_band={exit_band:.3f}")
    # 越界（span+400 之后）：画布按 ownership 隐藏，不再显示残留。
    page._seek((target.end_ms + 700) / 1000.0)
    wait_until(app, lambda: True, 0.8)
    hidden = str(getattr(page, "_advanced_canvas_source_kind", "")) != "web_live" or not getattr(page, "_web_live_is_fresh", lambda: False)()
    check("beyond_span_no_web_residue", hidden,
          f"kind={getattr(page, '_advanced_canvas_source_kind', '')}")
    _ = pm_hold

    # ---- D) node crash immunity after strip warm ----
    # 越界检查后 worker 已退场：seek 回 cue 内让条带回放接管，再验录制完成。
    page.video.set_paused(True)
    page._seek((target.start_ms + 400) / 1000.0)

    def _worker_alive():
        worker = getattr(page, "_web_live_worker", None)
        return worker is not None and worker.running

    wait_until(app, _worker_alive, timeout=25.0)
    from twobyteasr.live_web_preview import GLOBAL_WEB_STRIP_STORE

    deadline = time.monotonic() + 30.0
    prev_count = -1
    stable_since = None
    strip_frames = 0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.2)
        worker = getattr(page, "_web_live_worker", None)
        strip = GLOBAL_WEB_STRIP_STORE.peek(worker.strip_key) if worker is not None else None
        strip_frames = len(strip.frames) if strip is not None else 0
        if strip is not None and strip.done:
            break
        if strip_frames == prev_count and strip_frames > 20:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since > 2.0:
                break
        else:
            stable_since = None
        prev_count = strip_frames
    strip_done = page._web_live_worker is not None and GLOBAL_WEB_STRIP_STORE.is_complete(page._web_live_worker.strip_key)
    check("strip_recorded_in_studio", strip_done, f"frames={strip_frames}")

    from twobyteasr.renderer_service import GLOBAL_RENDERER_SERVICE

    page.video.set_paused(True)
    page._seek((target.start_ms + 200) / 1000.0)
    wait_until(app, lambda: True, 0.6)
    try:
        GLOBAL_RENDERER_SERVICE.inject_failure("node_crash")
    except Exception as exc:  # noqa: BLE001
        check("node_crash_injected", False, str(exc)[:120])
    page.video.set_paused(False)
    frames_after_crash = [0]
    baseline = float(getattr(page, "_web_live_last_frame_at", 0.0))
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.08)
        if float(getattr(page, "_web_live_last_frame_at", 0.0)) > baseline:
            frames_after_crash[0] += 1
            baseline = float(getattr(page, "_web_live_last_frame_at", 0.0))
    page.video.set_paused(True)
    check("replay_survives_node_crash", frames_after_crash[0] >= 15,
          f"frames_after_crash={frames_after_crash[0]}")
    check("kind_still_web_live", str(getattr(page, "_advanced_canvas_source_kind", "")) == "web_live",
          getattr(page, "_advanced_canvas_source_kind", ""))

    # ---- E) scope apply + warm → every cue has frames ----
    later = [c for c in page.project.cues if c.start_ms > target.end_ms][:2]
    applied = sum(1 for c in later if page._apply_web_theme(c.id, theme))
    warm = getattr(page, "_queue_web_strip_warm", None)
    if callable(warm) and later:
        warm([c.id for c in later])
    walked = 0
    for cue in later:
        page.video.set_paused(True)
        page._seek((cue.start_ms + min(800, max(200, (cue.end_ms - cue.start_ms) // 2))) / 1000.0)
        got = wait_until(
            app,
            lambda c=cue: str(getattr(page, "_advanced_canvas_source_kind", "")) == "web_live"
            and str(getattr(page, "_web_live_cue_id", "")) == c.id,
            timeout=25.0,
        )
        walked += 1 if got else 0
        check(f"scope_cue_{cue.id[:6]}_frames", got,
              f"kind={getattr(page, '_advanced_canvas_source_kind', '')}")
    check("scope_apply_walk", applied == len(later) and walked == len(later),
          f"applied={applied}/{len(later)} walked={walked}")

    # ---- F) export frames for visual review ----
    pm = getattr(page, "_advanced_cue_pixmap", None)
    if pm is not None and not pm.isNull():
        pm.save(str(SHOTS / "studio-web-frame.png"))
    check("frames_exported", len(list(SHOTS.glob('*.png'))) >= 4, str(sorted(p.name for p in SHOTS.glob('*.png'))))

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
        print(f"[R24-SUMMARY] {'PASS' if ok else 'FAIL'} {label} {detail}")
    print(f"[R24] {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
