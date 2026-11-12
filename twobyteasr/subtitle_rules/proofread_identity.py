"""Pure identity validation shared by recognition and the review page."""
def validate_new_suspects(value, originals):
    """Quarantine optional discoveries; they never authorize a text edit.

    Preserve raw rows, including malformed types, for honest local/global
    review. Only exact integer cue IDs attach to a known editable cue.
    """
    import copy
    scoped, unassigned, positions = {}, [], set()
    rows = value if isinstance(value, list) else [value]
    for original in rows:
        row = copy.deepcopy(original) if isinstance(original, dict) else {}
        errors = []
        if not isinstance(value, list):
            errors.append('new_suspects_not_array')
        if not isinstance(original, dict):
            errors.append('new_suspect_not_object')
        cue_id = row.get('cue_id', row.get('id'))
        if isinstance(row.get('id'), str):
            row.setdefault('suspect_id', row['id'])
        association = 'explicit_cue_id'
        # Repair only by a unique exact text span in this request. Never
        # parse digits out of an arbitrary suggestion/suspect identifier.
        if type(cue_id) is not int and isinstance(value, list):
            a,b,surface = row.get('start'),row.get('end'),row.get('surface')
            matches = [key for key,text in originals.items() if type(a) is int and type(b) is int
                       and isinstance(surface,str) and 0 <= a < b <= len(text) and text[a:b] == surface]
            if len(matches) == 1:
                cue_id = matches[0]
                association = 'unique_exact_primary_span'
            else:
                row['association_candidates'] = matches
        attributable = type(cue_id) is int and cue_id in originals and isinstance(value, list)
        if type(cue_id) is not int:
            errors.append('invalid_cue_id_type')
        elif cue_id not in originals:
            errors.append('unknown_editable_cue_id')
        start, end, surface = row.get('start'), row.get('end'), row.get('surface')
        valid_span_type = type(start) is int and type(end) is int
        if not valid_span_type:
            errors.append('invalid_span_type')
        if not isinstance(surface, str):
            errors.append('invalid_surface_type')
        if attributable and valid_span_type:
            raw = originals[cue_id]
            if not 0 <= start < end <= len(raw):
                errors.append('span_out_of_bounds')
            elif isinstance(surface, str) and raw[start:end] != surface:
                errors.append('surface_mismatch')
            position = (cue_id, start, end)
            if position in positions:
                errors.append('duplicate_new_suspect_position')
            positions.add(position)
        evidence = row.get('evidence')
        if not isinstance(evidence, str):
            errors.append('invalid_evidence_type')
        elif not evidence.strip():
            errors.append('empty_evidence')
        row.update(raw_model_row=copy.deepcopy(original),
            cue_id=cue_id if attributable else None, association_basis=association if attributable else 'unassigned',
            validation_state='invalid' if errors else 'validated_original_position',
            validation_errors=errors, model_evidence_is_not_source_proof=True)
        if attributable:
            scoped.setdefault(cue_id, []).append(row)
        else:
            unassigned.append(row)
    return scoped, unassigned

