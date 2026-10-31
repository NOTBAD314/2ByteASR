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
        for cue in removed:
            self._translations.after[cue.id] = None
        for cue_id, record in plan.translation_records.items():
            self._translations.ids.add(cue_id)
            self._translations.before[cue_id] = None
            self._translations.before_view[cue_id] = None
            self._translations.after[cue_id] = copy.deepcopy(record)
            self._translations.after_view[cue_id] = record['text']
        self._translations.active = self._translations.active or bool(plan.translation_records)
        self._acceptance_before = copy.deepcopy(project.generation_metadata.get('transcript_acceptance'))
        self._speaker_names_before = copy.deepcopy(project.generation_metadata.get('speaker_names'))
        self._recovery_metadata_before = {key:copy.deepcopy(project.generation_metadata.get(key))
            for key in ('speaker_recovery','asr_cue_states','superseded_asr_evidence')}
        self._evidence = ({key: copy.deepcopy(project.asr_evidence.get(key)) for key in plan.evidence},
                          copy.deepcopy(plan.evidence))
        from .studio_caption_timeline import KEY, independent_captions
        self._caption_key = KEY
        self._caption_state_present = KEY in project.studio_state
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
        extra_ids = {s.id for s in self.plan.extra_speakers}
        if forward:
            known = {s.id for s in self.project.speakers}
            self.project.speakers.extend(copy.deepcopy([s for s in self.plan.extra_speakers if s.id not in known]))
        elif extra_ids:
            self.project.speakers[:] = [s for s in self.project.speakers if s.id not in extra_ids]
            # validate/save materializes the roster's display names. Undo
            # removes those entries with the identities that introduced them.
            if self._speaker_names_before is None:
                self.project.generation_metadata.pop('speaker_names', None)
            else:
                self.project.generation_metadata['speaker_names'] = copy.deepcopy(self._speaker_names_before)
        if forward and self.plan.acceptance:
            from ..recognition.language_recovery_project import merge_acceptance
            merge_acceptance(self.project, self.plan)
        elif not forward:
            if self._acceptance_before is None:
                self.project.generation_metadata.pop('transcript_acceptance', None)
            else:
                self.project.generation_metadata['transcript_acceptance'] = copy.deepcopy(self._acceptance_before)
                from ..recognition.language_recovery_project import persist_selection_state
                persist_selection_state(self.project.generation_metadata['transcript_acceptance'])
            for key,value in self._recovery_metadata_before.items():
                if value is None:self.project.generation_metadata.pop(key,None)
                else:self.project.generation_metadata[key]=copy.deepcopy(value)
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
        if not forward and not self._caption_state_present:
            state = self.project.studio_state.get(self._caption_key) or {}
            if not state.get('instances') and not state.get('source_archive'):
                self.project.studio_state.pop(self._caption_key, None)
