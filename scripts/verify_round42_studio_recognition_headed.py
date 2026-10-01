"""R42 headed verification: 识别弹窗方案/二级选择/词库/后台芯片。

Phase A（独立 Studio 页）：识别弹窗——方案下拉含 API 转写、切 API 后三组合
api/off/api、词库真实点击后摘要正确、三行"选择…"按钮存在；截图。
Phase B（真 MainWindow）：识别弹窗 →"选择…"打开主页同款模型选择弹窗（二级），
关闭后回到识别弹窗并同步选择；截图。
Phase C（后台化）：dispatch(start_analysis) → 弹窗关闭、左侧字幕列表芯片
"识别中 · 准备模型 · mm:ss"+取消按钮可见，视频面板不被模态遮罩盖住；截图。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEDIA_MP4 = ROOT / "tmp" / "webtest" / "testsrc.mp4"
SHOTS = ROOT / "tmp" / "shots-round42"

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R42H] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)
    return bool(condition)


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
    print(f"[R42H] shot {out.name}", flush=True)


def _open_sheet(page, project_dir: Path) -> dict:
    media = project_dir / "recognition.flv"
    media.write_bytes(b"fixture")
    page.project.media.path = str(media)
    page.project.glossary_ids = ["洛克王国世界", "全局记忆"]
    page.project_path = project_dir / "recognition.2byteproj"
    page._open_recognition_sheet()
    return page._recognition_controls


def phase_a(app: QApplication, project_dir: Path) -> SubtitleStudioPage:
    project = SubtitleProject(
        media=StudioMedia(path=str(MEDIA_MP4), duration_ms=40_000, width=1280, height=720),
        cues=[StudioCue("c0", 1_000, 3_000, "第一句测试"), StudioCue("c1", 5_000, 8_000, "第二句测试")],
    )
    project.validate()
    save_project(project, project_dir / "panel.2byteproj")
    print("[R42H] phase A: project saved", flush=True)
    page = SubtitleStudioPage()
    page.resize(1440, 900)
    page.show()
    app.processEvents()
    page.open_project(str(project_dir / "panel.2byteproj"), skip_dirty_guard=True)
    wait_until(lambda: page.project is not None and page.video._startup_state == "READY", timeout=30.0, app=app)

    controls = _open_sheet(page, project_dir)
    plan = controls["plan"]
    keys = [plan.itemData(i) for i in range(plan.count())]
    check("A1_plan_options_full", {"api", "low_memory", "transcribe_only"} <= set(keys), f"keys={keys}")
    shot(page._recognition_sheet, "A1-sheet-default.png")

    plan.setCurrentIndex(plan.findData("api"))
    app.processEvents()
    check(
        "A2_api_plan_applies",
        controls["primary"].currentData() == "api"
        and controls["timeline"].currentData() == "off"
        and controls["review"].currentData() == "api",
        f"{controls['primary'].currentData()}/{controls['timeline'].currentData()}/{controls['review'].currentData()}",
    )
    advanced = controls["advanced"]
    advanced.setVisible(True)
    app.processEvents()
    picker_buttons = [b for b in advanced.findChildren(QPushButton) if b.text() == "选择…"]
    check("A2_picker_buttons", len(picker_buttons) == 3)
    shot(advanced, "A2-advanced-api.png")

    # 词库：真实点击（QTest 视图点击）→ 勾选 + 摘要同步（四十二轮根因修复）。
    combo = controls["glossaries"]
    model = combo.model()
    combo.showPopup()
    view = combo.view()
    rect = view.visualRect(model.index(0, 0))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
    app.processEvents()
    summary = next(
        (label for label in page._recognition_sheet.findChildren(QLabel) if label.text().startswith(("已选", "未选择词库"))),
        None,
    )
    check(
        "A3_glossary_summary_syncs",
        model.item(0).checkState() == Qt.CheckState.Checked
        and summary is not None
        and summary.text().startswith("已选 1 个词库"),
        f"state={model.item(0).checkState()} summary={summary.text() if summary else None!r}",
    )
    glossary_card = combo.parentWidget()
    shot(glossary_card, "A3-glossary-checked.png")
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
    controls = _open_sheet(win.studio_page, project_dir)
    advanced = controls["advanced"]
    advanced.setVisible(True)
    app.processEvents()
    picker_button = next(b for b in advanced.findChildren(QPushButton) if b.text() == "选择…")
    picker_button.click()
    app.processEvents()
    wait_until(lambda: win._modal_host.isVisible(), timeout=5.0, app=app)
    picker = getattr(win, "_model_picker_primary_panel", None)
    visible = win._modal_host.isVisible() and picker is not None and picker.isVisibleTo(win._modal_host)
    check("B1_picker_opens_over_sheet", visible)
    shot(win._modal_host.card, "B1-model-picker.png")

    done = next((b for b in (picker.findChildren(QPushButton) if picker else []) if b.text() == "完成"), None)
    if done is not None:
        done.click()
    app.processEvents()
    restored = wait_until(
        lambda: win._modal_host.isVisible() and win.studio_page._recognition_sheet.isVisibleTo(win._modal_host),
        timeout=5.0, app=app,
    )
    check("B2_sheet_restored_after_picker", restored)
    shot(win._modal_host.card, "B2-sheet-restored.png")
    win._modal_host.hide_content()
    app.processEvents()
    win.deleteLater()
    app.processEvents()


def phase_c(app: QApplication, page: SubtitleStudioPage):
    controls = page._recognition_controls
    emitted = []
    page.recognition_requested.connect(lambda action, media, project: emitted.append(action))
    controls["start"].click()
    app.processEvents()
    chip = page.recognition_chip
    check(
        "C1_chip_running",
        emitted == ["start_analysis"]
        and page._recognition_running
        and chip.isVisibleTo(chip.parentWidget())
        and page.recognition_chip_label.text().startswith("识别中 · 准备模型")
        and page.recognition_cancel_button.isVisibleTo(chip),
        f"text={page.recognition_chip_label.text()!r}",
    )
    page.set_recognition_runtime_stage("识别中", "在线 ASR API 主力转写")
    app.processEvents()
    shot(chip, "C1-chip-running.png")
    # 视频区可交互（无模态遮罩）：字幕列表整列截图。
    shot(page.cue_list_panel, "C2-cue-list-with-chip.png")
    page.fail_recognition_runtime("测试收尾")
    check(
        "C3_chip_fail_state",
        page.recognition_chip_label.text() == "识别未完成 · 测试收尾"
        and not page.recognition_cancel_button.isVisibleTo(chip),
        f"text={page.recognition_chip_label.text()!r}",
    )
    shot(chip, "C3-chip-failed.png")


def finish(app: QApplication, page: SubtitleStudioPage | None) -> int:
    if page is not None:
        try:
            page.close_page()
        except Exception:
            pass
    failures = [item for item in RESULTS if not item[1]]
    print("\n[R42H] ===== summary =====", flush=True)
    for label, ok, detail in RESULTS:
        print(f"[R42H] {'PASS' if ok else 'FAIL'} {label} {detail}", flush=True)
    print(f"[R42H] {len(RESULTS) - len(failures)}/{len(RESULTS)} passed", flush=True)
    return 1 if failures else 0


def main() -> int:
    app = QApplication.instance() or QApplication([])
    project_dir = ROOT / "tmp" / "round42-verify"
    project_dir.mkdir(parents=True, exist_ok=True)
    page = None
    try:
        page = phase_a(app, project_dir)
        phase_b(app, project_dir)
        phase_c(app, page)
    except Exception:
        traceback = __import__("traceback").format_exc()
        print(f"[R42H] EXCEPTION\n{traceback}", flush=True)
        check("no_exception", False, traceback.splitlines()[-1])
    return finish(app, page)


if __name__ == "__main__":
    raise SystemExit(main())
