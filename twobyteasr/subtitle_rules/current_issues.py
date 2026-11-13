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
from .review_evidence_policy import evidence_only_reason, retired_review_reason, unsupported_repeat_pattern

ISSUE_RULE_VERSION = 7
DECISIONS = "current_issue_decisions"
LEGACY_INPUTS = 'current_issue_legacy_inputs'
LEGACY_SCOPES = 'current_issue_legacy_scopes'
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


def unhandled_suggestion(project,cue_id,layer,row):
    """A current whole-issue keep also suppresses the same convenience mark."""
    if row.kind=='pronoun':return row
    handled=set()
    for issue in current_issue_view(project).diagnostics.get(str(cue_id),()):
        if issue.layer!=layer or issue.disposition!='handled':continue
        decision=project.studio_state.get(DECISIONS,{}).get(issue.issue_id,{})
        if (decision.get('status') not in {'resolved','ignored'}
                or decision.get('input_version')!=issue.input_version
                or decision.get('evidence_version')!=issue.evidence_version):
            continue  # a legacy whole-caption label is not a veto on new local evidence
        for prior in issue.suggestions:
            if (prior.start,prior.end,prior.original)==(row.start,row.end,row.original):
                handled.update(option.text for option in prior.options)
    options=tuple(option for option in row.options if option.text not in handled)
    return replace(row,options=options) if options else None


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


def legacy_scope(project,cue):
    """Freeze the evidence clock missing from older confirmation fingerprints."""
    refs=[]
    for ref in cue.evidence_refs:
        row=project.asr_evidence.get(ref,{})
        arbitration=row.get('caption_arbitration') or {}
        refs.append((ref,row.get('start_ms'),row.get('end_ms'),row.get('speaker_id'),
            row.get('words'),row.get('source_coverage'),arbitration.get('source_coverage'),
            arbitration.get('acoustic_words'),arbitration.get('word_timing')))
    return digest([cue.text,cue.start_ms,cue.end_ms,cue.speaker_id,refs])


def prepare_legacy_scopes(project):
    if project.studio_state.get(DECISIONS) and LEGACY_SCOPES not in project.studio_state:
        project.studio_state[LEGACY_SCOPES]={c.id:legacy_scope(project,c) for c in project.cues}


def legacy_asr_decision(project,cue,layer,language,decisions):
    """Honor an existing human decision when a rule is narrowed or renamed.

    No new human action or timestamp is created. The baseline is captured at
    open before editorial time changes; later effective evidence changes fail
    this compatibility gate and use the current rule's normal fingerprint.
    """
    scopes=project.studio_state.get(LEGACY_SCOPES,{})
    if cue.id not in scopes or scopes[cue.id]!=legacy_scope(project,cue):
        return False
    from .studio_qc import model_evidence,QCEvidence,_compact,normalize_spoken_text
    evidence=model_evidence(project,cue)
    distinct={_compact(cue.text):QCEvidence('Current',cue.text,'project')}
    for item in evidence:
        if item.text and not item.context_only and normalize_spoken_text(item.text)!=normalize_spoken_text(cue.text):
            distinct.setdefault(_compact(item.text),item)
    vectors=(('model_disagreement','asr_evidence',tuple(distinct.values())),
             ('local_model_correction','asr_local_candidate',tuple(e for e in evidence if not e.context_only)))
    for kind,source,items in vectors:
        key=digest([project.project_id,cue.id,cue.speaker_id,layer,language,kind,source,()])
        decision=decisions.get(key,{})
        if (decision.get('status') in {'resolved','ignored'}
                and decision.get('input_version')==digest([cue.text])
                and decision.get('evidence_version')==digest([(e.label,e.source,e.text,e.context_only) for e in items])):
            return True
    return False


def pending_review_changes(project):
    """One immutable decision batch over the entire project, independent of filters."""
    view = current_issue_view(project)
    rows = [row for row in view.records
            if row.disposition == 'actionable' and row.level in {'high', 'suggested'}]
    cue_ids = {row.cue_id for row in rows}
    from datetime import datetime, timezone
    reviewed_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    changes = {row.issue_id: {'input_version': row.input_version,
                'evidence_version': row.evidence_version, 'status': 'resolved',
                'action': 'reviewed_keep_current', 'reviewed_at': reviewed_at} for row in rows}
    for cue in project.cues:
        if cue.id in cue_ids:
            changes['reviewed:'+cue.id] = {'input_version': reviewed_version(project, cue),
                'status': 'resolved', 'action': 'reviewed_keep_current', 'reviewed_at': reviewed_at}
    return changes, cue_ids, len(rows)


