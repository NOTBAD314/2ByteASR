"""Visual subtitle groups over independent, stable editable text addresses."""


def group_rows(rows, entries, project, *, bilingual=False):
    cues = {cue.id: cue for cue in project.cues} if project is not None else {}
    entry_by_key = {entry.key: entry for entry in entries}
    groups = {}
    for row in rows:
        entry = entry_by_key[row['cue_id']]
        # Existing import/export associations alone join imported translations.
        owner = (entry.source_cue_id if entry.target.layer == 'translation' else '') or entry.target.cue_id
        row['group_id'] = owner
        row['audio_cue_id'] = owner if owner in cues else entry.target.cue_id
        groups.setdefault(owner, []).append(row)
    def order(item):
        owner, fields = item
        cue = cues.get(owner)
        return (cue.start_ms, cue.end_ms, owner) if cue is not None else (
            fields[0]['start_ms'], fields[0]['end_ms'], owner)
    ordered, indices = [], {}
    for number, (owner, fields) in enumerate(sorted(groups.items(), key=order), 1):
        fields.sort(key=lambda row: (row['target'].layer != 'original', row['target'].track_id, row['cue_id']))
        source = next((row for row in fields if row['target'].layer == 'original'), fields[0])
        has_translation = any(row['target'].layer == 'translation' for row in fields)
        indices[owner] = []
        for n, row in enumerate(fields):
            row.update(number=f'#{number}', group_first=n == 0, group_last=n == len(fields)-1,
                       group_secondary=n > 0, group_fields=tuple(field['cue_id'] for field in fields),
                       translation_missing=bool(bilingual and not has_translation and row is source),
                       time=source['time'], speaker=source['speaker'], speaker_id=source['speaker_id'])
            indices[owner].append(len(ordered))
            ordered.append(row)
    return ordered, indices


def subtitle_count(rows):
    return len({row.get('group_id', row['cue_id']) for row in rows})


def regroup_rows(rows):
    """Respect a changed group sort; keep source before translation inside it."""
    groups = {}
    for row in rows:groups.setdefault(row.get('group_id',row['cue_id']),[]).append(row)
    ordered, indices = [], {}
    for number,(owner,fields) in enumerate(groups.items(),1):
        fields.sort(key=lambda row:(row['target'].layer!='original',row['target'].track_id,row['cue_id']))
        indices[owner]=[]
        for index,row in enumerate(fields):
            row.update(number=f'#{number}',group_first=index==0,group_last=index==len(fields)-1,
                       group_secondary=index>0,group_fields=tuple(field['cue_id'] for field in fields))
            indices[owner].append(len(ordered));ordered.append(row)
    return ordered,indices
