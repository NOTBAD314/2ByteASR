"""Run a deterministic three-model R6 provenance fixture and write JSON evidence."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from moss_firered_pipeline import (
    _record_fused_review_classification,
    _run_audited_model_stage,
)
from twobyteasr.models import SpeechSegment, WordUnit


def run(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []

    class Legacy:
        ASR_CONSENSUS_MIN_SIMILARITY = 0.72

        @staticmethod
        def record_run_event(event, **payload):
            events.append({"event": event, **payload})

        @staticmethod
        def asr_consensus_similarity(_left, _right):
            return 1.0

    legacy = Legacy()
    worker = output / "fixture-worker.py"
    runtime = output / "fixture-python.exe"
    worker.write_text("# deterministic fixture worker\n", encoding="utf-8")
    runtime.write_text("fixture runtime\n", encoding="utf-8")
    media = str(output / "fixture-60s.wav")

    moss = _run_audited_model_stage(
        legacy,
        model_id="moss",
        role="primary_transcription_diarization",
        backend="fixture",
        media_path=media,
        worker=str(worker),
        runtime=str(runtime),
        runner=lambda: [{"start": 10.0, "end": 12.0, "text": "测试文本", "speaker": "S00"}],
    )
    firered = _run_audited_model_stage(
        legacy,
        model_id="firered-asr2-aed",
        role="timeline_alignment",
        backend="fixture",
        media_path=media,
        worker=str(worker),
        runtime=str(runtime),
        runner=lambda: [{"start": 10.2, "end": 11.4, "text": "测试文本", "confidence": 0.87}],
    )
    qwen = _run_audited_model_stage(
        legacy,
        model_id="qwen3-asr",
        role="text_verification",
        backend="fixture",
        media_path=media,
        worker=str(worker),
        runtime=str(runtime),
        runner=lambda: [{"start": 10.0, "end": 12.0, "text": "测试文本", "confidence": 0.93}],
    )

    cue = SpeechSegment(
        segment_id=1,
        start=10.0,
        end=12.0,
        text="测试文本",
        confidence=0.95,
        words=[WordUnit(10.0, 12.0, "测试文本", 0.95)],
        speaker="S00",
        moss_text=moss[0]["text"],
        moss_start=moss[0]["start"],
        moss_end=moss[0]["end"],
        firered_text=firered[0]["text"],
        firered_start=firered[0]["start"],
        firered_end=firered[0]["end"],
        firered_alignment_confidence=firered[0]["confidence"],
        qwen_text=qwen[0]["text"],
        qwen_asr_text=qwen[0]["text"],
        qwen_confidence=qwen[0]["confidence"],
        final_text="测试文本",
        final_start=firered[0]["start"],
        final_end=firered[0]["end"],
        final_text_owner="MOSS+FireRed+Qwen3",
        final_timing_owner="FireRed",
    )
    review_classification = _record_fused_review_classification(
        legacy,
        [cue],
        firered_selected=True,
        firered_failed=False,
        qwen_selected=True,
        qwen_failed=False,
    )
    summary = {
        "schema": "2byteasr.p9a-r6-model-fixture.v1",
        "evidence_class": "DETERMINISTIC MODEL-STAGE FIXTURE",
        "accepted": True,
        "models": {
            "moss": {"status": "MODEL_COMPLETED", "segment_count": len(moss)},
            "firered-asr2-aed": {"status": "MODEL_COMPLETED", "segment_count": len(firered)},
            "qwen3-asr": {"status": "MODEL_COMPLETED", "segment_count": len(qwen)},
        },
        "events": events,
        "three_source_cue": {
            "segment_id": cue.segment_id,
            "moss_text": cue.moss_text,
            "moss_start": cue.moss_start,
            "moss_end": cue.moss_end,
            "firered_text": cue.firered_text,
            "firered_start": cue.firered_start,
            "firered_end": cue.firered_end,
            "firered_alignment_confidence": cue.firered_alignment_confidence,
            "qwen_text": cue.qwen_text,
            "qwen_confidence": cue.qwen_confidence,
            "final_text": cue.final_text,
            "final_start": cue.final_start,
            "final_end": cue.final_end,
            "final_text_owner": cue.final_text_owner,
            "final_timing_owner": cue.final_timing_owner,
        },
        "review_classification": review_classification,
        "generated_at": time.time(),
    }
    (output / "runtime-result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.output)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
