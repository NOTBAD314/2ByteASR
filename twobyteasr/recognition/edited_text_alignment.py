"""Run a local aligner for text whose prior acoustic mapping became invalid."""

import hashlib
import math

from .transcript_data import WordUnit


def _validate_tokens(segment, segments, tokens, job, worker_row, content_exact):
    if not tokens:
        return "worker_returned_no_usable_tokens"
    if job.get("text", segment.text) != segment.text or worker_row.get("text", segment.text) != segment.text:
        return "worker_text_revision_mismatch"
    if content_exact("".join(row["text"] for row in tokens)) != content_exact(segment.text):
        return "target_text_coverage_mismatch"
    if any(row["start_basis"] != "model" or row["end_basis"] != "model" for row in tokens):
        return "unmeasured_endpoint"
    if any(not math.isfinite(row["start"] + row["end"]) or not 0 < row["end"] - row["start"] <= 3.0
           or (i and tokens[i-1]["end"] > row["start"]) for i, row in enumerate(tokens)):
        return "invalid_or_overlapping_token_intervals"
    start, end = tokens[0]["start"], tokens[-1]["end"]
    if not job["window_start_ms"] <= round(start * 1000) <= round(end * 1000) <= job["window_end_ms"]:
        return "outside_submitted_pcm"
    samples = (worker_row.get("input_processing") or {}).get("absolute_original_pcm_samples")
    if samples and not samples[0] <= round(start * 16000) <= round(end * 16000) <= samples[1]:
        return "outside_actual_pcm"
    low, high = segment.start, segment.end
    extensions = [(a, b) for a, b in ((start, low), (high, end)) if b - a > .001]
    if not extensions:
        return None
    if not samples or segment.timing_locked:
        return "extension_without_verified_pcm_or_unlocked_parent"
    if any(other is not segment and other.start < b and a < other.end
           for a, b in extensions for other in segments):
        return "extension_conflicts_with_neighbor"
    return None


def realign_edited_segments(segments, audio, legacy, *, enabled, language, evidence_dir):
    from .asr import aligner_tokens, run_qwen_aligner_worker
    from .service import CancelledError
    from .timing_evidence import save_aligner_payload
    from .word_timing_provenance import suspicious_numeric_word
    from ..subtitle_rules.text_rules import content_exact

    pending = {}
    jobs = []
    for segment in segments:
        arbitration = segment.caption_arbitration
        changes = [*arbitration.get("terminology_normalization", ()), *arbitration.get("numeric_formatting", ())]
        suspect_words = [word for word in segment.words if suspicious_numeric_word(word.text, word.start, word.end)]
        if not suspect_words and not any(isinstance(row, dict) and row.get("requires_acoustic_alignment") for row in changes):
            continue
        key = f"edited:{segment.segment_id}"
        start = round(segment.start * 1000)
        end = round(segment.end * 1000)
        receipt = {"status": "pending", "reason": "selected_alignment_unavailable",
                   "text_sha256": hashlib.sha256(segment.text.encode("utf-8")).hexdigest(),
                   "source_pcm_range_ms": [start, end], "language": language}
        if suspect_words:
            receipt["suspect_numeric_words"] = [{"text": word.text, "start": word.start, "end": word.end}
                                                for word in suspect_words]
        arbitration["edited_text_alignment"] = receipt
        arbitration["word_timing"] = {"basis": "uniform_display_estimate", "reason": "edited_text_alignment_pending"}
        arbitration.pop("acoustic_words", None)
        segment.words = []
        pending[key] = segment
        if enabled and language and end - start >= 180 and content_exact(segment.text):
            jobs.append({"id": key, "window_start_ms": max(0, start - 100),
                         "window_end_ms": end + 100, "text": segment.text, "language": language,
                         "speaker": segment.speaker, "parent_ids": [str(segment.segment_id)],
                         "parent_pcm_range_ms": [start, end], "source_clock_verified": True,
                         "material_contiguous": True})
    if not pending:
        return
    payload = {}
    if jobs:
        progress = dict(work_id="edited-text-alignment", label="改稿后词级对齐",
                        phase="edited_text_alignment", total=len(jobs))
        legacy.record_run_event("pipeline_work_progress", **progress, state="running", done=0)
        try:
            payload = run_qwen_aligner_worker(audio, jobs)
        except CancelledError:
            legacy.record_run_event("pipeline_work_progress", **progress, state="cancelled", done=0)
            raise
        except Exception as exc:
            legacy.record_run_event("edited_text_alignment_failed", reason=type(exc).__name__, jobs=len(jobs))

    batches = {}
    for token in aligner_tokens(payload):
        batches.setdefault(token["alignment_job"], []).append(token)
    evidence = save_aligner_payload(evidence_dir, "edited_segments", language, payload) if payload else None
    jobs_by_id = {job["id"]: job for job in jobs}
    results = {str(row.get("id")): row for row in payload.get("results") or ()}
    aligned = []
    for key, segment in pending.items():
        tokens = batches.get(key, [])
        receipt = segment.caption_arbitration["edited_text_alignment"]
        job = jobs_by_id.get(key)
        worker_row = results.get(key, {})
        if job is not None:
            receipt.update(submitted_pcm_range_ms=[job["window_start_ms"], job["window_end_ms"]],
                           worker_status=worker_row.get("status"), evidence=evidence,
                           returned_token_count=len(tokens))
            receipt["reason"] = _validate_tokens(segment, segments, tokens, job, worker_row, content_exact)
        if receipt["reason"] is None:
            low, high = segment.start, segment.end
            segment.start, segment.end = min(low, tokens[0]["start"]), max(high, tokens[-1]["end"])
            if segment.final_start == low:
                segment.final_start = segment.start
            if segment.final_end == high:
                segment.final_end = segment.end
            segment.words = [WordUnit(row["start"], row["end"], row["text"], row.get("confidence", 0.0)) for row in tokens]
            measured = [{"text": row["text"], "start_ms": round(row["start"] * 1000),
                         "end_ms": round(row["end"] * 1000)} for row in tokens]
            arbitration = segment.caption_arbitration
            arbitration["word_timing"] = {"basis": "aligner_words", "measured_words": measured}
            arbitration["acoustic_words"] = measured
            receipt.update(status="aligned", reason="complete_model_word_boundaries",
                           model=tokens[0].get("model"),
                           measured_range_ms=[measured[0]["start_ms"], measured[-1]["end_ms"]],
                           parent_after_ms=[round(segment.start * 1000), round(segment.end * 1000)])
            aligned.append(segment.segment_id)
            continue

        legacy.add_review_item(segment.start, "词级时间待对齐",
            "保留当前文字和段级时间，词级起止等待本地对齐。", segment.text,
            severity="review", segment_id=segment.segment_id, alignment_receipt=receipt)
    legacy.record_run_event("edited_text_alignment", aligned=aligned,
        pending=[segment.segment_id for segment in pending.values() if segment.segment_id not in aligned],
        submitted_windows=len(jobs),
        worker_completed=sum(row.get("status") == "aligned" for row in results.values()),
        applied_windows=len(aligned), evidence=evidence)
    if jobs:
        legacy.record_run_event("pipeline_work_progress", **progress,
            state="completed" if payload else "failed", done=len(jobs), applied=len(aligned),
            review_required=len(aligned) < len(pending))
