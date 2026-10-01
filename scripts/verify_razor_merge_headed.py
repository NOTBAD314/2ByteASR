# -*- coding: utf-8 -*-
"""Headed verification: razor drag preview, merge drag, and edit latency.

Checks (2026-09-03 razor/merge responsiveness round):
  1. Razor press-and-slide paints a full-height accent cut line and a large
     two-sentence preview card (pixel-probed, screenshot saved for review).
  2. Releasing commits the split at the previewed position.
  3. Merge press anchors, slide picks direction, arrow + card preview appear,
     release merges the pair; single click never merges with the old selection.
  4. Split / merge / undo stay responsive (<150ms sync, <150ms deferred flush).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    save_project,
)
from twobyteasr.studio_ui import SubtitleStudioPage

OUT = ROOT / "tmp" / "verify-razor-merge"
OUT.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[RAZOR-MERGE] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def mouse(widget, kind, x, y):
    event = QMouseEvent(
        kind, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    if kind == QMouseEvent.Type.MouseButtonPress:
        widget.mousePressEvent(event)
    elif kind == QMouseEvent.Type.MouseButtonRelease:
        widget.mouseReleaseEvent(event)
    else:
        widget.mouseMoveEvent(event)


def accent_pixels(image, region=None):
    hit = 0
    x0, y0, x1, y1 = region or (0, 0, image.width(), image.height())
    for y in range(max(0, y0), min(image.height(), y1)):
        for x in range(max(0, x0), min(image.width(), x1)):
            color = image.pixelColor(x, y)
            if color.red() > 180 and 60 < color.green() < 160 and color.blue() < 60:
                hit += 1
    return hit


def to_device(image, logical_x: float) -> int:
    # grab() returns a physical-pixel image; scale logical widget coordinates.
    ratio = image.devicePixelRatio() or 1.0
    return round(logical_x * ratio)


def fire_deferred(page, app) -> float:
    total = 0.0
    for _ in range(4):
        fired = False
        for timer in (page._visual_update_timer, page._preview_timer):
            if timer.isActive():
                timer.stop()
                t0 = time.perf_counter()
                timer.timeout.emit()
                total += (time.perf_counter() - t0) * 1000
                fired = True
        app.processEvents()
        if not fired:
            break
    return total


def main() -> int:
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=8000),
        cues=[
            StudioCue("a", 0, 2600, "我今天好想要吃肯德基麦当劳全家桶", speaker_id="S01"),
            StudioCue("b", 2800, 4600, "第二句我们一起去吃点东西", speaker_id="S01"),
            StudioCue("c", 4800, 7000, "第三句没问题走吧出发", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    page = SubtitleStudioPage()
    page.video.load = lambda *a, **k: None
    page._generate_waveform = lambda *a, **k: None
    page.open_project(save_project(project, OUT / "studio.2byteproj"))
    page.resize(1680, 1000)
    page.show()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    timeline = page.timeline
    timeline.set_visible_window(0, 8000)
    app.processEvents()
    baseline_accent = accent_pixels(timeline.grab().toImage())

    track = timeline._track_layout()[0]["S01"]
    cue_y = track.center().y()

    # ---- razor drag preview -------------------------------------------------
    timeline.set_tool_mode("razor")
    app.processEvents()
    # Hover alone must not paint a cut (2026-03 feedback: it read as if the
    # cue had already been split). The playhead capsule is orange by theme, so
    # compare against a baseline grabbed before the tool switch is exercised.
    hover_shot = timeline.grab().toImage()
    hover_shot.save(str(OUT / "razor_hover_none.png"))
    hover_accent = accent_pixels(hover_shot)
    check("razor hover alone paints no cut", hover_accent - baseline_accent < 25,
          f"accent px {hover_accent} vs baseline {baseline_accent}")

    x_press = timeline._time_to_x(900)
    x_slide = timeline._time_to_x(1900)
    mouse(timeline, QMouseEvent.Type.MouseButtonPress, x_press, cue_y)
    mouse(timeline, QMouseEvent.Type.MouseMove, x_slide, cue_y)
    app.processEvents()
    razor_shot = timeline.grab().toImage()
    razor_shot.save(str(OUT / "razor_preview.png"))
    preview_state = timeline._razor_preview()
    check("razor preview resolves while dragging", preview_state is not None)
    resolved, _cue = preview_state
    cut_x = to_device(razor_shot, timeline._time_to_x(resolved.split_ms))
    column = accent_pixels(razor_shot, (cut_x - 4, 0, cut_x + 4, razor_shot.height()))
    check("razor full-height cut line painted", column > 20, f"accent px in column: {column}")
    card_accent = accent_pixels(razor_shot) - baseline_accent - column
    check("razor preview card painted", card_accent > 150, f"accent px: {card_accent}")
    check(
        "razor preview texts cover the cue",
        resolved.left_text + resolved.right_text == page.project.cues[0].text,
        f"{resolved.left_text} | {resolved.right_text}",
    )

    t0 = time.perf_counter()
    mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x_slide, cue_y)
    app.processEvents()
    sync_ms = (time.perf_counter() - t0) * 1000
    deferred_ms = fire_deferred(page, app)
    check("razor release commits split", len(page.project.cues) == 4)
    check("split latency responsive", sync_ms < 150 and deferred_ms < 150,
          f"sync {sync_ms:.1f}ms deferred {deferred_ms:.1f}ms")

    # ---- undo latency -------------------------------------------------------
    t0 = time.perf_counter()
    page.undo_stack.undo()
    app.processEvents()
    undo_ms = (time.perf_counter() - t0) * 1000
    undo_deferred = fire_deferred(page, app)
    check("undo restores 3 cues", len(page.project.cues) == 3)
    check("undo latency responsive", undo_ms < 150 and undo_deferred < 150,
          f"sync {undo_ms:.1f}ms deferred {undo_deferred:.1f}ms")

    # ---- razor: long sentence must show every character ----------------------
    # A genuinely oversized sentence forces the card to its panel-width cap
    # and wrap; shorter sentences just make the card grow on a single line.
    page.resize(980, 900)
    app.processEvents()
    long_text = "这一句特别长用来验证预览卡完整换行显示所有文字内容" * 8  # 192 chars
    original_text = page.project.cues[0].text
    page.project.cues[0].text = long_text
    timeline.reindex_project()
    app.processEvents()
    lx = timeline._time_to_x(1700)
    mouse(timeline, QMouseEvent.Type.MouseButtonPress, timeline._time_to_x(1500), cue_y)
    mouse(timeline, QMouseEvent.Type.MouseMove, lx, cue_y)
    app.processEvents()
    long_state = timeline._razor_preview()
    long_shot = timeline.grab().toImage()
    long_shot.save(str(OUT / "razor_preview_long.png"))
    if long_state is not None:
        long_preview, _long_cue = long_state
        rows = [
            ("前段", long_preview.left_text, f"{len(long_preview.left_text)} 字"),
            ("后段", long_preview.right_text, f"{len(long_preview.right_text)} 字"),
        ]
        track_rect = timeline._track_layout()[0]["S01"]
        card = timeline._tool_card_geometry(rows, "标题", lx, track_rect)
        heights = timeline._tool_card_row_heights(rows, card.width())
        check("long-cue card wraps beyond one line", any(h > 24 for h in heights),
              f"heights={heights} card={card.width():.0f}x{card.height():.0f}")
        check("long-cue card fits panel width", card.width() <= timeline.width() - 20,
              f"card width {card.width():.0f} vs panel {timeline.width()}")
    mouse(timeline, QMouseEvent.Type.MouseButtonRelease, lx, cue_y)
    app.processEvents()
    fire_deferred(page, app)
    page.undo_stack.undo()  # drop the long-text split first...
    app.processEvents()
    fire_deferred(page, app)
    page.project.cues[0].text = original_text  # ...then restore the short text
    timeline.reindex_project()
    page.resize(1680, 1000)
    app.processEvents()

    # ---- razor: sub-drag wiggle commits the previewed position --------------
    wiggle_x = timeline._time_to_x(1250)
    mouse(timeline, QMouseEvent.Type.MouseButtonPress, timeline._time_to_x(1200), cue_y)
    mouse(timeline, QMouseEvent.Type.MouseMove, wiggle_x, cue_y)
    preview_state = timeline._razor_preview()
    mouse(timeline, QMouseEvent.Type.MouseButtonRelease, wiggle_x, cue_y)
    app.processEvents()
    fire_deferred(page, app)
    check("sub-drag wiggle still splits", len(page.project.cues) == 4)
    if preview_state is not None:
        resolved_preview, _target = preview_state
        by_text = {cue.text: cue for cue in page.project.cues}
        check(
            "committed split matches preview card",
            resolved_preview.left_text in by_text
            and by_text[resolved_preview.left_text].end_ms == resolved_preview.split_ms,
            f"preview split at {resolved_preview.split_ms}",
        )
    page.undo_stack.undo()
    app.processEvents()
    fire_deferred(page, app)

    # ---- razor: press/release over empty track space -------------------------
    gap_x = timeline._time_to_x(7500)  # past cue c (4800-7000), inside media
    mouse(timeline, QMouseEvent.Type.MouseButtonPress, gap_x, cue_y)
    check("empty-space press anchors nearest cue", timeline._razor_drag is not None)
    mouse(timeline, QMouseEvent.Type.MouseButtonRelease, gap_x, cue_y)
    app.processEvents()
    fire_deferred(page, app)
    check("release over empty space still cuts", len(page.project.cues) == 4)
    page.undo_stack.undo()
    app.processEvents()
    fire_deferred(page, app)

    # ---- merge drag preview -------------------------------------------------
    timeline.set_tool_mode("merge")
    app.processEvents()
    page.select_cue("a")  # stale selection must not leak into the merge
    x_anchor = timeline._time_to_x(3700)
    mouse(timeline, QMouseEvent.Type.MouseButtonPress, x_anchor, cue_y)
    mouse(timeline, QMouseEvent.Type.MouseMove, x_anchor + 140, cue_y)
    app.processEvents()
    merge_shot = timeline.grab().toImage()
    merge_shot.save(str(OUT / "merge_preview.png"))
    anchor, neighbor, direction = timeline._merge_state()
    check("merge anchor is the pressed cue", anchor is not None and anchor.id == "b")
    check("merge drag picks next neighbour", neighbor is not None and neighbor.id == "c" and direction == 1)
    merge_accent = accent_pixels(merge_shot)
    check("merge arrow/card painted", merge_accent > 150, f"accent px: {merge_accent}")

    t0 = time.perf_counter()
    mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x_anchor + 140, cue_y)
    app.processEvents()
    merge_ms = (time.perf_counter() - t0) * 1000
    merge_deferred = fire_deferred(page, app)
    texts = [cue.text for cue in page.project.cues]
    check("merge release merges anchor with neighbour", len(page.project.cues) == 2 and "第二句我们一起去吃点东西第三句没问题走吧出发" in texts, str(texts))
    check("merge latency responsive", merge_ms < 150 and merge_deferred < 150,
          f"sync {merge_ms:.1f}ms deferred {merge_deferred:.1f}ms")

    # ---- merge single click never touches the stale selection ---------------
    page.undo_stack.undo()
    app.processEvents()
    fire_deferred(page, app)
    page.select_cue("a")
    x_b = timeline._time_to_x(3700)
    mouse(timeline, QMouseEvent.Type.MouseButtonPress, x_b, cue_y)
    mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x_b, cue_y)
    app.processEvents()
    check("merge click only anchors (no accidental merge)", len(page.project.cues) == 3)

    # ---- ripple shortcuts ----------------------------------------------------
    page.select_cue("b")
    page.cue_controller.merge_with_neighbor(-1)
    app.processEvents()
    fire_deferred(page, app)
    check("Shift+Q ripple merges with previous",
          [cue.text for cue in page.project.cues][:1] == ["我今天好想要吃肯德基麦当劳全家桶第二句我们一起去吃点东西"])
    check("ripple selection lands on merged cue", page.selected_cue_id == "a")

    # ---- shortcut settings dialog opens and merge tool is B ------------------
    from twobyteasr.studio_shortcuts import ShortcutSettingsDialog

    dialog = ShortcutSettingsDialog(page._shortcut_values, page)
    check("shortcut dialog constructs", dialog.table.rowCount() > 0)
    check("merge tool default is B",
          dialog._editors["merge_tool"].keySequence().toString().upper() == "B")
    dialog.deleteLater()
    app.processEvents()

    page.close_page()
    page.deleteLater()
    app.processEvents()

    failed = [label for label, ok, _ in RESULTS if not ok]
    print()
    print(f"[RAZOR-MERGE] {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("[RAZOR-MERGE] FAILED:", "; ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
