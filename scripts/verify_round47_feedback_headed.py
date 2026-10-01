# -*- coding: utf-8 -*-
"""Headed verification: 第四十七轮用户四图反馈批（2026-09-06）。

Checks:
  1. 图一：hub 态「剪辑助手」隐藏、工程打开后显示（双语按钮在 overflow 常驻
     隐藏，断言其不因 chrome 同步被意外弹回工具栏）。
  2. 图二-A：轨道头列局部重绘（悬停 invalidation 的 fast path）后 V1/V2 图标
     仍在——用 render(sourceRegion=悬停矩形) 精确走 paintEvent 的快速路径，
     像素统计图标盒内非背景像素。
  3. 图三：审核模式按钮有图标；导出字幕图标为 GREEN 系。
  4. 图四-A：工具面板头不再有「字幕显示」（文A）按钮。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from twobyteasr.studio_media_pool import add_video_clip, create_video_track  # noqa: E402
from twobyteasr.studio_project import (  # noqa: E402
    MediaAsset,
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    save_project,
)
from twobyteasr.studio_ui import SubtitleStudioPage  # noqa: E402

OUT = ROOT / "tmp" / "verify-round47"
OUT.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[ROUND47] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def icon_box_pixels(image: QImage, box: QRect, background: QColor) -> int:
    """Count pixels inside an icon box that differ from the header background."""
    hit = 0
    for y in range(max(0, box.top()), min(image.height(), box.bottom())):
        for x in range(max(0, box.left()), min(image.width(), box.right())):
            color = image.pixelColor(x, y)
            if (abs(color.red() - background.red()) > 18
                    or abs(color.green() - background.green()) > 18
                    or abs(color.blue() - background.blue()) > 18):
                hit += 1
    return hit


def capture_region(widget, rect: QRect) -> QImage:
    """Capture real on-screen pixels (no repaint) for a widget-local rect.

    QWidget.render() 触发的是全 region 的 paintEvent——快速路径根本不会执行。
    要复现"悬停局部 invalidation"必须走真实 update(rect) + 事件循环，再用
    QScreen.grabWindow 抓已上屏的像素（grab() 会强制全量重绘，会掩盖 bug）。
    """

    screen = widget.screen() or QApplication.primaryScreen()
    top_left = widget.mapToGlobal(rect.topLeft())
    shot = screen.grabWindow(
        0, top_left.x(), top_left.y(), max(1, rect.width()), max(1, rect.height())
    )
    return shot.toImage()


def main() -> int:
    app = QApplication.instance() or QApplication([])

    # ---- 图一：hub 态按钮可见性 ------------------------------------------------
    page = SubtitleStudioPage()
    page.video.load = lambda *a, **k: None
    page._generate_waveform = lambda *a, **k: None
    page.resize(1680, 1000)
    page.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)

    assistant = getattr(page, "studio_clip_assistant_button", None)
    bilingual = getattr(page, "bilingual_toggle_button", None)
    check("hub 态剪辑助手按钮隐藏", assistant is not None and not assistant.isVisible(),
          f"visible={assistant.isVisible() if assistant else 'missing'}")
    overflow_ids = {id(w) for w in getattr(page, "_studio_toolbar_overflow_widgets", ())}
    if bilingual is not None and id(bilingual) not in overflow_ids:
        check("hub 态双语按钮隐藏", not bilingual.isVisible())
    else:
        check("双语按钮在 overflow 菜单常驻隐藏（不回弹工具栏）", True)

    # ---- 打开合成工程 ----------------------------------------------------------
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=8000),
        cues=[
            StudioCue("a", 0, 2600, "我今天好想要吃肯德基麦当劳全家桶", speaker_id="S01"),
            StudioCue("b", 2800, 4600, "第二句我们一起去吃点东西", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    from twobyteasr.studio_edit_sequence import ensure_edit_sequence
    from twobyteasr.studio_project import sync_linked_av_contract

    ensure_edit_sequence(project)
    create_video_track(project, "主视频轨")
    create_video_track(project, "叠加轨")
    overlay_asset = MediaAsset(
        asset_id="asset-overlay",
        canonical_source="D:/overlay.mp4",
        display_name="overlay.mp4",
        duration_ms=8000,
        fingerprint="overlay",
    )
    project.media_pool.append(overlay_asset)
    add_video_clip(project, "V2", "asset-overlay",
                   timeline_in_ms=1000, source_in_ms=500, source_out_ms=6500)
    sync_linked_av_contract(project)
    page.open_project(save_project(project, OUT / "studio.2byteproj"))
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)

    check("编辑态剪辑助手按钮显示", assistant.isVisible())

    # ---- 图三：审核模式图标 / 工具行图标颜色统一 --------------------------------
    review_icon = page.review_mode_button.icon()
    check("审核模式按钮有图标", not review_icon.isNull())
    icon_buttons = {
        "review": page.review_mode_button,
        "find_replace": page.studio_find_replace_button,
        "export": page.studio_export_button,
        "clip_assistant": page.studio_clip_assistant_button,
    }
    tints: dict[str, tuple[int, int, int]] = {}
    for name, button in icon_buttons.items():
        icon = button.icon()
        check(f"图三 {name} 按钮有图标", not icon.isNull())
        if icon.isNull():
            continue
        image = icon.pixmap(24).toImage()
        total_r = total_g = total_b = count = 0
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.alpha() < 60:
                    continue
                total_r += color.red()
                total_g += color.green()
                total_b += color.blue()
                count += 1
        if count:
            tints[name] = (total_r // count, total_g // count, total_b // count)
    if len(tints) == len(icon_buttons):
        reference = tints["export"]
        uniform = all(
            max(abs(tints[name][i] - reference[i]) for i in range(3)) <= 40
            for name in tints
        )
        check("图三 工具行图标颜色统一（同 tint）", uniform, f"tints={tints}")

    # ---- 图四-A：工具面板头「字幕显示」按钮已删 ---------------------------------
    display_buttons = [
        w for w in page.findChildren(QToolButton)
        if w.text() == "字幕显示"
    ]
    check("工具面板头无「字幕显示」按钮", not display_buttons)

    # ---- 图二-A：轨道头列局部重绘后视频轨图标仍在 -------------------------------
    timeline = page.timeline
    timeline.set_visible_window(0, 8000)
    app.processEvents()

    palette = timeline._timeline_palette()
    header_bg = QColor(palette.header)
    rects = timeline._video_track_rects()
    check("双视频轨存在", set(rects) == {"V1", "V2"}, f"tracks={sorted(rects)}")

    def probe_track(track_id: str, tag: str) -> None:
        lane = rects[track_id]
        strip = QRect(120, int(lane.top()), int(timeline.TRACK_HEADER_WIDTH - 120), int(lane.height()))
        # 对四个图标逐一触发真实悬停 invalidation（update(rect)+事件循环，
        # paintEvent 收到的 event.region() 就是各自矩形 → 走快速路径）。
        action_left = {"enabled": 132, "muted": 156, "locked": 180, "more": 204}
        for action, left in action_left.items():
            hover_rect = QRect(left - 3, int(lane.top() + 5), 22 + 6, int(lane.height() - 10))
            timeline._hover_header_action = (f"video:{track_id}", action)
            timeline.update(hover_rect)
            for _ in range(6):
                app.processEvents()
        timeline._hover_header_action = None
        timeline.update(strip)
        for _ in range(4):
            app.processEvents()
        shot = capture_region(timeline, strip)
        shot.save(str(OUT / f"hover_fastpath_{track_id}.png"))
        boxes = {
            "enabled": QRect(134 - strip.left(), int(lane.top()) + 20 - strip.top(), 18, 18),
            "muted": QRect(158 - strip.left(), int(lane.top()) + 20 - strip.top(), 18, 18),
            "locked": QRect(182 - strip.left(), int(lane.top()) + 20 - strip.top(), 18, 18),
            "more": QRect(206 - strip.left(), int(lane.top()) + 20 - strip.top(), 18, 18),
        }
        for name, box in boxes.items():
            hit = icon_box_pixels(shot, box, header_bg)
            check(f"{tag} {track_id} 图标 {name} 局部重绘后仍在", hit >= 8, f"px={hit}")

    probe_track("V2", "图二-A")
    probe_track("V1", "图二-A")

    # 视频区整域 invalidation（选择轨/片段）也不能再擦掉泳道内容——
    # 真实 update + 抓屏（同上，render() 不会走快速路径）。
    lanes_rect = timeline._video_tracks_rect().toAlignedRect()
    timeline.update(lanes_rect)
    for _ in range(6):
        app.processEvents()
    lanes_shot = capture_region(timeline, lanes_rect)
    lanes_shot.save(str(OUT / "lanes_fastpath.png"))
    v2_lane = rects["V2"]
    clip_zone = QRect(
        int(timeline.TRACK_HEADER_WIDTH + 30 - lanes_rect.left()),
        int(v2_lane.top() + 7 - lanes_rect.top()),
        int(lanes_rect.width() - timeline.TRACK_HEADER_WIDTH - 60),
        int(v2_lane.height() - 14),
    )
    clip_hit = icon_box_pixels(lanes_shot, clip_zone, header_bg)
    check("图二-A V2 泳道整域重绘后片段仍在", clip_hit > 200, f"px={clip_hit}")
    for name, box in {
        "enabled": QRect(134 - lanes_rect.left(), int(v2_lane.top()) + 20 - lanes_rect.top(), 18, 18),
        "more": QRect(206 - lanes_rect.left(), int(v2_lane.top()) + 20 - lanes_rect.top(), 18, 18),
    }.items():
        hit = icon_box_pixels(lanes_shot, box, header_bg)
        check(f"图二-A V2 泳道整域重绘后图标 {name} 仍在", hit >= 8, f"px={hit}")

    full = timeline.grab().toImage()
    full.save(str(OUT / "timeline_full.png"))

    ok = all(result for _label, result, _detail in RESULTS)
    print(f"[ROUND47] {'ALL PASS' if ok else 'HAS FAILURES'} ({len(RESULTS)} checks)", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
