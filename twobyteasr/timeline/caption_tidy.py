"""Tidy captions already in a project (2026-10-26).

The same two steps downloads now get on import (``media/link_tidy``), for
projects imported before: sound labels (``[Music]``, ``♪``, ``>>``) are
removed, and runs of word-timed captions are re-broken by words with the
English / European breaker. Each new caption keeps its words' times (the
receipt is written with them), a caption that held only a label is deleted,
and the whole tidy is one undo step.

A run is consecutive captions in scope, one speaker, each with word times,
less than 2 s apart. Captions without word times only lose their labels.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import uuid

from ..media.link_tidy import HARD_PAUSE_MS, lexicon_for, strip_word_labels, strip_labels
from ..projects.studio_project import StudioCue


@dataclass
class TidySplice:
    index: int
    removed: list
    inserted: list
    words: dict = field(default_factory=dict)       # new cue id -> receipt word rows
    alignment: str = ""


@dataclass
class TidyPlan:
    splices: list = field(default_factory=list)
    labels_removed: int = 0
    captions_before: int = 0
    captions_after: int = 0
    regrouped: bool = False
    word_timed: int = 0          # captions in scope with word times (only these can be re-broken)

    @property
    def changed(self) -> bool:
        return bool(self.splices)


def _tokens(cue, words):
    """Whitespace tokens of ``cue.text`` with the times of the words under them."""
    tokens, position = [], 0
    for piece in cue.text.split():
        lo = cue.text.index(piece, position)
        hi = lo + len(piece)
        position = hi
        under = [w for w in words if w.char_start < hi and w.char_end > lo]
        if not under:
            return None
        tokens.append(dict(text=piece, start_ms=min(w.start_ms for w in under), end_ms=max(w.end_ms for w in under),
                           ref=under[0].evidence_ref, cue=cue.id))
    return tokens


def _language(project) -> str:
    meta = project.generation_metadata.get("language") if isinstance(project.generation_metadata, dict) else None
    return str((meta or {}).get("code") or "") if isinstance(meta, dict) else str(meta or "")


def _new_cue(template: StudioCue, tokens: list[dict], end_ms: int, lexicon, evidence_refs) -> tuple[StudioCue, list]:
    from ..subtitle_rules.english_segmentation import _tools
    join = _tools(lexicon)[3]
    text = join([t["text"] for t in tokens])
    rows, cursor = [], 0
    for token in tokens:
        lo = text.find(token["text"], cursor)
        if lo < 0:
            rows = []
            break
        hi = lo + len(token["text"])
        rows.append(dict(text=token["text"], char_start=lo, char_end=hi, start_ms=int(token["start_ms"]),
                         end_ms=int(max(token["end_ms"], token["start_ms"] + 1)), evidence_ref=token["ref"]))
        cursor = hi
    cue = copy.deepcopy(template)
    cue.id = f"{template.id}-tidy-{uuid.uuid4().hex[:8]}"
    cue.start_ms = int(tokens[0]["start_ms"])
    cue.end_ms = int(max(end_ms, cue.start_ms + 50))
    cue.text = text
    cue.evidence_refs = list(evidence_refs)
    from ..caption_style.text_marks import with_marks
    cue.appearance_override = with_marks(cue, [])     # old marks pointed at the old text
    return cue, rows


def plan_caption_tidy(project, cue_ids, *, labels: bool = True, regroup: bool = True) -> TidyPlan:
    from ..recognition.cue_word_alignment import DOWNLOADED_WORD_ONSETS, MEASURED_ALIGNMENTS, cue_words
    from ..subtitle_rules.english_segmentation import split_tokens
    wanted = set(cue_ids)
    lexicon = lexicon_for(_language(project)) if regroup else None
    plan = TidyPlan(regrouped=lexicon is not None)
    plan.captions_before = sum(1 for cue in project.cues if cue.id in wanted)
    groups: list[list[tuple[int, StudioCue, list, str]]] = []
    current: list = []

    def close():
        nonlocal current
        if current:
            groups.append(current)
        current = []

    for index, cue in enumerate(project.cues):
        if cue.id not in wanted:
            close()
            continue
        words, reason = cue_words(project, cue)
        tokens = _tokens(cue, words) if words and reason in MEASURED_ALIGNMENTS else None
        plan.word_timed += tokens is not None
        if tokens is None:
            close()
            text, _speaker, removed = strip_labels(cue.text) if labels else (cue.text, False, 0)
            if removed:
                plan.labels_removed += removed
                if text:
                    edited = copy.deepcopy(cue)
                    edited.text = text
                    from ..caption_style.text_marks import with_marks
                    edited.appearance_override = with_marks(edited, [])
                    plan.splices.append(TidySplice(index, [cue], [edited]))
                else:
                    plan.splices.append(TidySplice(index, [cue], []))
            continue
        previous = current[-1] if current else None
        if previous and (previous[1].speaker_id != cue.speaker_id or index != previous[0] + 1
                         or cue.start_ms - previous[1].end_ms >= HARD_PAUSE_MS):
            close()
        current.append((index, cue, tokens, reason))
    close()

    for group in groups:
        removed = [cue for _i, cue, _t, _r in group]
        tokens = [token for _i, _c, toks, _r in group for token in toks]
        if labels:
            tokens, count, _speaker = strip_word_labels(tokens)
            plan.labels_removed += count
        reasons = {reason for _i, _c, _t, reason in group}
        alignment = DOWNLOADED_WORD_ONSETS if DOWNLOADED_WORD_ONSETS in reasons else (
            "derived_term_source_span" if "derived_term_source_span" in reasons else "exact_token_text")
        ends = {cue.id: cue.end_ms for cue in removed}
        pieces: list[list[dict]] = []
        if lexicon is not None and tokens:
            runs, run = [], []
            for token in tokens:
                if run and (token.get("break_before") or token["start_ms"] - run[-1]["start_ms"] >= HARD_PAUSE_MS):
                    runs.append(run)
                    run = []
                run.append(token)
            if run:
                runs.append(run)
            for run in runs:
                texts = [t["text"] for t in run]
                gaps = [max(0.0, (run[i + 1]["start_ms"] - run[i]["end_ms"]) / 1000) for i in range(len(run) - 1)]
                durations = [max(0.05, (t["end_ms"] - t["start_ms"]) / 1000) for t in run]
                pieces.extend(run[lo:hi] for lo, hi in split_tokens(texts, gaps, durations=durations, lexicon=lexicon))
        else:
            for cue in removed:
                own = [t for t in tokens if t["cue"] == cue.id]
                if own:
                    pieces.append(own)
        inserted, words = [], {}
        refs = list(dict.fromkeys(ref for cue in removed for ref in cue.evidence_refs))
        for number, piece in enumerate(pieces):
            nxt = pieces[number + 1][0]["start_ms"] if number + 1 < len(pieces) else None
            end = nxt if nxt is not None and nxt - piece[-1]["end_ms"] < HARD_PAUSE_MS else max(
                piece[-1]["end_ms"], min(ends[piece[-1]["cue"]], piece[-1]["end_ms"] + 1500))
            template = next(cue for cue in removed if cue.id == piece[0]["cue"])
            cue, rows = _new_cue(template, piece, end, lexicon, refs)
            inserted.append(cue)
            words[cue.id] = rows
        index_of = {cue.id: index for index, cue, _t, _r in group}
        for old, new in _aligned_parts(removed, pieces, inserted):
            # Same sentences as before: keep them as they are (and their timing).
            if [c.text for c in new] != [c.text for c in old]:
                plan.splices.append(TidySplice(index_of[old[0].id], old, new, {c.id: words[c.id] for c in new},
                                               alignment))
    plan.captions_after = plan.captions_before + sum(len(s.inserted) - len(s.removed) for s in plan.splices)
    return plan


def _aligned_parts(removed: list, pieces: list[list[dict]], inserted: list) -> list[tuple[list, list]]:
    """One re-broken run cut wherever an old and a new caption end on the same
    word (2026-10-26): each part is a small change the user can check on its
    own, instead of one row holding a whole run. Captions left with no words
    (only a label) go with the part after them, or the last part."""
    position = {cue.id: number for number, cue in enumerate(removed)}
    parts, new, taken = [], [], 0
    for number, piece in enumerate(pieces):
        new.append(inserted[number])
        following = pieces[number + 1][0] if number + 1 < len(pieces) else None
        if following is None or following["cue"] != piece[-1]["cue"]:
            upto = len(removed) if following is None else position[piece[-1]["cue"]] + 1
            parts.append((removed[taken:upto], new))
            taken, new = upto, []
    if taken < len(removed):
        if parts:
            parts[-1] = (parts[-1][0] + removed[taken:], parts[-1][1])
        else:
            parts.append((removed[taken:], []))
    return parts


def apply_caption_tidy(stack, project, plan: TidyPlan, changed=None, *, label: str = "整理字幕") -> int:
    """Push ``plan`` as one undo step; returns the number of replaced ranges."""
    from .studio_commands import SpliceCuesCommand
    if not plan.splices:
        return 0
    stack.beginMacro(label)
    try:
        # Highest index first: a splice moves only the captions after it.
        for splice in sorted(plan.splices, key=lambda item: -item.index):
            command = SpliceCuesCommand(project, splice.index, len(splice.removed), splice.inserted, label, changed)
            after = getattr(command, "_caption_after", None)
            if after is not None and splice.words:
                for cue in splice.inserted:
                    rows = splice.words.get(cue.id)
                    if rows and cue.id in after and after[cue.id] is not None:
                        after[cue.id].update(text=cue.text, words=copy.deepcopy(rows), word_alignment=splice.alignment,
                                             word_base_interval=[cue.start_ms, cue.end_ms],
                                             word_base_words=copy.deepcopy(rows), word_base_alignment=splice.alignment,
                                             word_clock_offset_ms=0)
            stack.push(command)
    finally:
        stack.endMacro()
    return len(plan.splices)


def prepare_cleanup_command(project, values, splices, local_steps=(), changed=None, *, label="AI 清理"):
    """Validate and plan the entire chosen cleanup before touching the live project.

    QUndoStack macros group history, but each child redo still emits a separate
    project revision. A mixed AI/local cleanup therefore exposed partly edited
    captions to render workers and could leave half an application on failure.
    Reuse the normal text/splice rules on an isolated data copy, then publish one
    ReplaceCuesCommand transaction, with the matching word/translation receipts.
    """
    from dataclasses import replace
    from .studio_commands import BatchReplaceTextCommand, CleanupCuesCommand
    from .studio_caption_timeline import KEY
    from ..subtitle_rules.subtitle_translation import snapshot
    from ..projects.studio_runtime_state import DirtyDomain, _json_snapshot, state_for
    from ..diagnostics.event_log import context

    values, splices = dict(values), list(splices)
    lookup = {cue.id: cue for cue in project.cues}
    if set(values) - set(lookup):
        raise ValueError("字幕已改变，整批清理没有应用。")
    occupied = set()
    for splice in splices:
        rows = project.cues[splice.index:splice.index + len(splice.removed)]
        ids = {cue.id for cue in rows}
        if (splice.index < 0 or not splice.removed or rows != splice.removed
                or occupied.intersection(ids)):
            raise ValueError("本地整理的字幕或位置已改变，请重新预览。")
        occupied.update(ids)

    # replace() copies dataclass fields only: no QObject, runtime subscribers or
    # caches leak into the planning copy. Evidence/media are read-only here.
    working = replace(project, cues=copy.deepcopy(project.cues),
                      studio_state=_json_snapshot(project.studio_state),
                      generation_metadata=_json_snapshot(project.generation_metadata),
                      styles=copy.deepcopy(project.styles), effects=copy.deepcopy(project.effects),
                      style_recipes=copy.deepcopy(project.style_recipes))
    class Planner:
        def beginMacro(self, _label): pass
        def endMacro(self): pass
        def push(self, command): command.redo()

    # The planning project is disposable. One nested transaction avoids 33
    # repeated copies of its several-MB metadata and 33 index rebuilds while
    # retaining the normal splice/word/translation rules (profiled 2026-10-26).
    with context(source="cleanup_planning", canonical=False), state_for(working).transaction(
        working, action_id="prepare_caption_cleanup",
        dirty=DirtyDomain.CUE_MODEL | DirtyDomain.CUE_CONTENT | DirtyDomain.PROJECT_METADATA,
        snapshot_cues=False,
    ):
        if values:
            BatchReplaceTextCommand(working, values).redo()
        edited = set(values)
        keep = [s for s in splices if not edited.intersection(c.id for c in s.removed)]
        again = [cue.id for s in splices if s not in keep for cue in s.removed]
        if again:
            keep += plan_caption_tidy(working, again, labels="labels" in local_steps,
                                      regroup="regroup" in local_steps).splices
        apply_caption_tidy(Planner(), working, TidyPlan(splices=keep))
    for cue in working.cues:
        cue.validate()
    if len({cue.id for cue in working.cues}) != len(working.cues):
        raise ValueError("整理结果包含重复字幕身份，整批清理没有应用。")
    command = CleanupCuesCommand(project, working.cues, label, changed)
    command._translation_states = (snapshot(project), snapshot(working))
    before = project.studio_state.get(KEY, {}).get("instances", {})
    after = working.studio_state.get(KEY, {}).get("instances", {})
    ids = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
    command._merge_caption_states = ({key: copy.deepcopy(before.get(key)) for key in ids},
                                     {key: copy.deepcopy(after.get(key)) for key in ids})
    return command
