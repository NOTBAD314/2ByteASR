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
AUDIT_VERSION = 3


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
        # Repeating a name or 'die' in game commentary cannot manufacture
        # strong German evidence merely by accumulating occurrences.
        from ..subtitle_rules.language_rules import _LATIN_MARKERS
        markers = set(_LATIN_MARKERS.get(code, ('', ''))[0].split())
        vocabulary = set(re.findall(r'[^\W\d_]+', text.casefold()))
        strong = strong and len(vocabulary & markers) >= 5
    else:
        dominant = {"zh": "han", "ja": "kana", "ko": "hangul", "ru": "cyrillic"}.get(code)
        strong = strong and bool(dominant) and evidence.get(dominant, 0) >= letters * .5
    return {"language": code if strong else None, "method": "bounded_transcript_heuristic",
            "characters": len(text), "scores": scores,
            "sample_sha256": hashlib.sha256(text.encode("utf8")).hexdigest()}


def primary_language_regions(rows):
    receipts = [dict(row["asr_language_receipt"]) for row in rows if row.get("asr_language_receipt")]
    if receipts:
        regions = []
        for receipt in receipts:
            # A receipt's bounded paragraph is request-level evidence, not a
            # language verdict on every second of a long request. Recompute
            # from source text only, within local time windows.
            groups = {}
            for row in rows:
                if float(row['end']) <= float(receipt['start']) or float(row['start']) >= float(receipt['end']):
                    continue
                index = max(0, int((float(row['start'])-float(receipt['start']))//60))
                groups.setdefault(index, []).append(row)
            for group in groups.values():
                regions.append({**receipt, 'request_start': receipt['start'], 'request_end': receipt['end'],
                    'start': min(float(r['start']) for r in group), 'end': max(float(r['end']) for r in group),
                    'source': 'bounded_source_text_window',
                    'transcript': transcript_language_sample(r.get('text') for r in group)})
        # In a conflicting request, a short unclassified tail is not positive
        # evidence for the selected language. Keep it reviewable, without
        # inventing a language or automatically changing any transcript.
        for receipt in receipts:
            group = [r for r in regions if r.get('request_start') == receipt['start'] and r.get('request_end') == receipt['end']]
            languages = {r['transcript'].get('language') for r in group} - {None, ''}
            for region in group:
                if languages and not region['transcript'].get('language'):
                    region['surrounding_text_languages'] = sorted(languages)
        return regions
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
    from .transcript_acceptance import digest
    signature = digest([AUDIT_VERSION, context.requested_language, rows])
    previous = context.language_evidence.get('primary_language_audit') or {}
    if previous.get('signature') == signature:
        return previous
    requested = normalize_language(context.requested_language)
    regions = primary_language_regions(rows)
    for region in regions:
        if not region['transcript'].get('language') and any(code != requested for code in region.get('surrounding_text_languages', [])):
            region['needs_manual_review'] = requested in TASK_LANGUAGES
    conflicts = [r for r in regions if requested in TASK_LANGUAGES and (
        (r.get("transcript") or {}).get("language") not in {None, "", requested} or r.get('needs_manual_review'))]
    audit = {"version": AUDIT_VERSION, "signature": signature, "requested_language": requested, "adopted_language": context.task_language, "mode": context.language_mode,
             "regions": regions, "conflicts": len(conflicts), "acoustic_language_verified": False}
    context.language_evidence["primary_language_audit"] = audit
    legacy.record_run_event("primary_language_audit", **audit)
    if conflicts:
        labels = {"en": "英语", "it": "意大利语", "zh": "中文", "ja": "日语", "ko": "韩语",
                  "es": "西班牙语", "de": "德语", "fr": "法语", "pt": "葡萄牙语", "ru": "俄语"}
        languages = "、".join(dict.fromkeys(labels.get(r['transcript'].get('language'), r['transcript'].get('language') or '证据不足')
                                           for r in conflicts))
        detail = (f"已选择{labels.get(requested, requested)}，但主力转写的 {len(conflicts)} 段长文本呈现{languages}特征。"
                  f"已按你选择的{labels.get(requested, requested)}处理，候选不会仅因此被隔离。"
                  "这是文字观察，不是音频语言验证。可查看候选并试听核对，或主动重新识别对应范围；源语言只有你主动修改才会变化。")
        legacy.add_review_item(conflicts[0]["start"], "转写语言需要核对", detail, priority=2, severity="warning",
                               language_conflicts=conflicts, retry_action="inspect_audio_then_recognize_range")
    return audit


def merge_language_notices(items):
    first=None;result=[]
    for item in items:
        if not isinstance(item,dict) or item.get('category')!='转写语言需要核对':
            result.append(item);continue
        if first is None:
            first=dict(item);first['language_conflicts']=list(item.get('language_conflicts') or []);result.append(first)
        else:
            existing={(r.get('start'),r.get('end'),r.get('remote_task_id')) for r in first['language_conflicts']}
            first['language_conflicts'].extend(r for r in item.get('language_conflicts',[]) if (r.get('start'),r.get('end'),r.get('remote_task_id')) not in existing)
    return result
