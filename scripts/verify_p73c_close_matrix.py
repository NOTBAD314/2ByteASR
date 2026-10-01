"""Formal headed P7.3C close responsiveness matrix."""

from __future__ import annotations

import copy
import faulthandler
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get(
    "TWOBYTEASR_P73C_CLOSE_OUTPUT",
    str(ROOT / "tmp" / "p73c" / "close-matrix"),
)).resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["TWOBYTEASR_P73C_SEEK_OUTPUT"] = str(OUTPUT)
os.environ["TWOBYTEASR_NO_OPEN"] = "1"
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"localappdata-{os.getpid()}")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox

import moss_firered_pipeline
import subtitle_core
from twobyteasr import studio_ui as studio_ui_module
from twobyteasr import ui
from twobyteasr.media_service import GLOBAL_MEDIA_SERVICE, ProxySettings
from twobyteasr.project_dirty_guard import DirtyGuardChoice, ProjectDirtyGuard
from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
from twobyteasr.service import CancellationToken
from twobyteasr.studio_ai import style_recipe_for_prompt
from twobyteasr.visual_runtime import VisualOwner

import verify_p73c_seek_matrix as seek_support


CASES = (
    "idle",
    "playback",
    "seek_pending",
    "rapid_seek",
    "renderer",
    "renderer_crash_restart",
    "provider_cli",
    "autosave",
    "waveform",
    "proxy",
    "renderer_provider",
    "asr",
)
SELECTED_CASES = tuple(
    item.strip()
    for item in os.environ.get("TWOBYTEASR_P73C_CLOSE_CASES", "").split(",")
    if item.strip()
) or CASES


def progress(message: str) -> None:
    print(f"[p73c-close] {message}", flush=True)


