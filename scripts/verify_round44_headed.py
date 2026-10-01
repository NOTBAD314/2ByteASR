"""R44 headed verification: 双视频轨道层级（V2 盖 V1）+ 重排跟随 + 剪气口 UI。

Phase A：合成工程（testsrc 主轨 V1）+ 导入红色 overlay 视频到新轨（V2）——
  _multitrack_preview_layers 顺序 [primary, overlay]；合成器收到 overlay 层；
  reorder_video_track 后顺序翻转（重排立即生效于绘制顺序）。
Phase B：剪辑面板"自动剪口播气口"卡片存在且可交互（阈值/按钮/状态）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEDIA_MAIN = ROOT / "tmp" / "webtest" / "testsrc.mp4"
MEDIA_OVERLAY = ROOT / "tmp" / "round44" / "overlay.mp4"
SHOTS = ROOT / "tmp" / "shots-round44"

from PySide6.QtWidgets import QApplication

from twobyteasr.studio_edit_sequence import ensure_edit_sequence, store_sequence
from twobyteasr.studio_media_pool import (
    active_video_clips,
    add_media_asset,
    add_video_clip,
    create_video_track,
    primary_video_track_id,
    reorder_video_track,
)
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R44H] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)
    return bool(condition)


def shot(widget, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    widget.repaint()
    widget.grab().save(str(SHOTS / name))
    print(f"[R44H] shot {name}", flush=True)


def wait_until(predicate, timeout: float = 8.0, *, app=None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    if app is not None:
        app.processEvents()
    return predicate()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    project_dir = ROOT / "tmp" / "round44"
    project_dir.mkdir(parents=True, exist_ok=True)

    project = SubtitleProject(
        media=StudioMedia(path=str(MEDIA_MAIN), duration_ms=40_000, width=1280, height=720),
        cues=[StudioCue("c0", 1_000, 3_000, "底层字幕")],
    )
    project.validate()
    save_project(project, project_dir / "dual.2byteproj")

    page = SubtitleStudioPage()
    page.resize(1440, 900)
    page.show()
    app.processEvents()
    page.open_project(str(project_dir / "dual.2byteproj"), skip_dirty_guard=True)
    wait_until(lambda: page.project is not None and page.video._startup_state == "READY", timeout=30.0, app=app)

    # 导入第二个视频到新轨（V2，5-13s 铺在主轨上）。
    asset = add_media_asset(
        page.project,
        MEDIA_OVERLAY,
        duration_ms=8_000,
        video_metadata={"has_video": True, "fps": 30.0, "width": 640, "height": 360},
        audio_metadata={"has_audio": True},
    )
    track = create_video_track(page.project, "覆盖轨")
    add_video_clip(page.project, track.id, asset.asset_id, timeline_in_ms=5_000)
    from twobyteasr.studio_media_pool import validate_media_graph

    validate_media_graph(page.project)
    page.cue_controller.model_changed()
    page.timeline.reindex_project()
    page.timeline.set_playhead(8_000)
    app.processEvents()

    layers = page._multitrack_preview_layers(8_000)
    keys = [layer["key"] for layer in layers]
    check("A1_two_layers", len(layers) == 2, f"keys={keys}")
    primary_first = str(layers[0]["track_id"]) == primary_video_track_id(page.project)
    check("A2_primary_bottom_overlay_top", primary_first and layers[-1]["mode"] == "multitrack", f"{keys}")
    # 合成器收到 overlay 层且可见（暂停态没有播放 tick，手动驱动一次同步）。
    page._sync_video_compositor(8_000)
    app.processEvents()
    wait_until(lambda: bool(page.video_compositor._layers), timeout=5.0, app=app)
    compositor_keys = [str(layer.get("key")) for layer in page.video_compositor._layers]
    check("A3_compositor_overlay_layer", any(key != "primary" for key in compositor_keys), f"{compositor_keys}")
    time.sleep(2.0)
    app.processEvents()
    shot(page.video, "A1-overlay-above.png")

    # 轨道重排：V2 移到 index 0 → 绘制顺序翻转（overlay 先画，主轨后画）。
    reorder_video_track(page.project, track.id, 0)
    validate_media_graph(page.project)
    app.processEvents()
    layers_after = page._multitrack_preview_layers(8_000)
    order_after = [str(layer["track_id"]) for layer in layers_after]
    check("A4_reorder_flips_paint_order", order_after[0] == track.id, f"{order_after}")
    # 还原（V2 回到顶层）。
    reorder_video_track(page.project, track.id, 1)
    app.processEvents()

    # 剪辑面板：自动剪口播气口卡片。
    panel = page.highlight_panel
    page._show_context_panel()
    page.context_drawer.setCurrentWidget(panel) if hasattr(page, "context_drawer") else None
    app.processEvents()
    check(
        "B1_autocut_card",
        hasattr(panel, "autocut_min_silence")
        and panel.autocut_min_silence.value() == 5.0
        and panel.autocut_detect_button.text() == "检测静音气口"
        and not panel.autocut_apply_button.isVisibleTo(panel),
    )
    panel.show_autocut_preview([(10_000, 16_000)], 6_000, 40_000)
    check(
        "B2_autocut_preview",
        panel.autocut_apply_button.isVisibleTo(panel) and "6.0 秒" in panel.autocut_status.text(),
        panel.autocut_status.text(),
    )
    panel.config_body.setVisible(True)
    app.processEvents()
    shot(panel.config_body, "B1-autocut-card.png")

    page.close_page()
    failures = [item for item in RESULTS if not item[1]]
    print(f"\n[R44H] {len(RESULTS) - len(failures)}/{len(RESULTS)} passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
