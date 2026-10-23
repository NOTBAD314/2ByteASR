"""What the AI analysis of a recognition task sends (2026-10-23).

A full task report can be several MB (a 24-minute task is about 3.4 MB;
pasted into a chat window it froze it, 2026-10-22). The digest keeps what
explains a result: status and errors, the models and switches used, every
step, failure / fallback events (a few of each kind), review categories with
a couple of examples, and the local findings. Secrets, query strings, e-mail
addresses and the user's home folder are removed (``diagnostics_report.scrub``)
from the whole text before it is shown or sent. Pure: no Qt, no IO.
"""
from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any

from .diagnosis_catalog import ACTION_LABELS, ISSUES, PIPELINE_OVERVIEW, STAGES

DIGEST_LIMIT = 24_000
_NOTABLE = re.compile(
    r"fail|error|fallback|reject|timeout|timed_out|degrad|missing|unavailable|retry|warn|rerout|"
    r"skip|cancel|exhaust|invalid|refus|denied|oom|overflow|truncat|abort|exit|not_configured|unsupported",
    re.IGNORECASE,
)
# Always kept (they say which path the run took).
_CONTEXT_EVENTS = {
    "task_language_resolved", "task_language", "task_audio_ready", "timeline_backend_rerouted",
    "polishing_summary", "domain_term_verification_summary", "moss_worker_failure",
    "asr_worker_exited", "incremental_chunk_overlap_split", "recognition_plan",
}
_DROP_KEYS = {"path", "config_file", "directory", "cache_dir", "stream_trace_path", "media_path",
              "identity", "fingerprint", "sha256", "task_audio_fingerprint"}


_WINDOWS_DIRS = re.compile(r"(?i)(?<![\w])(?:[a-z]:|\\\\[^\\/\s]+)[\\/](?:[^\\/\s\"'<>|*?]+[\\/])+")
_HOME_DIRS = re.compile(r"/(?:Users|home)/[^/\s]+/")


def strip_folders(text: str) -> str:
    """Keep file names, drop the folders (they name the user, drives, clients)."""
    return _HOME_DIRS.sub("/~/", _WINDOWS_DIRS.sub("…\\\\", str(text)))


def _clip_text(value: str, limit: int) -> str:
    value = strip_folders(value)
    return value if len(value) <= limit else value[:limit] + f"…（共 {len(value)} 字）"


def compact(value: Any, *, text: int = 400, items: int = 10, depth: int = 5) -> Any:
    """Bounded copy: long strings, long lists and deep nesting are cut."""
    if depth <= 0:
        return "…"
    if isinstance(value, dict):
        return {str(key): compact(item, text=text, items=items, depth=depth - 1)
                for key, item in value.items() if str(key) not in _DROP_KEYS}
    if isinstance(value, (list, tuple)):
        kept = [compact(item, text=text, items=items, depth=depth - 1) for item in list(value)[:items]]
        if len(value) > items:
            kept.append(f"…共 {len(value)} 项")
        return kept
    if isinstance(value, str):
        return _clip_text(value, text)
    return value


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def report_digest(report: dict, findings=(), *, item_error: str = "", per_event: int = 3,
                  examples: int = 2, environment: dict | None = None) -> dict:
    """The parts of a report that explain its result, bounded."""
    report = _dict(report)
    settings = _dict(report.get("settings"))
    events = _rows(report.get("events"))
    counts = Counter(str(row.get("event") or "") for row in events)
    notable: dict[str, list[dict]] = {}
    for row in events:
        name = str(row.get("event") or "")
        if not (_NOTABLE.search(name) or name in _CONTEXT_EVENTS or row.get("error")):
            continue
        bucket = notable.setdefault(name, [])
        if len(bucket) < per_event:
            bucket.append(compact({key: value for key, value in row.items() if key != "event"}, text=360, items=6, depth=4))
        elif len(bucket) == per_event and counts[name] > per_event:
            bucket.append(f"…同类共 {counts[name]} 条，只列前 {per_event} 条")
    review = _rows(report.get("review_items"))
    categories = Counter(str(row.get("category") or "") for row in review)
    review_examples: dict[str, list] = {}
    for row in review:
        key = str(row.get("category") or "")
        bucket = review_examples.setdefault(key, [])
        if len(bucket) < examples:
            bucket.append(compact({k: row.get(k) for k in ("severity", "message", "detail", "text", "start", "end", "cue_id")
                                   if row.get(k) not in (None, "")}, text=200, items=4, depth=3))
    media = _dict(report.get("media"))
    digest = {
        "status": report.get("status"),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "media": {key: media.get(key) for key in ("name", "size_bytes", "audio_seconds", "duration_seconds") if media.get(key) is not None},
        "result": compact(_dict(report.get("result")), text=1200, items=8, depth=4),
        "completion_page_error": _clip_text(item_error, 1200) if item_error else "",
        "settings": {
            "models": compact(_dict(settings.get("models")), text=160),
            "switches": compact(_dict(settings.get("switches")), text=160),
            "content_profile": compact(_dict(settings.get("content_profile")), text=200, items=6, depth=3),
            "config_warnings": compact(settings.get("config_warnings") or [], text=300, items=6),
            "subtitle_language": compact(settings.get("subtitle_language") or {}, text=120),
        },
        "stages": [compact(row, text=600, items=4, depth=3) for row in _rows(report.get("stages"))],
        "event_counts": dict(counts.most_common(60)),
        "notable_events": notable,
        "review_items": {"count": len(review), "by_category": dict(categories.most_common(20)),
                         "examples": review_examples},
        "polishing_summary": compact(_dict(report.get("polishing_summary")), text=300, items=6, depth=3),
        "terminology_summary": compact(_dict(report.get("terminology_summary")), text=300, items=6, depth=3),
        "moss_execution": compact(_dict(report.get("moss_execution")), text=300, items=6, depth=3),
        "cache": {key: compact(_dict(report.get("cache")).get(key) or [], text=120, items=12)
                  for key in ("hits", "rejected")},
        "local_findings": [
            {"id": finding.rule_id, "title": finding.issue.title, "confidence": finding.confidence,
             "severity": finding.severity, "evidence": [strip_folders(line) for line in finding.evidence]}
            for finding in findings
        ],
    }
    if environment:
        digest["this_computer_now"] = compact(environment, text=200, items=8, depth=3)
    return {key: value for key, value in digest.items() if value not in (None, "", {}, [])}