def children(process: psutil.Process) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for child in process.children(recursive=True):
        try:
            if child.is_running():
                rows.append({
                    "pid": child.pid,
                    "name": child.name(),
                    "command": child.cmdline(),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows


def resource_payload(page) -> dict[str, object]:
    snapshot = page._resource_governor.snapshot()
    return {
        "playback": snapshot.playback,
        "dragging": snapshot.dragging,
        "active": dict(snapshot.active),
        "foreground_active": dict(snapshot.foreground_active),
        "yield_counts": dict(snapshot.yield_counts),
    }


def wait_provider_child(
    app: QApplication,
    page,
    process: psutil.Process,
    baseline: set[int],
) -> bool:
    seek_support.wait_until(
        app,
        lambda: (
            int(page._resource_governor.snapshot().active.get("AI", 0)) > 0
            and any(int(item["pid"]) not in baseline for item in children(process))
        ),
        8.0,
        "Provider CLI child",
    )
    return True


def configure_provider_cli_case(page) -> dict[str, str]:
    settings = copy.deepcopy(page.runtime_settings)
    models = settings.setdefault("models", {})
    models.update({
        "polish_transport": "grok_cli",
        "polish_provider": "grok_oauth",
        "polish_model": "grok-4.6",
    })
    page.runtime_settings = settings
    return {
        "transport": str(models["polish_transport"]),
        "provider": str(models["polish_provider"]),
        "model": str(models["polish_model"]),
    }


def prepare_renderer(app: QApplication, page, label: str) -> dict[str, object]:
    cue = page.project.cues[0]
    page.select_cue(cue.id)
    page._seek((cue.start_ms + 400) / 1000.0)
    seek_support.wait_until(
        app, lambda: page.video._active_seek_trace is None, 4.0, "renderer seek",
    )
    recipe = style_recipe_for_prompt("高对比黄青渐变，双层描边，弹性入场")
    recipe.name = f"P73C {label} {time.time_ns()}"
    if not page._apply_style_recipe(cue.id, recipe):
        raise RuntimeError("renderer recipe did not apply")
    page._queue_advanced_preview(
        copy.deepcopy(page.project.style_recipes[page._cue_lookup[cue.id].style_id]),
        force=True,
        delay_ms=0,
    )
    seek_support.wait_until(
        app,
        lambda: (
            page._advanced_preview_worker_running
            and int(
                page._resource_governor.snapshot().foreground_active.get(
                    "ADVANCED_PREVIEW", 0
                )
            ) > 0
        ),
        10.0,
        "active Fidelity renderer",
    )
    return {
        "worker_active": True,
        "renderer_pid": page._advanced_preview_cache.renderer_service.process_id,
        "owner": page._visual_ownership.current.owner.value,
    }


def activate_case(
    case: str,
    app: QApplication,
    window,
    page,
    process: psutil.Process,
) -> tuple[dict[str, object], Callable[[], None] | None]:
    cue = page.project.cues[0]
    release = None
    evidence: dict[str, object] = {}
    if case == "idle":
        page.video.set_paused(True)
        page._cancel_media_ingest()
        seek_support.wait_until(
            app,
            lambda: not any(
                thread.name == "studio-waveform" and thread.is_alive()
                for thread in threading.enumerate()
            ),
            3.0,
            "idle waveform cancellation",
        )
        evidence["idle"] = True
    elif case == "playback":
        seek_support.wait_pause(app, page, False)
        evidence["playback"] = page._resource_governor.snapshot().playback
    elif case == "seek_pending":
        seek_support.wait_pause(app, page, False)
        page._seek(3600.0)
        evidence["seek_trace_active"] = page.video._active_seek_trace is not None
    elif case == "rapid_seek":
        seek_support.wait_pause(app, page, False)
        for index in range(20):
            page._seek(414.5 if index % 2 == 0 else 428.0)
        evidence["rapid_commands"] = 20
        evidence["seek_trace_active"] = page.video._active_seek_trace is not None
    elif case == "renderer":
        evidence.update(prepare_renderer(app, page, case))
    elif case == "renderer_crash_restart":
        warm = prepare_renderer(app, page, "renderer crash warmup")
        service = page._advanced_preview_cache.renderer_service
        old_pid = service.process_id
        if old_pid is None:
            raise RuntimeError("renderer process missing before crash injection")
        crash_done = threading.Event()
        crash_error: list[str] = []

        def inject_crash() -> None:
            try:
                service.inject_failure("node_crash", timeout=3.0)
            except Exception as exc:
                crash_error.append(f"{type(exc).__name__}: {exc}")
            finally:
                crash_done.set()

        threading.Thread(
            target=inject_crash,
            daemon=True,
            name="p73c-renderer-crash-inject",
        ).start()
        seek_support.wait_until(
            app,
            crash_done.is_set,
            5.0,
            "renderer crash injection",
        )
        if crash_error:
            raise RuntimeError(crash_error[0])
        seek_support.wait_until(
            app,
            lambda: service.process_id != old_pid,
            5.0,
            "renderer crash generation change",
        )
        restart_done = threading.Event()
        restart_error: list[str] = []
        manual_restart_started = False

        def restart() -> None:
            try:
                service.warm(timeout=30.0)
            except Exception as exc:
                restart_error.append(f"{type(exc).__name__}: {exc}")
            finally:
                restart_done.set()

        if service.process_id is None:
            manual_restart_started = True
            threading.Thread(
                target=restart,
                daemon=True,
                name="p73c-renderer-restart",
            ).start()
            seek_support.wait_until(
                app,
                lambda: service.process_id is not None,
                8.0,
                "renderer replacement process",
            )
        new_pid = service.process_id
        evidence.update({
            "warm": warm,
            "crashed_pid": old_pid,
            "restarted_pid": new_pid,
            "pid_changed": new_pid is not None and new_pid != old_pid,
            "restart_worker_active": bool(
                page._advanced_preview_worker_running
                or (manual_restart_started and not restart_done.is_set())
            ),
            "restart_error_before_close": list(restart_error),
        })
    elif case == "provider_cli":
        evidence["provider_config"] = configure_provider_cli_case(page)
        baseline = {int(item["pid"]) for item in children(process)}
        telemetry_before = len(GLOBAL_PROVIDER_SERVICE.telemetry())
        page.ai_prompt.setPlainText("关闭时取消 Provider 的验证")
        page._request_ai_suggestion()
        evidence["provider_cli_child"] = wait_provider_child(
            app, page, process, baseline,
        )
        evidence["telemetry_before"] = telemetry_before
    elif case == "autosave":
        release_event = threading.Event()
        started_event = threading.Event()
        original = studio_ui_module.save_autosave_revision

        def blocked_save(*args, **kwargs):
            started_event.set()
            release_event.wait(5.0)
            return original(*args, **kwargs)

        def release_autosave() -> None:
            release_event.set()
            studio_ui_module.save_autosave_revision = original

        studio_ui_module.save_autosave_revision = blocked_save
        try:
            page.cue_controller.nudge(19)
            due_at = time.monotonic() - page._autosave_deadline.interval_seconds
            page._autosave_deadline.dirty_since = due_at
            page._autosave_deadline.last_edit_at = due_at
            page._autosave_timer.stop()
            page._autosave()
            if not started_event.wait(2.0):
                raise TimeoutError("autosave worker did not enter the durable write")
            evidence["autosave_worker_active"] = bool(page._autosave_worker_running)
        except Exception:
            release_autosave()
            raise

        def release() -> None:
            release_autosave()

    elif case == "waveform":
        started_event = threading.Event()
        release_event = threading.Event()
        original = studio_ui_module.generate_progressive_waveform_cache

        def blocked_waveform(*_args, cancelled=None, **_kwargs):
            started_event.set()
            while not release_event.wait(0.01):
                if cancelled and cancelled():
                    raise InterruptedError("controlled waveform cancellation")
            raise InterruptedError("controlled waveform released")

        def release_waveform() -> None:
            release_event.set()
            studio_ui_module.generate_progressive_waveform_cache = original

        studio_ui_module.generate_progressive_waveform_cache = blocked_waveform
        try:
            page._cancel_media_ingest()
            page.timeline.set_cache(None)
            page._generate_waveform(page.project.media.path)
            if not started_event.wait(2.0):
                raise TimeoutError("waveform worker did not start")
            evidence["waveform_worker_active"] = any(
                thread.name == "studio-waveform" and thread.is_alive()
                for thread in threading.enumerate()
            )
        except Exception:
            release_waveform()
            raise

        def release() -> None:
            release_waveform()

    elif case == "proxy":
        page.video.set_paused(True)
        seek_support.wait_until(
            app,
            lambda: not page._resource_governor.snapshot().playback,
            2.0,
            "proxy playback yield",
        )
        job = GLOBAL_MEDIA_SERVICE.start_proxy(
            page.project.media.path,
            settings=ProxySettings(max_height=366, crf=41, preset="ultrafast"),
        )
        seek_support.wait_until(
            app,
            lambda: job.done or getattr(job, "_process", None) is not None,
            8.0,
            "proxy worker",
        )
        evidence.update({
            "proxy_thread_active": not job.done,
            "proxy_process_active": bool(
                getattr(job, "_process", None) is not None
                and job._process.poll() is None
            ),
        })
    elif case == "renderer_provider":
        evidence["provider_config"] = configure_provider_cli_case(page)
        baseline = {int(item["pid"]) for item in children(process)}
        page.ai_prompt.setPlainText("Renderer 与 Provider 同时关闭验证")
        page._request_ai_suggestion()
        evidence["provider_cli_child"] = wait_provider_child(
            app, page, process, baseline,
        )
        evidence["renderer"] = prepare_renderer(app, page, case)
        resource = resource_payload(page)
        evidence["simultaneous_resource"] = resource
        evidence["simultaneous"] = (
            int(resource["active"].get("AI", 0)) > 0
            and int(resource["foreground_active"].get("ADVANCED_PREVIEW", 0)) > 0
        )
    elif case == "asr":
        class ControlledAsrWorker(QThread):
            def run(self) -> None:
                while not self.isInterruptionRequested():
                    self.msleep(5)

        worker = ControlledAsrWorker(window)
        window.token = CancellationToken()
        window.worker = worker
        original_question = QMessageBox.question

        def approve_close(*_args, **_kwargs):
            return QMessageBox.StandardButton.Yes

        QMessageBox.question = approve_close
        worker.start()
        seek_support.wait_until(
            app, worker.isRunning, 2.0, "controlled ASR worker",
        )
        evidence["asr_worker_active"] = worker.isRunning()

        def release() -> None:
            QMessageBox.question = original_question
    else:
        raise ValueError(case)
    return evidence, release


def activation_passed(case: str, evidence: dict[str, object]) -> bool:
    if case == "idle":
        return evidence.get("idle") is True
    if case == "playback":
        return evidence.get("playback") is True
    if case in {"seek_pending", "rapid_seek"}:
        return evidence.get("seek_trace_active") is True
    if case == "renderer":
        return evidence.get("worker_active") is True
    if case == "renderer_crash_restart":
        return (
            evidence.get("pid_changed") is True
            and evidence.get("restart_worker_active") is True
        )
    if case == "provider_cli":
        return evidence.get("provider_cli_child") is True
    if case == "autosave":
        return evidence.get("autosave_worker_active") is True
    if case == "waveform":
        return evidence.get("waveform_worker_active") is True
    if case == "proxy":
        return (
            evidence.get("proxy_thread_active") is True
            or evidence.get("proxy_process_active") is True
        )
    if case == "renderer_provider":
        return (
            evidence.get("provider_cli_child") is True
            and evidence.get("simultaneous") is True
        )
    if case == "asr":
        return evidence.get("asr_worker_active") is True
    return False


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    process = psutil.Process()
    qt_events = seek_support.QtEventProbe(app)
    probe = seek_support.EventLoopProbe(app, qt_events)
    result: dict[str, object] = {
        "schema": "p73c-close-matrix-v1",
        "evidence_class": "formal_headed_runtime",
        "real_user_click": False,
        "project": str(seek_support.PROJECT),
        "cases": [],
    }

    target = OUTPUT / "runtime-result.json"
    for case in SELECTED_CASES:
        progress(f"starting {case}")
        case_output = OUTPUT / case
        case_output.mkdir(parents=True, exist_ok=True)
        os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(
            (case_output / "children.jsonl").resolve()
        )
        row: dict[str, object] = {"case": case}
        window = None
        page = None
        release = None
        try:
            started = time.perf_counter()
            window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
            row["constructor_ms"] = round(
                (time.perf_counter() - started) * 1000.0, 3,
            )
            window.resize(1600, 950)
            window.show()
            seek_support.pump(app, 100)
            page = window.studio_page
            original_studio_preferences = page._studio_preferences
            page._studio_preferences = lambda: {
                **original_studio_preferences(),
                "recovery_policy": "official",
            }
            row["recovery_policy"] = "official"
            opened = time.perf_counter()
            progress(f"{case} opening project")
            faulthandler.dump_traceback_later(20.0, repeat=False)
            try:
                window.open_studio_project(
                    seek_support.PROJECT, source=f"p73c-close-{case}",
                )
            finally:
                faulthandler.cancel_dump_traceback_later()
            page = window.studio_page
            seek_support.wait_until(
                app,
                lambda: page.project is not None
                and page.video.controller is not None
                and page.video.controller.running,
                15.0,
                "case mpv",
            )
            # Project hydration creates the controller. Inject the explicit
            # formal-test decision only after that replacement has completed.
            page.project_controller.dirty_guard._prompt = (
                lambda _action: DirtyGuardChoice.DISCARD
            )
            page.project_controller.dirty_guard.confirm = (
                lambda _action, **_kwargs: True
            )
            row["dirty_guard_choice"] = DirtyGuardChoice.DISCARD.value
            row["project_usable_ms"] = round(
                (time.perf_counter() - opened) * 1000.0, 3,
            )
            progress(f"{case} project usable")
            probe.page = page
            lag_index = probe.reset()
            progress(f"{case} activating")
            faulthandler.dump_traceback_later(20.0, repeat=False)
            try:
                evidence, release = activate_case(
                    case, app, window, page, process,
                )
            finally:
                faulthandler.cancel_dump_traceback_later()
            row["activation"] = evidence
            row["activation_passed"] = activation_passed(case, evidence)
            progress(f"{case} activated")
            row["resource_before_close"] = resource_payload(page)
            progress(f"{case} resource captured")
            row["children_before_close"] = children(process)
            progress(f"{case} children captured")
            active_guard = page.project_controller.dirty_guard
            active_guard._prompt = lambda _action: DirtyGuardChoice.DISCARD
            active_guard.confirm = lambda _action, **_kwargs: True
            if active_guard.confirm("formal close matrix") is not True:
                raise RuntimeError("formal DirtyGuard decision was not installed")
            close_started = time.perf_counter()
            page._studio_trace("HARNESS_CLOSE_CALL", case=case)
            progress(f"{case} calling close")
            faulthandler.dump_traceback_later(20.0, repeat=False)
            original_guard_confirm = ProjectDirtyGuard.confirm
            ProjectDirtyGuard.confirm = lambda _self, _action, **_kwargs: True
            try:
                window.close()
            finally:
                ProjectDirtyGuard.confirm = original_guard_confirm
                faulthandler.cancel_dump_traceback_later()
            row["visible_response_ms"] = round(
                (time.perf_counter() - close_started) * 1000.0, 3,
            )
            progress(f"{case} close returned")
            progress(
                f"{case} close state "
                f"pending={getattr(window, '_studio_close_pending', None)} "
                f"finalizing={getattr(window, '_studio_close_finalizing', None)} "
                f"worker_running={bool(window.worker and window.worker.isRunning())} "
                f"page_requested={getattr(page, '_close_requested', None)} "
                f"page_complete={getattr(page, '_close_complete', None)}"
            )
            row["window_hidden_after_response"] = not window.isVisible()
            seek_support.pump(app, 1)
            if release is not None:
                release()
                release = None
            row["cleanup_complete_ms"] = seek_support.wait_until(
                app,
                lambda: bool(page._close_complete),
                12.0,
                f"{case} cleanup",
            )
            progress(f"{case} studio cleanup complete")
            if case == "asr":
                seek_support.wait_until(
                    app,
                    lambda: not bool(window.worker and window.worker.isRunning()),
                    2.0,
                    "ASR worker shutdown",
                )
            seek_support.pump(app, 150)
            row["close_profile"] = dict(page.last_close_profile)
            row["asr_worker_running_after_close"] = bool(
                case == "asr" and window.worker and window.worker.isRunning()
            )
            row["asr_cancelled_after_close"] = bool(
                case != "asr" or window.token.is_cancelled
            )
            row["children_after_close"] = children(process)
            row["event_loop"] = probe.report_since(lag_index)
            profile = row["close_profile"]
            row["pass"] = bool(
                row["activation_passed"]
                and row["visible_response_ms"] < 100.0
                and row["window_hidden_after_response"]
                and page._close_complete
                and profile.get("provider_idle") is True
                and profile.get("proxy_idle") is True
                and int(profile.get("waveform_threads_alive", -1)) == 0
                and profile.get("advanced_thread_alive") is False
                and not row["asr_worker_running_after_close"]
                and row["asr_cancelled_after_close"]
                and not row["children_after_close"]
                and row["event_loop"]["threshold_counts"]["500"] == 0
                and row["event_loop"]["threshold_counts"]["1000"] == 0
            )
        except Exception as exc:
            row["fatal_error"] = f"{type(exc).__name__}: {exc}"
            row["traceback"] = traceback.format_exc()
            row["pass"] = False
            progress(f"{case} failed: {row['fatal_error']}")
        finally:
            progress(f"{case} entering final cleanup")
            if release is not None:
                try:
                    release()
                except Exception:
                    pass
            if window is not None and window.isVisible():
                try:
                    window.close()
                    seek_support.pump(app, 5)
                    if page is not None:
                        seek_support.wait_until(
                            app,
                            lambda: bool(page._close_complete),
                            12.0,
                            f"{case} failure cleanup",
                        )
                except Exception as exc:
                    row["cleanup_error"] = f"{type(exc).__name__}: {exc}"
            if window is not None:
                window.deleteLater()
                seek_support.pump(app, 20)
        result["cases"].append(row)
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        progress(f"finished {case}: pass={row.get('pass')}")

    rows = result["cases"]
    result["summary"] = {
        "case_count": len(rows),
        "passed": sum(row.get("pass") is True for row in rows),
        "max_visible_response_ms": round(max(
            (float(row.get("visible_response_ms", 9999.0)) for row in rows),
            default=9999.0,
        ), 3),
        "max_cleanup_ms": round(max(
            (float(row.get("cleanup_complete_ms", 9999.0)) for row in rows),
            default=9999.0,
        ), 3),
        "failed_cases": [
            str(row["case"]) for row in rows if row.get("pass") is not True
        ],
    }
    result["pass"] = all(row.get("pass") is True for row in rows)
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(target, flush=True)
    print(json.dumps({
        "pass": result["pass"],
        "summary": result["summary"],
        "cases": [
            {
                "case": row["case"],
                "pass": row.get("pass"),
                "visible_response_ms": row.get("visible_response_ms"),
                "cleanup_complete_ms": row.get("cleanup_complete_ms"),
                "fatal_error": row.get("fatal_error"),
            }
            for row in rows
        ],
    }, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    if any(argument in {"-h", "--help"} for argument in sys.argv[1:]):
        print(
            "Usage: set TWOBYTEASR_P73C_CLOSE_OUTPUT=<dir> and "
            "TWOBYTEASR_P73C_CLOSE_CASES=<comma-separated cases>, then run "
            "verify_p73c_close_matrix.py"
        )
        print("Cases: " + ", ".join(CASES))
        raise SystemExit(0)
    raise SystemExit(main())
