"""Formal headed P7.3C playback/renderer/provider/autosave concurrency evidence."""

from __future__ import annotations

import copy
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get(
    "TWOBYTEASR_P73C_CONCURRENT_OUTPUT",
    str(ROOT / "tmp" / "p73c" / "concurrent-load"),
)).resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["TWOBYTEASR_P73C_SEEK_OUTPUT"] = str(OUTPUT)
os.environ["TWOBYTEASR_P73C_ISOLATED_LOCALAPPDATA"] = "1"
os.environ["TWOBYTEASR_NO_OPEN"] = "1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import moss_firered_pipeline
import subtitle_core
from twobyteasr import ui
from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
from twobyteasr.runtime_trace import GLOBAL_STUDIO_TRACE
from twobyteasr.studio_ai import style_recipe_for_prompt
from twobyteasr.visual_runtime import VisualOwner

import verify_p73c_seek_matrix as seek_support


SEEK_COUNT = max(1, int(os.environ.get("TWOBYTEASR_P73C_CONCURRENT_SEEKS", "20")))
TOGGLE_COUNT = max(1, int(os.environ.get("TWOBYTEASR_P73C_CONCURRENT_TOGGLES", "20")))


def progress(message: str) -> None:
    print(f"[p73c-concurrent] {message}", flush=True)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else None,
    }


def resource_payload(page) -> dict[str, object]:
    snapshot = page._resource_governor.snapshot()
    return {
        "playback": snapshot.playback,
        "dragging": snapshot.dragging,
        "active": dict(snapshot.active),
        "foreground_active": dict(snapshot.foreground_active),
        "yield_counts": dict(snapshot.yield_counts),
        "background_limit": snapshot.background_limit,
    }


def child_rows(process: psutil.Process) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for child in process.children(recursive=True):
        try:
            if child.is_running():
                rows.append({"pid": child.pid, "name": child.name()})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows


class ResourceSampler:
    """Record state transitions while keeping the runtime evidence bounded."""

    def __init__(self, page, process: psutil.Process) -> None:
        self.page = page
        self.process = process
        self.rows: list[dict[str, object]] = []
        self.last_signature = ""
        self.last_periodic = 0.0
        self.observed_ai = False
        self.observed_fidelity_foreground = False
        self.observed_autosave = False
        self.observed_renderer = False
        self.max_children = 0
        self.max_rss_mb = 0.0
        self.timer = QTimer()
        self.timer.setInterval(5)
        self.timer.timeout.connect(self.sample)

    def start(self) -> None:
        self.sample(force=True)
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self.sample(force=True)

    def sample(self, *, force: bool = False) -> None:
        resource = resource_payload(self.page)
        active = resource["active"]
        foreground = resource["foreground_active"]
        autosave = bool(
            self.page._autosave_worker_running
            or (self.page._autosave_thread and self.page._autosave_thread.is_alive())
        )
        renderer = bool(
            self.page._advanced_preview_worker_running
            or self.page._advanced_preview_pending_job is not None
        )
        self.observed_ai = self.observed_ai or int(active.get("AI", 0)) > 0
        self.observed_fidelity_foreground = (
            self.observed_fidelity_foreground
            or int(foreground.get("ADVANCED_PREVIEW", 0)) > 0
        )
        self.observed_autosave = self.observed_autosave or autosave
        self.observed_renderer = self.observed_renderer or renderer
        children = child_rows(self.process)
        rss_mb = self.process.memory_info().rss / 1024 / 1024
        self.max_children = max(self.max_children, len(children))
        self.max_rss_mb = max(self.max_rss_mb, rss_mb)
        signature = json.dumps({
            "resource": resource,
            "ai_request_active": bool(self.page._ai_request_active),
            "autosave": autosave,
            "renderer": renderer,
            "children": [(item["pid"], item["name"]) for item in children],
        }, ensure_ascii=False, sort_keys=True)
        now = time.monotonic()
        if force or signature != self.last_signature or now - self.last_periodic >= 0.25:
            self.rows.append({
                "elapsed_ms": round((now - self.started) * 1000.0, 3)
                if hasattr(self, "started") else 0.0,
                "resource": resource,
                "ai_request_active": bool(self.page._ai_request_active),
                "autosave_worker_active": autosave,
                "fidelity_worker_active": renderer,
                "renderer_pid": self.page._advanced_preview_cache.renderer_service.process_id,
                "children": children,
                "rss_mb": round(rss_mb, 3),
            })
            self.last_signature = signature
            self.last_periodic = now
        if not hasattr(self, "started"):
            self.started = now

    def report(self) -> dict[str, object]:
        final_resource = resource_payload(self.page)
        return {
            "transitions": self.rows,
            "observed_ai_active": self.observed_ai,
            "observed_fidelity_foreground": self.observed_fidelity_foreground,
            "observed_autosave_active": self.observed_autosave,
            "observed_renderer_active": self.observed_renderer,
            "yield_counts": final_resource["yield_counts"],
            "max_children": self.max_children,
            "max_rss_mb": round(self.max_rss_mb, 3),
        }


