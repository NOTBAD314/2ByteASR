from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from twobyteasr.ai_providers import provider_for_stage
from twobyteasr.studio_ai import request_style_design
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project


def _signature(variant) -> str:
    payload = variant.to_style_recipe().to_dict()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def main() -> int:
    app = QApplication.instance() or QApplication([])
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tmp/p73c/provider-production-call/runtime-result.json"))
    parser.add_argument("--deadline", type=float, default=45.0)
    parser.add_argument("--smoke-only", action="store_true")
    args = parser.parse_args()

    settings = json.loads(Path("2byteasr_settings.json").read_text(encoding="utf-8"))
    if args.project is None:
        project = SubtitleProject(
            media=StudioMedia(path="synthetic-provider-fixture.mp4", duration_ms=8_000),
            cues=[StudioCue("synthetic-cue", 0, 2_400, "前方高能操作，请注意画面变化")],
        )
        project_label = "synthetic-non-private-fixture"
    else:
        project = load_project(args.project)
        project_label = str(args.project.resolve())
    cue = project.cues[0]
    models = settings.get("models", {})
    child_log = args.output.parent / "children.jsonl"
    child_log.parent.mkdir(parents=True, exist_ok=True)
    os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(child_log.resolve())

    if args.smoke_only:
        client = provider_for_stage(settings, "polish")
        started = time.monotonic()
        error = ""
        error_category = ""
        response = ""
        try:
            response = client.complete(
                [{"role": "user", "content": "Reply exactly with: OK"}],
                max_tokens=8,
                temperature=0.0,
                timeout=args.deadline,
                stage="p73c_short_smoke",
            )
        except Exception as exc:
            error = str(exc)
            error_category = str(getattr(exc, "category", type(exc).__name__))
        normalized = response.strip().strip("`\"' ").upper()
        result = {
            "evidence": "provider-short-smoke",
            "transport": models.get("polish_transport"),
            "provider": getattr(client, "provider_id", ""),
            "model": models.get("polish_model"),
            "deadline_seconds": args.deadline,
            "total_ms": round((time.monotonic() - started) * 1000.0, 3),
            "response_exact_ok": normalized == "OK",
            "response_length": len(response),
            "error_category": error_category,
            "error": error,
            "broker_telemetry": [
                dict(item) for item in client._service.telemetry()[-8:]
            ],
            "child_log": str(child_log.resolve()),
            "raw_response_persisted": False,
            "real_user_click": False,
        }
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["response_exact_ok"] else 2

    stage_events: list[dict[str, object]] = []
    started = time.monotonic()

    def stage_callback(stage: str) -> None:
        stage_events.append({
            "stage": str(stage),
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
        })

    suggestion = request_style_design(
        project,
        cue.id,
        "清晰、有层次、适合游戏实况的动态字幕",
        settings,
        deadline_seconds=args.deadline,
        stage_callback=stage_callback,
    )
    client = provider_for_stage(settings, "polish")
    variants = list(suggestion.variants)
    result = {
        "evidence": "provider-production-call",
        "project": project_label,
        "cue_id": cue.id,
        "transport": models.get("polish_transport"),
        "provider": getattr(client, "provider_id", ""),
        "model": models.get("polish_model"),
        "deadline_seconds": args.deadline,
        "total_ms": round((time.monotonic() - started) * 1000.0, 3),
        "provider_succeeded": suggestion.provider_succeeded,
        "provider_error_category": suggestion.provider_error_category,
        "stage_events": stage_events,
        "stage_timings_ms": suggestion.stage_timings_ms,
        "variant_count": len(variants),
        "variant_names": [item.name for item in variants],
        "variant_signatures": [_signature(item) for item in variants],
        "all_variants_validated": len(variants) == 3,
        "broker_telemetry": [
            dict(item) for item in client._service.telemetry()[-8:]
        ],
        "child_log": str(child_log.resolve()),
        "raw_response_persisted": False,
        "real_user_click": False,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if suggestion.provider_succeeded and len(variants) == 3 else 2


if __name__ == "__main__":
    raise SystemExit(main())
