"""Require actual selected Home model execution in the English deployment audit."""
from __future__ import annotations


def verify_home_evidence(report, asr_evidence, *, job_id):
    """A review notice may remain; failed or skipped required models may not."""
    if not job_id or report.get("job_id") != job_id:
        raise AssertionError("Home report does not belong to the completed task")
    events = report.get("events", [])
    summaries = [row.get("models", {}) for row in events
                 if row.get("event") == "model_summary"]
    if not summaries:
        raise AssertionError("Home report has no actual model execution summary")
    models = summaries[-1]
    required = ("moss", "qwen3-asr", "qwen_aligner")
    failures = []
    for name in required:
        state = models.get(name, {})
        if not (state.get("selected") is True
                and state.get("completed") is True
                and state.get("failed") is False
                and state.get("skipped") is False
                and state.get("segment_count", 0) > 0):
            failures.append(f"{name}: {state.get('failure_reason') or 'not completed'}")
    if failures:
        raise AssertionError("Required Home model execution failed: " + "; ".join(failures))
    final_alignments = [row for row in events
                        if row.get("event") == "forced_alignment"
                        and row.get("stage") == "final_cues"
                        and row.get("attached", 0) > 0
                        and row.get("statuses", {}).get("aligned", 0) > 0
                        and row.get("stats", {}).get("words", 0) > 0]
    if not final_alignments:
        raise AssertionError("Home task has no completed final-cue model alignment")
    measured = set()
    for row in asr_evidence.values():
        if not isinstance(row, dict):
            continue
        for word in row.get("caption_arbitration", {}).get("acoustic_words", []):
            if (word.get("model") == "qwen3_forced_aligner"
                    and word.get("start_basis") == "model"
                    and word.get("end_basis") == "model"
                    and word.get("end_ms", 0) > word.get("start_ms", 0) >= 0):
                measured.add((word.get("text"), word["start_ms"], word["end_ms"]))
    if len(measured) < 3:
        raise AssertionError("Project lacks actual Qwen model-derived word timing")
    return {
        "job_id": job_id,
        "required_models": {name: models[name] for name in required},
        "final_alignment_count": len(final_alignments),
        "qwen_model_word_count": len(measured),
        "review_items": report.get("review_items", []),
        "report_status": report.get("status"),
    }
