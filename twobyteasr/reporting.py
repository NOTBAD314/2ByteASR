"""Per-media task reports.  Reports intentionally contain no API keys or raw audio."""

import json
import os
import re
import time
import threading
from collections import Counter
from pathlib import Path

from .recognition_outcome import normalize_recognition_outcome


_active_report = None
_REPORT_LOCK = threading.RLock()
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _default_report_root() -> Path:
    """Reports must survive EXE rebuilds: keep them in the stable user-data tree.

    The install tree (PROJECT_ROOT) is still scanned for reading, but new
    reports are written here so a dist swap never starts history from zero.
    """
    try:
        from .runtime_paths import user_data_root

        return user_data_root() / "reports"
    except Exception:
        return PROJECT_ROOT / "reports"


REPORT_ROOT = _default_report_root()
# Read-only locations that may still hold older reports (previous install
# roots, source checkout). Deduplicated against REPORT_ROOT at load time.
LEGACY_REPORT_ROOTS: tuple[Path, ...] = (
    (PROJECT_ROOT / "reports",) if (PROJECT_ROOT / "reports") != REPORT_ROOT else ()
)

_SEVERITY_BY_CATEGORY = {
    "校对回退": "warning",
    "断句回退": "warning",
    "主力转写提前结束": "warning",
    "主力转写不完整": "warning",
    "时间轴模型失败": "warning",
    "Whisper失败": "warning",
    "漏句回退": "warning",
    "Qwen骨架缺口": "info",
    "时间锚覆盖低": "info",
}


def _review_severity(item):
    value = str(item.get("severity") or "").lower()
    if value in {"error", "warning", "review", "info", "debug"}:
        return value
    category = str(item.get("category") or "")
    return _SEVERITY_BY_CATEGORY.get(
        category,
        "review" if int(item.get("priority", 2) or 2) >= 2 else "info",
    )


def _build_review_summary(items):
    summaries = []
    aggregate = {
        "校对回退": ("AI 校对部分降级", "个批次使用本地结果"),
        "断句回退": ("AI 智能断句降级", "个批次使用本地断句"),
    }
    consumed = set()
    for category, (title, suffix) in aggregate.items():
        matching = [
            item for item in items
            if item.get("severity") == "warning"
            and item.get("category") == category
        ]
        if not matching:
            continue
        count = len({
            int(item.get("batch_index") or index + 1)
            for index, item in enumerate(matching)
        })
        total = max(
            (int(item.get("batch_total") or 0) for item in matching),
            default=0,
        ) or count
        summaries.append({
            "severity": "warning",
            "category": category,
            "count": count,
            "total": total,
            "message": f"{title}：{count} / {total} {suffix}。",
        })
        consumed.add(category)
    remaining = Counter(
        str(item.get("category") or "未分类")
        for item in items
        if item.get("severity") in {"error", "warning"}
        and item.get("category") not in consumed
    )
    summaries.extend(
        {
            "severity": "warning",
            "category": category,
            "count": count,
            "total": count,
            "message": f"{category}：{count} 项。",
        }
        for category, count in remaining.items()
    )
    return summaries


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def report_paths_for_media(media_path, job_id=None, media_index=None):
    path = Path(media_path)
    base_name = path.stem
    if job_id is None:
        from .runtime import get_runtime_context
        context = get_runtime_context()
        if context.identity_task_active and context.media_path and Path(context.media_path).resolve() == path.resolve():
            job_id = context.job_id
            media_index = context.media_index
    if job_id:
        from .recognition_result import validate_job_id
        base_name += "__" + validate_job_id(job_id) + "_" + str(int(media_index or 1))
    return (
        str(REPORT_ROOT / f"{base_name}_字幕任务报告.json"),
        str(REPORT_ROOT / f"{base_name}_字幕任务报告.txt"),
    )


def _archive_previous_report(json_path: Path, started_at: str) -> None:
    """Preserve a genuinely different run instead of overwriting it.

    Same media recognized twice must stay two records, so an existing report
    with a different started_at is renamed with its timestamp before the new
    one is written. Same-task rewrites keep overwriting in place.
    """
    try:
        if not json_path.exists():
            return
        previous = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        previous = None
    previous_started = (
        str(previous.get("started_at") or "") if isinstance(previous, dict) else ""
    )
    if previous_started and previous_started == str(started_at or ""):
        return
    stamp = re.sub(r"\D", "", previous_started)[:14] or time.strftime("%Y%m%d%H%M%S")
    base_stem = json_path.stem
    marker = "_字幕任务报告"
    if base_stem.endswith(marker):
        base_stem = base_stem[: -len(marker)]
    json_target = json_path.with_name(f"{base_stem}_{stamp}{marker}{json_path.suffix}")
    if json_target.exists():
        return
    try:
        json_path.replace(json_target)
        text_path = json_path.with_name(base_stem + marker + ".txt")
        if text_path.exists():
            text_path.replace(json_target.with_name(json_target.stem + ".txt"))
    except OSError:
        pass


