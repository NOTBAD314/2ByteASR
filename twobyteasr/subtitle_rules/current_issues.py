"""Current, versioned issues shared by the list, review queue and text editor.

Raw QC remains available for diagnosis. A missing human review or acoustic
receipt is not itself an error. Identities use persistent caption/track/layer
keys, and versions include only the inputs the particular rule consumes.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from types import SimpleNamespace, MappingProxyType

from .studio_qc import QCConfig, QCResult, QCSeverity, ReadabilityRule
from .review_suggestions import model_suggestions, ReviewSuggestion, SuggestionOption, GLOSSARY, MAX_MARKS
from .review_evidence_policy import evidence_only_reason

DECISIONS = "current_issue_decisions"
LEGACY_INPUTS = 'current_issue_legacy_inputs'
_EMPTY_DECISIONS = MappingProxyType({})
_EMPTY_QC = QCResult({})


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def suggestion_identity(target, row):
    return "suggestion:" + digest([target, row.kind, row.start, row.end,
                                    row.original, [o.text for o in row.options]])


def patch_identity(target, start, end, expected, kind='model'):
    return 'patch:'+digest([target,kind,start,end,expected])


def suggestion_handled(target, row, text, decisions):
    # Pronoun underlines are an always-available editing utility, not a todo.
    if row.kind == 'pronoun':
        return False
    version=digest(text)
    exact=decisions.get(suggestion_identity(target,row),{})
    if exact.get('input_version')==version and exact.get('status') in {'ignored','resolved'}:
        return True
    patch=decisions.get(patch_identity(target,row.start,row.end,row.original,row.kind),{})
    return (patch.get('input_version')==version and patch.get('status') in {'ignored','resolved'}
            and all(option.text in patch.get('options',()) for option in row.options))


def legacy_review_inputs(project):
    snapshot=getattr(project,'_legacy_review_inputs',None)
    if snapshot is None:
        manual=project.studio_state.get('manual_caption_text',{})
        saved=project.studio_state.get(LEGACY_INPUTS)
        if isinstance(saved,dict):
            snapshot={key:tuple(value) for key,value in saved.items() if isinstance(value,(list,tuple)) and len(value)==2}
        else:
            snapshot={key:(value,manual.get(key)) for key,value in
                      project.studio_state.get('review_confirmations',{}).items() if value and key in manual}
        project._legacy_review_inputs=snapshot
    return snapshot


def reviewed_version(project, cue):
    from .subtitle_translation import container_target
    return digest([cue.text, cue.start_ms, cue.end_ms, cue.speaker_id,
                   container_target(project), project.generation_metadata.get('translations', {}).get(cue.id, '')])


@dataclass(frozen=True)
class CurrentIssue:
    issue_id: str
    input_version: str
    cue_id: str
    track_id: str
    layer: str
    language: str
    kind: str
    level: str
    label: str
    detail: str
    text: str
    start_ms: int
    end_ms: int
    suggestions: tuple = ()
    disposition: str = "actionable"

    @property
    def action(self):
        return "替换 / 手动编辑" if self.suggestions else (
            "补充译文 / 重试" if self.kind == "missing_translation" else "定位试听 / 手动调整")


@dataclass
class CurrentIssueView:
    by_cue: dict
    diagnostics: dict
    records: tuple
    levels: dict

    def for_cue(self, cue_id, *, layer=None):
        rows = self.by_cue.get(str(cue_id), ())
        return tuple(r for r in rows if layer is None or r.layer == layer)

    def level(self, cue_id):
        return self.levels.get(str(cue_id), "confident")

    def counts(self):
        counts = Counter(self.levels.values())
        return {"priority": counts["suggested"], "critical": counts["high"]}

    def statistics(self):
        groups = defaultdict(list)
        for row in self.records:
            groups[row.kind].append(row)
        return {kind: {"raw": len(rows), "unique_cues": len({r.cue_id for r in rows}),
                       **dict(Counter(r.disposition for r in rows))}
                for kind, rows in groups.items()}


def invalidate(project):
    project._current_issue_view = None


def _language(project, cue, layer):
    from ..projects.subtitle_import import imported_track
    from .language_rules import project_language
    from .subtitle_translation import container_target
    return (container_target(project) if layer == "translation" else
            imported_track(project, cue.speaker_id).get("language") or project_language(project))


def _classify(issue, cue, text, language, cues):
    """Calibrate tasks, retaining the original event and a concrete explanation."""
    kind = issue.issue_type
    if evidence_only_reason(kind):
        return 'confident', 'diagnostic'
    if kind in {'model_disagreement','suspected_word','current_projection_difference'}:
        from .studio_qc import normalize_spoken_text
        readings=[r.text for r in issue.evidence if r.label!='Current' and r.text and not r.context_only]
        if readings and all(normalize_spoken_text(r)==normalize_spoken_text(text) for r in readings):
            return 'confident','stale'
    if kind=='terminology_mismatch' and issue.fix_metadata.get('surface'):
        from .studio_qc import _visible_text
        if issue.fix_metadata['surface'] not in _visible_text(text):return 'confident','stale'
    if issue.severity == QCSeverity.INFO:
        return "confident", "diagnostic"
    if kind == "high_cps" and issue.severity != QCSeverity.CRITICAL:
        return "confident", "optional"
    if kind == 'long_duration':
        if cue.end_ms-cue.start_ms > QCConfig().max_duration_ms*2:
            return 'high', 'actionable'
        return 'confident', 'optional'
    if kind == "low_confidence":
        return "confident", "optional"
    if kind in {"abnormal_punctuation", "duplicate_punctuation"}:
        # A spoken pause written as an ellipsis is valid, including Italian.
        remainder = re.sub(r"\.{2,}|…+", "…", text)
        if not re.search(r"([，,。.!！?？、;；:：])\1+|^[，,、;；:：]", remainder):
            return "confident", "diagnostic"
    if kind == "overlap":
        previous = cues.get(str(issue.fix_metadata.get("previous_cue_id", "")))
        if previous is not None and previous.speaker_id != cue.speaker_id:
            return "confident", "diagnostic"
    return ("high" if issue.severity == QCSeverity.CRITICAL else "suggested"), "actionable"


def current_issue_view(project):
    if project is None:
        return CurrentIssueView({}, {}, (), {})
    qc = getattr(project, "_qc_result", None) or _EMPTY_QC
    # Missing metadata is the ordinary state of an existing project. Its
    # identity must be stable too: a new {} per lookup defeated every cache
    # hit and rebuilt all issues for every painted list cell.
    decisions = project.studio_state.get(DECISIONS) or _EMPTY_DECISIONS
    # Exporters clone the project including runtime caches. Keep the global
    # read-only empty sentinel out of that graph (mappingproxy cannot copy).
    cache_decisions = None if decisions is _EMPTY_DECISIONS else decisions
    cache = getattr(project, "_current_issue_view", None)
    if cache is not None and cache[0] is qc and cache[1] is cache_decisions:
        return cache[2]
    cues = {str(c.id): c for c in project.cues}
    legacy=legacy_review_inputs(project)
    active, diagnostics, records = defaultdict(list), defaultdict(list), []
    seen = set()
    row_cache = getattr(project, '_current_issue_row_cache', {})
    next_rows_cache = {}

    def add(issue, cue, layer="original", language=None, text=None):
        text = cue.text if text is None else text
        language = language or _language(project, cue, layer)
        from ..projects.subtitle_import import imported_track
        role = 'translation' if layer == 'translation' else imported_track(project, cue.speaker_id).get('role', 'original')
        previous = cues.get(str(issue.fix_metadata.get('previous_cue_id', '')))
        previous_input = (previous.text, previous.start_ms, previous.end_ms, previous.speaker_id) if previous else None
        stamp = (text, cue.start_ms, cue.end_ms, cue.speaker_id, language, role, previous_input,
                 project.studio_state.get('review_confirmations', {}).get(cue.id),
                 project.studio_state.get('manual_caption_text', {}).get(cue.id),legacy.get(cue.id))
        location=(issue.fix_metadata.get('surface'),issue.fix_metadata.get('canonical')) if issue.category.value=='terminology' else ()
        cache_key = (cue.id, layer, issue.issue_type, issue.source,location)
        saved = row_cache.get(cache_key)
        if (saved is not None and saved[0] is issue and saved[1] == stamp
                and saved[2] == tuple(decisions.get(k) for k in saved[3])):
            row = saved[4]
            next_rows_cache[cache_key] = saved
            seen.add((row.issue_id, row.input_version))
            records.append(row)
            (active if row.disposition == 'actionable' else diagnostics)[cue.id].append(row)
            return
        key = digest([project.project_id, cue.id, cue.speaker_id, layer, language, issue.issue_type, issue.source,location])
        dependencies = [text]
        if issue.issue_type == 'missing_translation':
            dependencies.append(cue.text)
        if issue.category.value in {"timeline", "readability"} or issue.issue_type == "current_projection_difference":
            dependencies.extend([cue.start_ms, cue.end_ms])
        if issue.category.value == "speaker":
            dependencies.append(cue.speaker_id)
        if issue.fix_metadata.get("previous_cue_id") in cues:
            other = cues[issue.fix_metadata["previous_cue_id"]]
            dependencies.extend([other.id, other.text, other.start_ms, other.end_ms, other.speaker_id])
        version = digest(dependencies)
        level, disposition = _classify(issue, cue, text, language, cues)
        if (key, version) in seen:
            disposition = "duplicate"
        seen.add((key, version))
        decision = decisions.get(key, {})
        if decision.get("input_version") == version and decision.get("status") in {"ignored", "resolved"}:
            level, disposition = "confident", "handled"
        # Legacy human confirmations are accepted only for the exact text they
        # confirmed; mere pending/done labels are not issue decisions.
        elif (layer == "original" and issue.category.value in {'asr','text','terminology'}
              and legacy.get(cue.id)==(project.studio_state.get('review_confirmations',{}).get(cue.id),text)):
            level, disposition = "confident", "handled"
        candidates = [(e.text, (e.label,)) for e in issue.evidence
                      if e.text and not e.context_only and e.label not in {"Current","词库"} and e.text != text]
        # Incomplete time coverage does not justify deleting an unsupported
        # suffix. It offers listening / boundary adjustment, not a text patch.
        suggestions = tuple(model_suggestions(text, candidates)) if issue.category.value in {"asr", "terminology"} and issue.issue_type != 'current_projection_difference' else ()
        surface=issue.fix_metadata.get('surface');canonical=issue.fix_metadata.get('canonical')
        if issue.issue_type=='terminology_mismatch' and surface and canonical:
            suggestions=tuple(ReviewSuggestion(m.start(),m.end(),m.group(),(SuggestionOption(str(canonical)),),GLOSSARY)
                for m in list(re.finditer(re.escape(str(surface)),text))[:MAX_MARKS])
        target = dict(project_id=project.project_id, cue_id=cue.id, track_id=cue.speaker_id,
                      layer=layer, language=language, role=role)
        decision_keys = (key,) + tuple(k for r in suggestions for k in
            (suggestion_identity(target,r),patch_identity(target,r.start,r.end,r.original,r.kind)))
        visible_suggestions = tuple(r for r in suggestions if not suggestion_handled(target,r,text,decisions))
        if suggestions and not visible_suggestions and (candidates or surface):
            # Only resolve the complete candidate issue if the offered local
            # edits actually describe it in full. Unrepresented differences
            # remain a manual review task.
            from .studio_qc import normalize_spoken_text
            complete = not surface or len(suggestions)==text.count(surface)
            for candidate in candidates:
                reconstructed = text
                local = model_suggestions(text, [candidate])
                for mark in sorted(local, key=lambda r: r.start, reverse=True):
                    reconstructed = mark.apply(reconstructed)
                if normalize_spoken_text(reconstructed) != normalize_spoken_text(candidate[0]):
                    complete = False
                    break
            if complete:
                level, disposition = 'confident', 'handled'
        suggestions = visible_suggestions
        detail = issue.description
        if suggestions:
            detail += ' '+ '；'.join(f'位置 {r.start}–{r.end}「{r.original or "∅"}」→「{" / ".join(o.text or "∅" for o in r.options)}」' for r in suggestions)
        if issue.issue_type == "current_projection_difference":
            covered = " / ".join(e.text for e in issue.evidence if e.text)
            detail = f"{cue.start_ms/1000:.3f}–{cue.end_ms/1000:.3f}s：当前「{text}」；该区间证据「{covered}」。试听核对末尾及边界。"
        elif issue.category.value in {"readability", "timeline"}:
            detail = f"{cue.start_ms/1000:.3f}–{cue.end_ms/1000:.3f}s：{detail}"
            if issue.issue_type == 'overlap' and disposition == 'diagnostic':
                detail += ' 两条属于不同说话人/轨道；允许同时显示，此重叠本身不构成错误。'
        elif issue.issue_type in {"model_disagreement", "suspected_word", "terminology_mismatch"}:
            detail += " 当前：" + text + "；候选：" + " / ".join(e[0] for e in candidates)
        row = CurrentIssue(key, version, cue.id, cue.speaker_id, layer, language, issue.issue_type,
                           level, issue.label, detail, text, cue.start_ms, cue.end_ms, suggestions, disposition)
        records.append(row)
        next_rows_cache[cache_key] = (issue, stamp, tuple(decisions.get(k) for k in decision_keys), decision_keys, row)
        (active if disposition == "actionable" else diagnostics)[cue.id].append(row)

    for cue_id, rows in qc.issues_by_cue.items():
        cue = cues.get(str(cue_id))
        if cue is not None:
            for issue in rows:
                add(issue, cue)

    # Keep the operation's original boundary receipt visible as a diagnosis.
    # A missing word map alone is not independent evidence of an error.
    from .studio_qc import QCCategory, QCIssue
    receipts = project.studio_state.get('caption_timeline', {}).get('instances', {})
    for cue_id, receipt in receipts.items():
        cue = cues.get(str(cue_id))
        if cue is not None and receipt.get('needs_review'):
            note = str(receipt['needs_review'])[:512]
            add(QCIssue('boundary_receipt', QCSeverity.INFO, QCCategory.TIMELINE, cue.id,
                        '边界操作记录', '本次边界操作保留了原文；字词映射信息：'+note,
                        source='caption_receipt'), cue)

    # Measure associated translation text with the same readability rule and
    # its own language. Cache individual measurements across local edits.
    from .subtitle_translation import container_target, records_of, status_of, FAILED
    from .studio_qc import QCCategory, QCIssue
    target = container_target(project)
    translations = project.generation_metadata.get("translations", {})
    translation_cache = getattr(project, "_translation_issue_measurements", {})
    next_cache = {}
    proxy = SimpleNamespace(generation_metadata={"language": {"code": target}}, studio_state={}, cues=())
    context = SimpleNamespace(project=proxy, config=QCConfig())
    for cue_id, text in translations.items():
        cue = cues.get(str(cue_id))
        if cue is None or not text:
            continue
        stamp = (str(text), cue.start_ms, cue.end_ms, target)
        saved = translation_cache.get(cue_id)
        rows = saved[1] if saved and saved[0] == stamp else tuple(
            ReadabilityRule().evaluate(replace(cue, text=str(text)), context))
        next_cache[cue_id] = (stamp, rows)
        for issue in rows:
            add(issue, cue, "translation", target, str(text))
    project._translation_issue_measurements = next_cache
    for cue_id, record in records_of(project).items():
        cue = cues.get(str(cue_id))
        if cue and not translations.get(cue_id) and status_of(record, cue.text, target=target) == FAILED:
            issue = QCIssue("missing_translation", QCSeverity.WARNING, QCCategory.TEXT, cue.id,
                            "译文未完成", f"{target} 译文任务未完成：{record.get('error') or record.get('reason') or '可手动补充或重试'}")
            add(issue, cue, "translation", target, "")
    levels = {cue_id: ("high" if any(r.level == "high" for r in rows) else "suggested")
              for cue_id, rows in active.items()}
    result = CurrentIssueView(dict(active), dict(diagnostics), tuple(records), levels)
    project._current_issue_row_cache = next_rows_cache
    project._current_issue_view = (qc, cache_decisions, result)
    return result
