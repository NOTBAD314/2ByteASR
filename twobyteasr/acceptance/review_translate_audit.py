"""Opt-in acceptance (2026-10-27): English review false conflict and locating failed translations.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=review-translate`` against a
copied project (scripts/verify_review_translate_headed.py). The normal
MainWindow opens the copy; no provider is called.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback

from .studio_acceptance_audit import require


def run(output, window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..subtitle_rules import subtitle_translation as st
    from ..subtitle_rules.studio_review import cached_qc_result
    from ..studio.studio_cards import ReviewCandidateCard
    from .blank_project_audit import _capture
    from . import blank_project_audit

    output = Path(output)
    require(Path(os.environ["TWOBYTEASR_TEST_ROOT"]).resolve() == output.resolve())
    result = {"passed": False, "checks": [], "screenshots": [], "pid": os.getpid(),
              "entry": "quick_start.py normal MainWindow", "executable": sys.executable,
              "platform": QApplication.platformName(), "frozen": bool(getattr(sys, "frozen", False))}
    page = window.studio_page

    def receipt():
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(name, condition, detail=None):
        result["checks"].append({"name": name, "passed": bool(condition), "detail": detail})
        receipt()
        require(condition, name)

    def wait(predicate, message, seconds=60):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(50)
        require(predicate(), message)

    def capture(name, widget=None):
        QTest.qWait(200)
        path = output / (name + ".png")
        if widget is None:
            _capture(window, path)
        else:
            require(widget.grab().save(str(path)), "grab " + name)
        result["screenshots"].append(str(path))
        receipt()

    try:
        window.open_studio_project(os.environ["TWOBYTEASR_STARTUP_PROJECT"], mode="edit", source="review_translate_audit")
        wait(lambda: page.project is not None and getattr(page, "_readiness", None) and page._readiness.ready,
             "real project did not become ready")
        window.resize(1600, 1000)
        window.show()
        QApplication.setActiveWindow(window)
        page.video.set_paused(True)  # open_studio_project starts playback
        project = page.project

        # 1. The cue that showed "模型对「…」存在分歧" for an identical caption.
        review_id = os.environ.get("TWOBYTEASR_REVIEW_CUE", "135")
        cue = next(cue for cue in project.cues if cue.id == review_id)
        # The workbench scans QC in the background after opening.
        wait(lambda: getattr(project, "_qc_result", None) is not None, "background QC did not finish", 120)
        from ..recognition.asr_source_evidence import cue_source_hypotheses
        issues = [issue.issue_type for issue in cached_qc_result(project).for_cue(cue.id)]
        hypotheses = cue_source_hypotheses(project, cue)
        result["review_cue"] = {"id": cue.id, "text": cue.text, "issues": issues,
                                "domain": project.render_settings.get("_cue_domain"),
                                "evidence_refs": list(cue.evidence_refs),
                                "refs_present": [ref in project.asr_evidence for ref in cue.evidence_refs],
                                "receipt_keys": sorted(((project.studio_state.get("caption_timeline") or {})
                                                        .get("instances") or {}).get(cue.id, {}).keys()),
                                "hypotheses": [(row["model"], row["reference"], row["text"]) for row in hypotheses]}
        receipt()
        check("qc_ran_for_cue", bool(issues), issues)
        check("no_model_disagreement", "model_disagreement" not in issues, issues)
        page._set_review_mode(True)
        page._go_to_listed_cue(next(c for c in page._cue_jump_order if c.id == cue.id))
        page._refresh_review_summary_strip()
        QTest.qWait(400)
        cards = [widget for widget in page.findChildren(ReviewCandidateCard) if widget.isVisible()]
        result["review_strip"] = {"summary": page.review_summary_text.text(), "reason": page.review_reason_label.text(),
                                  "visible_cards": len(cards)}
        check("review_reason_has_no_conflict", "分歧" not in page.review_reason_label.text(), result["review_strip"])
        check("review_has_no_choice_cards", len(cards) <= 1, result["review_strip"])
        capture("01-review-strip")
        page._set_review_mode(False)

        # 2. Failed translations found from the dialog: the copy's own, else one injected.
        target = (project.generation_metadata.get("translation_records") or {}).get("target") or "zh-Hans"
        failed_ids = st.ids_with_status(project, {"failed"}, target=target)
        result["real_failures"] = len(failed_ids)
        if not failed_ids:
            failed_id = os.environ.get("TWOBYTEASR_FAILED_CUE", "400")
            # A failed retry keeps an existing good translation: make this a
            # line that was never translated, then fail it the normal way.
            st.migrate(project)
            st.records_of(project).pop(failed_id, None)
            (project.generation_metadata.get("translations") or {}).pop(failed_id, None)
            st.apply_translation_result(project, st.TranslationResult(
                target=target, model="fixture", provider="fixture", failed={failed_id: "english_output"},
                sources={failed_id: next(cue.text for cue in project.cues if cue.id == failed_id)}))
            failed_ids = [failed_id]
            result["injected"] = {"record": {k: v for k, v in st.records_of(project)[failed_id].items() if k != "previous"},
                                  "status": st.cue_status(project, failed_id, target=target),
                                  "same_project": page.project is project}
            receipt()
        page.select_cue(project.cues[0].id)
        page._seek(project.cues[0].start_ms / 1000)
        page._activate_filter("critical")
        QTest.qWait(400)
        page._open_translation_dialog()
        dialog = page._translation_dialog
        wait(lambda: dialog is not None and dialog.isVisible(), "translation dialog did not open")
        if "injected" in result:
            record = st.records_of(dialog.project).get(failed_ids[0]) or {}
            result["injected"]["after_open"] = {k: v for k, v in record.items() if k != "previous"}
            result["injected"]["dialog_same_project"] = dialog.project is project
            receipt()
        numbers = [page._cue_jump_index[cue_id] + 1 for cue_id in failed_ids]
        result["dialog"] = {"counts": dialog.counts.text(), "failed_note": dialog.failed_note.text(),
                            "button": dialog.locate_failed_button.text(), "list_numbers": numbers,
                            "errors": [st.records_of(project)[cue_id].get("error") for cue_id in failed_ids]}
        check("counts_match", dialog.counts.text().endswith(f"失败 {len(failed_ids)}"), result["dialog"])
        check("failed_line_names_cues", dialog.failed_note.text().startswith("失败的字幕：")
              and all(f"#{number} " in dialog.failed_note.text() for number in numbers[:3]), result["dialog"])
        check("locate_button_shown", dialog.locate_failed_button.isVisible())
        capture("02-dialog-before", dialog)
        result["located"] = []
        for step, failed_id in enumerate(failed_ids[:2]):
            failed = next(cue for cue in project.cues if cue.id == failed_id)
            QTest.mouseClick(dialog.locate_failed_button, Qt.MouseButton.LeftButton)
            scroll_at_click = page.cue_table.verticalScrollBar().value()
            wait(lambda: page.selected_cue_id == failed_id, f"locate {step + 1} did not select {failed_id}", 10)
            QTest.qWait(600)
            row = page.cue_model.row_for_cue_id(failed_id)
            playhead = int(page.timeline.playhead_ms)
            located = {"cue": failed_id, "selected": page.selected_cue_id, "list_row": row,
                       "filter": page.cue_model.filter_status, "playhead_ms": playhead,
                       "cue_start_ms": failed.start_ms, "cue_end_ms": failed.end_ms,
                       "list_number_shown": page.cue_model.data(page.cue_model.index(row, 0)) if row >= 0 else None,
                       "button_after": dialog.locate_failed_button.text(),
                       "table_visible": page.cue_table.isVisible(),
                       "viewport": list(page.cue_table.viewport().rect().getRect()),
                       "row_rect": list(page.cue_table.visualRect(page.cue_model.index(row, 3)).getRect()),
                       "scroll": page.cue_table.verticalScrollBar().value(), "scroll_at_click": scroll_at_click,
                       "selected_rows": [index.row() for index in page.cue_table.selectionModel().selectedRows()]}
            result["located"].append(located)
            capture(f"03-located-{step + 1}")
            check(f"locate_{step + 1}_selects", page.selected_cue_id == failed_id, located)
            check(f"locate_{step + 1}_list_shows_it", row >= 0 and page.cue_model.filter_status == "all", located)
            check(f"locate_{step + 1}_number_matches", located["list_number_shown"] == numbers[step], located)
            check(f"locate_{step + 1}_playhead_on_cue", failed.start_ms - 50 <= playhead <= failed.end_ms, located)
            check(f"locate_{step + 1}_row_visible", page.cue_table.viewport().rect().intersects(
                page.cue_table.visualRect(page.cue_model.index(row, 3))), located)
            check(f"locate_{step + 1}_dialog_open", dialog.isVisible())
        capture("04-dialog-after", dialog)
        check("no_provider_calls", not blank_project_audit._provider_calls)
        dialog.close()
        result["passed"] = all(item["passed"] for item in result["checks"])
        receipt()
        return 0
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
        receipt()
        return 1


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        window.result_exit_code = run(output, window)

        def stopped():
            path = Path(output) / "result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["gui_shutdown"] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(150, execute)
