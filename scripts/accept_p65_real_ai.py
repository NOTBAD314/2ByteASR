"""Run P6.5 acceptance against the user's configured real AI Provider."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.ai_providers import provider_for_stage
from PySide6.QtWidgets import QApplication
from twobyteasr.settings import load_runtime_settings
from twobyteasr.studio_ai import available_font_shortlist, request_style_design
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject


PROMPTS = (
    "黑白复古动画风格",
    "赛博朋克故障字幕，青色和洋红双层描边，出现时数字故障抖动",
    "手写便签纸，字像纸条展开，暖黄色底，深棕色描边",
)


def _runtime_settings() -> dict:
    loaded = load_runtime_settings()
    return loaded[0] if isinstance(loaded, tuple) else loaded


def _variant_payload(variant) -> dict:
    return {
        "name": variant.name,
        "engine_requirement": variant.engine_requirement,
        "typography": variant.typography,
        "fill": variant.fill,
        "strokes": variant.strokes,
        "glow": variant.glow,
        "shadow": variant.shadow,
        "background": variant.background,
        "motion": variant.motion.to_dict(),
        "ass": variant.ass.to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="tmp/p65-real-runtime/real-ai-acceptance.json")
    parser.add_argument("--max-prompts", type=int, default=3)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    settings = _runtime_settings()
    model_settings = settings.get("models", {})
    provider = provider_for_stage(settings, "polish")

    validation_started = time.perf_counter()
    status = provider.validate(timeout=30.0, use_cache=False)
    validation_seconds = time.perf_counter() - validation_started
    first_timings = dict(getattr(provider, "last_timings", {}) or {})
    cache_started = time.perf_counter()
    cached_status = provider.validate(timeout=30.0)
    cache_seconds = time.perf_counter() - cache_started
    request_started = time.perf_counter()
    reply = provider.complete(
        [{"role": "user", "content": "Return exactly: 2ByteASR_OK"}],
        max_tokens=32,
        temperature=0.0,
        timeout=90.0,
        stage="p65_connection_acceptance",
    ).strip()
    request_seconds = time.perf_counter() - request_started

    # Real Provider/Schema acceptance does not need to transmit any user
    # project content.  Keep the exact requested design prompts and use a
    # neutral local cue solely to satisfy the preview-only API contract.
    project = SubtitleProject(
        media=StudioMedia(path=""),
        cues=[StudioCue("p65-neutral-cue", 0, 1200, "示例字幕")],
    )
    font_shortlist = available_font_shortlist(limit=18)
    allowed_fonts = {
        str(family).casefold()
        for families in font_shortlist.values()
        for family in families
    }

    designs = []
    for prompt in PROMPTS[: max(1, min(3, args.max_prompts))]:
        started = time.perf_counter()
        suggestion = request_style_design(project, "p65-neutral-cue", prompt, settings)
        variants = [_variant_payload(item) for item in suggestion.variants]
        signatures = {
            (
                json.dumps(item["typography"], ensure_ascii=False, sort_keys=True),
                json.dumps(item["fill"], ensure_ascii=False, sort_keys=True),
                json.dumps(item["strokes"], ensure_ascii=False, sort_keys=True),
                json.dumps({"motion": item["motion"], "ass": item["ass"]}, ensure_ascii=False, sort_keys=True),
            )
            for item in variants
        }
        designs.append({
            "prompt": prompt,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "provider_backed": "provider_error" not in suggestion.raw_response,
            "design_intent": suggestion.design_intent,
            "visual_changes": list(suggestion.visual_changes),
            "motion_reason": suggestion.motion_reason,
            "rationale": suggestion.rationale,
            "raw_response": suggestion.raw_response,
            "parsed_primary": suggestion.recipe.to_dict(),
            "variants": variants,
            "distinct_variant_signatures": len(signatures),
            "fonts_from_shortlist": all(
                str(item["typography"].get("fontFamily") or "").casefold()
                in allowed_fonts
                for item in variants
            ),
        })

    result = {
        "provider": provider.provider_id,
        "model": model_settings.get("polish_model", ""),
        "status": {
            "available": status.available,
            "authenticated": status.authenticated,
            "models": list(status.models),
            "message": status.message,
        },
        "connection": {
            "validation_seconds": round(validation_seconds, 3),
            "startup_seconds": round(float(first_timings.get("startup_seconds", 0.0)), 3),
            "auth_model_discovery_seconds": round(float(first_timings.get("auth_seconds", 0.0)), 3),
            "cached_validation_seconds": round(cache_seconds, 4),
            "cache_authenticated": cached_status.authenticated,
            "request_response_seconds": round(request_seconds, 3),
            "reply": reply,
            "total_uncached_test_seconds": round(validation_seconds + request_seconds, 3),
            "total_cached_test_seconds": round(cache_seconds + request_seconds, 3),
        },
        "designs": designs,
        "font_shortlist": font_shortlist,
    }
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "provider": result["provider"],
        "model": result["model"],
        "authenticated": status.authenticated,
        "connection": result["connection"],
        "designs": [
            {
                "prompt": item["prompt"],
                "provider_backed": item["provider_backed"],
                "elapsed_seconds": item["elapsed_seconds"],
                "distinct_variant_signatures": item["distinct_variant_signatures"],
                "fonts_from_shortlist": item["fonts_from_shortlist"],
                "names": [variant["name"] for variant in item["variants"]],
            }
            for item in designs
        ],
        "output": str(target),
    }, ensure_ascii=False, indent=2))
    return 0 if (
        status.authenticated
        and reply == "2ByteASR_OK"
        and all(item["provider_backed"] for item in designs)
        and all(item["fonts_from_shortlist"] for item in designs)
    ) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        error_path = ROOT / "tmp" / "p65-real-runtime" / "real-ai-error.txt"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8",
        )
        print(f"{type(exc).__name__}: {exc}\nerror_log={error_path}", flush=True)
        raise SystemExit(1)