def summarize_seek_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    elapsed_names = {
        "T0_T2": "T2_optimistic_playhead_visible",
        "T0_T5": "T5_first_target_frame",
        "T0_T7": "T7_sustained_progression",
        "T0_T9": "T9_event_loop_settled",
    }
    result: dict[str, object] = {
        "count": len(rows),
        "settled_count": sum(row["trace"].get("settled") is True for row in rows),
        "t8_pass_count": sum(row["trace"].get("T8_passed") is True for row in rows),
        "callback": stats([float(row["callback_ms"]) for row in rows]),
    }
    for label, marker in elapsed_names.items():
        values = [
            float(row["trace"]["elapsed_ms"][marker])
            for row in rows
            if marker in row["trace"].get("elapsed_ms", {})
        ]
        result[label] = stats(values)
    return result


def wait_for_provider_child(
    app: QApplication,
    page,
    process: psutil.Process,
    baseline_pids: set[int],
    timeout: float = 8.0,
) -> bool:
    return bool(seek_support.wait_until(
        app,
        lambda: (
            int(page._resource_governor.snapshot().active.get("AI", 0)) > 0
            and any(
                int(item["pid"]) not in baseline_pids
                for item in child_rows(process)
            )
        ),
        timeout,
        "active Provider CLI child",
    ) >= 0.0)


