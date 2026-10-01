# -*- coding: utf-8 -*-
"""Headed verification: 第四十八轮用户实测反馈（2026-09-06）。

  1. 图二-A（续）：A2 音频行图标（muted/solo/master）悬停局部重绘后仍在
     ——上轮修复漏了"音频行夹在视频区联合矩形内走快速路径 1"的情况
     （用户截图实证：A2 只剩喇叭）。
  2. 拖片段到主轨泳道 = V1/V2 层级对调（不再序列插入）；撤销恢复。
  3. 主页（识别首页）回滚核验：三张识别方案卡恢复分档尺寸。
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

from PySide6.QtCore import QEvent, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.studio_edit_sequence import ensure_edit_sequence  # noqa: E402
from twobyteasr.studio_media_pool import (  # noqa: E402
    add_video_clip,
    create_video_track,
    sync_linked_av_contract,
    sync_primary_video_track_from_sequence,
)
from twobyteasr.studio_edit_sequence import sequence_of  # noqa: E402
from twobyteasr.studio_project import (  # noqa: E402
    MediaAsset,
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    save_project,
)
from twobyteasr.studio_ui import SubtitleStudioPage  # noqa: E402

OUT = ROOT / "tmp" / "verify-round48"
OUT.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[ROUND48] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def capture_region(widget, rect):
    screen = widget.screen() or QApplication.primaryScreen()
    top_left = widget.mapToGlobal(rect.topLeft())
    return screen.grabWindow(
        0, top_left.x(), top_left.y(), max(1, rect.width()), max(1, rect.height())
    ).toImage()


def icon_box_pixels(image, box, background: QColor) -> int:
    hit = 0
    for y in range(max(0, box.top()), min(image.height(), box.bottom())):
        for x in range(max(0, box.left()), min(image.width(), box.right())):
            color = image.pixelColor(x, y)
            if (abs(color.red() - background.red()) > 18
                    or abs(color.green() - background.green()) > 18
                    or abs(color.blue() - background.blue()) > 18):
                hit += 1
    return hit


def mouse(widget, kind: QEvent.Type, x, y):
    event = QMouseEvent(
        kind, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    if kind == QEvent.Type.MouseButtonPress:
        widget.mousePressEvent(event)
    elif kind == QEvent.Type.MouseButtonRelease:
        widget.mouseReleaseEvent(event)
    else:
        widget.mouseMoveEvent(event)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=20_000),
        cues=[StudioCue("a", 0, 2600, "我今天好想要吃肯德基麦当劳全家桶", speaker_id="S01")],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    ensure_edit_sequence(project)
    create_video_track(project, "主视频轨")
    create_video_track(project, "叠加轨")
    sync_primary_video_track_from_sequence(project, sequence_of(project))
    overlay = MediaAsset(
        asset_id="asset-overlay",
        canonical_source="D:/overlay.mp4",
        display_name="overlay.mp4",
        duration_ms=20_000,
        fingerprint="overlay",
    )
    project.media_pool.append(overlay)
    add_video_clip(project, "V2", "asset-overlay",
                   timeline_in_ms=2000, source_in_ms=0, source_out_ms=15_000)
    sync_linked_av_contract(project)

    page = SubtitleStudioPage()
    page.open_project(save_project(project, OUT / "studio.2byteproj"))
    page.resize(1680, 1000)
    page.show()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    timeline = page.timeline
    timeline.set_visible_window(0, 20_000)
    for _ in range(6):
        app.processEvents()

    # ---- 图二-A（续）：A2 音频图标悬停后仍在 ----------------------------------
    palette = timeline._timeline_palette()
    header_bg = QColor(palette.header)
    audio_rects = timeline._audio_track_rects()
    check("音频行存在（A2/A1）", set(audio_rects) >= {"A1", "A2"}, f"{sorted(audio_rects)}")
    a2 = audio_rects.get("A2")
    if a2 is not None:
        strip = QRect(int(96), int(a2.top()), int(timeline.TRACK_HEADER_WIDTH - 96), int(a2.height()))
        for action, left in {"muted": 108, "solo": 136, "master": 164}.items():
            hover = QRect(left - 3, int(a2.top() + 5), 34, int(a2.height() - 10))
            timeline._hover_header_action = ("audio:A2", action)
            timeline.update(hover)
            for _ in range(6):
                app.processEvents()
        timeline._hover_header_action = None
        timeline.update(strip)
        for _ in range(4):
            app.processEvents()
        shot = capture_region(timeline, strip)
        shot.save(str(OUT / "audio_hover_fastpath_A2.png"))
        for action, left in {"muted": 108, "solo": 136, "master": 164}.items():
            box = QRect(left - strip.left() + 3, int(a2.top()) + 10 - strip.top(), 15, 15)
            hit = icon_box_pixels(shot, box, header_bg)
            check(f"图二-A(续) A2 图标 {action} 悬停后仍在", hit >= 6, f"px={hit}")

    # ---- 拖 V2 片段到 V1 泳道 = 层级对调 --------------------------------------
    rects = timeline._video_track_rects()
    lane_v2, lane_v1 = rects["V2"], rects["V1"]
    v2_clip = project.video_tracks[1].clips[0]
    clip_mid = v2_clip.timeline_in_ms + (v2_clip.timeline_out_ms - v2_clip.timeline_in_ms) // 2
    clip_x = timeline._time_to_x(clip_mid)
    order_before = [track.id for track in project.video_tracks]
    z_before = [track.z_index for track in project.video_tracks]
    mouse(timeline, QEvent.Type.MouseButtonPress, clip_x, lane_v2.center().y())
    mouse(timeline, QEvent.Type.MouseMove, clip_x, lane_v1.center().y())
    for _ in range(4):
        app.processEvents()
    drag_shot = capture_region(timeline, timeline._video_tracks_rect().toAlignedRect())
    drag_shot.save(str(OUT / "swap_pending.png"))
    mouse(timeline, QEvent.Type.MouseButtonRelease, clip_x, lane_v1.center().y())
    for _ in range(8):
        app.processEvents()
    order_after = [track.id for track in project.video_tracks]
    z_after = [track.z_index for track in project.video_tracks]
    check("拖到主轨泳道=层级对调（z 序互换）", z_after[0] > z_after[1] and order_after == order_before,
          f"z {z_before}->{z_after}")
    check("片段仍留在 V2", len(project.video_tracks[1].clips) == 1)
    page.undo_stack.undo()
    for _ in range(6):
        app.processEvents()
    check("撤销恢复层级", [track.z_index for track in project.video_tracks] == z_before)

    full = timeline.grab().toImage()
    full.save(str(OUT / "timeline_full.png"))

    # ---- 主页回滚核验 ----------------------------------------------------------
    import subtitle_core
    from twobyteasr import ui as ui_module
    from twobyteasr.ui_recognition import RecognitionRoleCard
    from moss_firered_pipeline import moss_firered_pipeline
    window = ui_module.MainWindow(
        [], subtitle_core, moss_firered_pipeline, {"id": "round48-verify", "checks": 0}
    )
    window.resize(1600, 1000)
    window.show()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    home_shot = window.grab()
    home_shot.save(str(OUT / "home_page.png"))
    # 识别方案卡的图标尺寸恢复分档（normal ≥ 48px；compact 也 ≥ 40px）。
    cards = window.findChildren(RecognitionRoleCard)
    ok_size = any(w.icon_label.width() >= 40 for w in cards) if cards else False
    check("识别方案卡图标恢复分档尺寸（≥40px）", ok_size,
          f"cards={len(cards)} sizes={[w.icon_label.width() for w in cards][:4]}")

    ok = all(result for _label, result, _detail in RESULTS)
    print(f"[ROUND48] {'ALL PASS' if ok else 'HAS FAILURES'} ({len(RESULTS)} checks)", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
