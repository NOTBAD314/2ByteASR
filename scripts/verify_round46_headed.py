"""R46 headed verification: 真机场景叠加显示（FLV主轨+1080p60 MP4叠加）/轨道头拖拽换序/Premiere 式面板。"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORK = ROOT / "tmp" / "round46" / "verifyproj.2byteproj"
SHOTS = ROOT / "tmp" / "shots-round46"

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGroupBox

from twobyteasr.studio_ui import SubtitleStudioPage

RESULTS: list[tuple[str, bool, str]] = []


def check(label, condition, detail=""):
    RESULTS.append((label, bool(condition), detail))
    print(f"[R46H] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)
    return bool(condition)


def shot(widget, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    widget.repaint()
    widget.grab().save(str(SHOTS / name))
    print(f"[R46H] shot {name}", flush=True)


def wait_until(predicate, timeout=8.0, app=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def main() -> int:
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True)
    args=parser.parse_args()
    app = QApplication.instance() or QApplication([])
    WORK.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.project, WORK)
    page = SubtitleStudioPage()
    page.resize(1560, 940)
    page.show()
    app.processEvents()
    page.open_project(str(WORK), skip_dirty_guard=True)
    wait_until(lambda: page.project is not None and page.video._startup_state == "READY", 60.0, app)

    # --- A 真机场景：播放到 V2 区间（348-424s）→ 叠加画面可见 ---
    page.timeline.set_playhead(360_000)
    page._sync_video_compositor(360_000)
    page.video.set_paused(False)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    page.video.set_paused(True)
    page._sync_video_compositor(int(page.timeline.playhead_ms))
    wait_until(lambda: bool(page.video_compositor._layer_polygons), timeout=6.0, app=app)
    check("A1_overlay_visible_user_scene", bool(page.video_compositor._layer_polygons),
          f"pts={next(iter(page.video_compositor._players.values())).pts_ms}")
    # 暂停 scrub 后帧精确到位。
    page.timeline.set_playhead(400_000)
    page._sync_video_compositor(400_000)
    wait_until(lambda: abs(next(iter(page.video_compositor._players.values())).pts_ms - 51548) <= 600, timeout=6.0, app=app)
    check("A2_paused_scrub_frame_lands",
          abs(next(iter(page.video_compositor._players.values())).pts_ms - 51548) <= 600,
          f"pts={next(iter(page.video_compositor._players.values())).pts_ms}")
    shot(page.video_compositor, "A1-overlay-user-scene.png")

    # --- B 轨道头拖拽换序：V2 拖到 V1 泳道 → 整轨对调 ---
    tl = page.timeline
    rects = tl._video_track_rects()
    order_before = [t.id for t in page.project.video_tracks]
    v2_id = "V2"
    start = QPoint(50, int(rects[v2_id].center().y()))
    end = QPoint(50, int(rects["V1"].center().y()))
    QTest.mousePress(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    app.processEvents()
    for i in range(1, 9):
        y = start.y() + (end.y() - start.y()) * i // 8
        QTest.mouseMove(tl, QPoint(50, y))
        app.processEvents()
    QTest.mouseRelease(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    app.processEvents()
    order_after = [t.id for t in page.project.video_tracks]
    check("B1_track_header_drag_swaps", order_after[0] == "V2" and order_after[1] == "V1",
          f"{order_before} -> {order_after}")
    shot(tl, "B1-lanes-swapped.png")
    # 撤销恢复。
    page.undo_stack.undo()
    app.processEvents()
    check("B2_undo_restores", [t.id for t in page.project.video_tracks] == order_before)

    # --- C Premiere 式面板 ---
    v2_track = next(t for t in page.project.video_tracks if t.id == "V2")
    if v2_track.clips:
        page._video_clip_selected("V2", v2_track.clips[0].id)
    app.processEvents()
    page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
    app.processEvents()
    boxes = [b.title() for b in page.context_drawer.findChildren(QGroupBox)]
    check("C1_premiere_groups", "运动" in boxes and "混合" in boxes and any("绿幕" in b for b in boxes), str(boxes))
    for _child in page.context_drawer.findChildren(object):
        if getattr(_child, "objectName", lambda: "")() == "contextScroll":
            _child.ensureWidgetVisible(page.video_key_similarity)
    app.processEvents()
    shot(page.context_drawer, "C1-fx-panel-premiere.png")
    top_shot = page.context_drawer.grab()
    for _child in page.context_drawer.findChildren(object):
        if getattr(_child, "objectName", lambda: "")() == "contextScroll":
            _child.verticalScrollBar().setValue(0)
    app.processEvents()
    shot(page.context_drawer, "C2-fx-panel-top.png")

    page.close_page()
    failures = [item for item in RESULTS if not item[1]]
    print(f"\n[R46H] {len(RESULTS) - len(failures)}/{len(RESULTS)} passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