def main() -> int:
    global_result: dict[str, object] = {
        "schema": "p73c-concurrent-load-v1",
        "evidence_class": "formal_headed_runtime",
        "real_user_click": False,
        "project": str(seek_support.PROJECT),
        "errors": [],
    }
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    process = psutil.Process()
    window = None
    page = None
    probe = None
    sampler = None
    try:
        progress("constructing real MainWindow and opening the long FLV project")
        constructor_started = time.perf_counter()
        window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
        global_result["constructor_ms"] = round(
            (time.perf_counter() - constructor_started) * 1000.0, 3,
        )
        window.resize(1600, 950)
        window.show()
        window.activateWindow()
        seek_support.pump(app, 250)
        open_started = time.perf_counter()
        window.open_studio_project(seek_support.PROJECT, source="p73c-concurrent-load")
        page = window.studio_page
        seek_support.wait_until(
            app,
            lambda: page.project is not None
            and page.video.controller is not None
            and page.video.controller.running,
            15.0,
            "real mpv",
        )
        global_result["first_project_usable_ms"] = round(
            (time.perf_counter() - open_started) * 1000.0, 3,
        )

        qt_events = seek_support.QtEventProbe(app)
        probe = seek_support.EventLoopProbe(app, qt_events)
        probe.page = page
        sampler = ResourceSampler(page, process)
        sampler.start()
        stage_events: list[dict[str, object]] = []
        evidence_started = time.monotonic()
        page.ai_stage_signal.connect(lambda generation, stage: stage_events.append({
            "generation": int(generation),
            "stage": str(stage),
            "elapsed_ms": round((time.monotonic() - evidence_started) * 1000.0, 3),
        }))

        cues = list(page.project.cues[:3])
        if len(cues) < 3:
            raise RuntimeError("concurrent fixture requires at least three cues")
        recipe = style_recipe_for_prompt("高对比黄青渐变，双层描边，弹性入场")
        recipe.name = f"P73C Concurrent {time.time_ns()}"
        page.select_cue(cues[0].id)
        page._seek((cues[0].start_ms + 500) / 1000.0)
        seek_support.wait_until(
            app, lambda: page.video._active_seek_trace is None, 4.0, "setup seek",
        )
        if not page._apply_style_recipe(cues[0].id, recipe):
            raise RuntimeError("failed to apply the concurrent Advanced recipe")
        seek_support.wait_until(
            app,
            lambda: (
                not page._advanced_preview_worker_running
                and page._advanced_preview_pending_job is None
                and page._visual_ownership.current.owner
                is VisualOwner.ADVANCED_FIDELITY
            ),
            20.0,
            "initial Fidelity warmup",
        )
        shared_style = page._cue_lookup[cues[0].id].style_id
        shared_effect = page._cue_lookup[cues[0].id].effect_id
        for cue in cues[1:]:
            page._cue_lookup[cue.id].style_id = shared_style
            page._cue_lookup[cue.id].effect_id = shared_effect

        progress("starting playback, Provider, autosave, Fidelity and yielded prefetch")
        page._seek((cues[0].start_ms + 350) / 1000.0)
        seek_support.wait_until(
            app, lambda: page.video._active_seek_trace is None, 4.0, "concurrent pre-seek",
        )
        seek_support.wait_pause(app, page, False)
        seek_support.wait_until(
            app, lambda: page._resource_governor.snapshot().playback, 2.0,
            "playback foreground state",
        )
        page._queue_advanced_prefetch([cue.id for cue in cues[1:]])
        baseline_pids = {int(item["pid"]) for item in child_rows(process)}
        provider_telemetry_start = len(GLOBAL_PROVIDER_SERVICE.telemetry())
        page.ai_prompt.setPlainText("清晰、有层次、适合游戏实况的动态字幕")
        page._request_ai_suggestion()
        seek_support.wait_until(
            app, lambda: bool(page._ai_request_active), 2.0, "AI Design active",
        )
        page._autosave()
        page._queue_advanced_preview(
            copy.deepcopy(page.project.style_recipes[shared_style]),
            force=True,
            delay_ms=0,
        )
        provider_child_observed = wait_for_provider_child(
            app, page, process, baseline_pids,
        )

        lag_index = probe.reset()
        targets = [
            (cues[index % len(cues)].start_ms + 250 + (index % 3) * 80) / 1000.0
            for index in range(SEEK_COUNT)
        ]
        seek_rows = []
        for index, target in enumerate(targets, 1):
            seek_rows.append(seek_support.perform_seek(
                app,
                page,
                probe,
                label="concurrent_playing_seek",
                index=index,
                target=target,
                paused=False,
            ))
            if index % 5 == 0 or index == SEEK_COUNT:
                progress(f"playing seek {index}/{SEEK_COUNT}")

        toggle_callbacks: list[float] = []
        toggle_settlements: list[float] = []
        for index in range(TOGGLE_COUNT):
            for paused in (True, False):
                started = time.perf_counter()
                page.video.set_paused(paused)
                toggle_callbacks.append((time.perf_counter() - started) * 1000.0)
                toggle_settlements.append(seek_support.wait_until(
                    app,
                    lambda paused=paused: bool(
                        page.video.controller.observed_property("pause", not paused)
                    ) == paused,
                    2.0,
                    f"pause/play {index + 1} pause={paused}",
                ))
            if (index + 1) % 5 == 0 or index + 1 == TOGGLE_COUNT:
                progress(f"pause/play cycle {index + 1}/{TOGGLE_COUNT}")

        select_callbacks: list[float] = []
        for index in range(12):
            cue = cues[index % len(cues)]
            started = time.perf_counter()
            page.select_cue(cue.id)
            select_callbacks.append((time.perf_counter() - started) * 1000.0)
            seek_support.pump(app, 20)

        page.select_cue(cues[0].id)
        before_start = page._cue_lookup[cues[0].id].start_ms
        nudge_started = time.perf_counter()
        page.cue_controller.nudge(33)
        nudge_ms = (time.perf_counter() - nudge_started) * 1000.0
        nudged_start = page._cue_lookup[cues[0].id].start_ms
        page.undo_stack.undo()

        gradient_recipe = style_recipe_for_prompt("霓虹黄蓝渐变，双层描边，强节奏动效")
        gradient_recipe.name = f"P73C Gradient {time.time_ns()}"
        gradient_started = time.perf_counter()
        gradient_applied = page._apply_style_recipe(cues[0].id, gradient_recipe)
        gradient_callback_ms = (time.perf_counter() - gradient_started) * 1000.0
        page._autosave()

        select_all_started = time.perf_counter()
        page._select_all_timeline_cues()
        select_all_callback_ms = (time.perf_counter() - select_all_started) * 1000.0
        seek_support.wait_until(
            app,
            lambda: "T6_event_loop_settled"
            in page.selection_latency_snapshot().get("markers_ms", {}),
            2.0,
            "Ctrl+A selection settlement",
        )
        selection_snapshot = copy.deepcopy(page.selection_latency_snapshot())

        progress("waiting for the real Provider result to be consumed by Studio")
        seek_support.wait_until(
            app,
            lambda: (
                not page._ai_request_active
                and page._pending_suggestion is not None
            ),
            50.0,
            "credentialed Studio AI Design",
        )
        suggestion = page._pending_suggestion
        provider_succeeded = bool(suggestion.provider_succeeded)
        provider_variant_count = len(suggestion.variants)
        provider_error_category = str(suggestion.provider_error_category or "")
        provider_stage_timings = dict(suggestion.stage_timings_ms)
        provider_telemetry = [
            dict(item)
            for item in GLOBAL_PROVIDER_SERVICE.telemetry()[provider_telemetry_start:]
        ]
        preview_complete_ms = seek_support.wait_until(
            app,
            lambda: len(page._ai_variant_preview_done)
            >= len(page._ai_variant_preview_labels) > 0,
            30.0,
            "AI Design Fidelity cards",
        )
        preview_complete = preview_complete_ms >= 0.0

        action_event_loop = probe.report_since(lag_index)
        global_result["actions"] = {
            "playing_seek": summarize_seek_rows(seek_rows),
            "pause_play_cycles": TOGGLE_COUNT,
            "pause_play_callback": stats(toggle_callbacks),
            "pause_play_settlement": stats(toggle_settlements),
            "select_callbacks": stats(select_callbacks),
            "cue_drag_equivalent": {
                "operation": "timeline timing nudge +33ms then Undo",
                "callback_ms": round(nudge_ms, 3),
                "before_start_ms": before_start,
                "nudged_start_ms": nudged_start,
                "restored_start_ms": page._cue_lookup[cues[0].id].start_ms,
            },
            "gradient_style": {
                "applied": gradient_applied,
                "callback_ms": round(gradient_callback_ms, 3),
                "recipe_name": gradient_recipe.name,
            },
            "ctrl_a": {
                "callback_ms": round(select_all_callback_ms, 3),
                "selection": selection_snapshot,
            },
        }
        global_result["provider_success_under_load"] = {
            "provider_succeeded": provider_succeeded,
            "variant_count": provider_variant_count,
            "provider_error_category": provider_error_category,
            "stage_events": stage_events,
            "stage_timings_ms": provider_stage_timings,
            "broker_telemetry": provider_telemetry,
            "provider_cli_child_observed": provider_child_observed,
            "studio_consumed_result": page._pending_suggestion is suggestion,
            "fidelity_card_count": len(page._ai_variant_preview_labels),
            "fidelity_cards_complete": preview_complete,
            "fidelity_cards_complete_ms": preview_complete_ms,
        }
        global_result["event_loop_under_actions"] = action_event_loop

        progress("starting a second Provider + Fidelity + autosave load for close")
        page.select_cue(cues[0].id)
        seek_support.wait_pause(app, page, False)
        close_baseline_pids = {int(item["pid"]) for item in child_rows(process)}
        page.ai_prompt.setPlainText("第二次并发关闭验证，不保存原始响应")
        page._request_ai_suggestion()
        seek_support.wait_until(
            app, lambda: bool(page._ai_request_active), 2.0, "second AI Design active",
        )
        close_provider_child = wait_for_provider_child(
            app, page, process, close_baseline_pids,
        )
        close_recipe = style_recipe_for_prompt("高对比洋红青色渐变，双层描边")
        close_recipe.name = f"P73C Close Load {time.time_ns()}"
        page._apply_style_recipe(cues[0].id, close_recipe)
        page._queue_advanced_preview(
            copy.deepcopy(
                page.project.style_recipes[page._cue_lookup[cues[0].id].style_id]
            ),
            force=True,
            delay_ms=0,
        )
        page.cue_controller.nudge(17)
        page._autosave()
        close_active_observed = seek_support.wait_until(
            app,
            lambda: (
                int(page._resource_governor.snapshot().active.get("AI", 0)) > 0
                and (
                    page._advanced_preview_worker_running
                    or page._advanced_preview_pending_job is not None
                )
            ),
            10.0,
            "Provider and Fidelity concurrent close load",
        )
        before_close_resource = resource_payload(page)
        close_lag_index = probe.reset()
        close_started = time.perf_counter()
        window.close()
        seek_support.pump(app, 1)
        close_visible_ms = (time.perf_counter() - close_started) * 1000.0
        hidden_after_response = not window.isVisible()
        cleanup_ms = seek_support.wait_until(
            app,
            lambda: bool(page._close_complete),
            12.0,
            "concurrent close cleanup",
        )
        seek_support.pump(app, 150)
        remaining_children = child_rows(process)
        global_result["close_under_concurrent_load"] = {
            "provider_cli_child_observed": close_provider_child,
            "provider_and_fidelity_observed": close_active_observed >= 0.0,
            "resource_before_close": before_close_resource,
            "visible_response_ms": round(close_visible_ms, 3),
            "window_hidden_after_response": hidden_after_response,
            "cleanup_complete_ms": cleanup_ms,
            "profile": dict(page.last_close_profile),
            "remaining_children": remaining_children,
            "event_loop": probe.report_since(close_lag_index),
        }
        sampler.stop()
        global_result["resource_governor"] = sampler.report()
        global_result["recent_runtime_events"] = list(GLOBAL_STUDIO_TRACE.recent())[-160:]

        seek_summary = global_result["actions"]["playing_seek"]
        resource_report = global_result["resource_governor"]
        close_report = global_result["close_under_concurrent_load"]
        action_thresholds = action_event_loop["threshold_counts"]
        all_thresholds = {
            str(limit): sum(
                float(row["lateness_ms"]) > limit for row in probe.samples
            )
            for limit in probe.THRESHOLDS
        }
        global_result["event_loop_all"] = {
            "sample_count": len(probe.samples),
            "max_ms": round(max(
                (float(row["lateness_ms"]) for row in probe.samples), default=0.0,
            ), 3),
            "threshold_counts": all_thresholds,
            "stalls": probe.stalls,
        }
        global_result["checks"] = {
            "provider_success_consumed_by_studio": (
                provider_succeeded and provider_variant_count == 3
            ),
            "provider_cli_child_observed": provider_child_observed,
            "fidelity_cards_complete": bool(preview_complete),
            "playing_seek_20_settled": seek_summary["settled_count"] == SEEK_COUNT,
            "playing_seek_20_t8": seek_summary["t8_pass_count"] == SEEK_COUNT,
            "seek_feedback_p95_lt_50": float(
                seek_summary["T0_T2"]["p95_ms"] or 9999
            ) < 50.0,
            "seek_first_frame_p95_lt_200": float(
                seek_summary["T0_T5"]["p95_ms"] or 9999
            ) < 200.0,
            "seek_playable_p95_lt_300": float(
                seek_summary["T0_T7"]["p95_ms"] or 9999
            ) < 300.0,
            "pause_play_callbacks_p95_lt_50": float(
                global_result["actions"]["pause_play_callback"]["p95_ms"] or 9999
            ) < 50.0,
            "gradient_style_applied": bool(gradient_applied),
            "ctrl_a_settled": "T6_event_loop_settled"
            in selection_snapshot.get("markers_ms", {}),
            "autosave_active_observed": bool(resource_report["observed_autosave_active"]),
            "provider_ai_lease_observed": bool(resource_report["observed_ai_active"]),
            "fidelity_foreground_lease_observed": bool(
                resource_report["observed_fidelity_foreground"]
            ),
            "background_yield_observed": sum(
                int(value) for value in resource_report["yield_counts"].values()
            ) > 0,
            "no_action_freeze_over_500": action_thresholds["500"] == 0,
            "no_freeze_over_1000": all_thresholds["1000"] == 0,
            "close_provider_cli_child_observed": close_provider_child,
            "close_response_lt_100": close_visible_ms < 100.0,
            "close_window_hidden": hidden_after_response,
            "close_cleanup_complete": bool(page._close_complete),
            "close_provider_idle": close_report["profile"].get("provider_idle") is True,
            "close_proxy_idle": close_report["profile"].get("proxy_idle") is True,
            "close_waveform_threads_zero": int(
                close_report["profile"].get("waveform_threads_alive", -1)
            ) == 0,
            "no_remaining_children": not remaining_children,
        }
        global_result["pass"] = all(global_result["checks"].values())
    except Exception as exc:
        global_result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        global_result["traceback"] = traceback.format_exc()
        global_result["pass"] = False
        if sampler is not None:
            try:
                sampler.stop()
                global_result["resource_governor"] = sampler.report()
            except Exception:
                pass
    finally:
        if window is not None and window.isVisible():
            try:
                window.close()
                seek_support.pump(app, 20)
                if page is not None:
                    seek_support.wait_until(
                        app, lambda: bool(page._close_complete), 12.0,
                        "failure cleanup",
                    )
            except Exception as exc:
                global_result["cleanup_error"] = f"{type(exc).__name__}: {exc}"

    target = OUTPUT / "runtime-result.json"
    target.write_text(
        json.dumps(global_result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(target, flush=True)
    print(json.dumps({
        "pass": global_result.get("pass"),
        "constructor_ms": global_result.get("constructor_ms"),
        "first_project_usable_ms": global_result.get("first_project_usable_ms"),
        "provider_success_under_load": global_result.get("provider_success_under_load"),
        "actions": global_result.get("actions"),
        "resource_governor": global_result.get("resource_governor"),
        "close_under_concurrent_load": global_result.get("close_under_concurrent_load"),
        "event_loop_all": global_result.get("event_loop_all"),
        "checks": global_result.get("checks"),
        "fatal_error": global_result.get("fatal_error"),
    }, ensure_ascii=False, indent=2, default=str), flush=True)
    return 0 if global_result.get("pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())
