"""Headed Windows acceptance for P25.2.11.1 Studio usability corrections."""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p25.2.11.1-usability"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(OUTPUT / "local-app-data")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.studio_project import load_project, save_project
from twobyteasr.studio_qc import SubtitleQCEngine, terminology_from_project
from twobyteasr.studio_review import review_risks_from_qc
from twobyteasr.studio_ui import SubtitlePositionOverlay, SubtitleStudioPage


PROJECT_17 = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\[NOTBAD]星铁4.5前瞻2\[NOTBAD]星铁4.5前瞻2.2byteproj"
PROJECT_220 = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\大饭包 坎德拉\大饭包 坎德拉.2byteproj"


def pump(app: QApplication, seconds: float = 0.1) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


def qc_snapshot(path: Path) -> dict[str, object]:
    project = load_project(path)
    result = SubtitleQCEngine().analyze(project, terminology=terminology_from_project(project))
    risks = review_risks_from_qc(result)
    levels = Counter(row.level for row in risks.values())
    rules = Counter(issue.issue_type for issue in result.issues)
    return {
        "cue_count": len(project.cues),
        "无需检查": levels["confident"],
        "建议确认": levels["suggested"],
        "需要检查": levels["high"],
        "rules": dict(rules),
        "segmentation_only": rules["segmentation_difference"],
        "actual_lexical_disagreement": rules["model_disagreement"],
        "terminology_or_consensus": rules["suspected_word"],
        "low_confidence": rules["low_confidence"],
        "timeline": sum(rules[key] for key in ("overlap", "micro_overlap", "short_gap", "micro_gap")),
    }


def drag_numeric(app: QApplication, control, start, end) -> tuple[float, float, int]:
    control.setValue(start)
    page = control.window().findChild(SubtitleStudioPage)
    if page is None and isinstance(control.window(), SubtitleStudioPage):
        page = control.window()
    page._commit_style_now()
    before_index = page.undo_stack.index()
    editor = control.lineEdit()
    y = max(2, editor.height() // 2)
    pixels = round((end - start) * 4 / float(control.singleStep()))
    QTest.mousePress(editor, Qt.MouseButton.LeftButton, pos=QPoint(6, y))
    QTest.mouseMove(editor, QPoint(6 + pixels, y), delay=30)
    QTest.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=QPoint(6 + pixels, y))
    pump(app)
    result = float(control.value())
    undo_steps = page.undo_stack.index() - before_index
    page.undo_stack.undo()
    restored = float(control.value())
    return result, restored, undo_steps


