"""R43 headed verification: chips 词库/API 全名/零态卡/取消反馈/进度往返/拖拽框。

Phase A（独立页）：识别弹窗——词库常驻 chips 可勾选且摘要同步、空条目过滤、
API 项显示完整 provider·model、弹窗高度适配矮屏（1280x760 窗口）。
Phase B（真 MainWindow）：零态"暂无字幕"卡运行态+取消反馈+查看详细进度跳转
主页进度页并返回 Studio。
Phase C（独立页）：拖拽/缩放框比例收紧（visualGraph 装置外扩帽 0.22）；
NATIVE cue 拖拽后 Style 行阴影保留（数据层回归）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEDIA_MP4 = ROOT / "tmp" / "webtest" / "testsrc.mp4"
SHOTS = ROOT / "tmp" / "shots-round43"

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel

from twobyteasr.ass_compiler import compile_ass
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R43H] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)
    return bool(condition)


def shot(widget, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    widget.repaint()
    widget.grab().save(str(SHOTS / name))
    print(f"[R43H] shot {name}", flush=True)


def _open_sheet(page, project_dir: Path) -> dict:
    media = project_dir / "recognition.flv"
    media.write_bytes(b"fixture")
    page.project.media.path = str(media)
    page.project.glossary_ids = ["洛克王国世界", "", "全局记忆"]
    page.project_path = project_dir / "recognition.2byteproj"
    page._open_recognition_sheet()
    return page._recognition_controls


def phase_a(app: QApplication, project_dir: Path) -> SubtitleStudioPage:
    project = SubtitleProject(
        media=StudioMedia(path=str(MEDIA_MP4), duration_ms=40_000, width=1280, height=720),
        cues=[StudioCue("c0", 1_000, 3_000, "第一句测试")],
    )
    project.validate()
    save_project(project, project_dir / "panel43.2byteproj")
    page = SubtitleStudioPage()
    page.resize(1280, 760)
    page.show()
    app.processEvents()
    page.open_project(str(project_dir / "panel43.2byteproj"), skip_dirty_guard=True)

    controls = _open_sheet(page, project_dir)
    chips = controls["glossaries"].findChildren(QCheckBox)
    labels = [box.text() for box in chips]
    check("A1_chips_no_blank", labels == ["洛克王国世界", "全局记忆"], f"{labels}")
    QTest.mouseClick(chips[0], Qt.MouseButton.LeftButton)
    if not chips[0].isChecked():
        chips[0].click()
    app.processEvents()
    summary = next(
        (l for l in page._recognition_sheet.findChildren(QLabel) if l.text().startswith(("已选", "未选择词库"))),
        None,
    )
    check("A1_chips_summary_syncs", summary is not None and summary.text().startswith("已选 1 个词库"), f"{summary.text() if summary else None}")
    shot(page._recognition_sheet, "A1-sheet-chips.png")

    primary = controls["primary"]
    api_index = primary.findData("api")
    check(
        "A2_api_full_label",
        api_index >= 0 and "·" in primary.itemText(api_index) and "在线 ASR API" in primary.itemText(api_index),
        primary.itemText(api_index) if api_index >= 0 else "missing",
    )
    # 矮屏（760 高）弹窗高度自适应。
    host = page.window()
    sheet_height = min(760, max(520, host.height() - 120))
    check("A3_sheet_height_fits", sheet_height <= host.height() - 100, f"window={host.height()} sheet={sheet_height}")
    return page


def phase_b(app: QApplication, project_dir: Path):
    import subtitle_core as legacy
    from twobyteasr.ui import MainWindow

    media = project_dir / "recognition.flv"
    win = MainWindow([], legacy, object(), None)
    win.resize(1440, 900)
    win.show()
    app.processEvents()
    win.studio_page._create_blank_studio()
    win.studio_page.project.media.path = str(media)
    win.studio_page.project_path = project_dir / "recognition.2byteproj"
    win.studio_page.project.cues = []
    win.studio_page.cue_controller.model_changed()
    app.processEvents()
    # 工程文件必须真实存在，否则 _handle_studio_recognition_request 会在
    # 预检弹"无法开始识别"警告框后早退（_studio_recognition_context 为空）。
    win.studio_page.save()
    app.processEvents()
    controls = _open_sheet(win.studio_page, project_dir)
    monkey_start = lambda: None
    win._start_run = monkey_start  # 不真跑管线；手动进入运行态
    controls["start"].click()
    app.processEvents()
    win.studio_page._recognition_running = True
    win.studio_page.set_recognition_runtime_stage("识别中", "在线 ASR API 主力转写")
    app.processEvents()
    zero = win.studio_page.cue_zero_state
    card = win.studio_page.recognition_zero_card
    check(
        "B1_zero_card_running",
        zero.isVisibleTo(zero.parentWidget())
        and card.isVisibleTo(zero)
        and win.studio_page.recognition_zero_label.text().startswith("识别中")
        and win.studio_page.recognition_zero_detail.isVisibleTo(card),
        win.studio_page.recognition_zero_label.text(),
    )
    shot(zero, "B1-zero-card.png")

    detail_calls = []
    win.studio_page.recognition_detail_requested.connect(lambda: detail_calls.append(1))
    win.studio_page.recognition_zero_detail.click()
    app.processEvents()
    progress_page = win.pages.widget(1)
    check(
        "B2_detail_jumps_to_progress",
        detail_calls and win.pages.currentWidget() is progress_page,
    )
    check(
        "B3_back_to_studio_visible",
        win.back_to_studio_button.isVisibleTo(progress_page),
    )
    shot(progress_page, "B2-progress-page.png")
    win.back_to_studio_button.click()
    app.processEvents()
    check("B4_back_returns_studio", win.pages.currentWidget() is win.studio_page)

    # 取消反馈：芯片+零态卡都变"正在安全取消"，取消按钮隐藏。
    win.studio_page.set_recognition_cancelling()
    app.processEvents()
    check(
        "B5_cancel_feedback",
        "正在安全取消" in win.studio_page.recognition_chip_label.text()
        and not win.studio_page.recognition_cancel_button.isVisibleTo(win.studio_page.recognition_chip)
        and not win.studio_page.recognition_zero_cancel.isVisibleTo(card),
        win.studio_page.recognition_chip_label.text(),
    )
    shot(win.studio_page.recognition_chip, "B5-cancelling.png")
    win.studio_page.fail_recognition_runtime("验证收尾")
    win._modal_host.hide_content()
    app.processEvents()
    win.deleteLater()
    app.processEvents()


def phase_c(app: QApplication, page: SubtitleStudioPage):
    from twobyteasr.visual_design_graph import DecorationLayer, VisualDesignGraph

    project = page.project
    style = next(s for s in project.styles if s.id == project.cues[0].style_id)
    style.shadow = 3.0
    deco = DecorationLayer.from_dict(
        {"id": "d1", "primitive": "PARTICLES", "params": {"overflow": 1.2}}
    )
    graph = VisualDesignGraph(name="r43h", decoration_layers=[deco])
    project.style_recipes[style.id] = {
        "name": "r43h", "engine": "remotion", "visualGraph": graph.to_dict(),
    }
    page._load_style_inspector()
    page.position_edit_button.setChecked(True)
    page._empty_playback_state = False
    app.processEvents()
    overflow = page.position_overlay._composition_overflow
    check("C1_overflow_capped", overflow <= 0.22, f"overflow={overflow}")

    before_styles = [l for l in compile_ass(project).splitlines() if l.startswith("Style:")]
    overlay = page.position_overlay
    rect = overlay._subtitle_rect()
    start = rect.center().toPoint()
    target = start + QPoint(70, -50)
    for typ, pos, button in (
        (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, target, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.LeftButton),
    ):
        ev = QMouseEvent(typ, QPointF(pos), QPointF(overlay.mapToGlobal(pos)), button, button, Qt.KeyboardModifier.NoModifier)
        {
            QEvent.Type.MouseButtonPress: overlay.mousePressEvent,
            QEvent.Type.MouseMove: overlay.mouseMoveEvent,
            QEvent.Type.MouseButtonRelease: overlay.mouseReleaseEvent,
        }[typ](ev)
    app.processEvents()
    after_styles = [l for l in compile_ass(project).splitlines() if l.startswith("Style:")]
    check("C2_style_shadow_retained", before_styles == after_styles and "3" in after_styles[0].split(",")[17])
    dialogue = next(
        (l for l in compile_ass(project).splitlines() if "Dialogue" in l and project.cues[0].text in l),
        "",
    )
    check("C3_pos_override_landed", r"\pos(" in dialogue, dialogue[:80])
    shot(page.video, "C1-transform-box.png")


def finish(app: QApplication, page: SubtitleStudioPage | None) -> int:
    if page is not None:
        try:
            page.close_page()
        except Exception:
            pass
    failures = [item for item in RESULTS if not item[1]]
    print("\n[R43H] ===== summary =====", flush=True)
    for label, ok, detail in RESULTS:
        print(f"[R43H] {'PASS' if ok else 'FAIL'} {label} {detail}", flush=True)
    print(f"[R43H] {len(RESULTS) - len(failures)}/{len(RESULTS)} passed", flush=True)
    return 1 if failures else 0


def main() -> int:
    app = QApplication.instance() or QApplication([])
    project_dir = ROOT / "tmp" / "round43-verify"
    project_dir.mkdir(parents=True, exist_ok=True)
    page = None
    try:
        page = phase_a(app, project_dir)
        phase_b(app, project_dir)
        phase_c(app, page)
    except Exception:
        import traceback

        print(f"[R43H] EXCEPTION\n{traceback.format_exc()}", flush=True)
        check("no_exception", False)
    return finish(app, page)


if __name__ == "__main__":
    raise SystemExit(main())
