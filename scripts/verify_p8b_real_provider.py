"""Verify current credentialed Provider returns P8B ArtDirectionSpec + Graph A/B/C."""

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
    "赛博故障：短暂信号失真后快速锁定，hold期间稳定可读；给三套真正不同方向",
    "美漫 punchline：文字一级，burst/rays/halftone分层错峰；给三套真正不同方向",
    "游戏直播高能时刻：可读、克制、有冲击；不要默认青紫霓虹；给三套真正不同方向",
)


def _settings() -> dict:
    loaded = load_runtime_settings()
    return loaded[0] if isinstance(loaded, tuple) else loaded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("tmp/p8b/real-provider/runtime-result.json"))
    parser.add_argument("--deadline", type=float, default=120.0)
    parser.add_argument("--prompt", action="append")
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(output.parent / "children.jsonl")
    app = QApplication.instance() or QApplication([])
    settings = _settings()
    provider = provider_for_stage(settings, "polish")
    models = settings.get("models", {})
    project = SubtitleProject(
        media=StudioMedia(path="p8b-provider-fixture.mp4", duration_ms=8_000, width=1920, height=1080),
        cues=[StudioCue("cue", 0, 2_400, "这一刻太关键了")],
    )
    prompts = tuple(args.prompt or PROMPTS)
    result: dict[str, object] = {
        "schema": "2byteasr.p8b-real-provider.v1",
        "evidence_class": "CURRENT CREDENTIALED REAL PROVIDER",
        "real_user_click": False,
        "provider": getattr(provider, "provider_id", ""),
        "transport": models.get("polish_transport", ""),
        "model": models.get("polish_model", ""),
        "deadline_seconds_per_prompt": args.deadline,
        "selected_prompts": list(prompts),
        "started_at": time.time(),
        "prompts": [],
    }
    rows: list[dict[str, object]] = []
    try:
        for prompt in prompts:
            stages: list[dict[str, object]] = []
            started = time.monotonic()

            def on_stage(stage: str) -> None:
                stages.append({
                    "stage": stage,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                })

            suggestion = request_style_design(
                project, "cue", prompt, settings,
                deadline_seconds=args.deadline, stage_callback=on_stage,
            )
            directions = list(suggestion.art_directions)
            graphs = [VisualDesignGraph.from_dict(item.visual_graph) for item in suggestion.variants]
            scores = list(suggestion.quality_scores)
            signatures = {
                json.dumps(structural_signature(graph), ensure_ascii=False, sort_keys=True)
                for graph in graphs
            }
            checks = {
                "provider_succeeded_no_fallback": bool(
                    suggestion.provider_succeeded
                    and "provider_error" not in suggestion.raw_response
                ),
                "exactly_three_art_directions": len(directions) == 3,
                "three_dominant_families": len({item.primary_family for item in directions}) == 3,
                "three_motion_concepts": len({item.motion_concept.casefold() for item in directions}) == 3,
                "dominant_family_weight": all(item.family_mix[0] >= 60 for item in directions),
                "exactly_three_graphs": len(graphs) == 3,
                "three_structural_graphs": len(signatures) == 3,
                "quality_dimensions_present": len(scores) == 3 and all(
                    all(hasattr(score, field) for field in (
                        "readability", "hierarchy", "composition", "motion_quality",
                        "effect_specificity", "visual_density", "renderer_support",
                    )) for score in scores
                ),
                "quality_accepted": len(scores) == 3 and all(score.accepted for score in scores),
                "no_cheap_motion": all("CHEAP_MOTION" not in score.issues for score in scores),
                "no_primitive_soup": all("OVERDECORATED" not in score.issues for score in scores),
                "bounded_repair_events": sum(
                    1 for item in stages if item["stage"] == "REPAIRING"
                ) <= 1,
            }
            row = {
                "prompt": prompt,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "provider_succeeded": suggestion.provider_succeeded,
                "provider_error_category": suggestion.provider_error_category,
                "provider_error": str(suggestion.raw_response.get("provider_error") or ""),
                "stage_events": stages,
                "stage_timings_ms": dict(suggestion.stage_timings_ms),
                "checks": checks,
                "accepted": all(checks.values()),
                "art_directions": [item.to_dict() for item in directions],
                "quality_scores": [item.to_dict() for item in scores],
                "graphs": [graph.to_dict() for graph in graphs],
            }
            rows.append(row)
            result["prompts"] = rows
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({
                "prompt": prompt,
                "elapsed_seconds": row["elapsed_seconds"],
                "provider_succeeded": row["provider_succeeded"],
                "families": [item.primary_family for item in directions],
                "graph_names": [item.name for item in graphs],
                "checks": checks,
            }, ensure_ascii=False), flush=True)
    finally:
        GLOBAL_PROVIDER_SERVICE.cancel_all()
        GLOBAL_PROVIDER_SERVICE.wait_for_idle(timeout=5.0)

    result["complete_matrix"] = prompts == PROMPTS
    result["accepted"] = len(rows) == len(prompts) and all(row["accepted"] for row in rows)
    result["broker_telemetry"] = [dict(item) for item in GLOBAL_PROVIDER_SERVICE.telemetry()[-30:]]
    result["finished_at"] = time.time()
    result["duration_seconds"] = round(result["finished_at"] - result["started_at"], 3)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "accepted": result["accepted"], "complete_matrix": result["complete_matrix"],
        "provider": result["provider"], "model": result["model"],
        "duration_seconds": result["duration_seconds"], "output": str(output),
    }, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        target = ROOT / "tmp" / "p8b" / "real-provider" / "fatal-error.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8",
        )
        print(f"{type(exc).__name__}: {exc}\nfatal_error={target}", flush=True)
        raise SystemExit(1)
