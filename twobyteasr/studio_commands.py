"""QUndoStack commands for all mutable Subtitle Studio project operations."""

from __future__ import annotations

import bisect
import copy
import uuid
from enum import Enum
from typing import Callable, Iterable, Mapping

from PySide6.QtGui import QUndoCommand

from .studio_project import StudioCue, StudioSpeaker, SubtitleProject
from .studio_runtime_state import DirtyDomain, notify_legacy_if_unbound, state_for


ChangedCallback = Callable[[], None]


def _field_domains(fields: Iterable[str]) -> DirtyDomain:
    names = {str(item) for item in fields}
    dirty = DirtyDomain.AUTOSAVE
    if names & {"start_ms", "end_ms", "speaker_id"}:
        dirty |= (
            DirtyDomain.CUE_TIMING
            | DirtyDomain.TIMELINE_INDEX
            | DirtyDomain.TIMELINE_PIXELS
            | DirtyDomain.NATIVE_SUBTITLE
            | DirtyDomain.QC
        )
    if names & {"text", "original_text", "raw_ass_override"}:
        dirty |= (
            DirtyDomain.CUE_CONTENT
            | DirtyDomain.TIMELINE_PIXELS
            | DirtyDomain.NATIVE_SUBTITLE
            | DirtyDomain.ADVANCED_PREVIEW
            | DirtyDomain.QC
        )
    if names & {
        "style_id", "base_preset_id", "effect_id", "appearance_override",
        "appearance_generation", "transform",
    }:
        dirty |= (
            DirtyDomain.CUE_STYLE
            | DirtyDomain.TIMELINE_PIXELS
            | DirtyDomain.NATIVE_SUBTITLE
            | DirtyDomain.ADVANCED_PREVIEW
            | DirtyDomain.TRANSFORM
        )
    return dirty


def _commit_mutation(
    project: SubtitleProject,
    *,
    action_id: str,
    dirty: DirtyDomain,
    cue_ids: Iterable[str],
    mutate: Callable[[], None],
    changed: ChangedCallback | None,
    selection_after: str | None = None,
    snapshot_cues: bool = True,
) -> None:
    state = state_for(project)
    target_ids = tuple(str(item) for item in cue_ids if str(item))
    target_id_set = set(target_ids)
    before_ranges = {
        cue.id: (int(cue.start_ms), int(cue.end_ms))
        for cue in project.cues
        if cue.id in target_id_set
    }
    with state.transaction(
        project,
        action_id=action_id,
        dirty=dirty,
        affected_cue_ids=target_ids,
        selection_after=selection_after,
        snapshot_cues=snapshot_cues,
    ) as transaction:
        mutate()
        after_ranges = {
            cue.id: (int(cue.start_ms), int(cue.end_ms))
            for cue in project.cues
            if cue.id in target_id_set
        }
        transaction.mark_dirty(
            DirtyDomain.NONE,
            ranges=(*before_ranges.values(), *after_ranges.values()),
        )
    notify_legacy_if_unbound(project, changed)


class MutationOrigin(str, Enum):
    USER_EDIT = "user_edit"
    SEARCH_REPLACE = "search_replace"
    MODEL_ADOPTION = "model_adoption"
    SAFE_FIX = "safe_fix"
    ASR = "asr"
    LLM = "llm"
    IMPORT = "import"
    SYSTEM = "system"


# Only human text edits feed glossary learning; AI/SAFE_FIX/IMPORT/SYSTEM must
# never be recorded as manual corrections.
LEARNABLE_TEXT_ORIGINS = {MutationOrigin.USER_EDIT, MutationOrigin.SEARCH_REPLACE}

# (command, undone) -> None. Called after a learnable text mutation was really
# applied (redo) or reverted (undo), so learning evidence can follow undo/redo.
TextLearningObserver = Callable[[QUndoCommand, bool], None]


def cue_by_id(project: SubtitleProject, cue_id: str) -> StudioCue:
    """按 id 取 cue；剪辑模式下派生 id（"源id#段id"）解析回源 cue。

    命令因此始终作用于源数据（project.cues 全集），投影在事务重建时
    刷新——生成/返回剪辑不再触碰字幕，人工编辑天然跨视图保留。
    """
    from .studio_edit_sequence import source_cue_id_of

    if project.render_settings.get('_cue_domain') == 'timeline':
        for cue in project.cues:
            if cue.id == cue_id:
                return cue
    resolved = source_cue_id_of(str(cue_id))
    for cue in project.cues:
        if cue.id == resolved:
            return cue
    raise KeyError(f"cue not found: {cue_id}")


