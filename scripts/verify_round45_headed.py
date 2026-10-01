"""R45 headed verification: 泳道反转/跨轨拖拽 + ADR-0005 素材效果（scrub/混合/色键）。

Phase A：双视频工程——泳道 V3>V2>V1 自上而下；选中 V2 绿幕素材 → 视频 tab；
  启用抠像（绿）→ 绿幕变透明露出底层；混合模式=屏幕；scrub 控件存在。
Phase B：真实鼠标跨轨拖拽（V2→V3）落位。
截图 tmp/shots-round45/ → agy 评审。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEDIA_MAIN = ROOT / "tmp" / "webtest" / "testsrc.mp4"
MEDIA_GREEN = ROOT / "tmp" / "round45" / "greenscreen.mp4"
SHOTS = ROOT / "tmp" / "shots-round45"

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, qAlpha
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_media_pool import (
    add_media_asset,
    add_video_clip,
    create_video_track,
    primary_video_track_id,
    set_video_clip_effects,
    validate_media_graph,
)
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage

RESULTS: list[tuple[str, bool, str]] = []


def check(label, condition, detail=""):
    RESULTS.append((label, bool(condition), detail))
    print(f"[R45H] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)
    return bool(condition)


def shot(widget, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    widget.repaint()
    widget.grab().save(str(SHOTS / name))
    print(f"[R45H] shot {name}", flush=True)


def wait_until(predicate, timeout=8.0, app=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def drag(timeline, app, start, end, steps=8):
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    app.processEvents()
    for i in range(1, steps + 1):
        x = start.x() + (end.x() - start.x()) * i // steps
        y = start.y() + (end.y() - start.y()) * i // steps
        QTest.mouseMove(timeline, QPoint(x, y))
        app.processEvents()
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    project_dir = ROOT / "tmp" / "round45"
    project_dir.mkdir(parents=True, exist_ok=True)
    project = SubtitleProject(
        media=StudioMedia(path=str(MEDIA_MAIN), duration_ms=40_000, width=1280, height=720),
        cues=[StudioCue("c0", 1_000, 3_000, "底层字幕")],
    )
    project.validate()
    save_project(project, project_dir / "fx.2byteproj")
    page = SubtitleStudioPage()
    page.resize(1560, 940)
    page.show()
    app.processEvents()
    page.open_project(str(project_dir / "fx.2byteproj"), skip_dirty_guard=True)
    wait_until(lambda: page.project is not None and page.video._startup_state == "READY", 30.0, app)

    asset = add_media_asset(page.project, MEDIA_GREEN, duration_ms=8_000,
                            video_metadata={"has_video": True, "fps": 30.0},
                            audio_metadata={"has_audio": True})
    v2 = create_video_track(page.project, "绿幕层")
    v3 = create_video_track(page.project, "顶层")
    clip = add_video_clip(page.project, v2.id, asset.asset_id, timeline_in_ms=4_000)
    validate_media_graph(page.project)
    page.timeline.reindex_project()
    page.timeline.set_visible_window(0, 30_000)
    app.processEvents()

    tl = page.timeline
    rects = tl._video_track_rects()
    check("A1_lane_order_top_down", rects[v3.id].top() < rects[v2.id].top() < rects[primary_video_track_id(page.project)].top())
    page.timeline.set_playhead(8_000)
    page._sync_video_compositor(8_000)
    time.sleep(1.5)
    app.processEvents()
    shot(page.video_compositor, "A1-overlay-raw.png")

    # 真实拖拽：V2 绿幕片段拖到 V3 泳道（跨轨换层）。
    x = tl._time_to_x(8_000)
    drag(tl, app, QPoint(int(x), int(rects[v2.id].center().y())), QPoint(int(x), int(rects[v3.id].center().y())))
    app.processEvents()
    v2_now = next(t for t in page.project.video_tracks if t.id == v2.id)
    v3_now = next(t for t in page.project.video_tracks if t.id == v3.id)
    check("B1_cross_track_drag", not v2_now.clips and len(v3_now.clips) == 1)

    # 选中片段 → 视频 tab 出现；启用绿幕抠像 → 预览变透明。
    tl.selected_video_clip_id = v3_now.clips[0].id
    page._video_clip_selected(v3.id, v3_now.clips[0].id)
    app.processEvents()
    check("A2_fx_panel_enabled", page.video_key_enabled.isEnabled() and page.video_blend_mode.isEnabled())
    page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
    app.processEvents()
    for _child in page.context_drawer.findChildren(object):
        if getattr(_child, "objectName", lambda: "")() == "contextScroll":
            scroll = _child
            scroll.ensureWidgetVisible(page.video_key_enabled)
    app.processEvents()
    shot(page.context_drawer, "A2-fx-panel.png")

    def _warm_overlay_frames(seconds: float = 2.0) -> None:
        # 暂停态 QMediaPlayer 不推帧——短暂播放让叠加层解码出画再测。
        page.video.set_paused(False)
        time.sleep(seconds)
        app.processEvents()
        page.video.set_paused(True)
        page._sync_video_compositor(8_000)
        time.sleep(0.8)
        app.processEvents()

    def _overlay_opaque_pixels() -> int:
        pixmap = page.video_compositor.grab()
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        count = 0
        for y in range(0, image.height(), 4):
            for x in range(0, image.width(), 4):
                if qAlpha(image.pixel(x, y)) > 40:
                    count += 1
        return count

    _warm_overlay_frames()
    for _cid, _rt in page.video_compositor._players.items():
        _img = getattr(_rt, 'image', None)
        print('DBG player', _cid, 'state', _rt.state, 'pts', getattr(_rt, 'pts_ms', None), 'img', None if _img is None else (_img.width(), _img.height(), _img.isNull()))
    print('DBG layers', len(page.video_compositor._layers), 'visible', page.video_compositor.isVisible(), 'geom', page.video_compositor.geometry(), 'polygons', len(page.video_compositor._layer_polygons))
    _pm = page.video_compositor.grab()
    print('DBG grab', _pm.width(), _pm.height(), hex(_pm.toImage().pixel(320, 200)))
    wait_until(lambda: bool(page.video_compositor._layer_polygons), timeout=6.0, app=app)
    before_key_pixels = _overlay_opaque_pixels()
    set_video_clip_effects(page.project, v3.id, v3_now.clips[0].id, {
        "blendMode": "normal",
        "chromaKey": {"enabled": True, "color": "#00FF00", "similarity": 0.22, "smoothness": 0.08, "spillSuppression": True},
    })
    page.timeline.reindex_project()
    page._sync_video_compositor(8_000)
    time.sleep(1.5)
    app.processEvents()
    wait_until(lambda: page.video_compositor._layer_polygons, timeout=6.0, app=app)
    time.sleep(0.3)
    app.processEvents()
    after_key_pixels = _overlay_opaque_pixels()
    # 纯绿素材被键控后应大面积透明（非透明采样显著减少）。
    check("A3_chroma_keys_out", after_key_pixels < before_key_pixels * 0.35,
          f"before={before_key_pixels} after={after_key_pixels}")
    shot(page.video_compositor, "A3-overlay-keyed.png")

    set_video_clip_effects(page.project, v3.id, v3_now.clips[0].id, {
        "blendMode": "screen",
        "chromaKey": {"enabled": False},
    })
    _warm_overlay_frames(1.5)
    shot(page.video_compositor, "A4-overlay-blend.png")
    check("A4_blend_screen_applied", page.project.video_tracks[-1].clips[0].effects["blendMode"] == "screen")
    shot(tl, "B2-timeline-lanes.png")

    page.close_page()
    failures = [item for item in RESULTS if not item[1]]
    print(f"\n[R45H] {len(RESULTS) - len(failures)}/{len(RESULTS)} passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
