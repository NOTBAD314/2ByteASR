"""Validate P7.4B VisualDesignGraph output from the configured real Provider."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from twobyteasr.ai_providers import provider_for_stage
from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
from twobyteasr.settings import load_runtime_settings
from twobyteasr.studio_ai import request_style_design
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.visual_design_graph import VisualDesignGraph, structural_signature


PROMPTS = (
    "Streamer Gaming",
    "美漫经典爆裂",
    "故障字幕",
)


def _runtime_settings() -> dict:
    loaded = load_runtime_settings()
    return loaded[0] if isinstance(loaded, tuple) else loaded


def _signature_payload(graph: VisualDesignGraph) -> dict[str, object]:
    signature = structural_signature(graph)
    return {
        "panel": signature[0],
        "decorations": list(signature[1]),
        "effects": list(signature[2]),
        "motion_targets": [list(item) for item in signature[3]],
    }


def _animated_tracks(graph: VisualDesignGraph) -> list[dict[str, object]]:
    rows = []
    for track in graph.motion_graph.tracks:
        values = {float(frame.value) for frame in track.keyframes}
        rows.append({
            "target": track.target,
            "property": track.property,
            "keyframe_count": len(track.keyframes),
            "changes_value": len(values) > 1,
        })
    return rows


def _meaningful_streamer_motion(graph: VisualDesignGraph) -> bool:
    animated = [item for item in _animated_tracks(graph) if item["changes_value"]]
    return bool(
        len(animated) >= 2
        and any(item["property"] != "opacity" for item in animated)
    )


def _prompt_checks(prompt: str, graphs: list[VisualDesignGraph]) -> dict[str, bool]:
    signatures = {json.dumps(_signature_payload(item), sort_keys=True) for item in graphs}
    checks = {
        "exactly_three_graphs": len(graphs) == 3,
        "three_structural_signatures": len(signatures) == 3,
    }
    if prompt == "Streamer Gaming":
        checks["streamer_meaningful_motion"] = all(
            _meaningful_streamer_motion(item) for item in graphs
        )
    elif prompt == "美漫经典爆裂":
        checks["comic_panel_decoration_effect_motion"] = all(
            item.panel_layer.primitive != "NONE"
            and bool(item.decoration_layers)
            and bool(item.effect_layers)
            and bool(item.motion_graph.tracks)
            for item in graphs
        )
    elif prompt == "故障字幕":
        checks["glitch_effect_and_motion"] = all(
            any(effect.primitive == "GLITCH" for effect in item.effect_layers)
            and bool(item.motion_graph.tracks)
            for item in graphs
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tmp/p74b/real-provider-r1/runtime-result.json"),
    )
    parser.add_argument("--deadline", type=float, default=90.0)
    parser.add_argument("--prompt", action="append", choices=PROMPTS)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    child_log = output.parent / "children.jsonl"
    os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(child_log)

    app = QApplication.instance() or QApplication([])
    settings = _runtime_settings()
    models = settings.get("models", {})
    provider = provider_for_stage(settings, "polish")
    project = SubtitleProject(
        media=StudioMedia(
            path="neutral-p74b-provider-fixture.mp4",
            duration_ms=8_000,
            width=1920,
            height=1080,
        ),
        cues=[StudioCue(
            "p74b-provider-cue",
            0,
            2_400,
            "前方高能操作，请注意画面变化",
        )],
    )

    result: dict[str, object] = {
        "schema": "2byteasr.p74b-real-provider.v1",
        "evidence_class": "CURRENT CREDENTIALED REAL PROVIDER",
        "real_user_click": False,
        "provider": getattr(provider, "provider_id", ""),
        "transport": models.get("polish_transport", ""),
        "model": models.get("polish_model", ""),
        "deadline_seconds_per_prompt": args.deadline,
        "started_at": time.time(),
        "prompts": [],
    }
    rows: list[dict[str, object]] = []
    selected_prompts = tuple(args.prompt or PROMPTS)
    result["selected_prompts"] = list(selected_prompts)
    try:
        for prompt in selected_prompts:
            stages: list[dict[str, object]] = []
            started = time.monotonic()

            def stage_callback(stage: str) -> None:
                stages.append({
                    "stage": str(stage),
                    "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
                })

            suggestion = request_style_design(
                project,
                "p74b-provider-cue",
                prompt,
                settings,
                deadline_seconds=args.deadline,
                stage_callback=stage_callback,
            )
            graphs: list[VisualDesignGraph] = []
            graph_errors: list[str] = []
            for variant in suggestion.variants:
                try:
                    graphs.append(VisualDesignGraph.from_dict(variant.visual_graph))
                except Exception as exc:
                    graph_errors.append(f"{type(exc).__name__}: {exc}")
            checks = _prompt_checks(prompt, graphs)
            checks["provider_succeeded_no_fallback"] = bool(
                suggestion.provider_succeeded
                and "provider_error" not in suggestion.raw_response
            )
            checks["all_graphs_reparsed"] = not graph_errors and len(graphs) == 3
            row = {
                "prompt": prompt,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "provider_succeeded": suggestion.provider_succeeded,
                "provider_error_category": suggestion.provider_error_category,
                "provider_error": suggestion.raw_response.get("provider_error", ""),
                "variant_count": len(suggestion.variants),
                "graph_errors": graph_errors,
                "checks": checks,
                "accepted": all(checks.values()),
                "stage_events": stages,
                "stage_timings_ms": dict(suggestion.stage_timings_ms),
                "design_intent": suggestion.design_intent,
                "visual_changes": list(suggestion.visual_changes),
                "motion_reason": suggestion.motion_reason,
                "graphs": [
                    {
                        "name": graph.name,
                        "hash": graph.stable_hash(),
                        "signature": _signature_payload(graph),
                        "animated_tracks": _animated_tracks(graph),
                        "graph": graph.to_dict(),
                    }
                    for graph in graphs
                ],
            }
            rows.append(row)
            result["prompts"] = rows
            output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps({
                "prompt": prompt,
                "elapsed_seconds": row["elapsed_seconds"],
                "provider_succeeded": row["provider_succeeded"],
                "checks": checks,
                "names": [item.name for item in graphs],
            }, ensure_ascii=False), flush=True)
    finally:
        GLOBAL_PROVIDER_SERVICE.cancel_all()
        GLOBAL_PROVIDER_SERVICE.wait_for_idle(timeout=5.0)

    result["broker_telemetry"] = [
        dict(item) for item in GLOBAL_PROVIDER_SERVICE.telemetry()[-20:]
    ]
    result["child_log"] = str(child_log)
    result["complete_matrix"] = selected_prompts == PROMPTS
    result["accepted"] = len(rows) == len(selected_prompts) and all(
        bool(row["accepted"]) for row in rows
    )
    result["finished_at"] = time.time()
    result["duration_seconds"] = round(
        float(result["finished_at"]) - float(result["started_at"]), 3
    )
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output, flush=True)
    print(json.dumps({
        "accepted": result["accepted"],
        "provider": result["provider"],
        "model": result["model"],
        "duration_seconds": result["duration_seconds"],
    }, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        target = ROOT / "tmp" / "p74b" / "real-provider-r1" / "fatal-error.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8",
        )
        print(f"{type(exc).__name__}: {exc}\nfatal_error={target}", flush=True)
        raise SystemExit(1)