class SetCueFieldsCommand(QUndoCommand):
    def __init__(
        self,
        project: SubtitleProject,
        cue_id: str,
        changes: Mapping[str, object],
        text: str,
        changed: ChangedCallback | None = None,
        origin: MutationOrigin = MutationOrigin.USER_EDIT,
        learning_observer: TextLearningObserver | None = None,
        learning_meta: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(text)
        self.project = project
        self.cue_id = str(cue_id)
        from .studio_edit_sequence import map_timing_to_source, source_cue_id_of
        self.source_cue_id = source_cue_id_of(self.cue_id)
        cue = cue_by_id(project, self.cue_id)
        # 剪辑模式下 UI 提交的是序列域时间；映射回源域（裁边 cue 无法
        # 无损映射时忽略计时改动，其余字段照常）。identity 序列零变化。
        if {"start_ms", "end_ms"} & set(changes):
            start = int(changes.get("start_ms", cue.start_ms))
            end = int(changes.get("end_ms", cue.end_ms))
            mapped = map_timing_to_source(project, cue, start, end)
            if mapped is None:
                changes = {k: v for k, v in changes.items() if k not in {"start_ms", "end_ms"}}
            else:
                changes = dict(changes)
                if "start_ms" in changes:
                    changes["start_ms"] = mapped[0]
                if "end_ms" in changes:
                    changes["end_ms"] = mapped[1]
        self.before = {key: copy.deepcopy(getattr(cue, key)) for key in changes}
        self.after = {key: copy.deepcopy(value) for key, value in changes.items()}
        self.changed = changed
        self.origin = MutationOrigin(origin)
        self.learning_observer = learning_observer
        self.learning_meta = dict(learning_meta) if learning_meta else None
        self._manual_before = project.studio_state.get('manual_caption_text', {}).get(self.source_cue_id)

    def _apply(self, values: Mapping[str, object]) -> None:
        text_applied = False

        def mutate() -> None:
            nonlocal text_applied
            cue = cue_by_id(self.project, self.cue_id)
            if 'text' in values:
                manual = self.project.studio_state.setdefault('manual_caption_text', {})
                if self.origin in {MutationOrigin.ASR, MutationOrigin.LLM} and self.source_cue_id in manual:
                    return
                if self.origin in {MutationOrigin.USER_EDIT, MutationOrigin.MODEL_ADOPTION, MutationOrigin.SEARCH_REPLACE}:
                    if values is self.before:
                        if self._manual_before is None: manual.pop(self.source_cue_id, None)
                        else: manual[self.source_cue_id] = self._manual_before
                    else: manual[self.source_cue_id] = str(values['text'])
                text_applied = True
            appearance_changed = bool(
                set(values)
                & {"style_id", "base_preset_id", "effect_id", "appearance_override"}
            )
            for key, value in values.items():
                if key not in StudioCue.__dataclass_fields__:
                    raise AttributeError(key)
                setattr(cue, key, copy.deepcopy(value))
            if appearance_changed:
                cue.appearance_generation = int(cue.appearance_generation) + 1

        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=_field_domains(values),
            cue_ids=(self.source_cue_id,),
            mutate=mutate,
            changed=self.changed,
        )
        if (
            text_applied
            and 'text' in values
            and self.learning_observer is not None
            and self.origin in LEARNABLE_TEXT_ORIGINS
        ):
            try:
                self.learning_observer(self, values is self.before)
            except Exception:
                pass

    def redo(self) -> None:
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetCueFieldsCommand):
            return False
        if (
            self.cue_id != other.cue_id
            or set(self.after) != set(other.after)
            or self.origin != other.origin
        ):
            return False
        if set(self.after) != {"text"}:
            return False
        self.after = copy.deepcopy(other.after)
        return True

    def id(self) -> int:
        return 0x2B17 if set(self.after) == {"text"} else -1


class AdoptReviewCandidateCommand(SetCueFieldsCommand):
    """Adopt candidate text and resolve the review issue as one Undo step."""

    def __init__(
        self,
        project: SubtitleProject,
        cue_id: str,
        value: str,
        resolved_at: str,
        changed: ChangedCallback | None = None,
        *,
        command_text: str = "采用审核候选",
        origin: MutationOrigin = MutationOrigin.MODEL_ADOPTION,
        text_applied: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            project,
            cue_id,
            {"text": str(value)},
            command_text,
            changed,
            origin,
        )
        self._resolved_at = str(resolved_at)
        self._text_applied = text_applied
        statuses = project.studio_state.get("cue_statuses", {})
        confirmations = project.studio_state.get("review_confirmations", {})
        self._before_status = statuses.get(str(cue_id)) if isinstance(statuses, dict) else None
        self._had_status = isinstance(statuses, dict) and str(cue_id) in statuses
        self._before_confirmation = confirmations.get(str(cue_id)) if isinstance(confirmations, dict) else None
        self._had_confirmation = isinstance(confirmations, dict) and str(cue_id) in confirmations

    def _set_resolved(self) -> None:
        statuses = self.project.studio_state.setdefault("cue_statuses", {})
        confirmations = self.project.studio_state.setdefault("review_confirmations", {})
        if isinstance(statuses, dict) and isinstance(confirmations, dict):
            statuses[self.cue_id] = "done"
            confirmations[self.cue_id] = self._resolved_at

    def _restore_review_state(self) -> None:
        statuses = self.project.studio_state.setdefault("cue_statuses", {})
        confirmations = self.project.studio_state.setdefault("review_confirmations", {})
        if isinstance(statuses, dict):
            if self._had_status:
                statuses[self.cue_id] = self._before_status
            else:
                statuses.pop(self.cue_id, None)
        if isinstance(confirmations, dict):
            if self._had_confirmation:
                confirmations[self.cue_id] = self._before_confirmation
            else:
                confirmations.pop(self.cue_id, None)

    def redo(self) -> None:
        self._set_resolved()
        super().redo()
        if self._text_applied is not None:
            self._text_applied(str(self.after["text"]))

    def undo(self) -> None:
        self._restore_review_state()
        super().undo()
        if self._text_applied is not None:
            self._text_applied(str(self.before["text"]))

    def id(self) -> int:
        return -1


class SetCueTranslationCommand(QUndoCommand):
    """Edit optional bilingual text without changing the project schema."""

    def __init__(
        self,
        project: SubtitleProject,
        cue_id: str,
        value: str,
        changed: ChangedCallback | None = None,
    ) -> None:
        super().__init__("Edit translation")
        self.project = project
        self.cue_id = str(cue_id)
        translations = project.generation_metadata.get("translations", {})
        if not isinstance(translations, dict):
            translations = {}
        self.before = str(translations.get(self.cue_id, "") or "")
        self.after = str(value or "")
        self.changed = changed

    def _apply(self, value: str) -> None:
        def mutate() -> None:
            translations = self.project.generation_metadata.setdefault("translations", {})
            if not isinstance(translations, dict):
                translations = {}
                self.project.generation_metadata["translations"] = translations
            if value:
                translations[self.cue_id] = value
            else:
                translations.pop(self.cue_id, None)

        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=(
                DirtyDomain.CUE_CONTENT
                | DirtyDomain.TIMELINE_PIXELS
                | DirtyDomain.NATIVE_SUBTITLE
                | DirtyDomain.QC
                | DirtyDomain.AUTOSAVE
            ),
            cue_ids=(self.cue_id,),
            mutate=mutate,
            changed=self.changed,
        )

    def redo(self) -> None:
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetCueTranslationCommand) or self.cue_id != other.cue_id:
            return False
        self.after = other.after
        return True

    def id(self) -> int:
        return 0x2B18


