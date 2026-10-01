"""Per-media task reports.  Reports intentionally contain no API keys or raw audio."""

import json
import os
import re
import time
import threading
from collections import Counter
from pathlib import Path


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


def report_paths_for_media(media_path):
    path = Path(media_path)
    base_name = path.stem
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
    _active_report = {
        "schema_version": 1,
        "status": "running",
        "started_at": _now(),
        "media": {
            "name": path.name,
            "path": str(path),
            "size_bytes": int(stat.st_size),
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
        row = {"time": _now(), "event": str(event), **payload}
        _active_report["events"].append(row)
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


def _write_report(report):
    json_path, text_path = report_paths_for_media(report["media"]["path"])
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_previous_report(json_path, str(report.get("started_at") or ""))
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = report.get("result", {})
    elapsed_seconds = float(result.get("elapsed_seconds", 0) or 0)
    audio_seconds = float(result.get("audio_seconds", 0) or 0)
    realtime_ratio = elapsed_seconds / audio_seconds if audio_seconds > 0 else 0.0
    performance = report.get("settings", {}).get("performance", {})
    lines = [
        "2ByteASR 字幕任务报告",
        f"状态：{report['status']}",
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
        f"- MOSS 长音频分块：最多 {performance.get('moss_parallel_workers', 1)} 路，"
        f"显存门槛 {performance.get('moss_parallel_min_vram_gb', 0)} GB",
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
    if report["status"] in {"success", "degraded_success"}:
        correction_count = sum(
            len(event.get("edits", []))
            for event in report["events"]
            if event.get("event") == "cloud_correction_applied"
        )
        term_started = [
            event for event in report["events"]
            if event.get("event") == "domain_term_search_started"
        ]
        term_completed = [
            event for event in report["events"]
            if event.get("event") == "domain_term_search_completed"
        ]
        term_failed = [
            event for event in report["events"]
            if event.get("event") == "domain_term_search_failed"
        ]
        term_applied = sum(
            int(event.get("count", 0) or 0)
            for event in report["events"]
            if event.get("event") in {
                "domain_term_mapping_applied",
                "profile_term_mapping_applied",
            }
        )
        verification=report.get('terminology_summary',{})
        if verification:
            status=verification.get('status')
            term_status={'success':'核验成功','partial':'核验部分成功，仍有候选未核验',
                         'failed':'核验未执行或失败，本次不更新术语','not_run':'核验未执行'}.get(status,'核验状态未知')
            term_status+=f"；已核验 {verification.get('verified_count',0)} / {verification.get('candidate_count',0)} 条证据"
        elif term_completed:
            term_status = (
                f"已检索 {term_started[-1].get('candidate_count', 0)} 条候选，"
                f"采纳 {term_completed[-1].get('accepted_count', 0)} 组，"
                f"实际应用 {term_applied} 处"
            )
        elif term_failed:
            term_status = "联网检索失败，未自动修改专名（详情见 JSON 报告）"
        elif (
            report.get("settings", {}).get("content_profile", {}).get("domain_terms")
            and "polished" in report.get("cache", {}).get("hits", [])
        ):
            term_status = "命中校对缓存，沿用上次已核验术语结果"
        else:
            term_status = "未执行或没有可检索正文"
        summary=report.get('polishing_summary',{})
        if summary:
            lines.extend(['','校对结果：',
                f"- 成功：{summary.get('success_batches',0)} 批 / {summary.get('success_cues',0)} 条字幕",
                f"- ASR 原文回退：{summary.get('fallback_batches',0)} 批 / {summary.get('fallback_cues',0)} 条字幕",
                '- 失败分类：'+json.dumps(summary.get('failure_categories',{}),ensure_ascii=False),
                '- 可在识别记录中重试失败项；保留已成功校对子批次缓存。'])
        lines.extend([
            "",
            *(["降级说明：AI 校对或断句部分回退到本地，请查看待复核项和 JSON 事件。", ""]
              if report["status"] == "degraded_success" else []),
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
            f"TXT：{result.get('outputs', {}).get('txt', '')}",
            f"SRT：{result.get('outputs', {}).get('srt', '')}",
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
