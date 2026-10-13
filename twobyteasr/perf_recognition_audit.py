"""Opt-in recognition performance and memory-reclaim audit (source or frozen).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=perf-recognition`` via
``scripts/verify_perf_recognition_headed.py``, with runtimes, models and (when
AI stages are on) the encrypted key store borrowed read only through the hashed
manifest of ``glossary_live_resources``. It uses the ordinary Home controls:
the file button adds the media, Start launches the production worker. The run
repeats in the same process so growth across runs is visible.

Every second it samples the main process and each child process (RSS, private
bytes, GPU memory in use). Per run it records wall time, peaks, memory 5 s and
20 s after the result (and after ``gc.collect``), the children still alive, and
each child process started during the run with its command and caller, so
repeated environment probes can be told apart from model workers.
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path


def _gpu_used_mb():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=3,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def start(window, output):
    import psutil
    from PySide6.QtCore import QObject, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from .glossary_live_resources import install as install_resources

    output = Path(output)
    media = os.environ["PERF_RECOGNITION_MEDIA"]
    runs = int(os.environ.get("PERF_RECOGNITION_RUNS", "2"))
    borrowed = install_resources(output)
    process = psutil.Process()
    started = time.monotonic()

    # Every child process start (from this process) with its caller.
    child_log: list[dict] = []
    original_init = subprocess.Popen.__init__

    def popen_init(self, args, *a, **kw):
        stack = [f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in traceback.extract_stack(limit=16)[:-1]
                 if "subprocess" not in f.filename]
        text = args if isinstance(args, str) else " ".join(str(item) for item in args)
        row = {"t": round(time.monotonic() - started, 2), "cmd": text[:240], "caller": stack[-6:]}
        child_log.append(row)
        t = time.monotonic()
        original_init(self, args, *a, **kw)
        row["pid"] = self.pid

        def reap():
            try:
                psutil.Process(self.pid).wait(timeout=7200)
            except Exception:
                pass
            row["seconds"] = round(time.monotonic() - t, 2)
        threading.Thread(target=reap, daemon=True, name="perf-child-reaper").start()
    subprocess.Popen.__init__ = popen_init

    def tree():
        rows = []
        for item in [process, *process.children(recursive=True)]:
            try:
                info = item.memory_info()
                rows.append({"pid": item.pid, "name": item.name(), "rss_mb": round(info.rss / 1e6),
                             "private_mb": round(getattr(info, "private", 0) / 1e6),
                             "cmd": " ".join(item.cmdline())[:160] if item.pid != process.pid else "main"})
            except psutil.Error:
                pass
        return rows

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {"scenario": "perf-recognition", "media": media, "runs": [], "errors": {},
                           "borrowed_resources": borrowed.receipt(), "samples": []}
            try:
                from .build_identity import load_build_identity
                self.result["build"] = load_build_identity().to_dict()
            except Exception as exc:
                self.result["build"] = repr(exc)
            self.queue_result = None
            self.worker_error = None
            self.sampling = True
            threading.Thread(target=self._sampler, daemon=True, name="perf-recognition-sampler").start()
            self.steps = self.run()
            self.waiting = 0.0
            self.busy = False
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(100)

        def _sampler(self):
            while self.sampling:
                rows = tree()
                self.result["samples"].append({
                    "t": round(time.monotonic() - started, 1), "gpu_used_mb": _gpu_used_mb(),
                    "main_rss_mb": next((r["rss_mb"] for r in rows if r["pid"] == process.pid), None),
                    "children_rss_mb": sum(r["rss_mb"] for r in rows if r["pid"] != process.pid),
                    "children": len(rows) - 1})
                time.sleep(1.0)

        def write(self):
            self.result["child_processes"] = child_log
            (output / "perf-recognition.json").write_text(json.dumps(self.result, ensure_ascii=False, indent=1), "utf8")

        def snapshot(self, label):
            rows = tree()
            main = next((r for r in rows if r["pid"] == process.pid), {})
            return {"label": label, "t": round(time.monotonic() - started, 1), "main_rss_mb": main.get("rss_mb"),
                    "main_private_mb": main.get("private_mb"), "threads": process.num_threads(),
                    "handles": process.num_handles(), "gpu_used_mb": _gpu_used_mb(),
                    "children": [r for r in rows if r["pid"] != process.pid]}

        def watch_modals(self):
            dialog = getattr(window, "_completion_dialog", None)
            if dialog is not None and dialog.isVisible():
                self.result.setdefault("completion_dialogs", []).append(dialog.windowTitle())
                QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
            modal = QApplication.activeModalWidget()
            if isinstance(modal, QMessageBox):
                self.result.setdefault("unexpected_modals", []).append(modal.text() + " " + modal.informativeText())
                modal.reject()

        def tick(self):
            if self.busy:
                return
            self.busy = True
            try:
                self.watch_modals()
                if time.monotonic() - started > float(os.environ.get("PERF_TIMEOUT_S", "3000")):
                    raise TimeoutError("perf recognition audit timeout")
                if callable(self.waiting):
                    if not self.waiting():
                        return
                elif time.monotonic() < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else time.monotonic() + float(step)
            except StopIteration:
                self.finish()
            except BaseException:
                self.result["errors"]["fatal"] = traceback.format_exc()
                self.finish()
            finally:
                self.busy = False

        def run(self):
            yield 3.0
            self.result["baseline"] = self.snapshot("baseline")
            for index in range(runs):
                window._return_to_settings()
                yield 0.5
                picker = QFileDialog.getOpenFileNames
                QFileDialog.getOpenFileNames = lambda *args, **kwargs: ([media], "")
                try:
                    window.choose_media_button.click()
                finally:
                    QFileDialog.getOpenFileNames = picker
                yield lambda: bool(window.media_paths) and window.start_button.isEnabled()
                self.queue_result = None
                children_before = len(child_log)
                t0 = time.monotonic()
                window.start_button.click()
                yield 1.0
                worker = getattr(window, "worker", None)
                if worker is None:
                    raise RuntimeError("Start did not create the production worker: "
                                       + str(getattr(window, "_run_block_reason", "")))
                worker.result_ready.connect(lambda value: setattr(self, "queue_result", value))
                worker.unexpected_error.connect(lambda error: setattr(self, "worker_error", str(error)))
                yield lambda: (self.queue_result is not None or self.worker_error) and not window._run_in_progress
                wall = round(time.monotonic() - t0, 1)
                row = {"index": index, "wall_s": wall, "worker_error": self.worker_error,
                       "statuses": [r.status for r in self.queue_result.results] if self.queue_result else None,
                       "errors": [r.error for r in self.queue_result.results] if self.queue_result else None}
                window_samples = [s for s in self.result["samples"] if t0 - started <= s["t"]]
                row["peak_main_rss_mb"] = max((s["main_rss_mb"] or 0 for s in window_samples), default=None)
                row["peak_children_rss_mb"] = max((s["children_rss_mb"] for s in window_samples), default=None)
                row["peak_gpu_used_mb"] = max((s["gpu_used_mb"] or 0 for s in window_samples), default=None)
                yield 5.0
                row["after_5s"] = self.snapshot(f"run{index}-after-5s")
                yield 15.0
                row["after_20s"] = self.snapshot(f"run{index}-after-20s")
                gc.collect()
                yield 1.0
                row["after_gc"] = self.snapshot(f"run{index}-after-gc")
                row["children_started"] = child_log[children_before:]
                self.result["runs"].append(row)
                self.worker_error = None
                self.write()

        def finish(self):
            self.timer.stop()
            self.sampling = False
            self.result["finished"] = True
            self.write()
            window.close()
            self.result["gui_shutdown"] = True
            self.write()
            QApplication.quit()

    Audit()