class ReplaceCuesCommand(QUndoCommand):
    def __init__(
        self,
        project: SubtitleProject,
        replacement: Iterable[StudioCue],
        text: str,
        changed: ChangedCallback | None = None,
        origin: MutationOrigin = MutationOrigin.SYSTEM,
    ) -> None:
        super().__init__(text)
        self.project = project
        self.before = copy.deepcopy(project.cues)
        self.after = copy.deepcopy(list(replacement))
        self.changed = changed
        self.origin = MutationOrigin(origin)

    def _apply(self, cues: list[StudioCue]) -> None:
        before = {cue.id: cue for cue in self.project.cues}
        after = {cue.id: cue for cue in cues}
        affected = {
            cue_id for cue_id in set(before) | set(after)
            if before.get(cue_id) != after.get(cue_id)
        }
        state = state_for(self.project)
        selection_after = state.selected_cue_id
        if selection_after and selection_after not in after:
            before_order = [cue.id for cue in self.project.cues]
            old_index = (
                before_order.index(selection_after)
                if selection_after in before_order
                else 0
            )
            replacement_order = [cue.id for cue in cues]
            selection_after = (
                replacement_order[min(old_index, len(replacement_order) - 1)]
                if replacement_order
                else ""
            )
        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=(
                DirtyDomain.CUE_MODEL
                | DirtyDomain.CUE_CONTENT
                | DirtyDomain.CUE_TIMING
                | DirtyDomain.TIMELINE_INDEX
                | DirtyDomain.TIMELINE_PIXELS
                | DirtyDomain.NATIVE_SUBTITLE
                | DirtyDomain.QC
                | DirtyDomain.AUTOSAVE
            ),
            cue_ids=affected,
            mutate=lambda: setattr(self.project, "cues", copy.deepcopy(cues)),
            changed=self.changed,
            selection_after=selection_after,
        )

    def redo(self) -> None:
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)


class SpliceCuesCommand(QUndoCommand):
    """O(affected) structural cue edit that splices a contiguous list range.

    The ReplaceCuesCommand path deep-copies the entire cue list three times
    (helper replacement, ``__init__`` before/after, ``_apply``) plus a fourth
    full-list snapshot inside the state transaction — measured 60-110ms of
    GUI-thread time per razor/merge click on a ~1000-cue project. This command
    stores private copies of only the removed and inserted cues. Snapshot
    isolation still holds: the project never shares cue objects with command
    storage, and every inserted cue is validated (id uniqueness + timing)
    before the splice so the no-snapshot transaction cannot fail after the
    list has been mutated.
    """

    def __init__(
        self,
        project: SubtitleProject,
        index: int,
        removed_count: int,
        inserted: Iterable[StudioCue],
        text: str,
        changed: ChangedCallback | None = None,
        origin: MutationOrigin = MutationOrigin.SYSTEM,
    ) -> None:
        super().__init__(text)
        self.project = project
        self.index = int(index)
        self.removed_count = int(removed_count)
        self._before_cues = [
            copy.deepcopy(cue)
            for cue in project.cues[self.index:self.index + self.removed_count]
        ]
        self._after_cues = [copy.deepcopy(cue) for cue in inserted]
        self.changed = changed
        self.origin = MutationOrigin(origin)
        for cue in self._before_cues + self._after_cues:
            cue.validate()
        surviving_ids = {
            cue.id for position, cue in enumerate(project.cues)
            if not self.index <= position < self.index + self.removed_count
        }
        inserted_ids = [cue.id for cue in self._after_cues]
        duplicates = surviving_ids.intersection(inserted_ids)
        if len(inserted_ids) != len(set(inserted_ids)):
            duplicates.update(
                {cue_id for cue_id in inserted_ids if inserted_ids.count(cue_id) > 1}
            )
        if duplicates:
            raise ValueError(f"duplicate cue id in splice: {', '.join(sorted(duplicates))}")

    def _apply(self, replacing_count: int, inserted_source: list[StudioCue]) -> None:
        start = self.index
        inserted = [copy.deepcopy(cue) for cue in inserted_source]
        after_ids = {cue.id for cue in inserted}
        removed_ids = {cue.id for cue in self._before_cues}
        affected = removed_ids | after_ids
        state = state_for(self.project)
        selection_after = state.selected_cue_id
        if selection_after and selection_after not in after_ids:
            if selection_after in removed_ids and inserted:
                # The selected cue was split/merged away: keep the user on
                # the new result so ripple merges and repeated razors keep
                # their working context.
                selection_after = inserted[0].id
            else:
                before_order = [cue.id for cue in self.project.cues]
                if selection_after in before_order:
                    old_index = before_order.index(selection_after)
                    following = [
                        cue.id for position, cue in enumerate(self.project.cues)
                        if not start <= position < start + replacing_count
                    ]
                    following[start:start] = [cue.id for cue in inserted]
                    selection_after = (
                        following[min(old_index, len(following) - 1)]
                        if following
                        else ""
                    )
                else:
                    selection_after = next(iter(after_ids), "")

        def mutate() -> None:
            self.project.cues[start:start + replacing_count] = inserted

        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=(
                DirtyDomain.CUE_MODEL
                | DirtyDomain.CUE_CONTENT
                | DirtyDomain.CUE_TIMING
                | DirtyDomain.TIMELINE_INDEX
                | DirtyDomain.TIMELINE_PIXELS
                | DirtyDomain.NATIVE_SUBTITLE
                | DirtyDomain.QC
                | DirtyDomain.AUTOSAVE
            ),
            cue_ids=affected,
            mutate=mutate,
            changed=self.changed,
            selection_after=selection_after,
            snapshot_cues=False,
        )

    def redo(self) -> None:
        self._apply(self.removed_count, self._after_cues)

    def undo(self) -> None:
        self._apply(len(self._after_cues), self._before_cues)


def _splice_split(
    project: SubtitleProject,
    cue: StudioCue,
    split_ms: int,
    left_text: str,
    right_text: str,
    changed: ChangedCallback | None,
) -> SpliceCuesCommand:
    left = copy.deepcopy(cue)
    right = copy.deepcopy(cue)
    left.end_ms = int(split_ms)
    left.text = str(left_text)
    right.id = f"{cue.id}-split-{uuid.uuid4().hex[:8]}"
    right.start_ms = int(split_ms)
    right.text = str(right_text)
    index = next(
        position for position, item in enumerate(project.cues) if item.id == cue.id
    )
    return SpliceCuesCommand(
        project, index, 1, (left, right), "Split subtitle", changed
    )