def begin_media_report(media_path, cache_context, settings):
    global _active_report
    path = Path(media_path).resolve()
    stat = path.stat()
    from .runtime import get_runtime_context
    context = get_runtime_context()
    _active_report = {
        "schema_version": 1,
        "job_id": context.job_id if context.identity_task_active else "",
        "media_index": context.media_index if context.identity_task_active else 0,
        "status": "running",
        "started_at": _now(),
        "media": {
            "name": path.name,
            "path": str(path),
            "size_bytes": int(stat.st_size),
            "identity": dict(cache_context.get("identity") or {}),
        },
        "cache": {"directory": str(cache_context.get("cache_dir", "")), "hits": [], "writes": [], "accepted": [], "rejected": []},
        "settings": settings,
        "stages": [],
        "events": [],
        "review_items": [],
    }


def record_media_event(event, **payload):
    with _REPORT_LOCK:
        if _active_report is None:
            return
        if (_active_report.get('job_id') and payload.get('job_id')
                and payload['job_id'] != _active_report['job_id']):
            return
        row = {"time": _now(), "event": str(event), **payload}
        _active_report["events"].append(row)
        if event == 'task_audio_ready':
            # Known before any model runs, so a failed task still reports it.
            _active_report.setdefault('media', {})['audio_seconds'] = payload.get('seconds')
        elif event == 'moss_full_context_preparing':
            _active_report['moss_execution'] = {**payload, 'application_chunk_count': 0,
                'worker_count': 0, 'generation_attempts': 0, 'complete': False}
        elif event in {"moss_full_context_execution", "moss_full_context_result"}:
            _active_report.setdefault("moss_execution", {}).update(payload)
        elif event == 'asr_worker_started' and payload.get('backend') == 'moss':
            execution = _active_report.setdefault('moss_execution', {})
            pids = execution.setdefault('worker_pids', [])
            if payload['pid'] not in pids: pids.append(payload['pid'])
            execution['worker_count'] = len(pids)
        elif event == 'asr_worker_progress' and payload.get('backend') == 'moss':
            execution = _active_report.setdefault('moss_execution', {})
            for key in ('phase', 'elapsed_seconds', 'last_activity_elapsed_seconds',
                        'generated_tokens', 'input_tokens', 'max_new_tokens',
                        'application_chunk_count', 'sample_count', 'sample_rate',
                        'task_audio_fingerprint', 'attention_backend', 'dtype'):
                if key in payload: execution[key] = payload[key]
            if 'generation_attempt' in payload:
                execution['generation_attempts'] = int(payload['generation_attempt'])
        elif event == 'asr_worker_exited' and payload.get('backend') == 'moss':
            execution = _active_report.setdefault('moss_execution', {})
            execution['worker_returncode'] = payload.get('returncode')
            if payload.get('returncode'):
                execution.update(complete=False, failure_stage=execution.get('phase'),
                                 end_reason='worker_stopped_or_failed')
        elif event == "moss_full_context_coverage":
            execution = _active_report.setdefault("moss_execution", {})
            execution["complete"] = False
            execution.setdefault("truncation_reasons", []).append(payload.get("reason"))
            execution["coverage_check"] = payload
        elif event == "speaker_identity_stages":
            _active_report.setdefault("moss_execution", {})["speaker_stages"] = payload.get("stages", {})
        elif event == "moss_identity_mapping":
            _active_report.setdefault("moss_execution", {}).update(payload)
        if event == "stage_started":
            _active_report["stages"].append(
                {"index": payload.get("index"), "label": payload.get("label"), "resource": payload.get("resource"), "status": "running"}
            )
        elif event == 'stage_skipped':
            _active_report['stages'].append({
                'index': payload.get('index'), 'label': payload.get('label'),
                'resource': payload.get('resource'), 'status': 'skipped',
                'reason': payload.get('reason', 'not_applicable'), 'elapsed_seconds': 0.0,
            })
        elif event in {"stage_completed", "stage_failed", "stage_cancelled"}:
            for stage in reversed(_active_report["stages"]):
                if stage.get("label") == payload.get("label") and stage.get("status") == "running":
                    stage["status"] = {
                        "stage_completed": "completed",
                        "stage_failed": "failed",
                        "stage_cancelled": "cancelled",
                    }[event]
                    stage["elapsed_seconds"] = payload.get("elapsed_seconds")
                    if event in {"stage_failed", "stage_cancelled"}:
                        stage["error"] = payload.get("error", "")
                    break
        elif event == "cache_hit":
            _active_report["cache"]["hits"].append(payload.get("stage", "unknown"))
        elif event == "cache_write":
            _active_report["cache"]["writes"].append(payload.get("stage", "unknown"))
        elif event == "CACHE_ACCEPTED":
            _active_report["cache"].setdefault("accepted", []).append({"stage": payload.get("stage", "unknown"), "reason": payload.get("reason", "")})
        elif event == "CACHE_REJECTED":
            _active_report["cache"].setdefault("rejected", []).append({"stage": payload.get("stage", "unknown"), "reason": payload.get("reason", "")})
        elif event == 'polishing_summary':
            _active_report['polishing_summary']=dict(payload)
        elif event == 'domain_term_verification_summary':
            _active_report['terminology_summary']=dict(payload)


