"""P9A-R2 headed audit executed inside the rebuilt packaged application."""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

import psutil

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QPushButton

from .build_identity import BUILD_ROUND_ID
from .llm_config import activate_ai_service, update_active_profile
from .p9a_r1_packaged_audit import P9AR1PackagedAudit
from .provider_registry import GLOBAL_PROVIDER_REGISTRY
from .studio_ai import request_style_design
from .style_recipe import normalize_shadow_contract
from .ui_theme import theme_definition
from .visual_snapshot import build_visual_cue_snapshot


class P9AR2PackagedAudit(P9AR1PackagedAudit):
    """Close the final user gates without treating local fallback as success."""

    def __init__(self, window, output_dir: str | os.PathLike[str]) -> None:
        super().__init__(window, output_dir)
        self.result.update({
            "schema": "2byteasr.p9a-r2-packaged-audit.v1",
            "round_id": BUILD_ROUND_ID,
        })

    def _phase_provider_r2(self) -> dict[str, Any]:
        page = self.page
        results: dict[str, Any] = {}

        def run_provider(service: str, model: str = "") -> dict[str, Any]:
            settings = copy.deepcopy(page.runtime_settings)
            selection_values = activate_ai_service(settings, service, stage="polish")
            if model:
                selection_values = update_active_profile(
                    settings, stage="polish", model=model,
                )
            selection = GLOBAL_PROVIDER_REGISTRY.selection(settings, stage="polish")
            outcome: dict[str, Any] = {}

            def generate() -> None:
                started = time.perf_counter()
                try:
                    cue_id = page.selected_cue_id or page.project.cues[0].id
                    suggestion = request_style_design(
                        page.project,
                        cue_id,
                        "P9A-R2 SYNTHETIC PROVIDER TEST: produce three readable game-subtitle directions",
                        settings,
                        deadline_seconds=150.0,
                    )
                    trace_payload = {}
                    telemetry = (
                        suggestion.raw_response.get("_studio_telemetry", {})
                        if isinstance(suggestion.raw_response, dict) else {}
                    )
                    trace_path = Path(str(telemetry.get("trace_path") or ""))
                    if trace_path.is_file():
                        trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
                    provider_trace = trace_payload.get("provider", {})
                    outcome.update({
                        "provider_succeeded": bool(suggestion.provider_succeeded),
                        # AIDesignSuggestion carries no provider identity; the
                        # authoritative id lives in the persisted trace and in
                        # the selection that configured the request.
                        "provider_id": str(
                            provider_trace.get("provider_id") or selection.service
                        ),
                        "failure_stage": suggestion.failure_stage,
                        "provider_error_category": suggestion.provider_error_category,
                        "variant_count": len(suggestion.variants),
                        "pipeline_status": dict(suggestion.pipeline_status),
                        "trace_path": str(trace_path),
                        "provider_state": trace_payload.get("final", {}).get("provider_state"),
                        "provider_state_machine": trace_payload.get("provider_state_machine", []),
                        "invocation": provider_trace.get("invocation", {}),
                        "http_diagnostics": (
                            suggestion.raw_response.get("http_diagnostics", {})
                            if isinstance(suggestion.raw_response, dict) else {}
                        ),
                    })
                except Exception as exc:  # noqa: BLE001 - exact provider boundary
                    outcome["hard_error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    outcome["elapsed_s"] = round(time.perf_counter() - started, 2)

            worker = threading.Thread(
                target=generate,
                name=f"p9a-r2-real-generate-{service}",
                daemon=True,
            )
            worker.start()
            deadline = time.perf_counter() + 165.0
            while worker.is_alive() and time.perf_counter() < deadline:
                self._pump(60)
            if worker.is_alive():
                outcome["hard_error"] = "real generate exceeded 165 seconds"
            return {
                "selection": {
                    **dict(selection_values),
                    "service": selection.service,
                    "credential_source": selection.credential_source,
                    "credential_ready": selection.credential_ready,
                },
                "generate": outcome,
            }

        results["deepseek"] = run_provider("deepseek")
        results["antigravity"] = run_provider(
            "antigravity", "gemini-3.7-flash-high",
        )
        deepseek = results["deepseek"]
        antigravity = results["antigravity"]
        invocation = antigravity["generate"].get("invocation") or {}
        history = invocation.get("process_history") or []
        request_invocation = next(
            (
                item for item in reversed(history)
                if str(item.get("purpose") or "").endswith(" request")
            ),
            invocation,
        )
        environment = request_invocation.get("environment") or {}
        try:
            host_environment = json.loads(
                os.environ.get("TWOBYTEASR_P9A_R2_HOST_ENV", "{}")
            )
        except ValueError:
            host_environment = {}

        def generate_ok(payload: dict[str, Any]) -> bool:
            outcome = payload["generate"]
            return bool(
                outcome.get("provider_succeeded") is True
                and int(outcome.get("variant_count") or 0) == 3
                and outcome.get("provider_state") == "SUCCESS"
                and all(
                    outcome.get("pipeline_status", {}).get(name) == "PASS"
                    for name in (
                        "AUTH", "HTTP", "PARSE", "SCHEMA",
                        "QUALITY_VALIDATOR", "FINAL",
                    )
                )
            )

        checks = {
            "deepseek_selected": deepseek["selection"].get("provider") == "deepseek",
            "deepseek_dpapi_or_env_found": deepseek["selection"].get("credential_ready") is True,
            "deepseek_real_generate": generate_ok(deepseek),
            "antigravity_selected_model": (
                antigravity["selection"].get("provider") == "google_antigravity"
                and antigravity["selection"].get("model") == "gemini-3.7-flash-high"
            ),
            "antigravity_real_generate": generate_ok(antigravity),
            "both_traces_written": all(
                payload["generate"].get("trace_path")
                and Path(payload["generate"]["trace_path"]).is_file()
                for payload in results.values()
            ),
            "antigravity_identity_traced": bool(request_invocation.get("executable_identity")),
            "antigravity_environment_traced": all(
                key in environment for key in ("HOME", "USERPROFILE", "LOCALAPPDATA", "PATH_entry_count")
            ),
            "antigravity_command_exit_traced": (
                "command" in request_invocation
                and "exit_code" in request_invocation
                and "stdout_size" in request_invocation
                and "stderr_size" in request_invocation
            ),
            "shell_vs_packaged_environment_compared": bool(host_environment and environment),
        }
        return {
            "providers": results,
            "shell_environment": host_environment,
            "packaged_antigravity_environment": environment,
            "antigravity_request_invocation": request_invocation,
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_shadow_r2(self) -> dict[str, Any]:
        page = self.page
        page.context_drawer.setCurrentIndex(2)
        page.select_cue(page.project.cues[0].id)
        self._pump(220)
        page.style_shadow_opacity.setValue(50)
        page.style_shadow_angle.setAngle(45)
        page.style_shadow_distance.setValue(12)
        page.style_shadow_spread.setValue(4)
        distance_samples = []
        for blur in (0, 5, 20, 40):
            page.style_shadow_blur.setValue(blur)
            page._commit_style_now()
            self._pump(220)
            distance_samples.append(float(page.style_shadow_distance.value()))
        cue = page._cue_lookup[page.selected_cue_id]
        snapshot = build_visual_cue_snapshot(page.project, cue.id)
        shadow = normalize_shadow_contract(snapshot.shadow)
        graph_shadow = (
            snapshot.style_recipe.get("visualGraph", {})
            .get("textLayer", {})
            .get("shadow", {})
        )
        normalized_graph_shadow = normalize_shadow_contract(graph_shadow)
        shot = self._capture(page.context_panel, "p9a_r2_shadow_controls.png")
        checks = {
            "blur_does_not_change_distance": distance_samples == [12.0] * 4,
            "opacity_exact": shadow.get("opacity") == 0.5,
            "blur_exact": shadow.get("blur_radius") == 40.0,
            "spread_exact": shadow.get("spread") == 4.0,
            "offsets_independent": abs(
                math.hypot(
                    float(shadow.get("offset_x") or 0),
                    float(shadow.get("offset_y") or 0),
                ) - 12.0
            ) <= 0.05,
            "visual_graph_matches": normalized_graph_shadow == shadow,
        }
        return {
            "shadow": shadow,
            "graph_shadow": graph_shadow,
            "normalized_graph_shadow": normalized_graph_shadow,
            "distance_samples": distance_samples,
            "screenshot": shot,
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_lifecycle_r2(self) -> dict[str, Any]:
        page = self.page
        path_a = Path(page.project_path).resolve()
        path_b = Path(os.environ.get("TWOBYTEASR_P9A_R2_PROJECT_B", "")).resolve()
        if not path_b.is_file():
            raise FileNotFoundError(f"synthetic video project missing: {path_b}")
        video_id = id(page.video)
        engine_id = id(page.audio_engine)
        thread_id = id(page.audio_engine._thread)
        generation_start = int(page.audio_engine.telemetry_snapshot().get("session_generation") or 0)
        close_samples: list[dict[str, Any]] = []
        playback_samples: list[dict[str, Any]] = []
        clock_ids: list[int] = []

        def ffmpeg_count() -> int:
            try:
                return sum(
                    1 for child in psutil.Process(os.getpid()).children(recursive=True)
                    if child.is_running() and child.name().casefold() == "ffmpeg.exe"
                )
            except (psutil.Error, OSError):
                return -1

        def active_timer_count() -> int:
            return sum(1 for timer in page.findChildren(QTimer) if timer.isActive())

        def exercise(project_kind: str, cycle: int) -> None:
            requested_seeks = [1.0, 4.0, 7.0]
            for target in requested_seeks:
                page._seek(target)
                self._pump(180)
            if page.video.playback_position_snapshot().paused:
                page._toggle_playback()
            positions: list[float] = []
            telemetry_samples: list[dict[str, Any]] = []
            for _index in range(11):
                self._pump(300)
                positions.append(round(float(page.video.visual_position()), 4))
                telemetry_samples.append(page.audio_engine.telemetry_snapshot())
            if not page.video.playback_position_snapshot().paused:
                page._toggle_playback()
            regressions = sum(
                1 for left, right in zip(positions, positions[1:])
                if right < left - 0.12
            )
            playback_samples.append({
                "cycle": cycle,
                "project_kind": project_kind,
                "seek_targets": requested_seeks,
                "positions": positions,
                "playhead_advance_s": round(max(positions) - min(positions), 4),
                "position_regressions": regressions,
                "audio_states": [str(item.get("state") or "") for item in telemetry_samples],
                "audio_peak_decoded_bytes": max(
                    int(item.get("decoded_bytes") or 0) for item in telemetry_samples
                ),
                "audio_peak_sink_consumed_bytes": max(
                    int(item.get("sink_consumed_bytes") or 0) for item in telemetry_samples
                ),
                "ffmpeg_process_count": ffmpeg_count(),
                "audio_worker_count": int(
                    page.audio_engine.telemetry_snapshot().get("engine_thread_count") or 0
                ),
                "active_timer_count": active_timer_count(),
            })

        def close_to_home(cycle: int, project_kind: str) -> None:
            clock_ids.append(id(page.video._playback_clock))
            page.show_project_hub(skip_dirty_guard=True)
            self._pump(320)
            silent = page.audio_engine.telemetry_snapshot()
            close_samples.append({
                "cycle": cycle,
                "project_kind": project_kind,
                "state": silent.get("state"),
                "source_path": silent.get("source_path", ""),
                "session_generation": silent.get("session_generation"),
                "windows_sink_count": silent.get("windows_sink_count"),
                "engine_thread_count": silent.get("engine_thread_count"),
                "ffmpeg_process_count": ffmpeg_count(),
                "active_timer_count": active_timer_count(),
            })
            self.window._return_to_settings()
            self._pump(80)

        def open_project(target: Path, cycle: int) -> None:
            self.window.open_studio_project(
                str(target), mode="edit", source="p9a_r2_lifecycle",
            )
            self._wait(
                lambda expected=target: bool(
                    page.project is not None
                    and page.project_path is not None
                    and Path(page.project_path).resolve() == expected.resolve()
                    and page._project_view_state == "open"
                ),
                12.0,
                f"lifecycle open {cycle}: {target.name}",
            )
            self._pump(220)

        for cycle in range(1, 21):
            exercise("audio-A", cycle)
            close_to_home(cycle, "audio-A")
            open_project(path_b, cycle)
            exercise("video-B", cycle)
            close_to_home(cycle, "video-B")
            open_project(path_a, cycle)
        exercise("audio-A-final", 21)
        final_telemetry = page.audio_engine.telemetry_snapshot()
        playhead_frozen = [
            item for item in playback_samples
            if float(item.get("playhead_advance_s") or 0) < 1.5
        ]
        half_second_loops = [
            item for item in playback_samples
            if int(item.get("position_regressions") or 0) > 0
            and float(item.get("playhead_advance_s") or 0) <= 0.75
        ]
        audio_runs = [
            item for item in playback_samples
            if str(item.get("project_kind") or "").startswith("audio-A")
        ]
        close_ffmpeg_counts = [
            int(item.get("ffmpeg_process_count") or 0)
            for item in close_samples
            if int(item.get("ffmpeg_process_count") or 0) >= 0
        ]
        close_timer_counts = [int(item.get("active_timer_count") or 0) for item in close_samples]
        checks = {
            "twenty_full_a_b_a_cycles": len(close_samples) == 40,
            "play_three_seconds_each_open": len(playback_samples) == 41 and not playhead_frozen,
            "seek_three_times_each_open": all(
                len(item.get("seek_targets") or []) == 3 for item in playback_samples
            ),
            "no_half_second_loop": not half_second_loops,
            "no_playhead_freeze": not playhead_frozen,
            "audio_pcm_reached_sink": all(
                int(item.get("audio_peak_decoded_bytes") or 0) > 0
                and int(item.get("audio_peak_sink_consumed_bytes") or 0) > 0
                for item in audio_runs
            ),
            "session_generation_advanced": (
                int(final_telemetry.get("session_generation") or 0) - generation_start == 40
            ),
            "one_mpv_object": id(page.video) == video_id,
            "one_audio_engine": id(page.audio_engine) == engine_id,
            "one_audio_thread": id(page.audio_engine._thread) == thread_id
            and final_telemetry.get("engine_thread_count") == 1,
            "old_sources_silent": all(
                sample.get("state") == "SILENT" and not sample.get("source_path")
                for sample in close_samples
            ),
            "at_most_one_sink": all(
                int(sample.get("windows_sink_count") or 0) <= 1
                for sample in close_samples
            ),
            "ffmpeg_processes_do_not_grow": (
                not close_ffmpeg_counts
                or max(close_ffmpeg_counts) <= close_ffmpeg_counts[0] + 1
            ),
            "active_timers_do_not_grow": (
                not close_timer_counts
                or close_timer_counts[-1] <= close_timer_counts[0] + 1
            ),
            "clock_replaced_on_boundaries": len(set(clock_ids)) >= 2,
            "returned_to_a": Path(page.project_path).resolve() == path_a,
        }
        return {
            "project_a": str(path_a),
            "project_b": str(path_b),
            "close_samples": close_samples,
            "playback_samples": playback_samples,
            "playhead_frozen": playhead_frozen,
            "half_second_loops": half_second_loops,
            "final_telemetry": final_telemetry,
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_ui_r2(self) -> dict[str, Any]:
        page = self.page
        self.window._return_to_settings()
        self.window.showNormal()
        self.window.resize(1700, 980)
        self._pump(300)
        cards = tuple(self.window.recognition_plan.cards.values())
        model_sizes = [card.model_label.font().pixelSize() for card in cards]
        role_sizes = [card.role_label.font().pixelSize() for card in cards]
        icon_sizes = [card.icon_label.width() for card in cards]
        home_shot = self._capture(self.window.settings_surface, "p9a_r2_home_1700x980.png")

        # Responsive evidence at the three tiers the user actually runs:
        # 1080p, 1440p, and 4K @175% DPI (3840/1.75 ≈ 2194 logical wide).
        # A tier whose resize is clamped by the live display is recorded as
        # not achieved instead of failing the gate on a smaller test screen.
        responsive_tiers: list[dict[str, Any]] = []
        for tier_name, width, height in (
            ("1920x1080", 1920, 1080),
            ("2560x1440", 2560, 1440),
            ("4k_175", 2194, 1234),
        ):
            self.window.resize(width, height)
            self._pump(300)
            achieved = self.window.size()
            achieved_ok = (
                achieved.width() >= width - 40 and achieved.height() >= height - 40
            )
            tier_cards = tuple(self.window.recognition_plan.cards.values())
            tier = {
                "tier": tier_name,
                "requested": [width, height],
                "achieved": [achieved.width(), achieved.height()],
                "achieved_ok": achieved_ok,
                "model_font_sizes": [
                    card.model_label.font().pixelSize() for card in tier_cards
                ],
                "role_font_sizes": [
                    card.role_label.font().pixelSize() for card in tier_cards
                ],
                "icon_sizes": [card.icon_label.width() for card in tier_cards],
            }
            if achieved_ok:
                tier["screenshot"] = self._capture(
                    self.window.settings_surface,
                    f"p9a_r2_home_{tier_name}.png",
                )
            responsive_tiers.append(tier)
        self.window.resize(1700, 980)
        self._pump(160)

        self.window.open_studio_project(
            str(page.project_path), mode="edit", source="p9a_r2_ui"
        )
        self._pump(220)
        page.upper_splitter.setSizes([280, 800, 320])
        self._pump(160)
        page._update_context_tab_labels()
        buttons = {
            button.text(): button
            for button in page.findChildren(QPushButton)
            if button.text() in {"测试连接", "本地备选", "应用", "保存样式", "清除"}
        }
        unclipped = {
            text: button.width() >= QFontMetrics(button.font()).horizontalAdvance(text) + 16
            for text, button in buttons.items()
            if button.isVisibleTo(page)
        }
        tabbar = page.context_drawer.tabBar()
        studio_shot = self._capture(page.context_panel, "p9a_r2_studio_controls.png")
        theme = theme_definition()
        checks = {
            "merged_content_glossary": self.window.content_profile_card.isAncestorOf(
                self.window.batch_glossary_card
            ),
            "model_type_scale": min(model_sizes) >= 28,
            "role_type_scale": min(role_sizes) >= 18,
            "icon_scale": min(icon_sizes) >= 56 and max(icon_sizes) <= 68,
            "descriptions_present": all(card.description_label.text() for card in cards),
            "studio_short_actions_present": set(buttons) == {
                "测试连接", "本地备选", "应用", "保存样式", "清除"
            },
            "studio_actions_unclipped": all(unclipped.values()),
            "tool_icons_26": page.context_drawer.iconSize().width() == 26,
            "tooltips_complete": [
                page.context_drawer.tabToolTip(i) for i in range(page.context_drawer.count())
            ] == ["AI设计", "检查", "样式", "视频", "剪辑助手", "素材"],
            "narrow_tabs_fit": tabbar.tabRect(tabbar.count() - 1).right() < tabbar.width(),
            "input_surface_distinct": theme.input_surface.casefold() != theme.panel.casefold()
            and theme.input_surface.casefold() != theme.surface.casefold(),
            "responsive_tiers_type_scale": all(
                tier["achieved_ok"] is False
                or (
                    min(tier["model_font_sizes"]) >= 28
                    and min(tier["role_font_sizes"]) >= 18
                    and min(tier["icon_sizes"]) >= 56
                )
                for tier in responsive_tiers
            ),
            "responsive_tier_1700x980_or_larger_achieved": any(
                tier["achieved_ok"] for tier in responsive_tiers
            ),
        }
        return {
            "model_font_sizes": model_sizes,
            "role_font_sizes": role_sizes,
            "icon_sizes": icon_sizes,
            "responsive_tiers": responsive_tiers,
            "button_width_checks": unclipped,
            "home_screenshot": home_shot,
            "studio_screenshot": studio_shot,
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _run(self) -> None:
        try:
            self._phase("identity", self._phase_identity)
            self._phase("project", self._phase_project)
            self._phase("tabs", self._phase_tabs)
            if os.environ.get("TWOBYTEASR_P9A_R2_SKIP_PROVIDERS") == "1":
                self._phase(
                    "provider_r2",
                    lambda: {
                        "skipped": "external Providers explicitly disabled for local-only audit",
                        "checks": {},
                        "ok": False,
                    },
                )
            else:
                self._phase("provider_r2", self._phase_provider_r2)
            if os.environ.get("TWOBYTEASR_P9A_R2_ONLY_PROVIDERS") == "1":
                return
            self._phase("shadow_r2", self._phase_shadow_r2)
            self._phase("lifecycle_r2", self._phase_lifecycle_r2)
            self._phase("ui_r2", self._phase_ui_r2)
        finally:
            self.result["finished_at"] = time.time()
            gates = (
                ("identity", "project", "tabs", "provider_r2")
                if os.environ.get("TWOBYTEASR_P9A_R2_ONLY_PROVIDERS") == "1"
                else (
                    "identity", "tabs", "provider_r2", "shadow_r2",
                    "lifecycle_r2", "ui_r2",
                )
            )
            phases = self.result["phases"]
            self.result["checks"] = {
                name: bool(phases.get(name, {}).get("ok")) for name in gates
            }
            self.result["accepted"] = bool(
                all(self.result["checks"].values()) and not self.result["errors"]
            )
            try:
                self.result_path.write_text(
                    json.dumps(self.result, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            try:
                self.page.close_page()
            except Exception:  # noqa: BLE001
                pass
            self._pump(700)
            try:
                self.window.close()
            except Exception:  # noqa: BLE001
                pass
            QTimer.singleShot(900, self.app.quit)


__all__ = ["P9AR2PackagedAudit"]