def _splice_merge_adjacent(
    project: SubtitleProject,
    first: StudioCue,
    second: StudioCue,
    changed: ChangedCallback | None,
) -> SpliceCuesCommand | None:
    """Merge two cues adjacent in the list; ``None`` falls back to full replace."""
    positions = {
        cue.id: position for position, cue in enumerate(project.cues)
    }
    first_index = positions.get(first.id)
    second_index = positions.get(second.id)
    if first_index is None or second_index is None:
        return None
    low, high = sorted((first_index, second_index))
    if high - low != 1:
        return None
    if (first.start_ms, first.end_ms, first.id) <= (second.start_ms, second.end_ms, second.id):
        earlier, later = first, second
    else:
        earlier, later = second, first
    merged = copy.deepcopy(earlier)
    merged.start_ms = min(first.start_ms, second.start_ms)
    merged.end_ms = max(first.end_ms, second.end_ms)
    merged.text = earlier.text + later.text
    merged.original_text = earlier.original_text + later.original_text
    merged.evidence_refs = list(
        dict.fromkeys([*first.evidence_refs, *second.evidence_refs])
    )
    return SpliceCuesCommand(
        project, low, 2, (merged,), "Merge subtitles", changed
    )


def _splice_delete(
    project: SubtitleProject,
    cue_ids: Iterable[str],
    changed: ChangedCallback | None,
) -> SpliceCuesCommand | None:
    """Delete a contiguous run of cues; ``None`` falls back to full replace."""
    targets = set(str(item) for item in cue_ids)
    positions = sorted(
        position for position, cue in enumerate(project.cues) if cue.id in targets
    )
    if not positions or positions[-1] - positions[0] + 1 != len(positions):
        return None
    return SpliceCuesCommand(
        project, positions[0], len(positions), (), "Delete subtitles", changed
    )


def _splice_add(
    project: SubtitleProject,
    cue: StudioCue,
    changed: ChangedCallback | None,
) -> SpliceCuesCommand | None:
    """Insert one cue keeping the list chronologically sorted; ``None`` falls back."""

    def key(item: StudioCue) -> tuple[int, int, str]:
        return (item.start_ms, item.end_ms, item.id)

    existing_keys = [key(item) for item in project.cues]
    if existing_keys != sorted(existing_keys):
        return None
    index = bisect.bisect_right(existing_keys, key(cue))
    return SpliceCuesCommand(project, index, 0, (cue,), "Add subtitle", changed)


class ApplySafeFixesCommand(ReplaceCuesCommand):
    """Apply a prepared QC safe-fix plan as exactly one undo stack entry."""

    def __init__(
        self,
        project: SubtitleProject,
        plan,
        changed: ChangedCallback | None = None,
    ) -> None:
        total = int(getattr(plan, "total", 0) or 0)
        if total <= 0:
            raise ValueError("safe-fix plan does not contain changes")
        self.plan_counts = dict(getattr(plan, "counts", {}) or {})
        super().__init__(
            project,
            getattr(plan, "cues"),
            f"Safe Fix {total} items",
            changed,
            MutationOrigin.SAFE_FIX,
        )


def _validate_speaker_references(project: SubtitleProject) -> None:
    speaker_ids = {speaker.id for speaker in project.speakers}
    dangling = sorted({cue.speaker_id for cue in project.cues if cue.speaker_id not in speaker_ids})
    if dangling:
        raise ValueError(f"cue references missing speakers: {', '.join(dangling)}")


class SpeakerStateCommand(QUndoCommand):
    """Atomic snapshot for speaker metadata and all affected cue references."""

    def __init__(
        self,
        project: SubtitleProject,
        speakers: Iterable[StudioSpeaker],
        cues: Iterable[StudioCue],
        text: str,
        changed: ChangedCallback | None = None,
    ) -> None:
        super().__init__(text)
        self.project = project
        self.before_speakers = copy.deepcopy(project.speakers)
        self.before_cues = copy.deepcopy(project.cues)
        self.after_speakers = copy.deepcopy(list(speakers))
        self.after_cues = copy.deepcopy(list(cues))
        self.changed = changed

    def _apply(self, speakers: list[StudioSpeaker], cues: list[StudioCue]) -> None:
        self.project.speakers = copy.deepcopy(speakers)
        self.project.cues = copy.deepcopy(cues)
        self.project.validate()
        _validate_speaker_references(self.project)
        if self.changed:
            self.changed()

    def redo(self) -> None:
        self._apply(self.after_speakers, self.after_cues)

    def undo(self) -> None:
        self._apply(self.before_speakers, self.before_cues)


class RecoverSpeakersCommand(SpeakerStateCommand):
    """Candidate evidence, track selection and cues form one undo transaction."""

    def __init__(self, project, recovered, changed=None):
        super().__init__(project, recovered.speakers, recovered.cues, "从 MOSS 缓存恢复说话人", changed)
        self.before_metadata = copy.deepcopy(project.generation_metadata)
        self.after_metadata = copy.deepcopy(recovered.generation_metadata)
        if not self.before_metadata.get("speaker_recovery"):
            from .speaker_recovery import candidate_snapshot
            source = self.after_metadata["speaker_recovery"]
            self.before_metadata["speaker_recovery"] = candidate_snapshot(
                source["raw_segments"], {cue.speaker_id for cue in project.cues}, source.get("expected_speakers", 0))
        self.before_evidence = copy.deepcopy(project.asr_evidence)
        self.after_evidence = copy.deepcopy(recovered.asr_evidence)
        self.before_order = list(project.studio_state.get("speaker_track_order", []))
        self.after_order = list(recovered.studio_state.get("speaker_track_order", []))
        self.error = ""
        self._committed = False

    def _restore(self, forward):
        backup = (copy.deepcopy(self.project.generation_metadata), copy.deepcopy(self.project.asr_evidence),
                  copy.deepcopy(self.project.studio_state), copy.deepcopy(self.project.speakers), copy.deepcopy(self.project.cues))
        self.error = ""
        try:
            self.project.generation_metadata = copy.deepcopy(self.after_metadata if forward else self.before_metadata)
            self.project.asr_evidence = copy.deepcopy(self.after_evidence if forward else self.before_evidence)
            self.project.studio_state["speaker_track_order"] = list(self.after_order if forward else self.before_order)
            self._apply(self.after_speakers if forward else self.before_speakers,
                        self.after_cues if forward else self.before_cues)
            self._committed = True
        except Exception as exc:
            (self.project.generation_metadata, self.project.asr_evidence, self.project.studio_state,
             self.project.speakers, self.project.cues) = backup
            self.error = f"{type(exc).__name__}: {exc}"
            if not self._committed:
                self.setObsolete(True)
            try:
                if self.changed:
                    self.changed()
            except Exception as refresh_error:
                self.error += f"；回滚后刷新失败：{refresh_error}"

    def redo(self):
        self._restore(True)

    def undo(self):
        self._restore(False)


