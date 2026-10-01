"""R31 headed verification: panel restructure / glossary combo / native restore.

Phase A: 剪辑面板——空态常驻候选区（分隔+占位）、有候选卡片（证据行整句/
排版）、折叠态；截图到 tmp/shots-round31/。
Phase B: 识别字幕对话框——词库下拉默认不选；截图。
Phase C: FLV 工程——页面 hide→show 循环后原生字幕必须恢复（三十一轮⑦）。
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEDIA_FLV = Path("H:/record/Bilibili/Bilibili/企鹅带带北极熊/2026-09-04 20-05-04 异环新版本！拍卖！.flv")
MEDIA_MP4 = ROOT / "tmp" / "webtest" / "testsrc.mp4"
SHOTS = ROOT / "tmp" / "shots-round31"

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_edit_sequence import HighlightCandidate
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R31H] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)
    return bool(condition)


def prop(page, name, default=None):
    try:
        return page.video.controller.get_property(name, default)
    except (RuntimeError, TypeError):
        return default


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


def shot(widget, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    out = SHOTS / name
    widget.repaint()
    widget.grab().save(str(out))
    print(f"[R31H] shot {out.name}", flush=True)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    project_dir = ROOT / "tmp" / "round31-verify"
    project_dir.mkdir(parents=True, exist_ok=True)

    project = SubtitleProject(
        media=StudioMedia(
            path=str(MEDIA_MP4), duration_ms=40_000, width=1280, height=720,
        ),
        cues=[StudioCue("c0", 1_000, 3_000, "第一句测试"), StudioCue("c1", 5_000, 8_000, "第二句测试")],
    )
    project.validate()
    project_path = project_dir / "panel.2byteproj"
    save_project(project, project_path)

    page = SubtitleStudioPage()
    page.resize(1440, 900)
    page.show()
    app.processEvents()
    page.open_project(str(project_path), skip_dirty_guard=True)
    if not wait_until(
        lambda: page.project is not None and page.video._startup_state == "READY",
        timeout=30.0, app=app,
    ):
        check("project_open_ready", False, f"startup={page.video._startup_state}")
        return finish(app, page)
    check("project_open_ready", True)

    # --- Phase A: 剪辑面板 -------------------------------------------------
    panel = page.highlight_panel
    page.context_drawer.setCurrentWidget(panel) if hasattr(page, "context_drawer") else None
    app.processEvents()
    panel.set_project_status(page.project, "")

    check("A1_empty_candidates_zone", panel.candidates_body.isVisibleTo(panel) and panel.candidates_empty.isVisibleTo(panel))
    shot(panel, "A1-clip-empty.png")

    # 字符串证据回归样例：旧代码会渲染成“弹/幕/高”竖排
    panel.reload_candidates([
        HighlightCandidate(
            "k1", "抢仓血亏名场面", 10_000, 190_000, 0.96,
            reason="弹幕高峰，观众狂笑，主播情绪崩溃，是全场最搞笑最戏剧性的时刻",
            hook="主播为抢一个仓，花二十万道具费，结果血亏，当场崩溃大喊“不应该这样的”",
            danmaku_evidence="弹幕高峰 3 段共 48 条，最热时约为平时的 6.2 倍",
            quotes=["哈哈哈哈哈", "哈哈魔了"],
        ),
    ])
    card = panel.results.itemWidget(panel.results.item(0))
    evidence_labels = [w for w in card.findChildren(object) if w.objectName() == "highlightEvidence"]
    evidence_text = evidence_labels[0].text() if evidence_labels else ""
    check(
        "A2_evidence_single_row",
        "弹幕高峰 3 段共 48 条" in evidence_text and "约为平时的 6.2 倍" in evidence_text,
        f"evidence={evidence_text!r}",
    )
    check("A2_stage_collapsed", not panel.config_body.isVisibleTo(panel) and panel.active_stage() == "candidates")
    shot(panel, "A2-clip-candidate.png")

    panel.config_toggle.click()
    check("A3_settings_expand", panel.config_body.isVisibleTo(panel))
    shot(panel, "A3-clip-settings-open.png")
    panel.config_toggle.click()
    shot(panel, "A4-clip-collapsed.png")
    check("A4_collapsed_zone", panel.candidates_body.isVisibleTo(panel) and not panel.config_body.isVisibleTo(panel))

    # --- Phase B: 识别对话框词库下拉 ---------------------------------------
    page.project.glossary_ids = ["洛克王国世界", "绝区零"]
    page._open_recognition_sheet()
    app.processEvents()
    sheet = getattr(page, "_recognition_sheet", None)
    controls = getattr(page, "_recognition_controls", None)
    if sheet is None or controls is None:
        check("B1_sheet_open", False)
    else:
        combo = controls["glossaries"]
        model = combo.model()
        all_unchecked = all(
            model.item(row).checkState() == Qt.CheckState.Unchecked
            for row in range(combo.count())
        ) if combo.count() else True
        check("B1_glossary_default_none", all_unchecked and combo.count() > 0,
              f"items={combo.count()}")
        shot(sheet, "B1-recognition-glossary.png")
        modal = getattr(page, "_modal_host", None)
        if modal is not None:
            modal.hide_content()
    app.processEvents()

    # --- Phase C: FLV hide/show 后原生字幕恢复 ------------------------------
    if MEDIA_FLV.is_file():
        flv_project = SubtitleProject(
            media=StudioMedia(path=str(MEDIA_FLV), duration_ms=1_756_570, width=2560, height=1440),
            cues=[StudioCue("cue-1", 955_138, 957_138, "这个道具给它展示了")],
        )
        flv_project.validate()
        flv_path = project_dir / "flv-restore.2byteproj"
        save_project(flv_project, flv_path)
        page.close_page()
        page.deleteLater()

        page2 = SubtitleStudioPage()
        page2.resize(1440, 900)
        page2.show()
        app.processEvents()
        page2.open_project(str(flv_path), skip_dirty_guard=True)
        if not wait_until(
            lambda: page2.project is not None and page2.video._startup_state == "READY",
            timeout=40.0, app=app,
        ):
            check("C1_flv_ready", False, f"startup={page2.video._startup_state}")
            return finish(app, page2)
        page2._seek(955.7)
        wait_until(lambda: not prop(page2, "seeking", True), timeout=10.0, app=app)
        QTest.qWait(800)
        before = str(prop(page2, "sub-text", "") or "")
        check("C1_subtitle_before_hide", bool(before), f"sub-text={before!r}")

        page2.hide()
        app.processEvents()
        QTest.qWait(120)
        hidden_vis = bool(prop(page2, "sub-visibility", False))
        page2._ensure_renderer_when_visible(reason="verify_hide_cycle")
        page2.show()
        app.processEvents()
        QTest.qWait(600)
        after = str(prop(page2, "sub-text", "") or "")
        check("C2_subtitle_restored_after_show", bool(after), f"sub-text={after!r} hidden_vis={hidden_vis}")
        return finish(app, page2)
    check("C_skipped", True, "FLV 不在本机，跳过")
    return finish(app, page)


def finish(app, page) -> int:
    try:
        page.close_page()
    except Exception:
        traceback.print_exc()
    ok = all(flag for _, flag, _ in RESULTS)
    print(f"[R31H] summary ok={ok} total={len(RESULTS)}", flush=True)
    app.processEvents()
    QTimer.singleShot(200, app.quit)
    app.exec()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
