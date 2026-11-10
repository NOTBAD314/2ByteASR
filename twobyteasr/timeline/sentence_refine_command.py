"""Commit validated refinement ranges in one transaction and one undo step."""

from __future__ import annotations

import copy
import uuid

from PySide6.QtGui import QUndoCommand

from .studio_commands import _commit_mutation
from .studio_caption_timeline import caption_replacement_receipts, KEY
from ..projects.studio_runtime_state import DirtyDomain, state_for


class RefineCuesCommand(QUndoCommand):
    def __init__(self, project, replacements, changed=None):
        super().__init__("AI 断句")
        self.project = project
        self.changed = changed
        self.splices = []
        self.before_receipts = {}
        self.after_receipts = {}
        from types import SimpleNamespace
        from ..subtitle_rules import subtitle_translation as translation
        self.translations_before = translation.snapshot(project)
        shadow = SimpleNamespace(generation_metadata=copy.deepcopy(project.generation_metadata),
                                 cues=list(project.cues))
        delta = 0
        after_ids = [cue.id for cue in project.cues]
        for index, count, inserted in sorted(replacements):
            before = copy.deepcopy(project.cues[index:index + count])
            after = copy.deepcopy(inserted)
            for cue in after:
                cue.validate()
            # Reuse the editor's translation merge/split snapshots. Reflow
            # first joins the exact source range, then divides it at the new
            # edges. Translation provenance and estimates stay inspectable.
            parent = copy.deepcopy(before[0])
            if len(before) > 1:
                parent.text = ''.join(cue.text for cue in before)
                parent.end_ms = before[-1].end_ms
                _, metadata = translation.merged_snapshot(shadow, before, parent)
                shadow.generation_metadata.update({key: value for key, value in metadata.items() if value is not None})
                shadow.cues = [cue for cue in shadow.cues if cue.id not in {item.id for item in before}] + [parent]
            for position, cue in enumerate(after):
                tail = copy.deepcopy(cue)
                if position+1 < len(after):
                    tail.id = 'refine-tail-' + uuid.uuid4().hex
                    tail.text = ''.join(item.text for item in after[position+1:])
                    tail.start_ms = after[position+1].start_ms
                    tail.end_ms = after[-1].end_ms
                    _, metadata = translation.split_snapshot(shadow, parent, cue, tail)
                else:
                    metadata = translation.snapshot(shadow)
                    if parent.id != cue.id:
                        records = (metadata.get(translation.RECORDS_KEY) or {}).get('records', {})
                        if parent.id in records:
                            records[cue.id] = records.pop(parent.id)
                        view = metadata.get(translation.RENDER_KEY) or {}
                        if parent.id in view:
                            view[cue.id] = view.pop(parent.id)
                shadow.generation_metadata.update({key: value for key, value in metadata.items() if value is not None})
                shadow.cues = [item for item in shadow.cues if item.id != parent.id] + [cue]
                if position+1 < len(after):
                    shadow.cues.append(tail)
                    parent = tail
            self.splices.append((index, index + delta, before, after))
            delta += len(after) - count
            old, new = caption_replacement_receipts(project, before, after)
            self.before_receipts.update(old or {})
            self.after_receipts.update(new or {})
        self.translations_after = translation.snapshot(shadow)
        for index, _after_index, before, after in reversed(self.splices):
            after_ids[index:index + len(before)] = [cue.id for cue in after]
        if len(after_ids) != len(set(after_ids)):
            raise ValueError("AI 断句写回存在重复字幕 ID")
        self.ids = {cue.id for _, _, before, after in self.splices for cue in (*before, *after)}

    def _apply(self, reverse=False):
        state = state_for(self.project)
        selected = state.selected_cue_id
        for _before_index, _after_index, before, after in self.splices:
            removed, inserted = (after, before) if reverse else (before, after)
            original = next((cue for cue in removed if cue.id == selected), None)
            if original is not None and inserted:
                selected = min(inserted, key=lambda cue: abs(cue.start_ms-original.start_ms)).id
                break

        def mutate():
            from ..subtitle_rules.subtitle_translation import restore_snapshot
            restore_snapshot(self.project, self.translations_before if reverse else self.translations_after)
            for before_index, after_index, before, after in reversed(self.splices):
                index, removed, inserted = (after_index, after, before) if reverse else (before_index, before, after)
                self.project.cues[index:index + len(removed)] = copy.deepcopy(inserted)
            receipts = self.before_receipts if reverse else self.after_receipts
            if receipts:
                instances = self.project.studio_state[KEY].setdefault('instances', {})
                for key, value in receipts.items():
                    if value is None:
                        instances.pop(key, None)
                    else:
                        instances[key] = copy.deepcopy(value)

        _commit_mutation(self.project, action_id=self.text(),
            dirty=DirtyDomain.CUE_MODEL | DirtyDomain.CUE_CONTENT | DirtyDomain.CUE_TIMING
                | DirtyDomain.TIMELINE_INDEX | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.NATIVE_SUBTITLE
                | DirtyDomain.QC | DirtyDomain.AUTOSAVE | DirtyDomain.PROJECT_METADATA,
            cue_ids=self.ids, mutate=mutate, changed=self.changed, selection_after=selected,
            snapshot_cues=True, sync_caption_words=False,
            generation_metadata_keys=('translations', 'translation_records'))

    def redo(self):
        self._apply()

    def undo(self):
        self._apply(True)
