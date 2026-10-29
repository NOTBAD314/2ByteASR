"""Undoable replacement of one recognized range (2026-10-25, 只重新识别这一段).

``recognition.range_recognition.splice_range`` says what changes; this
command applies it as one undo step: the caption list, the new captions'
evidence rows, caption receipts and archive rows, and the translations shown
for the replaced captions (cleared: they belong to the old text). Undo puts
every one of them back exactly.
"""

from __future__ import annotations

import copy

from .studio_commands import MutationOrigin, ReplaceCuesCommand


class ReplaceRangeCuesCommand(ReplaceCuesCommand):
    def __init__(self, project, plan, entry=None, changed=None, text="只重新识别这一段字幕") -> None:
        selection = plan.inserted_ids[0] if plan.inserted_ids else ""
        super().__init__(project, plan.cues, text, changed, MutationOrigin.ASR, selection_after=selection)
        removed = [cue for cue in self.before if cue.id in set(plan.removed_ids)]
        # A re-recognized line gets no estimated piece of the old translation.
        from .caption_translation_splice import TranslationSplice
        self._translations = TranslationSplice(project, removed, [])
        self._evidence = ({key: copy.deepcopy(project.asr_evidence.get(key)) for key in plan.evidence},
                          copy.deepcopy(plan.evidence))
        from .studio_caption_timeline import KEY, independent_captions
        self._caption_key = KEY
        self._archive_rows = copy.deepcopy(plan.archive)
        self._archive_ids = {str(row.get("id")) for row in plan.archive}
        self._archive_present = "source_archive" in (project.studio_state.get(KEY) or {})
        if independent_captions(project):
            state = project.studio_state.setdefault(KEY, {"version": 1, "instances": {}})
            instances = state.setdefault("instances", {})
            keys = [*plan.removed_ids, *plan.inserted_ids]
            before = {key: copy.deepcopy(instances.get(key)) for key in keys}
            after = {key: None for key in plan.removed_ids}
            after.update({key: copy.deepcopy(plan.receipts.get(key)) for key in plan.inserted_ids})
            self._merge_caption_states = (before, after)
        self._entry = copy.deepcopy(entry) if entry is not None else None
        self.plan = plan

    def _mutate(self, cues) -> None:
        super()._mutate(cues)
        forward = cues is self.after
        for key, value in self._evidence[1 if forward else 0].items():
            if value is None:
                self.project.asr_evidence.pop(key, None)
            else:
                self.project.asr_evidence[key] = copy.deepcopy(value)
        if self._archive_rows:
            state = self.project.studio_state.setdefault(self._caption_key, {"version": 1, "instances": {}})
            archive = [row for row in state.get("source_archive") or []
                       if not (isinstance(row, dict) and str(row.get("id")) in self._archive_ids)]
            if forward:
                archive.extend(copy.deepcopy(self._archive_rows))
            if archive or forward or self._archive_present:
                state["source_archive"] = archive
            else:
                state.pop("source_archive", None)
        if self._entry is not None:
            from ..recognition.range_recognition import HISTORY_KEY
            history = [row for row in self.project.generation_metadata.get(HISTORY_KEY) or []
                       if row != self._entry]
            if forward:
                history.append(copy.deepcopy(self._entry))
            if history:
                self.project.generation_metadata[HISTORY_KEY] = history
            else:
                self.project.generation_metadata.pop(HISTORY_KEY, None)
