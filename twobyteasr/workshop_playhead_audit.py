"""Bounded normal-entry UI audit on a synthetic, isolated project."""
import json
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea


def start(window, out):
    def run():
        page = window.studio_page
        report = {"passed": False, "checks": {}, "notifications": []}

        def pump(seconds=.1):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                QApplication.processEvents()
                time.sleep(.005)

        def wait(predicate, timeout=45):
            end = time.monotonic() + timeout
            while not predicate() and time.monotonic() < end:
                pump(.03)
            if not predicate():
                raise AssertionError("runtime wait timed out")

        def check(name, condition):
            report["checks"][name] = bool(condition)
            if not condition:
                raise AssertionError(name)

        def key(code):
            page.timeline.setFocus()
            QTest.keyClick(page.timeline, code)
            pump(.08)

        def capture(name):
            window.grab().save(str(out / f"{name}.png"))

        try:
            from .build_identity import load_build_identity
            report["build"] = load_build_identity().to_dict()
            wait(lambda: page.project is not None and page._readiness.ready)
            window.resize(1460, 930)
            window.show()
            window.activateWindow()
            page._set_volume(0)
            page.video.set_paused(True)
            page._seek(.2)
            pump(.3)
            page.select_cue("old")
            key(Qt.Key_Space)
            wait(lambda: page.video.playback_position_snapshot().presentation_media_ms > 1450, 8)
            check("selection_remains_old_during_playback", page.selected_cue_id == "old")
            key(Qt.Key_E)
            wait(lambda: getattr(page, "_canvas_editor", None) is not None, 3)
            check("E_edits_playhead_cue", page.selected_cue_id == "now")
            check("E_pauses", page.video.playback_position_snapshot().paused)
            check("editor_contains_current_text", page.subtitle_edit_input.toPlainText() == "当前播放头字幕")
            capture("studio-e-current")
            page.subtitle_edit_input.setPlainText("当前字幕已修改")
            QTest.keyClick(page.subtitle_edit_input, Qt.Key_Return)
            pump(.2)
            check("edited_current_only", page.project.cues[0].text == "之前选中的字幕" and page.project.cues[1].text == "当前字幕已修改")
            page.undo_stack.undo()
            check("undo_restores_current", page.project.cues[1].text == "当前播放头字幕")
            page._seek(4.5)
            pump(.4)
            key(Qt.Key_E)
            check("gap_does_not_edit_old", getattr(page, "_canvas_editor", None) is None)
            check("gap_shows_reason", "没有字幕" in page.save_state.text())

            window._open_model_workshop()
            workshop = window.workshop_page
            pump(.2)
            from .theme_manager import apply_theme
            from .model_workshop import build_workshop_qss
            for theme in ("warm", "plum"):
                apply_theme(theme)
                workshop.setStyleSheet(build_workshop_qss())
                for model_key, role in (("firered", "primary"), ("qwen_aligner", "timeline"),
                                        ("moss", "primary"), ("canary_qwen", "primary"),
                                        ("omni_asr_llm_7b", "primary")):
                    workshop._set_role(role)
                    workshop.search.setText(workshop._cards[model_key].model.name)
                    workshop._view_model(model_key)
                    pump(.15)
                    capture(f"workshop-{theme}-{model_key}")
                    card = workshop._cards[model_key]
                    check(f"{theme}_{model_key}_card_visible", card.isVisible())
                    check(f"{theme}_{model_key}_summary_fits", card.summary_label.height() >= card.summary_label.heightForWidth(card.summary_label.width()))
                    bar = card.accuracy_bar
                    if model_key == "qwen_aligner":
                        check(f"{theme}_aligner_semantics", bar._caption.text() == "对齐精度" and "不能独立转写" in workshop.detail_workflow.text())
                    if model_key == "canary_qwen":
                        check(f"{theme}_english_explicit", bar._caption.text() == "英语转写准确度" and "不支持中文" in workshop.detail_workflow.text())
                    if model_key == "omni_asr_llm_7b":
                        check(f"{theme}_unknown_has_no_empty_track", bar._track.isHidden() and "暂无" in bar._word.text())
                # A shorter window must keep bottom actions reachable by scrolling.
                window.resize(1280, 760)
                pump(.2)
                report.setdefault("window_sizes", {})[theme] = {"requested": [1280, 760], "actual": [window.width(), window.height()]}
                check(f"{theme}_evidence_survives_resize", workshop.capability_rows[0]._note._full_text == workshop.capability_rows[0]._evidence["note"])
                scroller = next(s for s in workshop.findChildren(QScrollArea) if s.widget() is workshop.detail)
                scroller.ensureWidgetVisible(workshop.detail_action)
                pump(.1)
                check(f"{theme}_detail_action_reachable", scroller.viewport().rect().intersects(workshop.detail_action.rect().translated(workshop.detail_action.mapTo(scroller.viewport(), workshop.detail_action.rect().topLeft()))))
                capture(f"workshop-{theme}-compact")
                window.resize(1460, 930)
            workshop.search.clear()
            window.pages.setCurrentWidget(page)
            pump(.3)

            from . import export_notification
            original = export_notification.notify_export_completed
            def notify(parent, path):
                report["notifications"].append(str(path))
                original(parent, path)
            export_notification.notify_export_completed = notify
            QTest.mouseClick(page.studio_render_button, Qt.LeftButton)
            wait(lambda: page.export_workspace is not None)
            ui = page.export_workspace
            ui.directory.setText(str(out / "exports"))
            ui.filename.setText("完成提醒验证")
            ui.filename_prefix.clear()
            ui.filename_suffix.clear()
            if ui.encoder.findData("libx264") < 0:
                ui.encoder.addItem("Software x264", "libx264")
            ui.encoder.setCurrentIndex(ui.encoder.findData("libx264"))
            QTest.mouseClick(ui.export_button, Qt.LeftButton)
            wait(lambda: ui.pages.currentWidget() in (ui.success_page, ui.failure_page), 90)
            check("production_export_succeeded", ui.pages.currentWidget() is ui.success_page)
            check("completion_notified_once", len(report["notifications"]) == 1)
            check("output_published", Path(ui._last_job.output_path).is_file())
            report["receipt"] = ui._last_job.completion_metadata
            report["output"] = str(ui._last_job.output_path)
            pump(.4)
            capture("export-completed")
            ui._show_success(ui._last_job.output_path)
            check("repeated_receipt_does_not_notify", len(report["notifications"]) == 1)
            report["passed"] = True
        except Exception:
            report["error"] = traceback.format_exc()
            capture("failure")
        finally:
            (out / "runtime.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            window.close()
    QTimer.singleShot(300, run)