class SetSpeakerCommand(SpeakerStateCommand):
    def __init__(
        self,
        project: SubtitleProject,
        speaker_id: str,
        changes: Mapping[str, object],
        text: str = "Update speaker",
        changed: ChangedCallback | None = None,
    ) -> None:
        speakers = copy.deepcopy(project.speakers)
        speaker = next((item for item in speakers if item.id == str(speaker_id)), None)
        if speaker is None:
            raise KeyError(f"speaker not found: {speaker_id}")
        allowed = {"name", "color", "style_id", "hidden"}
        for key, value in changes.items():
            if key not in allowed:
                raise AttributeError(key)
            setattr(speaker, key, copy.deepcopy(value))
        speaker.validate()
        super().__init__(project, speakers, project.cues, text, changed)


class SetHostSpeakerCommand(SpeakerStateCommand):
    """设定主讲（唯一）：清除其它 speaker 的 is_host（三十八轮）。"""

    def __init__(
        self,
        project: SubtitleProject,
        speaker_id: str,
        changed: ChangedCallback | None = None,
    ) -> None:
        speakers = copy.deepcopy(project.speakers)
        if not any(item.id == str(speaker_id) for item in speakers):
            raise KeyError(f"speaker not found: {speaker_id}")
        for item in speakers:
            item.is_host = item.id == str(speaker_id)
            item.validate()
        super().__init__(
            project, speakers, project.cues, "Set host speaker", changed
        )


class SetSpeakersVisibilityCommand(SpeakerStateCommand):
    """批量设置说话人显示/隐藏（「仅保留此说话人」等，一步一撤销）。"""

    def __init__(
        self,
        project: SubtitleProject,
        hidden_ids: Iterable[str],
        changed: ChangedCallback | None = None,
    ) -> None:
        hidden = {str(value) for value in hidden_ids}
        speakers = copy.deepcopy(project.speakers)
        for item in speakers:
            item.hidden = item.id in hidden
            item.validate()
        super().__init__(
            project, speakers, project.cues, "Set speaker visibility", changed
        )


class MergeSpeakerCommand(SpeakerStateCommand):
    def __init__(
        self,
        project: SubtitleProject,
        source_id: str,
        target_id: str,
        changed: ChangedCallback | None = None,
    ) -> None:
        source_id, target_id = str(source_id), str(target_id)
        if source_id == target_id:
            raise ValueError("source and target speaker must differ")
        source = next((item for item in project.speakers if item.id == source_id), None)
        target = next((item for item in project.speakers if item.id == target_id), None)
        if source is None or target is None:
            raise KeyError("source or target speaker not found")
        speakers = [copy.deepcopy(item) for item in project.speakers if item.id != source_id]
        cues = copy.deepcopy(project.cues)
        for cue in cues:
            if cue.speaker_id != source_id:
                continue
            cue.speaker_id = target_id
            if cue.style_id == source.style_id:
                cue.style_id = target.style_id
        super().__init__(project, speakers, cues, f"Merge {source_id} into {target_id}", changed)


class AssignSpeakerCommand(SpeakerStateCommand):
    def __init__(
        self,
        project: SubtitleProject,
        cue_ids: Iterable[str],
        target_id: str,
        changed: ChangedCallback | None = None,
    ) -> None:
        target_id = str(target_id)
        if not any(item.id == target_id for item in project.speakers):
            raise KeyError(f"speaker not found: {target_id}")
        selected = {str(item) for item in cue_ids}
        if not selected:
            raise ValueError("at least one cue is required")
        cues = copy.deepcopy(project.cues)
        changed_count = 0
        for cue in cues:
            if cue.id in selected and cue.speaker_id != target_id:
                cue.speaker_id = target_id
                changed_count += 1
        if not changed_count:
            raise ValueError("selected cues already use this speaker")
        super().__init__(project, project.speakers, cues, f"Assign {changed_count} cues to {target_id}", changed)


