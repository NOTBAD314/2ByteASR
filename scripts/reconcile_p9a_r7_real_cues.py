"""Reconcile the persisted real R7 worker outputs through production fusion rules.

This is an evidence command, not a model fixture: every input must be a real
worker artifact produced for the same media sample.  The output is deliberately
bounded to five rows plus the production review classification.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import moss_firered_pipeline as pipeline
import subtitle_core as legacy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--moss", type=Path, default=Path("tmp/p9a_r7_moss.json"))
    parser.add_argument("--firered", type=Path, default=Path("tmp/p9a_r7_firered_inprocess_full.json"))
    parser.add_argument("--qwen", type=Path, default=Path("tmp/p9a_r7_real_execution.json"))
    parser.add_argument("--output", type=Path, default=Path("tmp/p9a_r7_real_execution.json"))
    parser.add_argument("--duration", type=float, default=120.0)
    args = parser.parse_args()

    moss_payload = json.loads(args.moss.read_text(encoding="utf-8"))
    firered_payload = json.loads(args.firered.read_text(encoding="utf-8"))
    qwen_payload = json.loads(args.qwen.read_text(encoding="utf-8"))
    tokens = firered_payload.get("tokens")
    if not isinstance(tokens, list):
        tokens = (firered_payload.get("results") or [{}])[0].get("timestamp", [])
    qwen_chunks = qwen_payload.get("qwen3", {}).get("sample", [])
    if not moss_payload.get("segments") or not tokens or not qwen_chunks:
        raise RuntimeError("real MOSS, FireRed, and Qwen artifacts are all required")

    # The source module owns the actual host selection, token-window matching,
    # Qwen attachment, arbitration, and review classification rules.
    segments = pipeline.build_moss_host_primary_segments(
        moss_payload,
        tokens,
        [{"start": 0.0, "end": float(args.duration)}],
        float(args.duration),
        legacy,
    )
    pipeline.attach_qwen_review_evidence(segments, qwen_chunks, legacy)
    pipeline.reconcile_firered_moss_qwen(segments, legacy)
    for segment in segments:
        segment.moss_start = float(segment.moss_start or segment.start)
        segment.moss_end = float(segment.moss_end or segment.end)
        segment.qwen_text = str(segment.qwen_asr_text or "")
        segment.final_text = str(segment.text or "")
        if segment.firered_text and segment.firered_end > segment.firered_start:
            segment.final_start = float(segment.firered_start)
            segment.final_end = max(segment.final_start + 0.01, float(segment.firered_end))
            segment.final_timing_owner = "FireRed"
        else:
            segment.final_start = float(segment.start)
            segment.final_end = float(segment.end)
            segment.final_timing_owner = "MOSS_DEGRADED"
        segment.final_text_owner = (
            "MOSS+FireRed+Qwen3"
            if segment.firered_text and segment.qwen_text
            else "MOSS+FireRed" if segment.firered_text
            else "MOSS+Qwen3" if segment.qwen_text
            else "MOSS"
        )

    counts = pipeline._record_fused_review_classification(
        legacy,
        segments,
        firered_selected=True,
        firered_failed=False,
        qwen_selected=True,
        qwen_failed=False,
    )
    cues = pipeline._real_three_source_cue_evidence(segments, limit=5)
    if len(cues) < 5:
        raise RuntimeError(f"only {len(cues)} three-source cues were reconciled")

    # Preserve the original execution telemetry and replace only the bounded
    # fusion/acceptance fields with the independently reconciled result.
    qwen_payload["three_source_cues"] = cues
    qwen_payload["review_classification"] = counts
    qwen_payload["acceptance"] = {
        "real_model_verified": True,
        "reason": "five cues contain real MOSS, FireRed, and Qwen evidence with explicit owners",
        "human_user_verified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(qwen_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"three_source_cues": len(cues), "review_classification": counts, "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