def main() -> int:
    for source in (PROJECT_17, PROJECT_220):
        if not source.is_file():
            raise FileNotFoundError(source)
    app = QApplication.instance() or QApplication(sys.argv)
    project_dir = OUTPUT / "projects"
    project_dir.mkdir(parents=True, exist_ok=True)
    source_project = load_project(PROJECT_220)
    project_paths = []
    for index in range(5):
        folder = project_dir / f"recent-{index + 1}"
        folder.mkdir(parents=True, exist_ok=True)
        clone = copy.deepcopy(source_project)
        clone.project_id = f"p252111recent{index + 1:02d}"
        target = save_project(clone, folder / f"大饭包 坎德拉 {index + 1}.2byteproj")
        project_paths.append(target)

    page = SubtitleStudioPage()
    page.resize(1600, 960)
    page.show()
    page.activateWindow()
    page.open_project(project_paths[0])
    pump(app, 1.5)

    cue = page.project.cues[0]
    cue.text = "太赖了"
    cue.evidence_refs = ["acceptance-four"]
    page.project.asr_evidence = {"acceptance-four": {
        "moss_text": "太赖了", "firered_text": "太烂了",
        "qwen_asr_text": "太累了", "alternate_text": "太快了",
    }}
    page._refresh_review_risks()
    page.select_cue(cue.id)
    page._set_review_mode(True)
    pump(app)
    four_candidates = len(page._review_candidates)
    four_shot = OUTPUT / "four-candidates.png"
    page.review_summary_strip.grab().save(str(four_shot))
    cards = [
        page.review_dock_candidate_layout.itemAt(index).widget()
        for index in range(page.review_dock_candidate_layout.count())
        if page.review_dock_candidate_layout.itemAt(index).widget() is not None
    ]
    cards_visible = sum(widget.isVisible() for widget in cards)

    page.open_project(project_paths[0])
    page._set_review_mode(True)
    page.activateWindow()
    page.timeline.setFocus()
    pump(app)
    processed = []
    for index in range(20):
        if not page.selected_cue_id or not page.cue_model.rowCount():
            break
        processed.append(page.selected_cue_id)
        page.timeline.setFocus()
        if index in {4, 11}:
            QTest.keyClick(page, Qt.Key.Key_Space)
            pump(app, 0.03)
        if index == 8:
            QTest.keyClick(page, Qt.Key.Key_Down)
            QTest.keyClick(page, Qt.Key.Key_Up)
        if index in {6, 13}:
            QTest.keyClick(page, Qt.Key.Key_E)
            pump(app)
            editor = getattr(page, "_canvas_editor", None)
            if editor is None:
                raise RuntimeError("E did not open the inline editor")
            editor.setPlainText(editor.toPlainText() + "。")
            QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        elif page._review_candidates:
            QTest.keyClick(page, Qt.Key.Key_1)
        else:
            QTest.keyClick(page, Qt.Key.Key_Return)
        pump(app)

    page._set_review_mode(False)
    page.style_scope.setCurrentIndex(page.style_scope.findData("current"))
    scrub = {
        "font_size": drag_numeric(app, page.style_font_size, 48, 96),
        "outline": drag_numeric(app, page.style_outline_width, 2.0, 4.0),
        "letter_spacing": drag_numeric(app, page.style_spacing, 0, 10),
    }
    page.undo_stack.clear()
    page.select_cue(page.project.cues[0].id)
    page.project.cues[0].text = "哦那再来一把吧"
    texts_before = [item.text for item in page.project.cues]
    for preset_id in ("default", "clean-white", "game", "livestream", "dialogue-a"):
        page.style_preset.setCurrentIndex(page.style_preset.findData(preset_id))
        page._apply_style()
    preset_text_preserved = texts_before == [item.text for item in page.project.cues]

    pump(app)
    overlay_focus_states = {
        "before": {
            "active_window_is_studio": QApplication.activeWindow() is page.window(),
            "host_active": page.window().isActiveWindow(),
            "source_visible": page.position_overlay.isVisible(),
        }
    }
    overlay_before = page.position_overlay_visual.isVisible()
    other = QWidget()
    other.setWindowTitle("P25.2.11.1 focus probe")
    other.resize(400, 240)
    other.show()
    other.activateWindow()
    pump(app, 0.2)
    overlay_focus_states["inactive"] = {
        "active_window_is_probe": QApplication.activeWindow() is other,
        "host_active": page.window().isActiveWindow(),
        "source_visible": page.position_overlay.isVisible(),
    }
    overlay_while_inactive = page.position_overlay_visual.isVisible()
    other.close()
    page.window().show()
    page.window().raise_()
    page.window().activateWindow()
    page.window().windowHandle().requestActivate()
    pump(app, 0.5)
    overlay_focus_states["after"] = {
        "active_window_is_studio": QApplication.activeWindow() is page.window(),
        "host_active": page.window().isActiveWindow(),
        "source_visible": page.position_overlay.isVisible(),
    }
    overlay_after = page.position_overlay_visual.isVisible()

    normal_geometry = page.window().geometry()
    QTest.mouseDClick(page.filename, Qt.MouseButton.LeftButton, pos=page.filename.rect().center())
    pump(app)
    maximized_by_double_click = page.window().isMaximized()
    QTest.mouseDClick(page.filename, Qt.MouseButton.LeftButton, pos=page.filename.rect().center())
    pump(app)
    restored_by_double_click = not page.window().isMaximized()

    controller = page.video.controller
    mpv = {}
    if controller is not None:
        for name in ("pause", "video-format", "aid", "sid"):
            try:
                mpv[name] = controller.get_property(name)
            except RuntimeError as exc:
                mpv[name] = {"unavailable": str(exc)}

    for path in project_paths[1:]:
        page.open_project(path)
        pump(app, 0.25)
    records = page.recent_project_records()
    page.show_project_hub()
    page.resize(1600, 960)
    pump(app)
    hub_shot = OUTPUT / "project-hub-five-covers.png"
    page.grab().save(str(hub_shot))
    covers = [record.get("cover_path", "") for record in records[:5]]

    report = {
        "qc": {"17_cue": qc_snapshot(PROJECT_17), "220_cue": qc_snapshot(PROJECT_220)},
        "review": {"processed": len(processed), "unique": len(set(processed)), "cue_ids": processed, "four_candidates": four_candidates, "visible_card_widgets": cards_visible},
        "scrub": scrub,
        "preset_text_preserved": preset_text_preserved,
        "project_hub": {"recent_count": len(records), "covers_existing": sum(Path(path).is_file() for path in covers), "screenshot": str(hub_shot)},
        "window": {"normal_geometry": [normal_geometry.x(), normal_geometry.y(), normal_geometry.width(), normal_geometry.height()], "maximize_double_click": maximized_by_double_click, "restore_double_click": restored_by_double_click},
        "overlay": {"before": overlay_before, "inactive": overlay_while_inactive, "after": overlay_after, "interaction_count": len(page.findChildren(SubtitlePositionOverlay)), "focus_states": overlay_focus_states},
        "mpv": mpv,
        "four_candidates_screenshot": str(four_shot),
    }
    report_path = OUTPUT / "acceptance-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    page.close_page()
    page.close()
    app.quit()
    passed = (
        report["review"]["processed"] >= 20
        and four_candidates == 4 and cards_visible >= 4
        and all(round(values[0], 2) == target for values, target in zip(scrub.values(), (96, 4, 10)))
        and preset_text_preserved and report["project_hub"]["covers_existing"] == 5
        and overlay_before and not overlay_while_inactive and overlay_after
        and maximized_by_double_click and restored_by_double_click
        and mpv.get("video-format") and mpv.get("sid") not in {None, False, "no"}
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
