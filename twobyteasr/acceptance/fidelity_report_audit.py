"""Replay saved report evidence through finalization inside source or frozen Python."""
from __future__ import annotations

from collections import Counter
import contextlib
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback


def main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8-sig"))
    output = Path(spec["output"]).resolve()
    if not output.is_relative_to(Path.cwd().resolve() / "tmp"):
        raise ValueError("Report replay output must be under cwd/tmp")
    output.mkdir(parents=True, exist_ok=True)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(output / "profile")
    os.environ["2BYTEASR_USER_DATA_ROOT"] = str(output / "profile/user-data")
    from ..test_isolation import install
    install()
    result = dict(passed=False, frozen=bool(getattr(sys, "frozen", False)),
                  asr_requests=0, provider_requests=0, checks=[])
    def check(name, passed, **details):
        result["checks"].append(dict(name=name, passed=bool(passed), **details))
        if not passed:
            raise AssertionError(name)
    with (output / "runtime.log").open("w", encoding="utf-8") as log, \
            contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            import requests
            import socket
            def forbidden(*_args, **_kwargs):
                raise RuntimeError("Network is forbidden during report fidelity replay")
            requests.sessions.Session.request = forbidden
            socket.create_connection = forbidden
            socket.socket.connect = forbidden
            import subtitle_core as core
            from ..diagnostics.build_identity import load_build_identity
            from ..recognition.asr_schema import normalize_firered_worker_result, flatten_segment_tokens
            from ..recognition.pipeline_runtime import finalize_cues
            from ..recognition.run_context import RuntimeContext, activate_runtime_context
            from ..recognition.transcript_data import SpeechSegment, SubtitleCue
            from ..projects.subtitle_import import _srt_rows
            from ..subtitle_rules.language_rules import language_scope
            from ..subtitle_rules.number_fidelity import cues_read_source_numbers
            from ..subtitle_rules.subtitle_fidelity import recover_final_content
            from ..subtitle_rules.text_rules import content_exact

            report_path = Path(spec["report"])
            original_bytes = report_path.read_bytes()
            result["report_sha256"] = hashlib.sha256(original_bytes).hexdigest()
            data = json.loads(original_bytes.decode("utf-8-sig"))
            events = data["events"]
            previews = {r["cue_id"]: r for e in events
                        if e["event"] == "cloud_batch_preview" and e["stage"] == "polished"
                        for r in e["rows"]}
            finals = {e["cue_id"]: e["details"] for e in events if e["event"] == "terminology_polish_final"}
            phases = {e["phase"]: e for e in events if e["event"] == "display_boundary_phase"}
            speakers = {r["speaker"] for p in phases.values() for r in p["cues"]}
            # Preview rows do not carry a speaker; never guess for a multi-speaker report.
            check("single_speaker_reconstruction_is_unambiguous", len(speakers) == 1)
            speaker = next(iter(speakers))
            check("complete_polished_source_ids", previews.keys() == finals.keys() and bool(previews))
            segments = [SpeechSegment(i, r["start"], r["end"], finals[i]["final_text"], 1, [], speaker=speaker)
                        for i, r in sorted(previews.items())]
            original_sources = [(s.segment_id, s.start, s.end, s.text, s.speaker, copy.deepcopy(s.words))
                                for s in segments]
            source_text = "".join(content_exact(s.text) for s in segments)
            raw = sorted((r for e in events if e["event"] == "asr_evidence_delta" for r in e["rows"]),
                         key=lambda r: r["segment_id"])
            jobs = [dict(segment_id=r["segment_id"], offset=r.get("offset", 0),
                         duration=r["duration"]) for r in raw]
            tokens = flatten_segment_tokens(normalize_firered_worker_result({"results": raw}, jobs),
                                            producer="saved_report", consumer="offline_finalization")
            result["inputs"] = dict(segments=len(segments), content_characters=len(source_text),
                                    firered_tokens=len(tokens), audio_seconds=data["media"]["audio_seconds"],
                                    fps=phases["grouped_before_display"]["fps"])
            result["limitations"] = ["Source words/arbitration metadata and full VAD regions are absent from this report.",
                                     "No source media decoding, new ASR, cloud calls or acoustic-quality assessment."]
            def cues(phase):
                return [SubtitleCue(r["id"], r["start_ms"]/1000, r["end_ms"]/1000,
                                    r["text"], speaker=r["speaker"]) for r in phases[phase]["cues"]]

            for mode in ("recover", "finalize"):
                omitted = []
                context = RuntimeContext(task_language="zh", requested_language="zh",
                                         event_log_path=str(output / (mode + "-events.jsonl")))
                with activate_runtime_context(context, legacy=core), language_scope("zh"):
                    with core.capture_review_items():
                        grouped = cues("grouped_before_display")
                        if mode == "recover":
                            # The report snapshot precedes this text-free clamp in production.
                            incoming = core.validate_final_cues(cues("short_gap_bridge"), segments,
                                        data["media"]["audio_seconds"], validate_text=False)
                            final = recover_final_content(incoming, grouped, segments, tokens, core)
                        else:
                            original_cleanup = core.apply_isolated_single_character_rules_safely
                            def capture_omissions(rows, *, omitted=None):
                                cleaned = original_cleanup(rows, omitted=omitted)
                                if omitted:
                                    recorded_omissions.extend(copy.deepcopy(omitted))
                                return cleaned
                            recorded_omissions = omitted
                            core.apply_isolated_single_character_rules_safely = capture_omissions
                            try:
                                final = finalize_cues(grouped, segments, tokens, [], data["media"]["audio_seconds"],
                                                      phases["grouped_before_display"]["fps"], core)
                            finally:
                                core.apply_isolated_single_character_rules_safely = original_cleanup
                final = sorted(final, key=lambda c: (c.start, c.end))
                (output / (mode + "-cues.json")).write_text(json.dumps([asdict(c) for c in final],
                     ensure_ascii=False, indent=2), encoding="utf-8")
                actual = "".join(content_exact(c.text) for c in final)
                accounted = sorted([*final, *omitted], key=lambda c: (c.start, c.end))
                accounted_text = "".join(content_exact(c.text) for c in accounted)
                check(mode + "_text_exact_with_recorded_omissions", accounted_text == source_text,
                      source_characters=len(source_text), output_characters=len(actual),
                      recorded_omissions=[asdict(c) for c in omitted])
                check(mode + "_numbers_preserved", cues_read_source_numbers(segments, accounted))
                # Final display relocking may bridge a <=500ms gap after the five-second clamp.
                limit = 5.05 if mode == "recover" else 5 + core.SHORT_DISPLAY_GAP_BRIDGE_SECONDS + 1/result["inputs"]["fps"]
                check(mode + "_positive_bounded_cues", all(0 < c.end-c.start <= limit
                      and core.display_length(c.text) <= 16 and c.start >= 0
                      and c.end <= data["media"]["audio_seconds"] + .05 for c in final),
                      maximum_seconds=max(c.end-c.start for c in final), display_limit=limit)
                check(mode + "_no_same_speaker_collisions", all(b.start >= a.end-.001
                      for a, b in zip(final, final[1:])))
                srt = core.render_srt(final)
                (output / (mode + ".srt")).write_text(srt, encoding="utf-8")
                imported = _srt_rows(srt)
                check(mode + "_srt_readback", len(imported) == len(final) and
                      "".join(content_exact(r.text) for r in imported) == actual,
                      cues=len(final), srt_cues=len(imported))
                phase_events = [json.loads(line) for line in Path(context.event_log_path).read_text("utf-8").splitlines()]
                result[mode] = dict(cues=len(final), maximum_seconds=max(c.end-c.start for c in final),
                                    event_counts=dict(Counter(e["event"] for e in phase_events)),
                                    affected_cues=[asdict(c) for c in final if c.end > 659 and c.start < 673])
            check("immutable_source_text_times_and_words", original_sources == [
                (s.segment_id, s.start, s.end, s.text, s.speaker, s.words) for s in segments])
            check("original_report_unchanged", report_path.read_bytes() == original_bytes)
            result["build_identity"] = asdict(load_build_identity())
            result["passed"] = all(c["passed"] for c in result["checks"])
        except Exception as exc:
            traceback.print_exc()
            result.update(error=str(exc), error_type=type(exc).__name__)
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(passed=result["passed"], checks=len(result["checks"]),
                         frozen=result["frozen"], error=result.get("error")), ensure_ascii=False))
    return 0 if result["passed"] else 1
