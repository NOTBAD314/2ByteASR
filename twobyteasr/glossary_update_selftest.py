"""Headless glossary-update self-test (source and packaged executable).

Runs one REAL networked term search through the packaged provider chain and
writes the structured result (candidates, diffs, evidence, timings) to a JSON
file — no GUI, no library writes. Mirrors --asr-provider-self-test usage:

    2ByteASR.exe --glossary-update-self-test <output.json> [--game NAME] [--service ID]

Exit codes: 0 ok (diffs may be empty), 2 usage, 3 capability/search failure,
4 cancelled/timeout. Never prints credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="glossary-update-self-test")
    parser.add_argument("output", help="result JSON path")
    parser.add_argument("--game", default="明日方舟终末地")
    parser.add_argument("--service", default="grok_account")
    parser.add_argument("--model", default="")
    args, _rest = parser.parse_known_args(argv)

    import subtitle_core as legacy
    from twobyteasr import glossary_skill as gs
    from twobyteasr.glossary_skill import settings_with_service_override

    settings = settings_with_service_override(
        dict(legacy.RUNTIME_SETTINGS), args.service, args.model
    )
    capability = gs.detect_search_capability(settings)
    stages: list[dict] = []

    def progress(stage: str, note: str) -> None:
        stages.append({"stage": stage, "note": note})
        print(f"[{stage}] {note}", flush=True)

    started = time.perf_counter()
    try:
        result = gs.run_term_search(
            legacy, args.game, settings, progress=progress
        )
    except gs.GlossarySearchError as exc:
        payload = {
            "ok": False,
            "error_code": exc.code,
            "error": exc.detail,
            "game": args.game,
            "service": args.service,
            "capability": capability,
            "wall_seconds": round(time.perf_counter() - started, 1),
            "stages": stages,
        }
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"FAILED [{exc.code}] {exc.detail}")
        return 3 if exc.code not in {"cancelled", "timeout"} else 4

    diffs = [
        {
            "change_type": d.change_type,
            "term": d.term.term,
            "category": d.term.category,
            "aliases": list(d.term.aliases),
            "priority": d.term.priority,
            "sources": [dict(s) for s in d.term.sources],
            "checked_by_default": d.checked_by_default,
        }
        for d in result["diffs"]
    ]
    payload = {
        "ok": True,
        "game": args.game,
        "service": args.service,
        "model": result["model"],
        "searched": result["searched"],
        "search_evidence": result["search_evidence"],
        "candidate_count": result["candidate_count"],
        "diff_count": len(diffs),
        "diffs": diffs,
        "wall_seconds": round(time.perf_counter() - started, 1),
        "provider_seconds": result["elapsed_seconds"],
        "capability": capability,
        "stages": stages,
    }
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        f"OK candidates={result['candidate_count']} diffs={len(diffs)} "
        f"searched={result['searched']} evidence={result['search_evidence']} "
        f"wall={payload['wall_seconds']}s -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
