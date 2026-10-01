"""Try a real AI cleanup call with the user's configured polish endpoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.settings import load_runtime_settings
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio_text_tools import request_text_cleanup

SHOTS = ROOT / "tmp" / "p53-accept"
SHOTS.mkdir(parents=True, exist_ok=True)


def main() -> int:
    settings, path, warnings = load_runtime_settings()
    project = SubtitleProject(
        media=StudioMedia(path="a.mp4", duration_ms=3000),
        cues=[
            StudioCue("c0", 0, 1500, "然后就是就是我们先过去看一下"),
            StudioCue("c1", 1500, 2800, "那个那个其实也还好"),
        ],
    )
    payload = {
        "settings_path": str(path),
        "provider": (settings.get("models") or {}).get("polish_provider"),
        "model": (settings.get("models") or {}).get("polish_model"),
        "warnings": list(warnings or []),
    }
    try:
        hits = request_text_cleanup(
            project, [cue.id for cue in project.cues],
            ["fillers", "repeats", "punctuation"],
            settings,
        )
        payload["ok"] = True
        payload["hits"] = [
            {
                "cue_id": hit.cue_id,
                "original": hit.original,
                "replacement": hit.replacement,
                "reason": hit.reason,
                "confidence": hit.confidence,
            }
            for hit in hits
        ]
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
    (SHOTS / "ai-cleanup.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
