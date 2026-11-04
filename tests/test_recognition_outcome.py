"""Production report shapes for the three independent outcome layers."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from twobyteasr.recognition.recognition_outcome import normalize_recognition_outcome


def current_report():
    # Reduced, non-private shape of the supplied 2026-10-04 23:33:59 report.
    return {
        "schema_version": 1, "status": "degraded_success",
        "started_at": "2026-10-04T23:33:59+0800",
        "finished_at": "2026-10-04T23:36:36+0800",
        "media": {"name": "本轮.mp4", "path": "fixture/本轮.mp4"},
        "settings": {"models": {"qwen_asr_model": "Qwen3-ASR", "polish_provider": "deepseek", "polish_model": "deepseek-v4-pro", "group_model": "deepseek-v4-pro"}, "switches": {}, "performance": {}},
        "cache": {"hits": [], "writes": []},
        "stages": [{"index": 8, "label": "云端模型字幕校对", "status": "completed", "elapsed_seconds": 5.997},
                   {"index": 9, "label": "云端模型全文智能断句", "status": "completed", "elapsed_seconds": 13.851},
                   {"index": 11, "label": "保存识别结果与工程", "status": "completed"}],
        "events": [{"event": "domain_term_search_started", "candidate_count": 31},
                   {"event": "domain_term_search_failed", "category": "unsupported_search", "error": "当前 Provider 未配置可验证的联网检索能力"},
                   {"event": "studio_project_saved", "project_path": "fixture/result.2byteproj"}],
        "polishing_summary": {"success_batches": 1, "success_cues": 31, "fallback_batches": 0, "fallback_cues": 0, "failure_categories": {}, "term_context": {"accepted_edits": 6}},
        "terminology_summary": {"status": "failed", "candidate_count": 31, "verified_count": 0, "unverified_count": 31, "failure_categories": {"unsupported_search": 31}},
        "result": {"elapsed_seconds": 156.424, "segment_count": 31, "cue_count": 32, "outputs": {"project": "fixture/result.2byteproj", "txt": ""}},
        "review_items": [{"category": "主力转写提前结束", "severity": "warning", "detail": "MOSS尾端55.64s与VAD56.21s不一致"},
                         *[{"category": "阅读较快", "severity": "review", "cue_id": index, "detail": "等待原音检查"} for index in range(10)]],
        "review_severity_counts": {"error": 0, "warning": 1, "review": 10, "info": 0, "debug": 0},
    }


def test_current_report_optional_search_does_not_overwrite_text_result():
    report = current_report()
    before = copy.deepcopy(report)
    outcome = normalize_recognition_outcome(report)
    assert outcome.core_status == "completed" and outcome.result_usable
    assert outcome.title == "字幕已生成" and outcome.status_label == "已完成 · 有待检查项"
    assert (outcome.polish_status, outcome.search_status) == ("completed", "unsupported")
    assert (outcome.processed_records, outcome.final_cues, outcome.success_records, outcome.fallback_records, outcome.accepted_edits) == (31, 32, 31, 0, 6)
    assert (outcome.severity_count("error"), outcome.severity_count("warning"), outcome.severity_count("review")) == (0, 1, 10)
    assert outcome.review_issue_count == 11 and outcome.review_affected_cues == 10
    assert not outcome.search_retryable and not outcome.polish_retryable
    assert outcome.elapsed_seconds == 156.424
    assert "MOSS尾端" in outcome.problems[0]
    assert report == before


@pytest.mark.parametrize("state", ["disabled", "not_configured", "unsupported", "not_run"])
def test_absent_optional_search_never_fails_core_or_enables_retry(state):
    report = current_report()
    report["terminology_summary"] = {"status": state, "retryable": False, "unverified_count": 31}
    outcome = normalize_recognition_outcome(report)
    assert outcome.core_status == "completed" and outcome.search_status == state
    assert not outcome.search_retryable and outcome.severity_count("error") == 0


def test_real_search_timeout_keeps_core_and_quality_separate():
    report = current_report()
    report["terminology_summary"] = {"status": "failed", "failure_categories": {"timeout": 1}, "retryable": True, "capability_available": True, "unverified_count": 31}
    outcome = normalize_recognition_outcome(report)
    assert outcome.core_status == "completed" and outcome.search_retryable
    assert outcome.search_status == "failed" and outcome.severity_count("error") == 0


def test_partial_text_polish_preserves_usable_results_and_real_failure_scope():
    report = current_report()
    report["polishing_summary"].update(success_cues=20, fallback_cues=11, fallback_batches=1, failure_categories={"timeout": 11})
    outcome = normalize_recognition_outcome(report)
    assert outcome.core_status == "partial" and outcome.result_usable
    assert outcome.polish_retryable and not outcome.search_retryable
    assert (outcome.success_records, outcome.fallback_records, outcome.final_cues) == (20, 11, 32)


@pytest.mark.parametrize("save_shape", ["event", "output", "stage"])
def test_required_project_save_failure_is_real_failure_even_with_cues(save_shape):
    report = current_report()
    if save_shape == "event":
        report["events"].append({"event": "studio_project_failed", "error": "disk full"})
    elif save_shape == "output":
        report["result"]["outputs"].update(project="", project_error="disk full")
    else:
        report["stages"][-1].update(status="failed", error="disk full")
    outcome = normalize_recognition_outcome(report)
    assert outcome.core_status == "failed" and not outcome.result_usable
    assert "disk full" in " ".join(outcome.core_errors)


def test_retry_success_does_not_inherit_earlier_worker_or_save_failure():
    report = current_report()
    report["events"].insert(0, {"event": "MODEL_FAILED", "error": "earlier attempt"})
    report["events"].insert(0, {"event": "studio_project_failed", "error": "earlier attempt"})
    report["stages"].insert(0, {"label": "保存识别结果与工程", "status": "failed", "error": "earlier attempt"})
    outcome = normalize_recognition_outcome(report)
    assert outcome.core_status == "completed" and outcome.severity_count("error") == 0


def test_cancelled_remains_distinct_and_unknown_legacy_is_not_guessed():
    report = current_report()
    report["status"] = "cancelled"
    assert normalize_recognition_outcome(report).core_status == "cancelled"
    assert normalize_recognition_outcome({"settings": {"models": {"polish_provider": "deepseek"}}}).core_status == "unknown"
    assert normalize_recognition_outcome({"status": "degraded_success"}).core_status == "unknown"


def test_quality_error_is_not_an_operational_failure_when_result_is_usable():
    report = current_report()
    report["review_items"].append({"severity": "error", "category": "字幕重叠", "detail": "需检查"})
    report["review_severity_counts"]["error"] = 1
    outcome = normalize_recognition_outcome(report)
    assert outcome.core_status == "completed" and outcome.severity_count("error") == 1


def test_search_success_requires_a_real_execution_receipt():
    report = current_report()
    report["terminology_summary"] = {"status": "success", "candidate_count": 31, "verified_count": 31, "evidence_verified": True, "search_evidence": [{"tool": "model_answer", "urls": ["https://example.test/generated"]}]}
    outcome = normalize_recognition_outcome(report)
    assert outcome.search_status == "unknown" and outcome.search_verified_records == 0
    report["terminology_summary"]["search_evidence"] = [{"tool": "web_search", "urls": ["https://example.test/source"]}]
    outcome = normalize_recognition_outcome(report)
    assert outcome.search_status == "completed" and outcome.search_verified_records == 31


def test_history_refresh_normalizes_unchanged_raw_report_and_version_invalidates_cache(tmp_path, monkeypatch):
    from twobyteasr.recognition import recognition_history as history
    report = current_report()
    path = tmp_path / "本轮_字幕任务报告.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    records, errors = history.load_recognition_records(tmp_path, cache={})
    assert not errors and records[0].status == "completed"
    assert records[0].payload["status"] == "degraded_success"
    assert records[0].status_label == normalize_recognition_outcome(report).status_label
    cache = {path: (path.stat().st_mtime_ns, path.stat().st_size, records[0], None, -1)}
    calls = []
    original = history.parse_recognition_report
    monkeypatch.setattr(history, "parse_recognition_report", lambda target: (calls.append(target), original(target))[1])
    history.load_recognition_records(tmp_path, cache=cache)
    assert calls == [path] and before == hashlib.sha256(path.read_bytes()).hexdigest()


def test_new_report_text_and_history_use_the_same_shared_outcome(tmp_path, monkeypatch):
    from twobyteasr.recognition import reporting
    from twobyteasr.recognition.recognition_history import parse_recognition_report
    report = current_report()
    media = tmp_path / "本轮.mp4"
    media.write_bytes(b"fixture")
    report["media"]["path"] = str(media)
    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path)
    json_path, text_path = reporting._write_report(report)
    text = open(text_path, encoding="utf-8").read()
    record = parse_recognition_report(json_path)
    assert "处理结果：" + record.status_label in text
    assert "AI文字校对已完成" in text and "当前通道不支持" in text
    assert "成功：1 批 / 31 条处理记录" in text and "字幕条数：32" in text
    assert "已采纳云端校对：6 处" in text
    assert "降级说明：" not in text and "TXT：" not in text
    assert record.severity_count("error") == 0 and record.review_count == 10


def test_explicit_locale_presentation_does_not_read_preferences(monkeypatch):
    from twobyteasr import i18n
    report = current_report()
    monkeypatch.setattr(i18n, "current_language", lambda: (_ for _ in ()).throw(AssertionError("no preference read")))
    monkeypatch.setitem(i18n._TRANSLATIONS["en"], "处理记录 {records} 条 · 最终字幕 {cues} 条", "{records} input records · {cues} final subtitles")
    outcome = normalize_recognition_outcome(report)
    assert "31 input records · 32 final subtitles" in outcome.localized_detail_lines("en")
    assert "处理记录 31 条 · 最终字幕 32 条" in outcome.detail_lines


def test_queue_aggregation_uses_independent_core_states():
    from twobyteasr.recognition.recognition_outcome import normalize_recognition_queue
    completed = current_report()
    partial = copy.deepcopy(completed)
    partial["polishing_summary"].update(success_cues=20, fallback_cues=11)
    failed = {"status": "failed", "result": {"error": "save failed"}}
    cancelled = {"status": "cancelled"}
    queue = normalize_recognition_queue([completed])
    assert queue.core_status == "completed" and queue.search_incomplete_count == 1
    assert queue.completed_count == 1 and queue.review_task_count == 1
    queue = normalize_recognition_queue([completed, partial, failed])
    assert queue.core_status == "partial" and queue.notification_level == "warning"
    assert (queue.completed_count, queue.partial_count, queue.failed_count) == (1, 1, 1)
    assert normalize_recognition_queue([failed]).core_status == "failed"
    assert normalize_recognition_queue([cancelled, completed]).core_status == "cancelled"
    assert normalize_recognition_queue([{}]).core_status == "unknown"


def test_verified_recovery_is_a_separate_delivery_and_does_not_rewrite_failure():
    from twobyteasr.recognition.recognition_outcome import RecognitionDeliveryWitness
    report = current_report()
    report['status'] = 'failed'
    report['result']['error'] = 'original save failed'
    report['result']['outputs'] = {'project': '', 'project_error': 'original save failed'}
    before = copy.deepcopy(report)
    witness = RecognitionDeliveryWitness(report_path='fixture/report.json', report_sha256='a' * 64,
        report_started_at=report['started_at'], project_path='fixture/recovered.2byteproj',
        project_sha256='b' * 64, cue_count=32, verified_saved_project=True)
    recovered = normalize_recognition_outcome(report, delivery_witness=witness)
    assert recovered.core_status == 'partial' and recovered.result_usable and recovered.delivery_recovered
    assert recovered.raw_status == 'failed' and recovered.original_core_status == 'failed'
    assert recovered.core_errors == () and 'original save failed' in ' '.join(recovered.historical_core_errors)
    assert normalize_recognition_outcome(report).core_status == 'failed'
    assert report == before
    invalid = RecognitionDeliveryWitness(report_path='fixture/report.json', report_sha256='a' * 64,
        report_started_at='different task', project_path='fixture/recovered.2byteproj',
        project_sha256='b' * 64, cue_count=32, verified_saved_project=True)
    with pytest.raises(ValueError):
        normalize_recognition_outcome(report, delivery_witness=invalid)
    with pytest.raises(TypeError):
        normalize_recognition_outcome(report, delivery_witness={'verified_saved_project': True})


@pytest.mark.parametrize("receipts,expected", [
    ([{"tool": "search_web", "step_index": 3}], "unknown"),
    ([{"tool": "search_web", "step_index": 3},
      {"tool": "https_source_fetch", "urls": ["https://example.test/official"],
       "verification": "target_present_in_fetched_body"}], "completed"),
    ([{"tool": "https_source_fetch", "urls": ["https://example.test/official"]}], "unknown"),
    ([{"tool": "web_search", "urls": ["http://example.test/insecure"]}], "unknown"),
])
def test_search_coverage_requires_execution_and_returned_https_sources(receipts, expected):
    report = current_report()
    report["terminology_summary"] = {"status": "completed", "verified_count": 31,
        "evidence_verified": True, "search_evidence": receipts}
    outcome = normalize_recognition_outcome(report)
    assert outcome.search_status == expected
    assert outcome.search_verified_records == (31 if expected == "completed" else 0)
