"""P7.3B persistent renderer/provider runtime evidence.

This is automated runtime evidence. It is never user-click acceptance.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-live", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


ARGS = arguments()
RUN = ARGS.output or ROOT / "tmp" / "p73b" / ("services-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
RUN.mkdir(parents=True, exist_ok=False)
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(RUN / "child-processes.jsonl")

import psutil

from twobyteasr.advanced_preview import AdvancedPreviewCache
from twobyteasr.ai_providers import AIProviderError, provider_for_stage
from twobyteasr.renderer_service import RendererJob, RendererService, RendererServiceError
from twobyteasr.settings import load_runtime_settings
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
)
from twobyteasr.style_recipe import FillSpec, normalize_glow_contract, normalize_shadow_contract
from twobyteasr.visual_snapshot import build_visual_cue_snapshot


def ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def recipe(name: str, *, motion: bool = False, color_a: str = "#FF168BFF", color_b: str = "#FFFFD84A"):
    motion_payload = {"mode": "none"}
    if motion:
        motion_payload = {
            "mode": "explicit",
            "entrance": {"type": "pop", "duration_ms": 260, "amplitude": 0.18},
            "hold": {"type": "pulse", "amplitude": 0.06, "frequency": 1.4},
            "exit": {"type": "fade", "duration_ms": 180},
        }
    return {
        "name": name,
        "engine": "remotion",
        "typography": {"fontFamily": "Microsoft YaHei UI", "fontSize": 104, "bold": True},
        "colors": {"fill": FillSpec.linear([
            {"color": color_a, "position": 0.0},
            {"color": color_b, "position": 1.0},
        ]).to_dict()},
        "outline": {
            "width": 4,
            "layers": [{"color": "#FF071018", "width": 5.0, "opacity": 1.0}],
            "shadow": normalize_shadow_contract(1.0),
        },
        "background": {},
        "effects": {"glow": normalize_glow_contract({
            "enabled": True, "color": "#FF00FFFF", "radius": 10,
            "opacity": 0.72, "intensity": 1.0,
        })},
        "layout": {},
        "motion": motion_payload,
        "ass": {},
    }


def snapshot_fixture():
    project = SubtitleProject(
        media=StudioMedia("fixture.mp4", duration_ms=2400, width=640, height=360),
        cues=[StudioCue("renderer-base", 0, 2400, "PERSISTENT FIDELITY", style_id="advanced")],
        speakers=[StudioSpeaker("S00", "Speaker")],
        styles=[
            SubtitleStyle("default", "Default"),
            SubtitleStyle(
                "advanced", "Advanced", font_family="Microsoft YaHei UI",
                font_size=104, bold=True, position_x=960, position_y=540,
            ),
        ],
        style_recipes={"advanced": recipe("P7.3B", motion=True)},
    )
    project.validate()
    return build_visual_cue_snapshot(project, "renderer-base", width=640, height=240, fps=30.0)


def renderer_evidence():
    service = RendererService()
    cache = AdvancedPreviewCache(RUN / "cache", renderer_service=service)
    base = snapshot_fixture()
    process = psutil.Process()
    before_rss = process.memory_info().rss
    result: dict[str, object] = {}
    try:
        started = time.perf_counter()
        cold = cache.render_snapshot(
            base, force=True, relative_ms=300, width=640, height=240,
            generation=1, batch_group="benchmark-cold",
        )
        result["cold_still_ms"] = ms(started)
        first_pid = service.process_id

        warm_snapshot = replace(base, cue_id="renderer-warm", text="WARM FIDELITY")
        started = time.perf_counter()
        warm = cache.render_snapshot(
            warm_snapshot, force=True, relative_ms=300, width=640, height=240,
            generation=2, batch_group="benchmark-warm",
        )
        result["warm_still_ms"] = ms(started)
        result["same_service_pid"] = first_pid == service.process_id
        result["service_pid"] = service.process_id
        result["artifact_sizes"] = [cold[1].stat().st_size, warm[1].stat().st_size]

        cards = [
            replace(
                base,
                cue_id=f"card-{index}",
                text=f"STYLE {index + 1}",
                style_recipe=recipe(
                    f"Card {index + 1}",
                    color_a=("#FF168BFF", "#FFFF4D7D", "#FF45D483")[index],
                    color_b=("#FFFFD84A", "#FFFFFFFF", "#FF8C6BFF")[index],
                ),
            )
            for index in range(3)
        ]
        started = time.perf_counter()
        card_results = cache.render_snapshot_batch(
            [(item, 300, 640, 240) for item in cards],
            force=True,
            generation=3,
            batch_group="benchmark-cards",
            render_type="style_cards",
        )
        result["three_cards_ms"] = ms(started)
        result["three_cards_count"] = len(card_results)
        result["three_card_hashes"] = [
            hashlib.sha256(item[1].read_bytes()).hexdigest()
            for item in card_results
        ]
        result["three_cards_visually_distinct"] = (
            len(set(result["three_card_hashes"])) == len(card_results)
        )

        started = time.perf_counter()
        motion_results = cache.render_snapshot_batch(
            [(base, frame_ms, 640, 240) for frame_ms in (0, 90, 220, 520, 1120, 2050, 2350)],
            force=True,
            generation=4,
            batch_group="benchmark-motion",
            render_type="motion_frames",
        )
        result["seven_motion_frames_ms"] = ms(started)
        result["seven_motion_frames_count"] = len(motion_results)

        service.inject_failure("browser_crash")
        browser_generation_before = max(
            [int(item.get("renderer_generation") or 0) for item in service.telemetry()] or [0]
        )
        cache.render_snapshot(
            replace(base, cue_id="browser-recovery", text="BROWSER RECOVERY"),
            force=True, generation=5, batch_group="browser-recovery",
        )
        browser_generation_after = max(
            [int(item.get("renderer_generation") or 0) for item in service.telemetry()] or [0]
        )
        result["browser_crash_recovered"] = browser_generation_after > browser_generation_before

        node_pid = service.process_id
        service.inject_failure("node_crash")
        cache.render_snapshot(
            replace(base, cue_id="node-recovery", text="NODE RECOVERY"),
            force=True, generation=6, batch_group="node-recovery",
        )
        result["node_crash_recovered"] = service.process_id not in {None, node_pid}

        malformed_detected = False
        malformed_pid = service.process_id
        try:
            service.inject_failure("malformed_response")
        except RendererServiceError:
            malformed_detected = True
        cache.render_snapshot(
            replace(base, cue_id="protocol-recovery", text="PROTOCOL RECOVERY"),
            force=True, generation=7, batch_group="protocol-recovery",
        )
        result["malformed_response_recovered"] = malformed_detected and service.process_id != malformed_pid

        props, duration = cache._snapshot_props(base, width=640, height=240)
        latest_a = RendererJob(str(RUN / "latest-a.png"), props, min(duration - 1, 5))
        latest_b = RendererJob(str(RUN / "latest-b.png"), props, min(duration - 1, 6))
        first = service.submit(
            [latest_a], generation=8, snapshot_identity="latest-a",
            batch_group="latest-wins", timeout=30.0,
        )
        second = service.submit(
            [latest_b], generation=9, snapshot_identity="latest-b",
            batch_group="latest-wins", timeout=30.0,
        )
        stale_rejected = False
        try:
            first.result(35.0)
        except RendererServiceError:
            stale_rejected = True
        second_result = second.result(35.0)
        result["latest_wins"] = stale_rejected and bool(second_result.outputs)

        cancel_job = RendererJob(str(RUN / "cancelled.png"), props, min(duration - 1, 7))
        cancel_handle = service.submit(
            [cancel_job], generation=10, snapshot_identity="cancel",
            batch_group="cancel", timeout=30.0,
        )
        cancel_started = time.perf_counter()
        cancel_handle.cancel()
        cancelled = False
        try:
            cancel_handle.result(5.0)
        except RendererServiceError:
            cancelled = True
        result["cancelled"] = cancelled
        result["cancel_ms"] = ms(cancel_started)

        result["service_generations"] = service.service_generation
        result["telemetry"] = list(service.telemetry())
        result["rss_delta_mb"] = round((process.memory_info().rss - before_rss) / (1024 * 1024), 3)
        children = []
        for child in process.children(recursive=True):
            try:
                children.append({
                    "pid": child.pid,
                    "name": child.name(),
                    "rss_mb": round(child.memory_info().rss / (1024 * 1024), 3),
                    "threads": child.num_threads(),
                })
            except (psutil.Error, OSError):
                continue
        result["live_children"] = children
    finally:
        service.shutdown()
    result["targets"] = {
        "warm_still_under_300ms": float(result.get("warm_still_ms", 1e9)) < 300.0,
        "three_cards_under_2s": float(result.get("three_cards_ms", 1e9)) < 2000.0,
        "three_cards_visually_distinct": bool(result.get("three_cards_visually_distinct")),
        "seven_frames_under_2s": float(result.get("seven_motion_frames_ms", 1e9)) < 2000.0,
    }
    return result


def provider_evidence():
    loaded = load_runtime_settings()
    settings = loaded[0] if isinstance(loaded, tuple) else loaded
    provider = provider_for_stage(settings, "polish")
    started = time.perf_counter()
    status = provider.validate(timeout=8.0, use_cache=False)
    result: dict[str, object] = {
        "provider_id": provider.provider_id,
        "transport": provider.transport.value,
        "health_ms": ms(started),
        "available": status.available,
        "authenticated": status.authenticated,
        "message": status.message,
        "models": list(status.models),
        "capabilities": provider.capabilities().__dict__,
        "live_requested": bool(ARGS.provider_live),
        "request_status": "NOT VERIFIED",
        "cancel_status": "NOT VERIFIED",
    }
    timed_out_health = "timed out" in status.message.casefold() or "超时" in status.message
    if ARGS.provider_live and status.available and (status.authenticated or timed_out_health):
        request_started = time.perf_counter()
        try:
            response = provider.complete(
                [{"role": "user", "content": "Return exactly: 2ByteASR_OK"}],
                max_tokens=32,
                temperature=0.0,
                timeout=30.0,
                stage="p73b_provider_acceptance",
            ).strip()
            result["request_status"] = "VERIFIED" if response == "2ByteASR_OK" else "INVALID_RESPONSE"
            result["request_response"] = response[:80]
        except Exception as exc:
            result["request_status"] = "FAILED"
            result["request_error"] = str(exc)
        result["request_ms"] = ms(request_started)
        cancel_started = time.perf_counter()
        try:
            handle = provider.submit(
                [{"role": "user", "content": "Return exactly: CANCEL_TEST"}],
                max_tokens=32,
                temperature=0.0,
                timeout=30.0,
                stage="p73b_cancel_acceptance",
            )
            time.sleep(0.25)
            handle.cancel()
            handle.result(5.0)
            result["cancel_status"] = "COMPLETED_BEFORE_CANCEL"
        except AIProviderError as exc:
            result["cancel_status"] = "VERIFIED" if exc.category == "cancelled" else "FAILED"
            result["cancel_category"] = exc.category
        except Exception as exc:
            result["cancel_status"] = "FAILED"
            result["cancel_error"] = str(exc)
        result["cancel_ms"] = ms(cancel_started)

    grok_settings = copy.deepcopy(settings)
    grok_models = grok_settings.setdefault("models", {})
    grok_models["polish_transport"] = "grok_cli"
    grok_models["polish_provider"] = "grok_oauth"
    grok_models["polish_model"] = "grok-4.6"
    grok = provider_for_stage(grok_settings, "polish")
    started = time.perf_counter()
    grok_status = grok.validate(timeout=1.8, use_cache=False)
    result["known_unauthenticated"] = {
        "health_ms": ms(started),
        "available": grok_status.available,
        "authenticated": grok_status.authenticated,
        "message": grok_status.message,
    }
    if grok_status.available and not grok_status.authenticated:
        started = time.perf_counter()
        try:
            grok.complete([{"role": "user", "content": "Return exactly: NEVER_SENT"}], timeout=2.0)
            result["known_unauthenticated"]["fail_fast"] = False
        except AIProviderError as exc:
            result["known_unauthenticated"]["fail_fast"] = exc.category == "authentication_required"
            result["known_unauthenticated"]["category"] = exc.category
        result["known_unauthenticated"]["fail_fast_ms"] = ms(started)
    return result


def main():
    payload = {
        "evidence_tier": "AUTOMATED REAL PROCESS RUNTIME",
        "user_verified": False,
        "renderer": renderer_evidence(),
        "provider": provider_evidence(),
    }
    child_log = RUN / "child-processes.jsonl"
    children = []
    if child_log.is_file():
        children = [json.loads(line) for line in child_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload["child_processes"] = {
        "records": len(children),
        "visible_windows": sum(
            1 for item in children for window in item.get("windows", ()) if window.get("visible")
        ),
        "all_hidden": all(bool(item.get("hidden")) for item in children),
    }
    target = RUN / "runtime-result.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    print(json.dumps({
        "renderer": {
            key: payload["renderer"].get(key)
            for key in (
                "cold_still_ms", "warm_still_ms", "three_cards_ms",
                "seven_motion_frames_ms", "same_service_pid", "browser_crash_recovered",
                "node_crash_recovered", "malformed_response_recovered", "latest_wins", "cancelled",
            )
        },
        "provider": payload["provider"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
