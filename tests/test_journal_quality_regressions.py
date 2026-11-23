import json
import threading
from types import SimpleNamespace

import pytest


def test_streamed_report_validates_tail_and_redacts_without_truncating(tmp_path):
    from twobyteasr.recognition.recognition_history import _sensitive_key, redact_report_payload
    from twobyteasr.recognition.report_stream import (
        ReportCancelled, project_report, save_redacted_report, search_report,
    )

    source, output = tmp_path / "old.json", tmp_path / "redacted.json"
    original = {
        "settings": {"headers": {"Authorization": "Bearer key-secret123456789"}},
        "stages": [],
        "events": [{"event": "odd", "data": 'A \" marker ] and } \\'} for _ in range(15)],
        "review_items": [{"category": "needs review"}],
    }
    source.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    metadata, pages = project_report(source)
    assert metadata["events"] == []
    assert list(pages.read("events", 10, 3)) == original["events"][10:13]
    assert len(search_report(pages, "marker", redact_report_payload, _sensitive_key)) == 15
    assert search_report(pages, "secret123", redact_report_payload, _sensitive_key) == []
    save_redacted_report(source, output, redact_report_payload, _sensitive_key, identity=pages.identity)
    assert json.loads(output.read_text("utf-8")) == redact_report_payload(original)

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ReportCancelled):
        project_report(source, cancel=cancel)
    source.write_text(source.read_text("utf-8")[:-1], encoding="utf-8")
    with pytest.raises(ValueError):
        project_report(source)


def test_small_task_reference_projects_large_evidence(tmp_path):
    from twobyteasr.recognition.recognition_history import parse_recognition_report

    directory = tmp_path / "12345678123456781234567812345678"
    directory.mkdir()
    report = tmp_path / "report.json"
    task = directory / "task.json"
    head = dict(journal_version=1, job_id=directory.name, status="partial",
                settings={}, stages=[], media={"name": "recording"}, result={"cue_count": 12},
                task={"reports": [str(report)]})
    report.write_text(json.dumps({**head, "events": [{"event": "e", "text": "x"*5000}]*30}), encoding="utf-8")
    task.write_text(json.dumps(head), encoding="utf-8")

    record = parse_recognition_report(task)
    assert record.cue_count == 12 and record.report_pages.path == report
    assert len(record.report_pages.arrays["events"]) == 30
    assert record.payload["events"] == []
    report.write_text('{"results":[', "utf-8")
    broken = parse_recognition_report(task)
    assert broken.report_pages is None and broken.payload.get("report_read_error")


def test_all_raw_latin_and_fixed_phrase_interiors_stay_out_of_model_domain():
    import subtitle_core as core
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.subtitle_rules import ai_boundary_policy
    from twobyteasr.subtitle_rules.grouping_quality import quality_for_segments
    from twobyteasr.subtitle_rules.grouping_quality_request import correction_regression

    with activate_runtime_context(RuntimeContext(task_language="zh"), legacy=core):
        rows = [
            core.SpeechSegment(1, 0, 3.9, "Take it easy have fun it's just enough", 1, []),
            core.SpeechSegment(2, 4.2, 6.0, "嗯二选一的话", 1, []),
        ]
        quality = quality_for_segments(rows)
        ai_boundary_policy.select_model_boundary_domain(quality)
        end = len(core.content_exact(rows[0].text))
        assert not any(item["kind"] == "length" for item in ai_boundary_policy.inspect(quality, [end, quality.total]))
        for edge in (5, 16, end+2, end+3):
            assert edge not in ai_boundary_policy.break_candidates(quality)
            assert correction_regression(quality, [end, quality.total],
                sorted({edge, end, quality.total}), 0, quality.total) == "new_immutable_word_split"
            assert any(ai_boundary_policy.must_retain_source(issue) for issue in
                ai_boundary_policy.inspect(quality, sorted({edge, end, quality.total})))


def test_contradictory_pronoun_reason_does_not_adopt_the_edit():
    import subtitle_core as core
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits

    decisions = []
    source = '你认识她？'
    patch = dict(start=3, end=4, type="pronoun_gender", **{"from": "她", "to": "他"},
                 evidence='ASR作“他”，指代对象菲欧妮为女性，但主稿“她”已正确，无需改')
    with activate_runtime_context(RuntimeContext(task_language="zh"), legacy=core):
        text, edits = apply_correction_edits(source, ["你认识他"], [patch],
            independent_sources=[("firered", "你认识他")], decisions=decisions)
    assert text.startswith("你认识她") and not edits
    assert decisions[0]["rule_id"] == "pronoun_proposal_contradicts_retain_reason"


def test_display_tail_cannot_erase_measured_pause_or_relabel_display_as_acoustic():
    from twobyteasr.recognition.transcript_data import SubtitleCue
    from twobyteasr.subtitle_rules.display_timing import begin_display_receipts, record_display_receipts
    from twobyteasr.subtitle_rules.timing import bridge_short_display_gaps, extend_cue_tails_by_speaker

    left, right = SubtitleCue(1, 0.1, 1, "字幕"), SubtitleCue(2, 1.3, 2, "下一句")
    left.end_timing_basis, right.start_timing_basis = "firered_word", "provider_word"
    begin_display_receipts([left, right], [left, right])
    extend_cue_tails_by_speaker([left, right], 3, 60)
    bridge_short_display_gaps([left, right], 3, 60)
    record_display_receipts([left, right], "final")
    assert left.end == 1
    assert left.display_timing_receipt["acoustic_ms"] == [None, 1000]
    assert left.display_timing_receipt["measured_pause_after_ms"] == 300


def test_recognition_term_groups_require_an_unchanged_source_revision():
    from twobyteasr.glossary.recognition_term_candidates import preview_occurrences, project_candidates
    from twobyteasr.projects.studio_project import StudioCue

    cues = [StudioCue(id="first", start_ms=100, end_ms=900, text="菲欧妮来了", original_text="菲欧妮来了",
                      evidence_refs=["segment:5"])]
    row = {"final_text": "菲欧妮来了", "caption_arbitration": {"terminology_polish": {
        "rejected_edits": [{"type": "phonetic_correction", "from": "菲欧妮", "to": "菲欧尼",
                            "rule_id": "local_difference_without_two_sources"}]}}}
    project = SimpleNamespace(project_id="fixture", cues=cues, asr_evidence={"segment:5": row})
    group, = project_candidates(project)
    assert list(group["variants"]) == ["菲欧妮"]
    hit, = preview_occurrences(project, group, "菲欧尼", {"菲欧妮"})
    assert hit.original == "菲欧妮" and hit.span == (0, 3)
    row["final_text"] = "后来菲欧妮来了"
    assert list(preview_occurrences(project, group, "菲欧尼", {"菲欧妮"})) == []


def test_oversized_numeric_provider_word_has_no_measured_boundary():
    from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
    from twobyteasr.subtitle_rules.grouping_quality import boundary_timing_basis

    row = SpeechSegment(1, 0, 18, "506070", 1, [WordUnit(0.1, 17.81, "506070", 1)])
    row.caption_arbitration["word_timing"] = {"basis": "provider_words", "measured_words": [
        {"text": "506070", "start_ms": 100, "end_ms": 17810}]}
    assert boundary_timing_basis([row], [], 0.1, "start", "5") == "estimate"
    assert boundary_timing_basis([row], [], 17.81, "end", "0") == "estimate"