class SetCuePresentationCommand(QUndoCommand):
    """Atomically apply text/style/effect plus referenced project definitions."""

    def __init__(
        self,
        project: SubtitleProject,
        cue_id: str,
        *,
        cue_changes: Mapping[str, object],
        styles=None,
        effects=None,
        style_recipes=None,
        text: str,
        changed: ChangedCallback | None = None,
        origin: MutationOrigin = MutationOrigin.USER_EDIT,
    ) -> None:
        super().__init__(text)
        self.project = project
        self.cue_id = cue_id
        cue = cue_by_id(project, cue_id)
        self.before_cue = {key: copy.deepcopy(getattr(cue, key)) for key in cue_changes}
        self.after_cue = copy.deepcopy(dict(cue_changes))
        self.before_styles = copy.deepcopy(project.styles)
        self.before_effects = copy.deepcopy(project.effects)
        self.before_style_recipes = copy.deepcopy(project.style_recipes)
        self.after_styles = copy.deepcopy(styles if styles is not None else project.styles)
        self.after_effects = copy.deepcopy(effects if effects is not None else project.effects)
        self.after_style_recipes = copy.deepcopy(
            style_recipes if style_recipes is not None else project.style_recipes
        )
        self.changed = changed
        self.origin = MutationOrigin(origin)

    def _apply(self, cue_values, styles, effects, style_recipes) -> None:
        def mutate() -> None:
            cue = cue_by_id(self.project, self.cue_id)
            appearance_changed = bool(
                set(cue_values)
                & {"style_id", "base_preset_id", "effect_id", "appearance_override"}
            )
            for key, value in cue_values.items():
                setattr(cue, key, copy.deepcopy(value))
            if appearance_changed:
                cue.appearance_generation = int(cue.appearance_generation) + 1
            self.project.styles = copy.deepcopy(styles)
            self.project.effects = copy.deepcopy(effects)
            self.project.style_recipes = copy.deepcopy(style_recipes)

        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=(
                _field_domains(cue_values)
                | DirtyDomain.CUE_STYLE
                | DirtyDomain.NATIVE_SUBTITLE
                | DirtyDomain.ADVANCED_PREVIEW
                | DirtyDomain.TRANSFORM
                | DirtyDomain.AUTOSAVE
            ),
            cue_ids=(self.cue_id,),
            mutate=mutate,
            changed=self.changed,
        )

    def redo(self) -> None:
        self._apply(
            self.after_cue, self.after_styles, self.after_effects,
            self.after_style_recipes,
        )

    def undo(self) -> None:
        self._apply(
            self.before_cue, self.before_styles, self.before_effects,
            self.before_style_recipes,
        )


class SetCuesPresentationCommand(QUndoCommand):
    """Apply one presentation preset to many cues with one refresh and undo step."""

    COMMAND_ID = 0x2209

    def __init__(
        self,
        project: SubtitleProject,
        cue_ids: Iterable[str],
        *,
        style_id: str,
        effect_id: str,
        style_ids: Mapping[str, str] | None = None,
        base_preset_id: str | None = None,
        base_preset_ids: Mapping[str, str] | None = None,
        appearance_override: Mapping[str, object] | None = None,
        appearance_overrides: Mapping[str, Mapping[str, object]] | None = None,
        effect_ids: Mapping[str, str] | None = None,
        styles=None,
        effects=None,
        style_recipes=None,
        # 2026-09-19：应用几何（"同时应用位置与缩放"）时需要按 cue 清理
        # transform 里的几何键，否则旧 \pos/\fscx 逐事件覆盖压住新样式。
        transform_overrides: Mapping[str, Mapping[str, object] | None] | None = None,
        merge_enabled: bool = True,
        text: str,
        changed: ChangedCallback | None = None,
    ) -> None:
        super().__init__(text)
        self.project = project
        selected = {str(cue_id) for cue_id in cue_ids}
        if not selected:
            raise ValueError("at least one cue is required")
        self.before = {
            cue.id: (
                cue.style_id, cue.effect_id, cue.base_preset_id,
                copy.deepcopy(cue.appearance_override),
                copy.deepcopy(dict(cue.transform)) if cue.transform else {},
            )
            for cue in project.cues
            if cue.id in selected
        }
        if len(self.before) != len(selected):
            raise KeyError("one or more cues were not found")
        mapped = dict(style_ids or {})
        mapped_effects = dict(effect_ids or {})
        mapped_presets = dict(base_preset_ids or {})
        mapped_appearance = {
            str(cue_id): copy.deepcopy(dict(value))
            for cue_id, value in dict(appearance_overrides or {}).items()
        }
        mapped_transforms = {
            str(cue_id): (copy.deepcopy(dict(value)) if value else None)
            for cue_id, value in dict(transform_overrides or {}).items()
        }
        self.after = {
            cue_id: (
                str(mapped.get(cue_id, style_id)),
                str(mapped_effects.get(cue_id, effect_id)),
                str(
                    mapped_presets.get(
                        cue_id,
                        base_preset_id
                        if base_preset_id is not None
                        else self.before[cue_id][2],
                    )
                ),
                copy.deepcopy(
                    mapped_appearance.get(
                        cue_id,
                        dict(appearance_override)
                        if appearance_override is not None
                        else self.before[cue_id][3],
                    )
                ),
                (
                    mapped_transforms[cue_id]
                    if cue_id in mapped_transforms
                    else self.before[cue_id][4]
                ),
            )
            for cue_id in self.before
        }
        self.before_styles = copy.deepcopy(project.styles)
        self.before_effects = copy.deepcopy(project.effects)
        self.before_style_recipes = copy.deepcopy(project.style_recipes)
        self.after_styles = copy.deepcopy(styles if styles is not None else project.styles)
        self.after_effects = copy.deepcopy(effects if effects is not None else project.effects)
        self.after_style_recipes = copy.deepcopy(
            style_recipes if style_recipes is not None else project.style_recipes
        )
        self.changed = changed

        self.merge_enabled = bool(merge_enabled)

    def _apply(self, values, styles, effects, style_recipes) -> None:
        def mutate() -> None:
            for cue in self.project.cues:
                presentation = values.get(cue.id)
                if presentation is not None:
                    (
                        cue.style_id,
                        cue.effect_id,
                        cue.base_preset_id,
                        cue.appearance_override,
                        cue.transform,
                    ) = (
                        presentation[0],
                        presentation[1],
                        presentation[2],
                        copy.deepcopy(presentation[3]),
                        copy.deepcopy(presentation[4]) if presentation[4] else {},
                    )
                    cue.appearance_generation = int(cue.appearance_generation) + 1
            self.project.styles = copy.deepcopy(styles)
            self.project.effects = copy.deepcopy(effects)
            self.project.style_recipes = copy.deepcopy(style_recipes)

        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=(
                DirtyDomain.CUE_STYLE
                | DirtyDomain.TIMELINE_PIXELS
                | DirtyDomain.NATIVE_SUBTITLE
                | DirtyDomain.ADVANCED_PREVIEW
                | DirtyDomain.TRANSFORM
                | DirtyDomain.AUTOSAVE
            ),
            cue_ids=values.keys(),
            mutate=mutate,
            changed=self.changed,
        )

    def redo(self) -> None:
        self._apply(self.after, self.after_styles, self.after_effects, self.after_style_recipes)

    def undo(self) -> None:
        self._apply(self.before, self.before_styles, self.before_effects, self.before_style_recipes)

    def id(self) -> int:
        return self.COMMAND_ID if self.merge_enabled else -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetCuesPresentationCommand):
            return False
        if self.project is not other.project or self.before.keys() != other.before.keys():
            return False
        self.after = copy.deepcopy(other.after)
        self.after_styles = copy.deepcopy(other.after_styles)
        self.after_effects = copy.deepcopy(other.after_effects)
        self.after_style_recipes = copy.deepcopy(other.after_style_recipes)
        self.setText(other.text())
        # PySide can retain the merged Python wrapper until a later GC pass.
        # Release its 10k-cue payload immediately instead of retaining it per edit.
        other.before.clear()
        other.after.clear()
        other.before_styles = []
        other.before_effects = {}
        other.after_styles = []
        other.after_effects = {}
        other.after_style_recipes = {}
        other.changed = None
        return True


