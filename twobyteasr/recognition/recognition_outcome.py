"""Read-only task outcomes shared by delivery, reports and recognition history.

The raw report remains evidence. Optional search diagnostics and earlier worker
attempts never replace the final core result. Quality counts keep their own unit.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Any

OUTCOME_VERSION = 1
SEVERITIES = ("error", "warning", "review", "info", "debug")
_SUCCESS = {"success", "completed", "degraded_success"}
_SAVE_FAILURES = {"studio_project_failed", "studio_project_save_failed", "project_save_failed", "recognition_result_save_failed"}
_SEVERITY_BY_CATEGORY = {
    "校对回退": "warning", "断句回退": "warning", "主力转写提前结束": "warning",
    "时间轴模型失败": "warning", "Whisper失败": "warning", "漏句回退": "warning",
    "Qwen骨架缺口": "info", "时间锚覆盖低": "info",
}

def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}

def _rows(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0

def review_severity(item: dict) -> str:
    explicit = str(item.get("severity") or "").lower()
    if explicit in SEVERITIES:
        return explicit
    return _SEVERITY_BY_CATEGORY.get(str(item.get("category") or ""), "review" if _int(item.get("priority", 2)) >= 2 else "info")

def _note(item: dict) -> str:
    return str(item.get("message") or item.get("detail") or item.get("category") or "").strip()

def _unique(items) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))

def _optional_search(row: dict) -> bool:
    name = str(row.get("event") or row.get("label") or row.get("stage") or "").lower()
    return any(part in name for part in ("domain_term_search", "domain_term_verification", "term_search", "联网", "检索核验"))

def _polish_stage(row: dict) -> bool:
    label = str(row.get("label") or row.get("stage") or "").lower()
    return any(part in label for part in ("polish", "文字校对", "文本校对", "字幕校对"))

@dataclass(frozen=True)
class RecognitionOutcome:
    raw_status: str
    core_status: str
    status_label: str
    title: str
    result_usable: bool
    polish_status: str
    polish_label: str
    search_status: str
    search_label: str
    search_reason: str
    search_retryable: bool
    polish_retryable: bool
    severity_counts: tuple[tuple[str, int], ...]
    problems: tuple[str, ...]
    review_notes: tuple[str, ...]
    core_errors: tuple[str, ...]
    processed_records: int
    final_cues: int
    success_records: int
    fallback_records: int
    accepted_edits: int
    review_issue_count: int
    review_affected_cues: int | None
    review_affected_records: int | None
    search_verified_records: int
    search_unverified_records: int
    elapsed_seconds: float
    delivery_recovered: bool = False
    original_core_status: str = ""
    historical_core_errors: tuple[str, ...] = ()

    def severity_count(self, severity: str) -> int:
        return dict(self.severity_counts).get(severity, 0)

    @property
    def has_review(self) -> bool:
        return self.review_issue_count > 0

    @property
    def detail_lines(self) -> tuple[str, ...]:
        return self.localized_detail_lines("zh")

    def localized_detail_lines(self, language: str) -> tuple[str, ...]:
        """Render an already-normalized result in an explicit locale.

        Only this presentation boundary imports i18n; normalization never reads
        preferences, loads a report, constructs Qt widgets or performs IO.
        """
        from ..i18n import translate

        def line(source, **arguments):
            return translate(source, language).format(**arguments)

        lines = [translate(self.polish_label, language), translate(self.search_label, language)]
        if self.search_reason:
            lines.append(translate(self.search_reason, language))
        if self.processed_records:
            lines.append(line("处理记录 {records} 条 · 最终字幕 {cues} 条", records=self.processed_records, cues=self.final_cues))
        if self.accepted_edits:
            lines.append(line("实际接受文字修改 {count} 处", count=self.accepted_edits))
        if self.fallback_records:
            lines.append(line("文字校对已完成 {success} 条处理记录；{fallback} 条回退到原文", success=self.success_records, fallback=self.fallback_records))
        if self.search_verified_records or self.search_unverified_records:
            lines.append(line("联网范围：已核验 {verified} 条处理记录；未核验 {unverified} 条处理记录", verified=self.search_verified_records, unverified=self.search_unverified_records))
        if self.review_issue_count:
            lines.append(line("待检查问题 {count} 项", count=self.review_issue_count))
        if self.review_affected_cues is not None:
            lines.append(line("明确关联字幕 {count} 条", count=self.review_affected_cues))
        if self.review_affected_records is not None:
            lines.append(line("明确关联处理记录 {count} 条", count=self.review_affected_records))
        lines.extend(translate(error, language) for error in self.core_errors)
        if self.delivery_recovered:
            lines.append(translate("恢复副本已保存并重新载入；原任务报告与诊断保持不变", language))
            lines.extend(line("原任务诊断：{reason}", reason=error) for error in self.historical_core_errors)
        return tuple(lines)

def _normalize_report_outcome(payload: dict[str, Any] | None) -> RecognitionOutcome:
    """Derive display state without mutating or upgrading historical evidence."""
    payload = _dict(payload)
    result = _dict(payload.get("result"))
    outputs = _dict(result.get("outputs"))
    events = _rows(payload.get("events"))
    stages = _rows(payload.get("stages"))
    items = _rows(payload.get("review_items"))
    polish = _dict(payload.get("polishing_summary"))
    if not polish:
        polish = next((row for row in reversed(events) if row.get("event") == "polishing_summary"), {})
    search = _dict(payload.get("terminology_summary")) or _dict(payload.get("terminology_status")) or _dict(polish.get("terminology"))
    if not search:
        search = next((row for row in reversed(events) if row.get("event") == "domain_term_verification_summary"), {})
    raw_status = str(payload.get("status") or "unknown").lower()

    # Content quality is not a count of optional operation errors.
    item_counts = Counter(review_severity(item) for item in items)
    stored = _dict(payload.get("review_severity_counts"))
    counts = {key: max(item_counts[key], _int(stored.get(key))) for key in SEVERITIES}
    config_notes = [str(item) for item in (_dict(payload.get("settings")).get("config_warnings") or []) if str(item).strip()]
    if not stored:
        counts["warning"] += len(config_notes)
    problems = [_note(item) for item in items if review_severity(item) in {"error", "warning"}]
    problems.extend(config_notes)
    review_notes = [_note(item) for item in items if review_severity(item) == "review"]

    final_cues = _int(result.get("cue_count"))
    success_records = _int(polish.get("success_cues", polish.get("success_records")))
    fallback_records = _int(polish.get("fallback_cues", polish.get("fallback_records")))
    processed_records = _int(result.get("segment_count")) or success_records + fallback_records
    context = _dict(polish.get("term_context"))
    accepted_edits = _int(context.get("accepted_edits")) if "accepted_edits" in context else sum(len(row.get("edits") or []) for row in events if row.get("event") == "cloud_correction_applied")
    if fallback_records or _int(polish.get("fallback_batches")):
        polish_status, polish_label = "partial", "部分AI文字校对未完成"
    elif polish and (success_records or _int(polish.get("success_batches"))):
        polish_status, polish_label = "completed", "AI文字校对已完成"
    elif any(_polish_stage(row) and row.get("status") in _SUCCESS for row in stages):
        polish_status, polish_label = "completed", "AI文字校对已完成"
    elif any(review_severity(row) == "warning" and row.get("category") == "校对回退" for row in items):
        polish_status, polish_label = "partial", "部分AI文字校对未完成"
    elif _dict(_dict(payload.get("settings")).get("switches")).get("enable_ai_polish") is False:
        polish_status, polish_label = "disabled", "AI文字校对未启用"
    elif "polished" in (_dict(payload.get("cache")).get("hits") or []):
        polish_status, polish_label = "completed", "AI文字校对已完成（复用文字缓存）"
    else:
        polish_status, polish_label = "unknown", "文字校对状态待确认"

    search_status = str(search.get("status") or "unknown").lower()
    categories = _dict(search.get("failure_categories"))
    search_events = [row for row in events if _optional_search(row)]
    if search_status == "failed" and categories and set(categories) <= {"unsupported_search", "not_configured", "disabled"}:
        search_status = "not_configured" if "not_configured" in categories else "disabled" if "disabled" in categories else "unsupported"
    elif search_status == "unknown":
        capability_failure = next((row for row in reversed(search_events) if row.get("category") in {"unsupported_search", "not_configured"}), {})
        if capability_failure:
            search_status = "unsupported" if capability_failure.get("category") == "unsupported_search" else "not_configured"
        elif any(row.get("event") == "domain_term_search_failed" for row in search_events):
            search_status = "failed"
        elif any(row.get("event") == "domain_term_search_completed" for row in search_events):
            search_status = "unknown"
        elif _dict(_dict(payload.get("settings")).get("switches")).get("enable_term_search") is False:
            search_status = "disabled"
    if search_status == "success":
        search_status = "completed"
    if search_status == "skipped":
        search_status = "disabled" if "disabled" in str(search.get("reason") or "").lower() else "not_run"
    search_labels = {
        "completed": "联网核验已完成", "partial": "联网核验部分完成", "failed": "联网核验未完成",
        "timeout": "联网核验超时", "insufficient_evidence": "联网核验证据不足",
        "not_configured": "联网核验未配置", "unsupported": "联网核验未执行（当前通道不支持）",
        "disabled": "联网核验未启用", "not_run": "联网核验未执行", "unknown": "联网核验状态待确认",
    }
    # A structured model answer or its generated URLs do not prove retrieval.
    receipts = _rows(search.get("search_evidence"))
    search_tools = {"web_search", "search_web", "dashscope_web_search"}
    def returned_sources(row):
        return [url for url in (row.get("urls") if isinstance(row.get("urls"), list) else ())
                if isinstance(url, str) and url.startswith("https://")]
    evidence_verified = bool(search.get("evidence_verified")) and bool(receipts) and (
        any(row.get("tool") in search_tools for row in receipts)
        and all(row.get("tool") in search_tools | {"https_source_fetch"}
                and (returned_sources(row) or type(row.get("step_index")) is int) for row in receipts)
        and any(returned_sources(row) for row in receipts)
    )
    unproved_search = search_status in {"completed", "partial"} and not evidence_verified
    if unproved_search:
        search_status = "unknown"
    search_label = search_labels.get(search_status, "联网核验状态待确认")
    search_reason = str(search.get("reason") or search.get("error") or "").strip()
    if unproved_search:
        search_reason = "历史报告未保留可验证的联网检索证据"
    if not search_reason:
        search_reason = next((str(row.get("error") or row.get("reason") or "").strip() for row in reversed(search_events) if row.get("error") or row.get("reason")), "")
    search_retryable = bool(search.get("retryable")) and search_status in {"partial", "failed", "timeout", "insufficient_evidence"}

    core_errors = []
    save_error = str(outputs.get("project_error") or result.get("project_save_error") or "").strip()
    if save_error:
        core_errors.append("识别结果工程保存失败：" + save_error)
    # A successful retry supersedes the earlier save attempt, which remains raw evidence.
    save_events = [row for row in events if str(row.get("event") or "").lower() in _SAVE_FAILURES | {"studio_project_saved"}]
    if save_events and str(save_events[-1].get("event") or "").lower() in _SAVE_FAILURES:
        core_errors.append(str(save_events[-1].get("error") or "识别结果工程保存失败"))
    latest_stages = {str(row.get("label") or row.get("index") or ""): row for row in stages}
    for row in latest_stages.values():
        if row.get("status") == "failed" and not _optional_search(row) and not _polish_stage(row):
            core_errors.append(str(row.get("error") or f"{row.get('label', '核心处理')}未完成"))
    if result.get("error"):
        core_errors.append(str(result["error"]))
    usable_evidence = final_cues > 0 or bool(outputs.get("project") or outputs.get("srt"))
    usable = usable_evidence and not core_errors
    if raw_status in {"cancelled", "canceled"}:
        core_status, label, title = "cancelled", "已取消", "任务已取消"
    elif raw_status == "failed" or core_errors:
        usable = False
        core_status, label, title = "failed", "失败", "识别未完成"
    elif raw_status in _SUCCESS:
        usable = usable or ("cue_count" in result and final_cues == 0)
        if not usable:
            core_status, label, title = "unknown", "状态待确认", "任务状态待确认"
        elif polish_status == "partial":
            core_status, label, title = "partial", "部分完成", "字幕已生成 · 部分AI校对未完成"
        else:
            core_status = "completed"
            label = "已完成 · 有待检查项" if sum(counts[key] for key in ("error", "warning", "review")) else "完成"
            title = "字幕已生成"
    elif raw_status == "running":
        core_status, label, title = "running", "进行中", "正在生成字幕"
    elif raw_status == "skipped":
        core_status, label, title = "skipped", "已跳过", "任务已跳过"
    else:
        core_status, label, title = "unknown", "状态待确认", "任务状态待确认"
    problems.extend(core_errors)
    affected_cues = {str(item["cue_id"]) for item in items if item.get("cue_id") is not None and review_severity(item) in {"error", "warning", "review"}}
    affected_records = {str(item["segment_id"]) for item in items if item.get("segment_id") is not None and review_severity(item) in {"error", "warning", "review"}}
    return RecognitionOutcome(
        raw_status=raw_status, core_status=core_status, status_label=label, title=title,
        result_usable=usable, polish_status=polish_status, polish_label=polish_label,
        search_status=search_status, search_label=search_label, search_reason=search_reason,
        search_retryable=search_retryable, polish_retryable=fallback_records > 0,
        severity_counts=tuple((key, counts[key]) for key in SEVERITIES),
        problems=_unique(problems), review_notes=_unique(review_notes), core_errors=_unique(core_errors),
        processed_records=processed_records, final_cues=final_cues, success_records=success_records,
        fallback_records=fallback_records, accepted_edits=accepted_edits,
        review_issue_count=sum(counts[key] for key in ("error", "warning", "review")),
        review_affected_cues=len(affected_cues) if affected_cues else None,
        review_affected_records=len(affected_records) if affected_records else None,
        search_verified_records=_int(search.get("verified_count")) if evidence_verified else 0,
        search_unverified_records=max(_int(search.get("candidate_count")), _int(search.get("unverified_count"))) if unproved_search else _int(search.get("unverified_count")),
        elapsed_seconds=float(result.get("elapsed_seconds") or 0),
    )


@dataclass(frozen=True)
class RecognitionDeliveryWitness:
    """Caller-verified local delivery, separate from immutable task evidence.

    This type is never parsed from a report or model response. The UI creates
    it only after saving and reopening the recovered project and comparing
    both file hashes. Keeping it outside the report prevents historical failure
    records from being rewritten as new processing successes.
    """
    report_path: str
    report_sha256: str
    report_started_at: str
    project_path: str
    project_sha256: str
    cue_count: int
    verified_saved_project: bool


def normalize_recognition_outcome(payload: dict[str, Any] | None, *, delivery_witness: RecognitionDeliveryWitness | None = None) -> RecognitionOutcome:
    outcome = _normalize_report_outcome(payload)
    if delivery_witness is None:
        return outcome
    if not isinstance(delivery_witness, RecognitionDeliveryWitness):
        raise TypeError("recovered delivery must use a caller-verified RecognitionDeliveryWitness")
    witness = delivery_witness
    valid_hash = lambda value: len(str(value)) == 64 and all(char in "0123456789abcdef" for char in str(value).lower())
    if (not witness.verified_saved_project or not witness.report_path or not witness.project_path
            or not valid_hash(witness.report_sha256) or not valid_hash(witness.project_sha256)
            or witness.cue_count < 0
            or witness.report_started_at != str(_dict(payload).get("started_at") or "")):
        raise ValueError("recovered delivery lacks matching report identity and verified saved project evidence")
    if outcome.core_status == "cancelled":
        # A recovered artifact can be usable while the user's cancellation
        # remains the task's independent terminal state.
        status, label, title = "cancelled", "已取消 · 已有结果已恢复", "已有字幕结果已恢复"
    elif outcome.core_status == "completed":
        status, label, title = "completed", outcome.status_label, outcome.title
    else:
        status, label, title = "partial", "已有结果已恢复 · 原任务未完成", "已有字幕结果已恢复"
    historical = outcome.core_errors
    return replace(outcome, core_status=status, status_label=label, title=title,
                   result_usable=True, final_cues=witness.cue_count, core_errors=(),
                   problems=tuple(note for note in outcome.problems if note not in historical),
                   delivery_recovered=True, original_core_status=outcome.core_status,
                   historical_core_errors=historical)


@dataclass(frozen=True)
class RecognitionQueueOutcome:
    core_status: str
    status_label: str
    title: str
    notification_level: str
    completed_count: int
    partial_count: int
    failed_count: int
    cancelled_count: int
    skipped_count: int
    unknown_count: int
    review_task_count: int
    review_issue_count: int
    search_incomplete_count: int
    total_count: int


def normalize_recognition_queue(payloads) -> RecognitionQueueOutcome:
    """Aggregate normalized per-task facts; file loading belongs to the caller."""
    outcomes = tuple(value if isinstance(value, RecognitionOutcome) else normalize_recognition_outcome(value)
                     for value in payloads)
    counts = Counter(value.core_status for value in outcomes)
    completed, partial, failed = counts["completed"], counts["partial"], counts["failed"]
    cancelled, skipped, unknown = counts["cancelled"], counts["skipped"], counts["unknown"] + counts["running"]
    if failed:
        status = "partial" if completed or partial else "failed"
    elif cancelled:
        status = "cancelled"
    elif partial:
        status = "partial"
    elif unknown:
        status = "partial" if completed else "unknown"
    elif completed:
        status = "completed"
    elif skipped:
        status = "skipped"
    else:
        status = "empty"
    titles = {"completed": "字幕生成完成", "partial": "字幕生成部分完成", "failed": "字幕生成失败",
              "cancelled": "字幕任务已取消", "unknown": "字幕任务状态待确认", "skipped": "字幕生成完成", "empty": "字幕任务已结束"}
    labels = {"completed": "完成", "partial": "部分完成", "failed": "失败", "cancelled": "已取消",
              "unknown": "状态待确认", "skipped": "已跳过", "empty": "没有任务结果"}
    return RecognitionQueueOutcome(
        core_status=status, status_label=labels[status], title=titles[status],
        notification_level="error" if status == "failed" else "warning" if status in {"partial", "cancelled", "unknown"} else "information",
        completed_count=completed, partial_count=partial, failed_count=failed,
        cancelled_count=cancelled, skipped_count=skipped, unknown_count=unknown,
        review_task_count=sum(value.has_review for value in outcomes),
        review_issue_count=sum(value.review_issue_count for value in outcomes),
        search_incomplete_count=sum(value.search_status in {"unsupported", "not_configured", "not_run", "partial", "failed", "timeout", "insufficient_evidence"} for value in outcomes),
        total_count=len(outcomes),
    )
