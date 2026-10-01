"""Headed P6.2 runtime exercise using real Studio media dependencies."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "tmp" / "p62-runtime"
SOURCE_MEDIA = ROOT / "tmp" / "p53-accept" / "clips" / "native-30s.mp4"
SOURCE_XML = ROOT / "tmp" / "p53-accept" / "clips" / "native-30s.xml"
MEDIA = EVIDENCE / "fixture" / "native-30s.mp4"
XML = EVIDENCE / "fixture" / "native-30s.xml"

EVIDENCE.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(EVIDENCE / "localappdata")
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(EVIDENCE / "child-processes-harness.jsonl")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_edit_sequence import sequence_of
from twobyteasr.studio_project import load_project
from twobyteasr.studio_ui import SubtitleStudioPage


class ChildWindowMonitor:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.observed_pids: set[int] = set()
        self.visible_windows: list[dict[str, object]] = []
        self.thread = threading.Thread(target=self._work, daemon=True, name="p62-window-monitor")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2.0)

    @staticmethod
    def _visible_windows_for(pids: set[int]) -> list[dict[str, object]]:
        if os.name != "nt" or not pids:
            return []
        user32 = ctypes.windll.user32
        results: list[dict[str, object]] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(hwnd, _lparam):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in pids or not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            results.append({"pid": int(pid.value), "hwnd": int(hwnd), "title": buffer.value})
            return True

        user32.EnumWindows(callback_type(visit), 0)
        return results

    def _work(self) -> None:
        while not self.stop_event.is_set():
            pids: set[int] = set()
            for process in psutil.process_iter(("pid", "name")):
                try:
                    name = str(process.info.get("name") or "").casefold()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if name in {"ffmpeg.exe", "ffprobe.exe"}:
                    pids.add(int(process.info["pid"]))
            self.observed_pids.update(pids)
            for item in self._visible_windows_for(pids):
                if item not in self.visible_windows:
                    self.visible_windows.append(item)
            self.stop_event.wait(0.01)


def wait_until(app: QApplication, predicate, timeout: float) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        app.processEvents()
        if predicate():
            return (time.perf_counter() - started) * 1000.0
        time.sleep(0.01)
    raise TimeoutError(f"condition not reached within {timeout:.1f}s")


def main() -> int:
    MEDIA.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_MEDIA, MEDIA)
    shutil.copy2(SOURCE_XML, XML)
    child_log = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])

    monitor = ChildWindowMonitor()
    monitor.start()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("2ByteASR P6.2 Runtime Acceptance")
    page = SubtitleStudioPage()
    page.setWindowTitle("2ByteASR P6.2 Runtime Acceptance")
    page.resize(1600, 1000)
    page.show()
    app.processEvents()
    result: dict[str, object] = {
        "source_media": str(MEDIA),
        "source_size": MEDIA.stat().st_size,
        "xml": str(XML),
    }
    try:
        page.show_project_hub()
        page._create_blank_studio()
        app.processEvents()
        result["blank_project"] = {
            "created": page.project is not None,
            "media_path": page.project.media.path if page.project else None,
            "empty_state_visible": bool(page.video_empty_hint.isVisible()),
            "project_path": str(page.project_path or ""),
        }

        ingest_started = time.perf_counter()
        page._open_or_create_media_project(MEDIA)
        loading_ms = (time.perf_counter() - ingest_started) * 1000.0
        result["loading"] = {
            "state": page._media_ingest_state,
            "visible": page.video_empty_hint.isVisible(),
            "label": page.video_empty_label.text(),
            "returned_ms": round(loading_ms, 1),
        }

        wait_until(app, lambda: page._media_ingest_state in {"READY", "ERROR"}, 45.0)
        ready_ms = (time.perf_counter() - ingest_started) * 1000.0
        if page._media_ingest_state != "READY":
            raise RuntimeError(page.save_state.toolTip() or page.save_state.text())
        preview_running = bool(page.video.controller and page.video.controller.running)
        result["media_ready"] = {
            "elapsed_ms": round(ready_ms, 1),
            "preview_running": preview_running,
            "duration_ms": page.project.media.duration_ms,
            "width": page.project.media.width,
            "height": page.project.media.height,
            "ingest": dict(page.project.studio_state.get("media_ingest", {})),
        }

        wait_until(
            app,
            lambda: page.timeline.waveform_state in {"READY", "ERROR"},
            120.0,
        )
        waveform_ms = (time.perf_counter() - ingest_started) * 1000.0
        result["waveform"] = {
            "state": page.timeline.waveform_state,
            "elapsed_ms": round(waveform_ms, 1),
            "message": page.timeline.waveform_message,
            "cache_loaded": page.timeline.cache is not None,
        }
        sequence = sequence_of(page.project)
        result["xml_match"] = {
            "mode": page.project.studio_state.get("media_xml_match"),
            "bound_path": sequence.danmaku_path,
            "candidates": list(page.project.studio_state.get("media_xml_candidates", [])),
            "panel": page.highlight_panel.xml_status.text(),
        }

        locked_initial_segments = len(sequence.segments)
        for point in range(1_000, 11_000, 1_000):
            page._razor_video_at(point)
        locked_after_segments = len(sequence_of(page.project).segments)
        page._toggle_video_lock()
        unlocked = not sequence_of(page.project).video_track_locked
        for point in range(1_000, 11_000, 1_000):
            page._razor_video_at(point)
            app.processEvents()
        razor_segments = len(sequence_of(page.project).segments)
        page.undo_stack.undo()
        undo_segments = len(sequence_of(page.project).segments)
        page.undo_stack.redo()
        redo_segments = len(sequence_of(page.project).segments)
        page._toggle_video_lock()
        relocked = sequence_of(page.project).video_track_locked
        before_locked_retry = len(sequence_of(page.project).segments)
        page._razor_video_at(15_000)
        after_locked_retry = len(sequence_of(page.project).segments)
        result["razor_lock"] = {
            "initial_locked": True,
            "locked_attempt_segments_before": locked_initial_segments,
            "locked_attempt_segments_after": locked_after_segments,
            "unlocked": unlocked,
            "segments_after_10_razors": razor_segments,
            "segments_after_undo": undo_segments,
            "segments_after_redo": redo_segments,
            "relocked": relocked,
            "segments_after_relocked_attempt": after_locked_retry,
            "relocked_attempt_unchanged": before_locked_retry == after_locked_retry,
        }

        page.save()
        saved_path = Path(page.project_path)
        saved = load_project(saved_path)
        saved_sequence = sequence_of(saved)
        result["save"] = {
            "path": str(saved_path),
            "exists": saved_path.is_file(),
            "segments": len(saved_sequence.segments),
            "xml": saved_sequence.danmaku_path,
        }
        page.open_project(saved_path)
        app.processEvents()
        reopened = sequence_of(page.project)
        result["reopen"] = {
            "segments": len(reopened.segments),
            "xml": reopened.danmaku_path,
            "media": page.project.media.path,
            "locked": reopened.video_track_locked,
        }

        page.timeline.repaint()
        app.processEvents()
        wait_until(app, lambda: not page.timeline._thumbnails._pending, 30.0)
        result["thumbnail"] = {
            "pending": len(page.timeline._thumbnails._pending),
            "memory_entries": len(page.timeline._thumbnails._memory),
        }
        screenshot = EVIDENCE / "studio-ready.png"
        result["screenshot_saved"] = bool(page.grab().save(str(screenshot)))
        result["screenshot"] = str(screenshot)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        page.close_page()
        page.close()
        page.deleteLater()
        app.processEvents()
        monitor.stop()

    records = []
    if child_log.is_file():
        for line in child_log.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    result["child_processes"] = records
    result["child_process_summary"] = {
        "records": len(records),
        "all_hidden": bool(records) and all(bool(item.get("hidden")) for item in records),
        "purposes": sorted({str(item.get("purpose")) for item in records}),
        "observed_ffmpeg_ffprobe_pids": sorted(monitor.observed_pids),
        "visible_windows": monitor.visible_windows,
        "visible_window_count": len(monitor.visible_windows),
    }
    result_path = EVIDENCE / "runtime-result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result_path)
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
