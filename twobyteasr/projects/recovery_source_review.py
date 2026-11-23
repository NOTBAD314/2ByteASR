"""Identify machine-created recovery rows that lack a usable acoustic anchor."""
def rejected_source_cues(project):
    from ..recognition.asr_schema import firered_text
    from ..recognition.speech_coverage import FILL_ROW_SOURCE
    spans = project.generation_metadata.get('segmentation_source_spans', {}).get('cues', {})
    owners = {}
    for cue in project.cues:
        parts = spans.get(cue.id, {}).get('parts', ())
        for key in {piece.get('source_id') for piece in parts}:
            owners.setdefault(key, []).append((cue, parts))
    rejected = {}
    for key, group in owners.items():
        evidence = project.asr_evidence.get(f'segment:{key}', {})
        if evidence.get('primary_source') != FILL_ROW_SOURCE:
            continue
        raw = evidence.get('text', '')
        seconds = (evidence['end_ms'] - evidence['start_ms']) / 1000
        reason = None
        if firered_text(raw) != raw.strip():
            reason = 'model_control_in_recovery'
        elif len(raw) > 80 and len(raw) / max(.01, seconds) > 20:
            reason = 'unsupported_recovery_rate'
        if reason is None or any(cue.text != cue.original_text or
                cue.text != ''.join(part['raw_text'] for part in parts) or
                any(part.get('source_id') != key for part in parts)
                for cue, parts in group):
            continue
        if ''.join(cue.text for cue, _ in group) != raw:
            continue
        rejected[key] = dict(reason=reason, cue_ids=[cue.id for cue, _ in group],
                             source_ms=[evidence['start_ms'], evidence['end_ms']])
    return rejected