def digest_text(report: dict, findings=(), *, limit: int = DIGEST_LIMIT, **kwargs) -> str:
    """Redacted JSON of the digest, shrunk until it fits ``limit`` characters."""
    from ..diagnostics.diagnostics_report import scrub
    per_event, examples = 3, 2
    while True:
        digest = report_digest(report, findings, per_event=per_event, examples=examples, **kwargs)
        text = scrub(json.dumps(digest, ensure_ascii=False, indent=1, default=str))
        if len(text) <= limit:
            return text
        if per_event > 1:
            per_event -= 1
            continue
        if examples > 0:
            examples -= 1
            continue
        # Last resort: keep the head (status, errors, settings, stages come first).
        return text[:limit] + "\n…（报告摘要已截断）"


def knowledge_text(focus: set[str] | None = None) -> str:
    """The catalog, as the AI reads it.

    ``focus``: issue ids written out in full (the local findings and their
    pipeline stages); the others get one line (title and what the user saw),
    which keeps the request about half as long. None writes every entry in full.
    """
    lines = [PIPELINE_OVERVIEW.strip(), "", "已知问题清单（id · 阶段 · 标题）："]
    for issue in ISSUES.values():
        if focus is not None and issue.id not in focus:
            lines.append(f"[{issue.id}] {STAGES.get(issue.stage, issue.stage)} · {issue.title}：{issue.symptom}")
            continue
        lines.append(f"\n[{issue.id}] {STAGES.get(issue.stage, issue.stage)} · {issue.title}")
        lines.append(f"- 用户看到：{issue.symptom}")
        lines.append(f"- 原因：{issue.cause}")
        lines.append(f"- 处理：{issue.advice}")
        if issue.actions:
            lines.append("- 软件里的入口：" + "、".join(ACTION_LABELS[action] for action in issue.actions))
        if issue.fixed:
            lines.append(f"- 修正情况：{issue.fixed}")
    if focus is not None:
        lines.append("\n（只有一行的条目在本次报告里没有对应迹象；需要时按标题判断。）")
    return "\n".join(lines)


def focus_issues(findings) -> set[str]:
    """The local findings, plus what they hide (a specific entry stands for its generic one)."""
    ids = {finding.rule_id for finding in findings}
    return ids | {other for finding in findings for other in finding.issue.supersedes}


def token_estimate(*texts: str) -> int:
    """The provider layer's own bound (UTF-8 bytes / 3, provider_input_budget.measure)."""
    return sum(len(text.encode("utf-8")) for text in texts) // 3 + 300


# Whole request (system + user) bound; the provider allows 32,768 for this kind.
REQUEST_TOKEN_BUDGET = 24_000