def acknowledged_issue_views(project, changes):
    """Precompute the save-only batch projection without rerunning QC rules."""
    from ..projects.studio_runtime_state import state_for
    view = current_issue_view(project)
    accepted = {r.issue_id: replace(r, level='confident', disposition='handled')
                for r in view.records if r.issue_id in changes}
    active = {key: tuple(r for r in rows if r.issue_id not in accepted)
              for key, rows in view.by_cue.items()}
    active = {key: rows for key, rows in active.items() if rows}
    diagnostics = {key: tuple(rows) for key, rows in view.diagnostics.items()}
    for row in accepted.values():
        diagnostics[row.cue_id] = (*diagnostics.get(row.cue_id, ()), row)
    levels = dict(view.levels)
    for row in accepted.values():
        levels[row.cue_id] = 'confident'
    after = CurrentIssueView(active, diagnostics,
        tuple(accepted.get(r.issue_id, r) for r in view.records), levels)
    parts = project._current_issue_parts
    after_parts = [{key: tuple(accepted.get(r.issue_id, r) for r in rows)
                    for key, rows in part.items()} for part in parts]
    return dict(qc=project._qc_result, revision=state_for(project).qc_revision,
                policy=issue_policy_version(project), before=(view, parts), after=(after, after_parts))


def adopt_acknowledged_view(project, prepared, *, undo=False):
    from ..projects.studio_runtime_state import state_for
    if (prepared is None or prepared['qc'] is not getattr(project, '_qc_result', None)
            or prepared['revision'] != state_for(project).qc_revision
            or prepared['policy'] != issue_policy_version(project)):
        return
    view, parts = prepared['before' if undo else 'after']
    project._current_issue_view = (prepared['qc'], project.studio_state.get(DECISIONS) or None, view, prepared['policy'])
    project._current_issue_parts = parts
    project._current_issue_row_cache = {}
    project._current_issue_dirty_ids = set()


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
    evidence_version: str = ""

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

    def totals(self):
        active=[r for r in self.records if r.disposition=='actionable']
        return dict(cues=len({r.cue_id for r in active}),issues=len(active))

    def candidate_groups(self):
        groups=defaultdict(list)
        for row in self.records:
            if row.disposition!='actionable':
                continue
            for suggestion in row.suggestions:
                if len(suggestion.original)<2:
                    continue
                key=(row.language,suggestion.original,tuple(o.text for o in suggestion.options))
                groups[key].append((row,suggestion))
        return tuple(tuple(rows) for rows in groups.values() if len({row.cue_id for row,_ in rows})>1)

    def statistics(self):
        groups = defaultdict(list)
        for row in self.records:
            groups[row.kind].append(row)
        return {kind: {"raw": len(rows), "unique_cues": len({r.cue_id for r in rows}),
                       **dict(Counter(r.disposition for r in rows))}
                for kind, rows in groups.items()}


def invalidate(project, cue_ids=None):
    if cue_ids and getattr(project, '_current_issue_view', None) is not None:
        pending = getattr(project, '_current_issue_dirty_ids', None)
        project._current_issue_dirty_ids = set(pending or ()) | {str(key) for key in cue_ids}
    else:
        project._current_issue_view = None
        project._current_issue_dirty_ids = None


def _language(project, cue, layer):
    from ..projects.subtitle_import import imported_track
    from .language_rules import project_language
    from .subtitle_translation import container_target
    return (container_target(project) if layer == "translation" else
            imported_track(project, cue.speaker_id).get("language") or project_language(project))


