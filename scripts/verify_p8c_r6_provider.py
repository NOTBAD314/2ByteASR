"""Run one real R6 design request per shared provider profile."""

from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.ai_providers import provider_for_stage
from twobyteasr.settings import load_runtime_settings
from twobyteasr.studio_ai import request_style_design
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.llm_config import activate_ai_service


def run(service_id: str, base: dict, project: SubtitleProject) -> dict:
    settings = copy.deepcopy(base)
    activate_ai_service(settings, service_id, stage="polish")
    values = settings["models"]
    provider = provider_for_stage(settings, "polish")
    started = time.perf_counter()
    result: dict = {
        "service": service_id,
        "provider_id": str(getattr(provider, "provider_id", "")),
        "transport": str(getattr(getattr(provider, "transport", ""), "value", getattr(provider, "transport", ""))),
        "model": str(values.get("polish_model") or ""),
    }
    try:
        status = provider.validate(timeout=30.0, use_cache=False)
        result["validate"] = {
            "available": bool(status.available),
            "authenticated": bool(status.authenticated),
            "message": str(status.message or "")[:240],
            "models": list(status.models),
        }
        suggestion = request_style_design(
            project,
            "r6-neutral",
            "为示例字幕生成三套清晰、可读、带轻微动态的字幕视觉方案",
            settings,
        )
        result.update({
            "provider_succeeded": bool(suggestion.provider_succeeded),
            "failure_stage": str(suggestion.failure_stage or ""),
            "provider_error_category": str(suggestion.provider_error_category or ""),
            "pipeline_status": dict(suggestion.pipeline_status),
            "variant_count": len(suggestion.variants),
            "repair_attempted": bool(suggestion.repair_attempted),
            "raw_response_keys": sorted(str(key) for key in suggestion.raw_response),
        })
    except Exception as exc:
        result.update({"exception": f"{type(exc).__name__}: {exc}"})
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return result


def main() -> int:
    QApplication.instance() or QApplication([])
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR"
    loaded = load_runtime_settings(root)
    base = loaded[0] if isinstance(loaded, tuple) else loaded
    project = SubtitleProject(media=StudioMedia(path=""), cues=[StudioCue("r6-neutral", 0, 1200, "示例字幕")])
    selected = str(os.environ.get("P8C_R6_ONLY_SERVICE") or "").strip()
    services = [selected] if selected in {"deepseek", "antigravity"} else ["deepseek", "antigravity"]
    results = [run(service, base, project) for service in services]
    target = ROOT / "tmp" / "p8c-r6-provider-real.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