def system_prompt(language_name: str, app_version: str = "", findings=None) -> str:
    version = f"用户现在的程序版本是 {app_version}。" if app_version else ""
    focus = None if findings is None else focus_issues(findings)
    return (
        "你是 2ByteASR（兔白字幕）的排错助手。用户的一次识别任务失败、部分完成或结果不理想，"
        "你要读任务报告摘要，结合下面的软件说明和已知问题清单，告诉用户原因和该怎么做。\n"
        f"{version}\n\n"
        f"{knowledge_text(focus)}\n\n"
        "回答要求：\n"
        f"1. 用{language_name}回答，写给不懂技术的普通用户；字段名、事件名可以原样引用作为依据。\n"
        "2. 结构：**结论**（一两句：最可能的原因）→ **依据**（报告里的哪几处，最多 4 条）→ **怎么做**（按顺序，"
        "写软件里真实存在的按钮或设置名）→ 如果像软件本身的缺陷、用户自己无法解决，说明「请用“回报问题”把这次的诊断包发给开发者」。\n"
        "3. 本地检查结果（local_findings）是程序按规则核对过的事实，优先采信；你可以补充或指出它们之间的关系，"
        "但不要与报告矛盾。报告里没有证据的事不要断定，用“可能”并说明还需要什么信息。\n"
        "4. 不要编造软件没有的功能、设置或版本号；不确定修好的版本时就说“更新到最新版”。不要索要 API Key 或文件。\n"
        "5. 简洁：通常 150–400 字；不要复述整份报告。"
    )


def user_prompt(digest: str, page_error: str = "") -> str:
    parts = ["下面是这次识别任务的报告摘要（JSON，已隐藏密钥与个人路径）："]
    parts.append("```json\n" + digest + "\n```")
    if page_error:
        from ..diagnostics.diagnostics_report import scrub
        parts.append("完成页显示的错误：" + scrub(_clip_text(page_error, 800)))
    parts.append("请分析原因并告诉我该怎么做。")
    return "\n\n".join(parts)


def build_request(diagnosis, *, language_name: str, app_version: str = "", item_error: str = "",
                  environment: dict | None = None, budget: int = REQUEST_TOKEN_BUDGET) -> tuple[list[dict], str]:
    """(messages, digest) for one analysis; the digest shrinks until the whole fits ``budget``."""
    facts = diagnosis.facts
    system = system_prompt(language_name, app_version, diagnosis.findings)
    page_error = "\n".join(facts.errors[:2])
    limit = DIGEST_LIMIT
    while True:
        digest = digest_text(facts.report, diagnosis.findings, item_error=item_error, environment=environment,
                             limit=limit)
        user = user_prompt(digest, page_error)
        if token_estimate(system, user) <= budget or limit <= 4000:
            return [{"role": "system", "content": system}, {"role": "user", "content": user}], digest
        limit = int(limit * 0.8)


def plain_report(diagnosis, *, language: str = "zh", task_name: str = "", ai_answer: str = "",
                 app_version: str = "") -> str:
    """Text the user can copy and send to the developer (redacted)."""
    from ..diagnostics.diagnostics_report import scrub
    from ..i18n import translate
    from .run_diagnosis import CONFIDENCE_LABELS, SEVERITY_LABELS, specific_text

    def t(source, **values):
        return translate(source, language).format(**values)

    facts = diagnosis.facts
    outcome = facts.outcome
    lines = [t("2ByteASR 识别排查报告")]
    if task_name:
        lines.append(t("任务：{name}", name=task_name))
    if app_version:
        lines.append(t("程序版本：{version}", version=app_version))
    if outcome is not None:
        lines.append(t("结果：{status}", status=translate(outcome.title, language)))
    models = facts.models
    lines.append(t("主力转写：{primary} · 字幕时间轴：{timeline} · 文字复核：{review}",
                   primary=models.get("primary_asr_backend", "?"), timeline=models.get("firered_asr_backend", "?"),
                   review=models.get("qwen_asr_backend", "?")))
    for error in facts.errors[:3]:
        lines.append(t("错误：{error}", error=_clip_text(error, 400)))
    lines.append("")
    if diagnosis.findings:
        lines.append(t("本地检查找到 {count} 个可能原因：", count=len(diagnosis.findings)))
        for index, finding in enumerate(diagnosis.findings, 1):
            lines.append(f"{index}. [{translate(SEVERITY_LABELS[finding.severity], language)} · "
                         f"{translate(CONFIDENCE_LABELS[finding.confidence], language)}] "
                         f"{translate(finding.issue.title, language)} ({finding.rule_id})")
            specific = specific_text(finding, language)
            if specific:
                lines.append("   " + specific)
            for line in finding.evidence[:4]:
                lines.append("   - " + strip_folders(line))
    else:
        lines.append(t("本地检查没有发现已知问题。"))
    if ai_answer.strip():
        lines += ["", t("AI 分析："), ai_answer.strip()]
    return scrub("\n".join(lines))


# The plain report's own lines (the localization test reads this).
REPORT_STRINGS = (
    "2ByteASR 识别排查报告", "任务：{name}", "程序版本：{version}", "结果：{status}",
    "主力转写：{primary} · 字幕时间轴：{timeline} · 文字复核：{review}", "错误：{error}",
    "本地检查找到 {count} 个可能原因：", "本地检查没有发现已知问题。", "AI 分析：",
)