def _classify(issue, cue, text, language, cues):
    """Calibrate tasks, retaining the original event and a concrete explanation."""
    kind = issue.issue_type
    if retired_review_reason(kind, issue.source):
        return 'confident', 'retired_rule'
    if unsupported_repeat_pattern(issue):
        return 'confident', 'unsubstantiated_pattern'
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
    policy = issue_policy_version(project)
    cache = getattr(project, "_current_issue_view", None)
    if cache is not None and (len(cache) < 4 or cache[3] != policy):
        cache = None
    dirty = getattr(project, '_current_issue_dirty_ids', None)
    if cache is not None and cache[0] is qc and cache[1] is cache_decisions and not dirty:
        return cache[2]
    old_parts = getattr(project, '_current_issue_parts', None)
    changed = None
    if cache is not None and cache[1] is cache_decisions and old_parts is not None:
        changed = set(dirty or ())
        old_qc = cache[0].issues_by_cue
        changed.update(str(key) for key in old_qc.keys() | qc.issues_by_cue.keys()
                       if old_qc.get(key) is not qc.issues_by_cue.get(key))
        # An overlap's version consumes its previous caption too. Rebuild the
        # direct dependants, not a transitive chain of unchanged captions.
        inputs = set(changed)
        changed.update(str(key) for key, rows in qc.issues_by_cue.items()
                       if str(key) not in inputs and any(
                           str(row.fix_metadata.get('previous_cue_id', '')) in inputs for row in rows))
        if len(changed) > max(64, len(project.cues)//2):
            changed = None
    cues = {str(c.id): c for c in project.cues}
    legacy=legacy_review_inputs(project)
    active, diagnostics, records = defaultdict(list), defaultdict(list), []
    parts = [dict(part) for part in old_parts] if changed is not None else [{} for _ in range(4)]
    if changed is not None:
        active.update({key: rows for key, rows in cache[2].by_cue.items() if key not in changed})
        diagnostics.update({key: rows for key, rows in cache[2].diagnostics.items() if key not in changed})
        for part in parts:
            for key in changed:part.pop(key, None)
    phase = 0
    seen = set()
    content_tasks = {}
    row_cache = getattr(project, '_current_issue_row_cache', {})
    next_rows_cache = ({key: value for key, value in row_cache.items() if key[0] not in changed}
                       if changed is not None else {})

    def add(issue, cue, layer="original", language=None, text=None):
        text = cue.text if text is None else text
        language = language or _language(project, cue, layer)
        from ..projects.subtitle_import import imported_track
        role = 'translation' if layer == 'translation' else imported_track(project, cue.speaker_id).get('role', 'original')
        previous = cues.get(str(issue.fix_metadata.get('previous_cue_id', '')))
        previous_input = (previous.text, previous.start_ms, previous.end_ms, previous.speaker_id) if previous else None
        stamp = (policy, text, cue.start_ms, cue.end_ms, cue.speaker_id, language, role, previous_input,
                 project.studio_state.get('review_confirmations', {}).get(cue.id),
                 project.studio_state.get('manual_caption_text', {}).get(cue.id),legacy.get(cue.id),
                 legacy_scope(project,cue) if cue.id in project.studio_state.get(LEGACY_SCOPES,{}) else None)
        location=(issue.fix_metadata.get('surface'),issue.fix_metadata.get('canonical')) if issue.category.value=='terminology' else ()
        cache_key = (cue.id, layer, issue.issue_type, issue.source,location)
        saved = row_cache.get(cache_key)
        if (saved is not None and saved[0] is issue and saved[1] == stamp
                and saved[2] == tuple(decisions.get(k) for k in saved[3])):
            row = saved[4]
            if (row.issue_id, row.input_version) in seen:
                return
            next_rows_cache[cache_key] = saved
            seen.add((row.issue_id, row.input_version))
            records.append(row)
            parts[phase].setdefault(cue.id, []).append(row)
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
        evidence_inputs=[(e.label,e.source,e.text,e.context_only) for e in issue.evidence]
        evidence_version = digest([evidence_inputs,issue.fix_metadata['evidence_scope']]
            if issue.fix_metadata.get('evidence_scope') else evidence_inputs)
        evaluated_text = text
        if issue.issue_type in {'abnormal_punctuation', 'duplicate_punctuation'}:
            from .punctuation_style import style_text, style_translation, project_mode, math_enabled, protected_terms_of
            if layer == 'translation':
                evaluated_text = style_translation(text, project_mode(project), math=math_enabled(project))
            else:
                evaluated_text = style_text(text, project_mode(project), language=language,
                    math=math_enabled(project), protected_terms=protected_terms_of(project)).text
        level, disposition = _classify(issue, cue, evaluated_text, language, cues)
        if (key, version) in seen:
            return
        seen.add((key, version))
        decision = decisions.get(key, {})
        if (decision.get("input_version") == version and decision.get("status") in {"ignored", "resolved"}
                and decision.get('evidence_version', evidence_version) == evidence_version):
            level, disposition = "confident", "handled"
        elif (issue.issue_type in {'model_disagreement','local_model_correction'}
                and legacy_asr_decision(project,cue,layer,language,decisions)):
            level,disposition='confident','handled'
        # Legacy human confirmations are accepted only for the exact text they
        # confirmed; mere pending/done labels are not issue decisions.
        elif (layer == "original" and issue.category.value in {'asr','text','terminology'}
              and not decision.get('evidence_version')
              and legacy.get(cue.id)==(project.studio_state.get('review_confirmations',{}).get(cue.id),text)):
            level, disposition = "confident", "handled"
        candidates = [(e.text, (e.label,)) for e in issue.evidence
                      if e.text and not e.context_only and e.label not in {"Current","词库"} and e.text != text]
        if issue.issue_type in {'model_disagreement','local_model_correction','suspected_word'}:
            from .studio_qc import model_evidence, normalize_spoken_text
            eligible = {normalize_spoken_text(e.text) for e in model_evidence(project,cue) if not e.context_only}
            accepted = [c for c in candidates if normalize_spoken_text(c[0]) in eligible]
            if candidates and not accepted:
                level, disposition = 'confident', 'invalidated_machine_suggestion'
            candidates = accepted
        # Incomplete time coverage does not justify deleting an unsupported
        # suffix. It offers listening / boundary adjustment, not a text patch.
        suggestions = tuple(model_suggestions(text, candidates)) if issue.category.value in {"asr", "terminology"} and issue.issue_type != 'current_projection_difference' else ()
        surface=issue.fix_metadata.get('surface');canonical=issue.fix_metadata.get('canonical')
        if issue.issue_type=='terminology_mismatch' and surface and canonical:
            suggestions=tuple(ReviewSuggestion(m.start(),m.end(),m.group(),(SuggestionOption(str(canonical)),),GLOSSARY)
                for m in list(re.finditer(re.escape(str(surface)),text))[:MAX_MARKS])
        from ..recognition.asr_source_evidence import annotate_suggestions
        unvalidated_suggestions = suggestions
        suggestions = annotate_suggestions(project,cue,suggestions)
        if (unvalidated_suggestions and not suggestions
                and all(r.kind=='model' for r in unvalidated_suggestions)
                and issue.issue_type in {'model_disagreement','local_model_correction'}):
            level,disposition='confident','invalidated_machine_suggestion'
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
        if candidates and not suggestions and issue.issue_type in {'model_disagreement','local_model_correction'}:
            from .machine_text_policy import protected_deletions
            if all(protected_deletions(text, value) for value,_ in candidates):
                level, disposition = 'confident', 'invalidated_machine_suggestion'
        if disposition=='actionable' and issue.category.value in {'asr','terminology'}:
            # Identical local decisions from ASR and terminology are one task;
            # retain every raw rule and its evidence in the diagnostic view.
            signature=(cue.id,layer,tuple(sorted((r.start,r.end,r.original,
                tuple(sorted(o.text for o in r.options))) for r in suggestions)))
            if suggestions and signature in content_tasks:
                level,disposition='confident','duplicate'
            elif suggestions:
                content_tasks[signature]=key
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
                           level, issue.label, detail, text, cue.start_ms, cue.end_ms, suggestions, disposition,
                           evidence_version)
        records.append(row)
        parts[phase].setdefault(cue.id, []).append(row)
        next_rows_cache[cache_key] = (issue, stamp, tuple(decisions.get(k) for k in decision_keys), decision_keys, row)
        (active if disposition == "actionable" else diagnostics)[cue.id].append(row)

    for cue_id, rows in qc.issues_by_cue.items():
        if changed is not None and str(cue_id) not in changed:continue
        cue = cues.get(str(cue_id))
        if cue is not None:
            for issue in rows:
                add(issue, cue)

    # Keep the operation's original boundary receipt visible as a diagnosis.
    # A missing word map alone is not independent evidence of an error.
    from .studio_qc import QCCategory, QCIssue
    receipts = project.studio_state.get('caption_timeline', {}).get('instances', {})
    phase = 1
    for cue_id, receipt in receipts.items():
        if changed is not None and str(cue_id) not in changed:continue
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
    next_cache = ({key: value for key, value in translation_cache.items() if str(key) not in changed}
                  if changed is not None else {})
    proxy = SimpleNamespace(generation_metadata={"language": {"code": target}}, studio_state=project.studio_state, cues=())
    context = SimpleNamespace(project=proxy, config=QCConfig())
    phase = 2
    for cue_id, text in translations.items():
        if changed is not None and str(cue_id) not in changed:continue
        cue = cues.get(str(cue_id))
        if cue is None or not text:
            continue
        stamp = (str(text), cue.start_ms, cue.end_ms, target, policy)
        saved = translation_cache.get(cue_id)
        rows = saved[1] if saved and saved[0] == stamp else tuple(
            ReadabilityRule().evaluate(replace(cue, text=str(text)), context))
        next_cache[cue_id] = (stamp, rows)
        for issue in rows:
            add(issue, cue, "translation", target, str(text))
    project._translation_issue_measurements = next_cache
    translation_records = records_of(project)
    phase = 3
    for cue_id, record in translation_records.items():
        if changed is not None and str(cue_id) not in changed:continue
        cue = cues.get(str(cue_id))
        if cue and not translations.get(cue_id) and status_of(record, cue.text, target=target) == FAILED:
            issue = QCIssue("missing_translation", QCSeverity.WARNING, QCCategory.TEXT, cue.id,
                            "译文未完成", f"{target} 译文任务未完成：{record.get('error') or record.get('reason') or '可手动补充或重试'}")
            add(issue, cue, "translation", target, "")
    levels = {cue_id: ("high" if any(r.level == "high" for r in rows) else "suggested")
              for cue_id, rows in active.items()}
    # Preserve the full builder's rule and mapping order while sharing every
    # unchanged cue's rows. Flattening references is cheap; recalibrating tens
    # of thousands of issues/languages on every edit was seconds of GUI work.
    records = tuple(row for part, order in zip(parts, (qc.issues_by_cue, receipts, translations, translation_records))
                    for key in order for row in part.get(str(key), ()))
    result = CurrentIssueView(dict(active), dict(diagnostics), records, levels)
    project._current_issue_row_cache = next_rows_cache
    project._current_issue_parts = tuple(parts)
    project._current_issue_dirty_ids = set()
    project._current_issue_view = (qc, cache_decisions, result, policy)
    return result


