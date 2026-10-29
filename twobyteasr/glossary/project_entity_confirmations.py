"""Human entity decisions are scoped to a media identity and reviewed locally."""
from __future__ import annotations
import re


def confirmation_receipt(project, alias, canonical, cue_ids):
    alias, canonical = str(alias).strip(), str(canonical).strip()
    if not alias or not canonical or alias == canonical:
        raise ValueError('A confirmation requires distinct, nonempty literal spellings')
    wanted = set(cue_ids)
    return {'kind': 'project_entity_confirmation', 'source': 'user_confirmed',
        'project_id': project.project_id, 'media_fingerprint': project.media.fingerprint,
        'media_path': project.media.path, 'alias': alias, 'canonical': canonical,
        'audio_verified_by_model': False,
        'confirmed_occurrences': [{'cue_id': c.id, 'start_ms': c.start_ms,
            'end_ms': c.end_ms, 'text': c.text} for c in project.cues if c.id in wanted]}


def confirmed_entity_occurrences(project, *, locked_ids=(), diagnostics=None):
    from ..studio.studio_text_tools import TextOccurrence, cue_locked
    fingerprints = project.media.fingerprint
    hits, seen, scoped = [], set(), []
    for row in project.generation_metadata.get('glossary_review_jobs', ()):
        if (not isinstance(row, dict) or row.get('kind') != 'project_entity_confirmation'
                or row.get('source') != 'user_confirmed'
                or row.get('project_id') != project.project_id):
            continue
        if fingerprints:
            if row.get('media_fingerprint') != fingerprints:
                continue
        elif not project.media.path or row.get('media_path') != project.media.path:
            continue
        alias, canonical = row.get('alias'), row.get('canonical')
        if not isinstance(alias,str) or not isinstance(canonical,str) or not alias or not canonical:
            continue
        scoped.append((alias,canonical))
    destinations = {}
    for alias,canonical in scoped:
        destinations.setdefault(alias,set()).add(canonical)
    conflicts = {alias for alias,values in destinations.items() if len(values)>1}
    if diagnostics is not None:
        diagnostics.extend(sorted(conflicts))
    for alias,canonical in scoped:
        if alias in conflicts:
            continue
        # Complete Latin tokens only: a confirmed So may not rewrite Somebody.
        expression = re.escape(alias)
        if re.search(r'[A-Za-z0-9]', alias):
            expression = r'(?<![A-Za-z0-9_])' + expression + r'(?![A-Za-z0-9_])'
        for cue in project.cues:
            if cue_locked(cue, locked_ids):
                continue
            for match in re.finditer(expression, cue.text):
                identity = (cue.id, match.span(), canonical)
                if identity in seen:
                    continue
                seen.add(identity)
                hits.append(TextOccurrence(cue.id, cue.start_ms, match.group(), canonical,
                    match.span(), reason='user_confirmed'))
    return hits
