"""Proofread existing text in its own language; source text is reference only."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from types import SimpleNamespace

from .terminology import GlossarySnapshot, TermResolver
from .studio_glossary_review import diff_occurrences
from ..studio.subtitle_text_targets import bind_occurrence


def _script(text):
    if re.search(r"[ぁ-ヿ]", text):
        return "ja"
    if re.search(r"[가-힣]", text):
        return "ko"
    if re.search(r"[一-鿿]", text):
        return "zh"
    if re.search(r"[А-яЁё]", text):
        return "ru"
    return "latin"


def language_snapshot(snapshot, language):
    """The current term schema has no language field: never infer a translation.

    Han-only names are ambiguous in Japanese, so they remain AI reference.
    Confirmed same-script aliases and Latin identifiers may normalize locally.
    """
    base = language.split("-")[0]
    permitted = {"zh", "latin"} if base == "zh" else {base, "latin"} if base in {"ja", "ko", "ru"} else {"latin"}
    libraries = []
    for library in snapshot.libraries:
        terms = []
        for term in library.terms:
            script = _script(term.canonical)
            if script not in permitted:
                continue
            aliases = tuple(alias for alias in term.aliases if (_script(alias) in permitted if base == 'zh' else _script(alias) == script))
            canonical = term.canonical
            if base == "zh":
                from ..subtitle_rules.chinese_script import convert_text
                canonical = convert_text(canonical, language)
                aliases = tuple(convert_text(alias, language) for alias in aliases)
            terms.append(replace(term, canonical=canonical, aliases=aliases))
        libraries.append(replace(library, terms=tuple(terms), reference_terms=()))
    return GlossarySnapshot(tuple(libraries))


SYSTEM = """你是字幕词库校对员。只校对输入中已有的 target_text，按每条的 target_language 纠错、统一术语和角色译名。
source_reference 仅用于理解句意，不是写入目标；不能修改原文、ID、时间、语言、轨道或字幕关联。没有原文关联时只按已有文本判断。
保留原句意思、信息、语气和目标语言；不要重译、扩写、删句或补译空白。中文规范词不能直接替换英语、意大利语或日语等目标文本。
same_language_terms 是可用规范词/别名；cross_language_pairs 只在有可靠方向对应时提供。reference_terms 只作参考，缺少可靠译名时给出需人工判断的建议并说明不确定。
所有建议由用户确认。只返回 JSON：{"changes":[{"target_id":"输入ID","original":"完整target_text快照","replacement":"建议全文","reason":"修改原因及不确定性"}]}。
没有需要修改的文本返回空 changes。original 必须逐字等于输入；replacement 不得为空。"""


def preview_language_correction(project, entries, snapshot, settings, *, token, use_ai=True, progress=None):
    from .studio_glossary_service import GlossaryReviewPreview
    from ..studio.studio_text_tools import cue_locked
    from ..providers.ai_providers import provider_for_stage
    token.raise_if_cancelled()
    locked = set(project.studio_state.get("locked_cue_ids", ()))
    cues = {cue.id: cue for cue in project.cues}
    entries = [entry for entry in entries if entry.text.strip() and entry.target.cue_id not in locked
               and not bool(getattr(cues.get(entry.key), "locked", False))]
    receipt = {"kind": "current_glossary_text_review", "project_id": project.project_id,
        "snapshot": snapshot.to_dict(), "snapshot_summary": snapshot.summary(), "mode": "existing_text_language_review",
        "checked_cues": len(entries), "requested_cues": len(entries), "successful_cues": 0, "fallback_cues": 0,
        "asr_run": False, "audio_verified": False, "web_search_run": False, "segments": [], "pending_rows": [],
        "failed_cues": [], "request_errors": [], "ai_requested": bool(use_ai), "missing_associations": 0,
        "rejected_changes": 0, "automatic_changes": 0, "confirmation_changes": 0, "terminology_conflicts": []}
    filtered = {language: language_snapshot(snapshot, language) for language in {e.target.language for e in entries}}
    from .translation_terms import policy_of, relevant, violations, freeze, PROMPT as TERM_PROMPT
    from ..subtitle_rules.subtitle_translation import _translation_language
    policy = freeze(policy_of(project))
    source_language = _translation_language(project)
    terms_by_key = {entry.key: relevant(policy, entry.source_language or source_language, entry.target.language, entry.source_text)
                    if entry.target.layer == 'translation' and entry.source_cue_id else [] for entry in entries}
    drafts, hits = {}, []
    for entry in entries:
        # Pre-existing projects retain their same-language proofreading.
        # This never supplies translation-generation pairs; an explicit new
        # translation configuration (including disabled) ends that fallback.
        legacy_review = 'translation_terminology' not in project.generation_metadata
        resolver = TermResolver(filtered[entry.target.language] if entry.target.layer == 'original' or legacy_review else GlossarySnapshot())
        resolution = resolver.resolve(entry.text)
        drafts[entry.key] = resolution.text
        cue = SimpleNamespace(id=entry.key, text=entry.text, start_ms=entry.start_ms)
        from .proofread_rules import normalize_occurrence
        for hit in diff_occurrences(cue, resolution.text, reason="目标语言词库的已确认别名", source="local_confirmed"):
            hit = normalize_occurrence(hit, entry.text, resolver)
            if hit is not None:
                hits.append(bind_occurrence(hit, entry))
        receipt["segments"].append({"cue_id": entry.key, "target": entry.target.to_dict(),
            "original_baseline": entry.text, "source_reference": entry.source_text, "input_text": entry.text,
            "local_draft": resolution.text, "translation_terminology": terms_by_key[entry.key],
            "terminology_warnings": violations(entry.source_text, entry.text, terms_by_key[entry.key])})
    batches = []
    batch, size = [], 0
    for entry in entries:
        cost = len(entry.text) + len(entry.source_text) + 200
        if batch and (len(batch) >= 24 or size + cost > 8000):
            batches.append(batch)
            batch, size = [], 0
        batch.append(entry)
        size += cost
    if batch:
        batches.append(batch)
    provider = None
    if use_ai and entries:
        try:
            provider = provider_for_stage(settings, "polish")
        except Exception as exc:
            receipt["request_errors"].append(str(exc))
            receipt["fallback_cues"] = len(entries)
    schema = {"type": "object", "properties": {"changes": {"type": "array", "items": {
        "type": "object", "properties": {key: {"type": "string"} for key in ("target_id", "original", "replacement", "reason")},
        "required": ["target_id", "original", "replacement", "reason"]}}}, "required": ["changes"]}
    for number, batch in enumerate(batches if provider else [], 1):
        token.raise_if_cancelled()
        if callable(progress):
            progress(number - 1, len(batches))
        from ..subtitle_rules.subtitle_translation import normalize_glossary, container_target
        pairs = normalize_glossary(project.generation_metadata.get("translation_glossary", ()))
        languages = {entry.target.language for entry in batch}
        payload = {"targets": [{"target_id": entry.key, **entry.target.to_dict(), "target_language": entry.target.language or 'und',
                    "target_text": entry.text, "source_reference": entry.source_text,
                    "source_language": entry.source_language if entry.target.layer == 'translation' else entry.target.language,
                    "translation_terminology": terms_by_key[entry.key]} for entry in batch],
            "same_language_terms": {language: filtered[language].evidence() for language in languages
                                    if any(e.target.layer == 'original' and e.target.language == language for e in batch)},
            "cross_language_pairs": [{"source": source, "target": target, "target_language": container_target(project)}
                                     for source, target in pairs] if container_target(project) in languages else [],
            "reference_terms": list(snapshot.canonical_terms)[:400] if any(e.target.layer == 'original' for e in batch) else []}
        try:
            raw = provider.complete([{"role": "system", "content": SYSTEM + '\n' + TERM_PROMPT},
                                     {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                max_tokens=5000, temperature=.1, timeout=(10, 90), enable_thinking=False,
                response_format={"type": "json_object"}, stage="studio_translation_proofread",
                structured_retry_system_prompt=SYSTEM, json_schema=schema, cancel_check=token.raise_if_cancelled)
            token.raise_if_cancelled()
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            changes = parsed.get("changes") if isinstance(parsed, dict) else None
            if not isinstance(changes, list):
                raise ValueError("AI 没有返回有效 changes 列表")
            lookup = {entry.key: entry for entry in batch}
            seen = set()
            rejected = set()
            for change in changes:
                if not isinstance(change, dict):
                    receipt["rejected_changes"] += 1
                    continue
                entry = lookup.get(change.get("target_id"))
                if entry is None:
                    receipt["rejected_changes"] += 1
                    continue
                new = change.get("replacement")
                valid = (entry.key not in seen and change.get("original") == entry.text and isinstance(new, str)
                         and bool(new.strip()) and len(new) <= max(80, len(entry.text) * 2))
                if valid and ((entry.target.language and entry.target.language.split("-")[0] not in {"zh", "ja", "ko"})
                              or not entry.target.language and _script(entry.text) == 'latin'):
                    # A Chinese-only glossary must never turn a Latin caption
                    # into Chinese. Existing foreign names may stay unchanged.
                    valid = not (set(re.findall(r"[一-鿿ぁ-ヿ가-힣]", new)) - set(entry.text))
                from ..subtitle_rules.math_text import mask_formulas
                if valid:
                    valid = mask_formulas(new)[1] == mask_formulas(entry.text)[1]
                if valid and terms_by_key[entry.key]:
                    conflicts = violations(entry.source_text, new, terms_by_key[entry.key])
                    if conflicts:
                        receipt['terminology_conflicts'].append(dict(target_id=entry.key, start_ms=entry.start_ms,
                            speaker_id=entry.speaker_id, source_reference=entry.source_text, current=entry.text,
                            candidate=new, required=conflicts))
                    valid = not conflicts
                if not valid:
                    rejected.add(entry.key)
                    receipt["rejected_changes"] += 1
                    continue
                seen.add(entry.key)
                if new == entry.text:
                    continue
                cue = SimpleNamespace(id=entry.key, text=entry.text, start_ms=entry.start_ms)
                term_reason = '; '.join(f"{row['source']} → {row['target']}" for row in terms_by_key[entry.key])
                for hit in diff_occurrences(cue, new, reason=str(change.get("reason") or "AI 目标语言校对；请确认") + (' · ' + term_reason if term_reason else ''),
                                           source="translation_ai", selected=False, missing="请核对句意与译名对应"):
                    hits.append(bind_occurrence(hit, entry))
            receipt["successful_cues"] += len(batch) - len(rejected)
            hits = [hit for hit in hits if hit.source != 'translation_ai' or hit.target_key not in rejected]
            receipt["fallback_cues"] += len(rejected)
            receipt["failed_cues"].extend({"cue_id": key, "reason": "invalid_or_stale_response"} for key in rejected)
        except Exception as exc:
            token.raise_if_cancelled()
            receipt["fallback_cues"] += len(batch)
            receipt["request_errors"].append(str(exc))
            receipt["failed_cues"].extend({"cue_id": entry.key, "reason": str(exc)} for entry in batch)
    token.raise_if_cancelled()
    if callable(progress):
        progress(len(batches), len(batches))
    unique = {}
    for hit in hits:
        unique.setdefault((hit.target_key, hit.span, hit.replacement), hit)
    hits = list(unique.values())
    # A model and a deterministic alias may offer the same edit. Keep the
    # confirmed alias, while competing alternatives require explicit choice.
    receipt["proposed_changes"] = len(hits)
    receipt["proposed_cues"] = len({hit.target_key for hit in hits})
    receipt["automatic_changes"] = sum(hit.default_selected for hit in hits)
    receipt["confirmation_changes"] = sum(not hit.default_selected for hit in hits)
    for row in receipt['segments']:
        row['final_diff'] = [{'span': list(hit.span), 'from': hit.original, 'to': hit.replacement,
                             'target': hit.target.to_dict(), 'source': hit.source, 'default_selected': hit.default_selected}
                            for hit in hits if hit.target_key == row['cue_id']]
    receipt["empty_state"] = "request_failed" if receipt["request_errors"] else "needs_confirmation" if hits or receipt['terminology_conflicts'] else "no_changes"
    return GlossaryReviewPreview(tuple(hits), receipt)