def split_cue_command(
    project: SubtitleProject,
    cue_id: str,
    split_ms: int,
    left_text: str,
    right_text: str,
    changed: ChangedCallback | None = None,
) -> QUndoCommand:
    cue = cue_by_id(project, cue_id)
    split_ms = int(split_ms)
    if split_ms <= cue.start_ms or split_ms >= cue.end_ms:
        raise ValueError("split position must be inside the cue")
    return _splice_split(project, cue, split_ms, left_text, right_text, changed)


def merge_cues_command(
    project: SubtitleProject,
    cue_ids: Iterable[str],
    changed: ChangedCallback | None = None,
) -> QUndoCommand:
    selected = set(str(item) for item in cue_ids)
    matches = [cue for cue in project.cues if cue.id in selected]
    if len(matches) < 2:
        raise ValueError("at least two cues are required for merge")
    matches.sort(key=lambda item: (item.start_ms, item.end_ms, item.id))
    spliced = _splice_merge_adjacent(project, matches[0], matches[1], changed)
    if spliced is not None:
        return spliced
    merged = copy.deepcopy(matches[0])
    merged.start_ms = min(item.start_ms for item in matches)
    merged.end_ms = max(item.end_ms for item in matches)
    merged.text = "".join(item.text for item in matches)
    merged.original_text = "".join(item.original_text for item in matches)
    merged.evidence_refs = list(
        dict.fromkeys(ref for item in matches for ref in item.evidence_refs)
    )
    first_index = min(index for index, item in enumerate(project.cues) if item.id in selected)
    replacement = [copy.deepcopy(item) for item in project.cues if item.id not in selected]
    replacement.insert(first_index, merged)
    return ReplaceCuesCommand(project, replacement, "Merge subtitles", changed)


def delete_cues_command(
    project: SubtitleProject,
    cue_ids: Iterable[str],
    changed: ChangedCallback | None = None,
) -> QUndoCommand:
    selected = set(str(item) for item in cue_ids)
    spliced = _splice_delete(project, selected, changed)
    if spliced is not None:
        return spliced
    replacement = [copy.deepcopy(item) for item in project.cues if item.id not in selected]
    if len(replacement) == len(project.cues):
        raise ValueError("no matching cues to delete")
    return ReplaceCuesCommand(project, replacement, "Delete subtitles", changed)


def add_cue_command(
    project: SubtitleProject,
    cue: StudioCue,
    changed: ChangedCallback | None = None,
) -> QUndoCommand:
    if any(item.id == cue.id for item in project.cues):
        raise ValueError(f"duplicate cue id {cue.id}")
    spliced = _splice_add(project, cue, changed)
    if spliced is not None:
        return spliced
    replacement = [*copy.deepcopy(project.cues), copy.deepcopy(cue)]
    replacement.sort(key=lambda item: (item.start_ms, item.end_ms, item.id))
    return ReplaceCuesCommand(project, replacement, "Add subtitle", changed)


class SetCuesFieldsCommand(QUndoCommand):
    """Apply the same field changes to many cues as one undoable operation."""
    def __init__(self, project: SubtitleProject, cue_ids: Iterable[str], changes: Mapping[str, object], text: str = "Batch edit subtitles", changed: ChangedCallback | None = None) -> None:
        super().__init__(text)
        self.project = project
        self.ids = {str(item) for item in cue_ids}
        if not self.ids:
            raise ValueError("at least one cue is required")
        self.changes = copy.deepcopy(dict(changes))
        allowed = {"start_ms", "end_ms", "text", "speaker_id", "style_id", "effect_id", "raw_ass_override"}
        if not set(self.changes) <= allowed:
            raise AttributeError(next(iter(set(self.changes) - allowed)))
        self.before = {
            cue.id: {key: copy.deepcopy(getattr(cue, key)) for key in self.changes}
            for cue in project.cues if cue.id in self.ids
        }
        if len(self.before) != len(self.ids):
            raise KeyError("one or more cues were not found")
        self.changed = changed

    def _apply(self, values: Mapping[str, Mapping[str, object]] | None = None) -> None:
        def mutate() -> None:
            for cue in self.project.cues:
                if cue.id not in self.ids:
                    continue
                patch = values.get(cue.id, {}) if values is not None else self.changes
                for key, value in patch.items():
                    setattr(cue, key, copy.deepcopy(value))

        fields = self.changes if values is None else {
            key for patch in values.values() for key in patch
        }
        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=_field_domains(fields),
            cue_ids=self.ids,
            mutate=mutate,
            changed=self.changed,
        )

    def redo(self) -> None:
        self._apply()

    def undo(self) -> None:
        self._apply(self.before)


