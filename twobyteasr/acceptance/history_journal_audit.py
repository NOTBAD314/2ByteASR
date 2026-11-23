"""Exercise the history page through the normal packaged Windows entry."""

import gc
import json
import os
from pathlib import Path
import time


def start(window, output):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QDialog
    from ..diagnostics.build_identity import load_build_identity
    from ..recognition.recognition_history import RecognitionHistoryDetail, summarize_report
    from ..storage.atomic_files import write_text_atomic
    from .studio_acceptance_audit import require

    fixture = output / "fixture_字幕任务报告.json"
    require(fixture.is_file(), "missing isolated 102 MB fixture")
    window._open_recognition_history()
    page = window.history_page
    task = output / "recognition-tasks" / "54e6e4107c804b20810b66b80ff0e08e" / "task.json"
    require(task.is_file(), "missing isolated task reference")
    page.extra_roots = (*page.extra_roots, output, task.parent.parent)
    page.refresh()
    app = QApplication.instance()
    process = None
    try:
        import psutil
        process = psutil.Process()
    except ImportError:
        pass
    build = load_build_identity()
    started = last = time.perf_counter()
    gaps = []
    cycles = []
    memory = []
    report = {"passed": False, "git_sha": build.git_sha, "exe": os.path.abspath(os.sys.executable),
              "cycles": cycles, "provider_calls": 0}

    def write():
        write_text_atomic(output / "history-audit.json", json.dumps(report, indent=2))

    def heartbeat():
        nonlocal last
        now = time.perf_counter()
        gaps.append((now - last) * 1000)
        last = now
        if process:
            memory.append(process.memory_info().private)

    pulse = QTimer(window)
    pulse.setTimerType(Qt.TimerType.PreciseTimer)
    pulse.timeout.connect(heartbeat)
    pulse.start(20)

    def finish(error=""):
        report.update(passed=not error, error=error, peak_private_bytes=max(memory, default=0))
        write()
        window.close()

    def open_next():
        if not page.records or page.background_busy():
            if time.perf_counter() - started > 45:
                finish("history list timed out")
            else:
                QTimer.singleShot(100, open_next)
            return
        if len(cycles) == 20:
            finish()
            return
        if not cycles:
            report["initial_list_ms"] = round((time.perf_counter() - started) * 1000, 2)
        iteration = len(cycles)
        path = fixture if iteration % 2 == 0 else task
        row = next((record for record in page.records if record.path == path), None)
        if row is None and path == task:
            row = summarize_report(task)
        if row is None:
            finish("large report is absent from the history list")
            return
        begin = time.perf_counter()
        gaps.clear()
        stats = {"entry": "direct" if path == fixture else "task_reference", "cancelled": iteration % 5 == 4}
        monitor = QTimer(window)
        monitor.setTimerType(Qt.TimerType.PreciseTimer)

        def observe():
            dialog = next((item for item in page.findChildren(QDialog) if item.isVisible()), None)
            if dialog is None:
                return
            elapsed = (time.perf_counter() - begin) * 1000
            stats.setdefault("feedback_ms", round(elapsed, 2))
            if stats["cancelled"] or elapsed > 45000:
                monitor.stop()
                dialog.reject()
                return
            detail = dialog.findChild(RecognitionHistoryDetail)
            if detail is None or "detail_ms" in stats:
                return
            stats["detail_ms"] = round(elapsed, 2)
            detail.raw_button.click()
            monitor.stop()

        monitor.timeout.connect(observe)
        monitor.start(10)
        page._show_detail(row)
        monitor.stop()
        monitor.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        def finish_cycle():
            stats["heartbeat_max_ms"] = round(max(gaps, default=0), 2)
            stats["remaining_dialogs"] = len(page.findChildren(QDialog))
            if iteration in {4, 9, 14, 19}:
                gc.collect()
                if process:
                    stats["post_collection_private_bytes"] = process.memory_info().private
            cycles.append(stats)
            write()
            QTimer.singleShot(100, open_next)

        def check_raw():
            raw_page = page.json_page
            viewer = raw_page.paged_view if raw_page is not None else None
            if viewer is None or not viewer.report_search.isEnabled():
                if time.perf_counter() - begin > 46:
                    finish("paged JSON did not appear")
                else:
                    QTimer.singleShot(50, check_raw)
                return
            stats["raw_ms"] = round((time.perf_counter() - begin) * 1000, 2)
            stats["raw_characters"] = viewer.raw_view.document().characterCount()
            if not 0 < stats["raw_characters"] <= 128 * 1024 + 1 or not viewer.report_model.rowCount():
                finish("paged JSON preview missing or above document limit")
                return
            if page.main_stack.currentWidget() is not raw_page or not raw_page.copy_button.isHidden():
                finish("large report did not open in the dedicated JSON view")
                return
            if iteration == 0:
                page.grab().save(str(output / "history-report.png"))
            raw_page.back_button.click()
            finish_cycle()

        if stats["cancelled"]:
            finish_cycle()
        else:
            QTimer.singleShot(0, check_raw)

    def stopped():
        report["gui_shutdown"] = True
        write()

    app.aboutToQuit.connect(stopped)
    QTimer.singleShot(0, open_next)