def _moss_window_lines(execution):
    """Readable window plan of a long MOSS task (2026-10-13)."""
    plan = execution.get("window_plan") or {}
    windows = execution.get("windows") or []
    if not plan:
        return []
    usable = (plan.get("usable_bytes") or 0) / 2**30
    if plan.get("mode") == "insufficient":
        return [f"- MOSS 分段：显存不足，可用约 {usable:.1f} GiB，最短窗口需要约 "
                f"{(plan.get('needed_bytes') or 0) / 2**30:.1f} GiB"]
    if len(windows) <= 1 and plan.get("mode") == "single_context":
        return [f"- MOSS 分段：一次完成（可用显存约 {usable:.1f} GiB，输入 {plan.get('prompt_tokens')} tokens）"]
    spans = "、".join(f"{row.get('start', 0) / 60:.1f}–{row.get('end', 0) / 60:.1f} 分"
                     f"（峰值 {row.get('peak_allocated_gb') or 0:.1f} GiB）" for row in windows)
    return [f"- MOSS 分段：计划 {plan.get('count')} 段，实际 {len(windows)} 段，可用显存约 {usable:.1f} GiB；{spans}"]


def _write_report(report):
    json_path, text_path = report_paths_for_media(report["media"]["path"], job_id=report.get("job_id"), media_index=report.get("media_index"))
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_previous_report(json_path, str(report.get("started_at") or ""))
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = report.get("result", {})
    elapsed_seconds = float(result.get("elapsed_seconds", 0) or 0)
    audio_seconds = float(result.get("audio_seconds", 0) or report.get("media", {}).get("audio_seconds") or 0)
    realtime_ratio = elapsed_seconds / audio_seconds if audio_seconds > 0 else 0.0
    outcome = normalize_recognition_outcome(report)
    performance = report.get("settings", {}).get("performance", {})
    lines = [
        "2ByteASR 字幕任务报告",
        f"状态：{report['status']}",
        f"处理结果：{outcome.status_label}",
        *outcome.detail_lines,
        f"素材：{report['media']['name']}",
        f"开始：{report['started_at']}",
        f"结束：{report.get('finished_at', '')}",
        f"耗时：{elapsed_seconds:.2f} 秒",
        f"素材时长：{audio_seconds:.2f} 秒",
        f"处理倍率：{realtime_ratio:.2f}x 实时",
        "",
        "模型：",
        f"- Qwen3-ASR：{report['settings']['models']['qwen_asr_model']}",
        f"- 字幕校对：{report['settings']['models']['polish_model']}",
        f"- 全文断句：{report['settings']['models']['group_model']}",
        "",
        "模型执行状态：",
        *[
            f"- {model_id}："
            f"{'COMPLETED' if state.get('completed') else 'FAILED' if state.get('failed') else 'SKIPPED' if state.get('skipped') else 'NOT_RUN'}"
            f"（segments={int(state.get('segment_count', 0) or 0)}"
            f"{', ' + str(state.get('failure_reason')) if state.get('failure_reason') else ''}）"
            for model_id, state in sorted((result.get('model_statuses') or {}).items())
            if isinstance(state, dict)
        ],
        "",
        "复核分类（模型融合后）：",
        *[
            f"- {category}：{int(count or 0)}"
            for category, count in sorted((result.get('review_classification') or {}).items())
        ],
        "",
        "加速配置：",
        f"- 云端批次：{'并行' if performance.get('parallel_cloud_batches') else '串行'}，"
        f"最多 {performance.get('cloud_batch_workers', 1)} 路",
        f"- MOSS/VAD：{'并行' if performance.get('parallel_cpu_vad') else '串行'}",
        "- MOSS：能放下时完整任务音频单上下文生成；超出本机容量时按静音切成几个大窗口依次生成",
        *_moss_window_lines(report.get("moss_execution", {})),
        "- MOSS 实际执行：" + json.dumps(report.get("moss_execution", {}), ensure_ascii=False),
        f"- Qwen3-ASR：每批最多 {performance.get('qwen_asr_batch_size', 4)} 个短块",
        f"- FireRed/Qwen3 GPU：{'允许并行' if performance.get('parallel_gpu_asr') else '串行'}，"
        f"显存门槛 {performance.get('parallel_gpu_asr_min_vram_gb', 0)} GB",
        "",
        f"真实三源融合 Cue：{len(result.get('real_three_source_cues') or [])}",
        "",
        f"缓存命中：{', '.join(report['cache']['hits']) or '无'}",
        f"缓存写入：{', '.join(report['cache']['writes']) or '无'}",
        "",
        "阶段：",
    ]
    for stage in report["stages"]:
        lines.append(f"- {stage.get('index')}. {stage.get('label')}：{stage.get('status')}（{stage.get('elapsed_seconds', 0)} 秒）")
    mapping_events = [
        event
        for event in report["events"]
        if event.get("event") == "host_voiceprint_mapping"
    ]
    if mapping_events:
        lines.extend(["", "声纹标签合并："])
        for source, info in mapping_events[-1].get("assignments", {}).items():
            lines.append(
                f"- {source} -> {info.get('label')} {info.get('name')} "
                f"（相似度 {info.get('score')}，余量 {info.get('margin')}）"
            )
    if outcome.result_usable and outcome.core_status in {"completed", "partial"}:
        correction_count = outcome.accepted_edits
        term_status = outcome.search_label
        if outcome.search_reason:
            term_status += "；" + outcome.search_reason
        if outcome.search_verified_records or outcome.search_unverified_records:
            term_status += f"；已核验 {outcome.search_verified_records} / 未核验 {outcome.search_unverified_records} 条处理记录"
        summary=report.get('polishing_summary',{})
        if summary:
            lines.extend(['','校对结果：',
                f"- 成功：{summary.get('success_batches',0)} 批 / {summary.get('success_cues',0)} 条处理记录",
                f"- ASR 原文回退：{summary.get('fallback_batches',0)} 批 / {summary.get('fallback_cues',0)} 条处理记录",
                '- 失败分类：'+json.dumps(summary.get('failure_categories',{}),ensure_ascii=False),
                *(['- 可重试失败文字校对；保留已成功校对子批次缓存。'] if outcome.polish_retryable else [])])
        lines.extend([
            "",
            *(["降级说明：AI 校对或断句部分回退到本地，请查看待复核项和 JSON 事件。", ""]
              if outcome.polish_status == "partial" or any(item.get("category") == "断句回退" for item in report.get("review_items", [])) else []),
            *(
                [item.get("message", "") for item in report.get("review_summary", [])]
                + ([""] if report.get("review_summary") else [])
            ),
            f"字幕条数：{result.get('cue_count', 0)}",
            f"已采纳云端校对：{correction_count} 处（具体内容见 JSON 报告）",
            f"联网术语：{term_status}",
            f"待复核项：{sum(report.get('review_severity_counts', {}).get(key, 0) for key in ('error', 'warning', 'review'))}",
            "诊断分级：" + "，".join(
                f"{key} {report.get('review_severity_counts', {}).get(key, 0)}"
                for key in ("error", "warning", "review", "info", "debug")
            ),
            *[f"{key.upper()}：{result.get('outputs', {}).get(key)}" for key in ("txt", "srt") if result.get("outputs", {}).get(key)],
            *([f"工程：{result['outputs']['project']}"] if result.get("outputs", {}).get("project") else []),
        ])
    else:
        lines.extend(["", f"错误：{result.get('error', '')}"])
    Path(text_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(json_path), text_path


def finish_media_report(status, **result):
    global _active_report
    if _active_report is None:
        return "", ""
    review_items = result.pop("review_items", [])
    _active_report["status"] = status
    _active_report["finished_at"] = _now()
    _active_report["result"] = result
    normalized_items = []
    severity_counts = {
        "error": 0, "warning": 0, "review": 0, "info": 0, "debug": 0
    }
    for source in review_items or []:
        item = dict(source)
        item["severity"] = _review_severity(item)
        severity_counts[item["severity"]] += 1
        normalized_items.append(item)
    _active_report["review_items"] = normalized_items
    _active_report["review_severity_counts"] = severity_counts
    _active_report["review_summary"] = _build_review_summary(normalized_items)
    report = _active_report
    report["stages"].sort(key=lambda stage: (int(stage.get("index") or 0), stage.get("label", "")))
    _active_report = None
    try:
        return _write_report(report)
    except OSError as exc:
        # A report must never turn a successfully generated subtitle into a failure,
        # but silently losing every record hides the problem entirely.
        try:
            print(f"   [警告] 任务报告未能写入 {REPORT_ROOT}：{exc}")
        except Exception:
            pass
        return "", ""


def active_media_report():
    return _active_report