class BatchReplaceTextCommand(QUndoCommand):
    """Replace text across many cues with per-cue values in one undo step."""

    def __init__(
        self,
        project: SubtitleProject,
        values: Mapping[str, str],
        *,
        needle: str = "",
        changed: ChangedCallback | None = None,
        origin: MutationOrigin = MutationOrigin.SEARCH_REPLACE,
        learning_observer: TextLearningObserver | None = None,
        learning_meta: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(f"批量替换“{needle}”" if needle else "Batch replace text")
        self.project = project
        self.after = {str(cue_id): str(value) for cue_id, value in values.items()}
        self.before = {
            cue.id: cue.text for cue in project.cues if cue.id in self.after
        }
        if len(self.before) != len(self.after):
            raise KeyError("one or more cues were not found")
        self.changed = changed
        self.origin = MutationOrigin(origin)
        self.needle = str(needle or "")
        self.learning_observer = learning_observer
        self.learning_meta = dict(learning_meta) if learning_meta else None

    def _apply(self, values: Mapping[str, str]) -> None:
        def mutate() -> None:
            for cue in self.project.cues:
                if cue.id in values:
                    cue.text = values[cue.id]

        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=_field_domains(("text",)),
            cue_ids=values.keys(),
            mutate=mutate,
            changed=self.changed,
        )
        if (
            values
            and self.learning_observer is not None
            and self.origin in LEARNABLE_TEXT_ORIGINS
        ):
            try:
                self.learning_observer(self, values is self.before)
            except Exception:
                pass

    def redo(self) -> None:
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)


class EditCueIntervalsCommand(QUndoCommand):
    """Commit a whole timeline gesture, including track changes, atomically."""

    def __init__(self, project, values, changed=None):
        super().__init__("调整字幕时间与轨道")
        self.project, self.changed = project, changed
        # 2026-09-19 P0：values 的键可能是剪辑视图的派生 id（"源id#段id"），
        # 时间是序列域——解析回源 id 并映射回源域；裁边 cue 保持源计时。
        from .studio_edit_sequence import map_timing_to_source, source_cue_id_of
        source_by_id = {cue.id: cue for cue in project.cues}
        resolved: dict[str, tuple[int, int, str]] = {}
        for key, value in values.items():
            source_id = source_cue_id_of(str(key))
            cue = source_by_id.get(source_id)
            if cue is None:
                raise KeyError(f"edited cue no longer exists: {key}")
            mapped = map_timing_to_source(
                project, cue, int(value.start_ms), int(value.end_ms)
            )
            if mapped is None:
                mapped = (int(cue.start_ms), int(cue.end_ms))
            resolved[source_id] = (mapped[0], mapped[1], str(value.speaker_id))
        self.after = resolved
        self.before = {cue.id: (cue.start_ms, cue.end_ms, cue.speaker_id)
                       for cue in project.cues if cue.id in self.after}
        if len(self.before) != len(self.after):
            raise KeyError("one or more edited cues no longer exist")
        if any(start < 0 or end-start < 50 for start, end, _ in self.after.values()):
            raise ValueError("subtitle interval must be at least 50ms")

    def _apply(self, values):
        def mutate():
            for cue in self.project.cues:
                if cue.id in values:
                    cue.start_ms, cue.end_ms, cue.speaker_id = values[cue.id]
        _commit_mutation(self.project, action_id=self.text(),
                         dirty=_field_domains(("start_ms", "end_ms", "speaker_id")) | DirtyDomain.ADVANCED_PREVIEW,
                         cue_ids=values, mutate=mutate, changed=self.changed)

    def redo(self): self._apply(self.after)

    def undo(self): self._apply(self.before)


class RepairDisplayHandoffsCommand(EditCueIntervalsCommand):
    """Undoable end-only policy repair; acoustic evidence and visual styles stay intact."""
    def __init__(self, project, ends, audit, changed=None):
        from .timeline_cue_gesture import CueInterval
        values={c.id:CueInterval(c.start_ms,ends[c.id],c.speaker_id) for c in project.cues if c.id in ends}
        super().__init__(project,values,changed)
        self.setText("收口说话人交接边界")
        self.before_audit=copy.deepcopy(project.generation_metadata.get('display_overlap_audit'))
        self.after_audit=copy.deepcopy(audit)

    def redo(self):
        self.project.generation_metadata['display_overlap_audit']=copy.deepcopy(self.after_audit)
        super().redo()

    def undo(self):
        self.project.generation_metadata['display_overlap_audit']=dict(status='user_undone',previous=copy.deepcopy(self.before_audit))
        super().undo()


class BatchTimingCommand(QUndoCommand):
    def __init__(self, project: SubtitleProject, values: Mapping[str, tuple[int, int]], text: str = "Timing offset", changed: ChangedCallback | None = None) -> None:
        super().__init__(text)
        # 2026-09-19 P0：values 键可能是剪辑视图派生 id——解析回源 id
        # （输入时间本身来自 project.cues 报告，已是源域，不做映射）。
        from .studio_edit_sequence import source_cue_id_of
        self.project, self.changed = project, changed
        self.after = {source_cue_id_of(str(k)): tuple(map(int, v)) for k, v in values.items()}
        self.before = {cue.id: (cue.start_ms, cue.end_ms) for cue in project.cues if cue.id in self.after}
        if len(self.before) != len(self.after):
            raise KeyError("one or more cues were not found")

    def _apply(self, values: Mapping[str, tuple[int, int]]) -> None:
        def mutate() -> None:
            for cue in self.project.cues:
                if cue.id in values:
                    cue.start_ms, cue.end_ms = values[cue.id]

        _commit_mutation(
            self.project,
            action_id=self.text(),
            dirty=_field_domains(("start_ms", "end_ms")),
            cue_ids=values.keys(),
            mutate=mutate,
            changed=self.changed,
        )

    def redo(self): self._apply(self.after)
    def undo(self): self._apply(self.before)


def set_cues_timing_offset_command(project: SubtitleProject, cue_ids: Iterable[str], offset_ms: int, *, text: str = "Timing offset", changed: ChangedCallback | None = None) -> BatchTimingCommand:
    selected = {str(item) for item in cue_ids}
    duration = int(project.media.duration_ms or 0)
    changes: dict[str, tuple[int, int]] = {}
    for cue in project.cues:
        if cue.id not in selected:
            continue
        start = max(0, cue.start_ms + int(offset_ms))
        end = cue.end_ms + int(offset_ms)
        if duration:
            end = min(duration, end)
        if end <= start:
            continue
        # A single command stores per-cue values while preserving one undo step.
        changes[cue.id] = (start, end)
    if not changes:
        raise ValueError("offset would create invalid timing")
    return BatchTimingCommand(project, changes, text, changed)