def _decision_version(project):
    # Cue, language/model and sequence inputs are guarded by qc_revision.
    # Review decisions are save-only and may change while that job runs.
    return digest({key: project.studio_state.get(key, {}) for key in
                   (DECISIONS, 'review_confirmations', 'manual_caption_text', LEGACY_INPUTS,LEGACY_SCOPES)})


def issue_policy_version(project):
    from .language_rules import project_language
    from .subtitle_translation import container_target
    return digest([ISSUE_RULE_VERSION, project_language(project), container_target(project),
                   (project.generation_metadata.get('subtitle_imports') or {}).get('tracks', {}),
                   project.studio_state.get('punctuation')])


def prepare_issue_cache(project):
    """Private QC-worker result; contains data only, never the worker project."""
    view = current_issue_view(project)
    return dict(version=ISSUE_RULE_VERSION, project_id=project.project_id,
                policy=issue_policy_version(project), decisions=_decision_version(project), view=view,
                parts=project._current_issue_parts, rows=project._current_issue_row_cache,
                translations=project._translation_issue_measurements)


def adopt_issue_cache(project, qc, prepared):
    """Adopt only after the caller's session/QC token and current decisions agree."""
    if (not isinstance(prepared, dict) or prepared.get('version') != ISSUE_RULE_VERSION
            or prepared.get('project_id') != project.project_id
            or prepared.get('policy') != issue_policy_version(project)
            or prepared.get('decisions') != _decision_version(project)):
        return False
    decisions = project.studio_state.get(DECISIONS) or _EMPTY_DECISIONS
    project._current_issue_view = (qc, None if decisions is _EMPTY_DECISIONS else decisions, prepared['view'], issue_policy_version(project))
    project._current_issue_parts = prepared['parts']
    project._current_issue_row_cache = prepared['rows']
    project._translation_issue_measurements = prepared['translations']
    project._current_issue_dirty_ids = set()
    return True
