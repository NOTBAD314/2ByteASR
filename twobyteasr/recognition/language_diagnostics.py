"""Bounded transcript evidence; never an acoustic language ID or a rewrite.

Inspect one bounded paragraph per provider request, or at most twelve sampled
regions for older cached rows. Short quotes and foreign names are inconclusive.
There are no extra ASR/LLM requests, per-cue warnings or automatic retries.
"""
from __future__ import annotations

import hashlib
import math
import re

from ..subtitle_rules.language_rules import detect_language, normalize_language, TASK_LANGUAGES

MAX_TEXT = 6000
MAX_REGIONS = 12


def transcript_language_sample(texts):
    parts, size = [], 0
    for raw in texts:
        part = str(raw or "")[:MAX_TEXT - size]
        parts.append(part)
        size += len(part) + 1
        if size >= MAX_TEXT:
            break
    text = " ".join(parts)
    code, evidence = detect_language([text])
    letters = sum(evidence.get(k, 0) for k in ("latin", "han", "kana", "hangul", "cyrillic"))
    strong = letters >= 400
    scores = evidence.get("latin_scores") or {}
    if scores:
        ordered = sorted(scores.values(), reverse=True)
        strong = strong and len(re.findall(r"\w+", text)) >= 80 and scores.get(code, 0) >= 24
        strong = strong and scores.get(code, 0) >= 2 * max(1, ordered[1])
    else:
        dominant = {"zh": "han", "ja": "kana", "ko": "hangul", "ru": "cyrillic"}.get(code)
        strong = strong and bool(dominant) and evidence.get(dominant, 0) >= letters * .5
    return {"language": code if strong else None, "method": "bounded_transcript_heuristic",
            "characters": len(text), "scores": scores,
            "sample_sha256": hashlib.sha256(text.encode("utf8")).hexdigest()}


def primary_language_regions(rows):
    receipts = [dict(row["asr_language_receipt"]) for row in rows if row.get("asr_language_receipt")]
    if receipts:
        return receipts
    if not rows:
        return []
    # Old caches have no provider request receipt. Sample the task clock,
    # explicitly reporting sampled regions rather than invented request IDs.
    start = min(float(row["start"]) for row in rows)
    end = max(float(row["end"]) for row in rows)
    width = max(60., (end - start) / MAX_REGIONS)
    groups = {}
    for row in rows:
        index = min(MAX_REGIONS - 1, max(0, math.floor((float(row["start"]) - start) / width)))
        group = groups.setdefault(index, {"texts": [], "size": 0, "start": float(row["start"]),
                                         "end": float(row["end"])})
        if group["size"] < MAX_TEXT:
            text = str(row.get("text") or "")[:MAX_TEXT - group["size"]]
            group["texts"].append(text)
            group["size"] += len(text) + 1
            group["end"] = float(row["end"])
    return [{"source": "cached_primary_text_sample", "start": g["start"], "end": g["end"],
             "provider_detected_language": None, "transcript": transcript_language_sample(g["texts"])}
            for g in groups.values()]


def audit_primary_language(rows, context, legacy):
    """One task-level, actionable warning; explicit language remains unchanged."""
    if "primary_language_audit" in context.language_evidence:
        return context.language_evidence["primary_language_audit"]
    requested = normalize_language(context.requested_language)
    regions = primary_language_regions(rows)
    conflicts = [r for r in regions if requested in TASK_LANGUAGES
                 and (r.get("transcript") or {}).get("language") not in {None, "", requested}]
    audit = {"requested_language": requested, "adopted_language": context.task_language,
             "regions": regions, "conflicts": len(conflicts), "acoustic_language_verified": False}
    context.language_evidence["primary_language_audit"] = audit
    legacy.record_run_event("primary_language_audit", **audit)
    if conflicts:
        labels = {"en": "英语", "it": "意大利语", "zh": "中文", "ja": "日语", "ko": "韩语",
                  "es": "西班牙语", "de": "德语", "fr": "法语", "pt": "葡萄牙语", "ru": "俄语"}
        languages = "、".join(dict.fromkeys(labels.get(r["transcript"]["language"], r["transcript"]["language"])
                                           for r in conflicts))
        detail = (f"已选择{labels.get(requested, requested)}，但主力转写的 {len(conflicts)} 段长文本呈现{languages}特征。"
                  "这是文字抽样证据，不是音频语言检测。原始回答和所选语言保留，疑似范围在对齐前隔离。"
                  "请从完成页或工作台的恢复入口试听音轨、选择已有模型，只重新识别异常范围；仅重试校对或翻译不能恢复原文。")
        legacy.add_review_item(conflicts[0]["start"], "转写语言需要核对", detail, priority=2, severity="warning",
                               language_conflicts=conflicts, retry_action="inspect_audio_then_recognize_range")
    return audit
