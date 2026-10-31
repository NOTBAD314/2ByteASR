"""Project-relative review identities; historical events never become todos."""
import hashlib
import json
from collections import defaultdict

DECISIONS_KEY = 'recognition_review_decisions'
TEXT_CATEGORIES = {'多模型争议', '术语候选', '术语候选待确认', '术语召回缺口'}
WARNINGS = {'校对回退', '断句回退'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def current_review(project, report):
    from .processing_recovery import _input_text
    from ..subtitle_rules.review_evidence_policy import evidence_only_reason
    job = str(report.get('job_id') or project.generation_metadata.get('job_id') or project.project_id)
    cues = {str(c.id): c for c in project.cues}
    refs = defaultdict(list)
    for cue in project.cues:
        for ref in cue.evidence_refs:
            refs[str(ref)].append(cue.id)
    originals = defaultdict(list)
    cue_texts = defaultdict(list)
    evidence_texts = defaultdict(list)
    for cue in project.cues:
        cue_texts[cue.text].append(cue)
    evidence = project.asr_evidence
    for ref, record in evidence.items():
        if not str(ref).startswith('segment:') or not isinstance(record, dict):
            continue
        identity = (record.get('caption_arbitration') or {}).get('processing_identity') or {}
        if identity.get('polish_record_id') is not None:
            originals[str(identity['polish_record_id'])].append(str(ref))
        for text in {_input_text(record), str(record.get('text') or ''), str(record.get('final_text') or '')}:
            if text:
                evidence_texts[text].append(str(ref))
    decisions = project.studio_state.get(DECISIONS_KEY) or {}
    manual = project.studio_state.get('manual_caption_text') or {}
    current, suggestions, warnings = {}, {}, []
    raw = list(report.get('review_items') or ())
    historical = [r for r in raw if r.get('category') in ('阅读较快', '显示过短')]
    sources = [r for r in raw if r.get('category') not in ('阅读较快', '显示过短')]
    # These two rules are deterministic and can be recomputed from CURRENT
    # caption text/times, including edits and restored/ignored speakers.
    # The facade initializes text_rules and polishing together. Importing
    # text_rules first here leaves polishing with a partially populated core.
    from subtitle_core import REVIEW_FAST_CHARS_PER_SECOND, display_length
    language=project.generation_metadata.get('language') or {}
    tag=language.get('locale') or language.get('code') if isinstance(language,dict) else language
    if tag:
        from ..subtitle_rules.segmentation_profiles import profile_for,measure
        policy=profile_for(tag)
        text_length=lambda text:measure(text,tag)
        fast_limit=policy.warning_cps
    else:
        text_length=display_length;fast_limit=REVIEW_FAST_CHARS_PER_SECOND
    for cue in project.cues:
        duration = max(.001, (cue.end_ms-cue.start_ms)/1000)
        length = text_length(cue.text)
        reasons = []
        if duration < .45:
            reasons.append(('显示过短', f'只显示 {duration:.2f} 秒'))
        if length >= 8 and length/duration > fast_limit:
            reasons.append(('阅读较快', f'约 {length/duration:.1f} 字/秒'))
        sources.extend(dict(category=category, detail=detail, cue_id=cue.id, text=cue.text,
                            timestamp=cue.start_ms/1000, severity='review') for category, detail in reasons)
    for source in sources:
        row = dict(source)
        category = str(row.get('category') or '')
        if evidence_only_reason(category):
            row['severity'] = 'info'
            historical.append(row)
            continue
        if category in WARNINGS:
            warnings.append(row)
            continue
        if row.get('severity') in ('info', 'debug'):
            historical.append(row)
            continue
        if category == '说话人需要确认':
            roles = (project.generation_metadata.get('speaker_recovery') or {}).get('roles') or {}
            pending = [s.id for s in project.speakers if roles.get(s.id) == 'unconfirmed']
            if not pending:
                historical.append(row)
                continue
            ids, identity = [], ['speakers', sorted(pending)]
            row.update(target='speakers', speaker_ids=pending)
        elif row.get('segment_id') is not None:
            original = str(row['segment_id'])
            found = originals.get(original, [])
            if not found:
                ref = 'segment:'+original
                record = evidence.get(ref) or {}
                # A bare number alone is never proof after segment deletion.
                if record and (str(row.get('text') or '') in (_input_text(record), str(record.get('text') or ''), str(record.get('final_text') or ''))):
                    found = [ref]
            ids = list(dict.fromkeys(c for ref in found for c in refs[ref] if c in cues))
            identity = ['processing', original, sorted(found)]
        else:
            cue_id = str(row.get('cue_id') or '')
            ids = [cue_id] if cue_id in cues else []
            # Older timing/QC reports omitted IDs. Resolve their complete
            # text AND timestamp to exactly one current caption; the resolved
            # stable cue ID then owns the issue, never its displayed number.
            if not ids and row.get('text') and row.get('timestamp') is not None:
                at = round(float(row['timestamp'])*1000)
                matches = [c for c in cue_texts[str(row['text'])] if abs(c.start_ms-at) <= 80]
                if len(matches) == 1:
                    ids = [matches[0].id]
                elif category in TEXT_CATEGORIES:
                    matched_refs = list(dict.fromkeys(evidence_texts[str(row['text'])]))
                    if len(matched_refs) == 1:
                        ids = [c for c in refs[matched_refs[0]] if c in cues]
            identity = ['cue', cue_id]
            if ids:
                identity = ['cue', sorted(ids)]
        if not ids and row.get('target') != 'speakers':
            historical.append(row)
            continue
        if category in TEXT_CATEGORIES and ids:
            if all(manual.get(c) == cues[c].text for c in ids):
                historical.append(row)
                continue
        statuses = project.studio_state.get('cue_statuses') or {}
        if ids and all(statuses.get(c) == 'done' and c in (project.studio_state.get('review_confirmations') or {}) for c in ids):
            historical.append(row)
            continue
        if category not in TEXT_CATEGORIES and ids and row.get('text') and len(ids) == 1:
            if str(row['text']) != cues[ids[0]].text:
                historical.append(row)
                continue
        location = [row.get(k) for k in ('suspect_id', 'term_id', 'surface', 'start', 'end')]
        key = job+':review:'+_digest([category, identity, location])[:24]
        version = _digest([[c, cues[c].start_ms, cues[c].end_ms, cues[c].text, cues[c].speaker_id] for c in ids]
                          if ids else identity)
        row.update(issue_id=key, cue_ids=ids, input_version=version)
        if decisions.get(key, {}).get('input_version') == version and decisions[key].get('status') in ('ignored', 'resolved'):
            historical.append(row)
            continue
        # No recalled candidate does not establish a typo. Keep every surface
        # available as an optional glossary suggestion, not a failed task.
        if category == '术语召回缺口':
            row['severity'] = 'info'
            suggestions[key] = row
        else:
            row['severity'] = 'review'
            current[key] = row
    return dict(items=list(current.values()), suggestions=list(suggestions.values()), warnings=warnings,
                history=historical, affected_cues=len({c for row in current.values() for c in row['cue_ids']}),
                unit='issue', result_complete=bool(project.cues) and len(cues) == len(project.cues)
                    and all(c.end_ms > c.start_ms >= 0 and c.speaker_id in {s.id for s in project.speakers}
                            for c in project.cues))
