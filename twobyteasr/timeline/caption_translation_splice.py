"""Keep translation records and their sentence groups through structural edits."""
from copy import deepcopy
from ..subtitle_rules import subtitle_translation as translation
from ..caption_style.text_marks import layer_marks


class TranslationSplice:
    def __init__(self, project, before, after):
        self.ids = {cue.id for cue in before+after}
        metadata = project.generation_metadata
        container, _ = translation._migrated_container(metadata, project.cues)
        records = (container or {}).get('records', {})
        self.before_container_present = 'translation_records' in metadata
        self.before_view_present = 'translations' in metadata
        self.before = {key: deepcopy(records.get(key)) for key in self.ids}
        self.before_view = {key: metadata.get('translations', {}).get(key) for key in self.ids}
        self.after = deepcopy(self.before)
        self.after_view = deepcopy(self.before_view)
        self.template = deepcopy(container or {'version': 1, 'records': {}})
        if self.before_container_present: self.template['records'] = {}
        for key in self.ids:
            self.after_view[key] = None
        source = [(cue, self.before.get(cue.id)) for cue in before if self.before.get(cue.id)]
        if len(before) == 1 and len(after) > 1 and source:
            parent, record = source[0]
            from ..subtitle_rules.translation_split import split_translation_text
            from ..caption_style.text_marks import remap_marks
            pieces = split_translation_text(after[0].text, after[1].text, record['text'], record.get('target', translation.DEFAULT_TARGET))
            group = deepcopy(parent.appearance_override.get('translation_group') or
                {'id': parent.id, 'original_translation': record['text'], 'original_source': parent.text,
                 'original_marks': deepcopy(layer_marks(parent, 'translation'))})
            group['review'] = 'estimated_translation_split' if pieces else 'split_needs_translation_alignment'
            for index, cue in enumerate(after):
                cue.appearance_override['translation_group'] = deepcopy(group)
                linked = deepcopy(record)
                value = pieces[index] if pieces else record['text']
                linked.update(text=value, group_id=group['id'], split_estimate=True)
                linked['split_from'] = {'cue_id':parent.id, 'source_text':parent.text, 'translation':record['text']}
                cue.appearance_override.setdefault('translation', {})['text_marks'] = remap_marks(
                    record['text'], value, layer_marks(parent, 'translation'))
                self.after[cue.id] = linked
                self.after_view[cue.id] = value
        elif len(before) > 1 and len(after) == 1 and source:
            cue = after[0]
            texts, marks, groups, offset = [], [], set(), 0
            for parent, record in sorted(source, key=lambda item: (item[0].start_ms, item[0].id)):
                group = parent.appearance_override.get('translation_group', {}).get('id')
                groups.add(group or parent.id)
                value = str(record.get('text') or '')
                if texts: offset += 1
                marks.extend(dict(m, start=m['start']+offset, end=m['end']+offset)
                             for m in layer_marks(parent, 'translation'))
                texts.append(value); offset += len(value)
            value = '\n'.join(texts)
            parent_group = before[0].appearance_override.get('translation_group', {})
            if parent_group and all(record.get('group_id') == parent_group['id'] and record.get('split_estimate') for _,record in source) and all(item.appearance_override.get('translation_group', {}).get('id') == parent_group['id'] for item in before) and translation.normalize_source(cue.text) == translation.normalize_source(parent_group.get('original_source')):
                value = parent_group['original_translation']
                marks = deepcopy(parent_group.get('original_marks', []))
            record = deepcopy(source[0][1]); record['text'] = value
            record['structural_parents'] = [item.id for item, _ in source]
            cue.appearance_override.pop('translation_group', None)
            cue.appearance_override.setdefault('translation', {})['text_marks'] = marks
            self.after[cue.id], self.after_view[cue.id] = record, value
        else:
            for cue in after:
                self.after_view[cue.id] = self.before_view.get(cue.id)
        self.active = any(value is not None for value in self.before.values())

    def follow(self, cues, state):
        """Move the estimated translation marks onto the texts the records hold.

        2026-10-24 caption-marks port: in the daily line a split or merge keeps its
        records through ``split_snapshot`` / ``merged_snapshot`` (statuses, history,
        merge-back); this class then only carries the marks. ``state`` is that
        snapshot's after side."""
        from ..caption_style.text_marks import remap_marks
        records = ((state or {}).get(translation.RECORDS_KEY) or {}).get('records', {})
        for cue in cues:
            layer = cue.appearance_override.get('translation')
            if cue.id not in self.ids or not isinstance(layer, dict) or not layer.get('text_marks'):
                continue
            estimated = self.after_view.get(cue.id)
            actual = str((records.get(cue.id) or {}).get('text') or '')
            if estimated is not None and estimated != actual:
                layer['text_marks'] = remap_marks(estimated, actual, layer['text_marks'])

    def apply(self, project, forward):
        if not self.active: return
        meta = project.generation_metadata
        records = meta.setdefault('translation_records', deepcopy(self.template)).setdefault('records', {})
        view = meta.setdefault('translations', {})
        for key, value in (self.after if forward else self.before).items():
            if value is None: records.pop(key, None)
            else: records[key] = deepcopy(value)
        for key, value in (self.after_view if forward else self.before_view).items():
            if value is None: view.pop(key, None)
            else: view[key] = value
        if not forward and not self.before_container_present:
            meta.pop('translation_records', None)
        if not forward and not self.before_view_present and not view:
            meta.pop('translations', None)  # undo restores the metadata exactly (2026-10-24 port)
