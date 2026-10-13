"""Conservative timing intelligence and selection helpers for Subtitle Studio.

The functions in this module are deliberately UI-independent.  Evidence is read
from the persisted project payload, so a missing or ambiguous signal produces a
skip instead of an invented timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .studio_project import StudioCue, SubtitleProject
from .selection_scope import SelectionMode, SelectionScope


@dataclass(frozen=True)
class AlignmentRecommendation:
    cue_id: str
    recommended_start: int | None
    recommended_end: int | None
    current_start: int
    current_end: int
    start_reason: str = ""
    end_reason: str = ""
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.recommended_start is not None or self.recommended_end is not None


@dataclass
class AlignmentReport:
    recommendations: list[AlignmentRecommendation] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def applied_count(self) -> int:
        return sum(item.changed for item in self.recommendations)

    @property
    def average_change_ms(self) -> int:
        changes = [
            abs((item.recommended_start or item.current_start) - item.current_start)
            for item in self.recommendations
        ] + [
            abs((item.recommended_end or item.current_end) - item.current_end)
            for item in self.recommendations
        ]
        return round(sum(changes) / len(changes)) if changes else 0


def _ms(value: Any, *, default: int | None = None) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    # Evidence produced by ASR is commonly seconds, while Studio stores ms.
    return round(number * 1000) if abs(number) < 100 else round(number)


def _points(value: Any) -> list[tuple[int, int]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[tuple[int, int]] = []
    for item in value:
        if isinstance(item, Mapping):
            try:
                start = round(float(item['start_ms'])) if 'start_ms' in item else round(float(item.get('start', item.get('begin')))*1000)
                end = round(float(item['end_ms'])) if 'end_ms' in item else round(float(item.get('end', item.get('finish')))*1000)
            except (TypeError, ValueError):
                continue
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            start, end = _ms(item[0]), _ms(item[1])
        else:
            continue
        if start is not None and end is not None and end > start:
            result.append((start, end))
    return result


def _evidence(project: SubtitleProject, cue: StudioCue) -> tuple[list[tuple[int, int]], list[tuple[int, int]], list[str]]:
    words: list[tuple[int, int]] = []
    speech: list[tuple[int, int]] = []
    labels: list[str] = []
    for ref in cue.evidence_refs:
        row = project.asr_evidence.get(ref, {})
        if not isinstance(row, Mapping):
            continue
        for key in ("word_timestamps", "words", "tokens", "alignment"):
            points = _points(row.get(key))
            if points:
                words.extend(points)
                labels.append("首字/末字时间")
                break
        for key in ("speech_regions", "vad", "regions"):
            points = _points(row.get(key))
            if points:
                speech.extend(points)
                labels.append("语音起止")
                break
    return words, speech, list(dict.fromkeys(labels))


def recommend_cue_alignment(
    project: SubtitleProject,
    cue: StudioCue,
    *,
    max_adjust_ms: int = 400,
    min_duration_ms: int = 80,
) -> AlignmentRecommendation | None:
    words, speech, labels = _evidence(project, cue)
    if not words and not speech:
        return None
    candidates = words or speech
    start = min(item[0] for item in candidates)
    end = max(item[1] for item in candidates)
    if words and speech:
        start = max(start, min(item[0] for item in speech))
        end = min(end, max(item[1] for item in speech))
    duration = end - start
    if duration < min_duration_ms:
        return None
    current_start, current_end = cue.start_ms, cue.end_ms
    start_delta, end_delta = start - current_start, end - current_end
    if abs(start_delta) > max_adjust_ms:
        start = current_start
    if abs(end_delta) > max_adjust_ms:
        end = current_end
    if end <= start:
        return None
    return AlignmentRecommendation(
        cue.id,
        None if start == current_start else start,
        None if end == current_end else end,
        current_start,
        current_end,
        " + ".join(labels) or "时间证据",
        " + ".join(labels) or "时间证据",
        0.9 if words and speech else 0.72,
        tuple(labels),
    )


def recommend_many(project: SubtitleProject, cue_ids: Iterable[str] | None = None, **kwargs: Any) -> AlignmentReport:
    wanted = {str(item) for item in cue_ids} if cue_ids is not None else None
    report = AlignmentReport()
    ordered = sorted(project.cues, key=lambda item: (item.start_ms, item.end_ms, item.id))
    for index, cue in enumerate(ordered):
        if wanted is not None and cue.id not in wanted:
            continue
        recommendation = recommend_cue_alignment(project, cue, **kwargs)
        if recommendation is None:
            report.skipped.append(cue.id)
            continue
        # Never create an overlap with the neighboring cue on the same track.
        previous = ordered[index - 1] if index else None
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        start = recommendation.recommended_start
        end = recommendation.recommended_end
        if previous and previous.speaker_id == cue.speaker_id and start is not None:
            start = max(start, previous.end_ms)
        if following and following.speaker_id == cue.speaker_id and end is not None:
            end = min(end, following.start_ms)
        if start is not None and end is not None and end <= start:
            report.skipped.append(cue.id)
            continue
        report.recommendations.append(AlignmentRecommendation(
            cue.id, start, end, cue.start_ms, cue.end_ms,
            recommendation.start_reason, recommendation.end_reason,
            recommendation.confidence, recommendation.evidence,
        ))
    return report


def loop_region(cue: StudioCue, *, pre_roll_ms: int = 250, post_roll_ms: int = 300, duration_ms: int = 0) -> tuple[int, int]:
    start = max(0, cue.start_ms - max(0, int(pre_roll_ms)))
    end = cue.end_ms + max(0, int(post_roll_ms))
    if duration_ms:
        end = min(end, int(duration_ms))
    return start, max(start + 1, end)


# Mirrors studio_theme.MIN_CUE_DURATION_MS without importing the Qt-facing
# theme module into this UI-independent helper.
SPLIT_MIN_CUE_DURATION_MS = 50


ESTIMATED_SPLIT = "estimated_text_allocation"


@dataclass(frozen=True)
class SplitPreview:
    """One resolved razor cut: exact split time plus both resulting cues.

    ``split_ms`` is the media cut (where the cue interval is cut).  With
    measured words the text boundary sits between ``left_word_end_ms`` and
    ``right_word_start_ms``; ``straddled`` names the word whose sound the cut
    passes through, which stays on the left.  Without words the text boundary
    is an explicit estimate (``timing_source == ESTIMATED_SPLIT``).
    """

    split_ms: int
    left_text: str
    right_text: str
    left_start_ms: int
    left_end_ms: int
    right_start_ms: int
    right_end_ms: int
    timing_source: str = ESTIMATED_SPLIT
    timing_reason: str = "missing_word_timestamps"
    right_word_start_ms: int | None = None
    left_word_end_ms: int | None = None
    straddled: object | None = None
    words: tuple = ()

    @property
    def measured(self) -> bool:
        return self.timing_source != ESTIMATED_SPLIT


@dataclass(frozen=True)
class SplitBlocked:
    """A razor position that cannot produce two nonempty cues."""

    split_ms: int
    reason: str  # before_first_word | after_last_word_onset | too_short | single_character
    timing_source: str = ESTIMATED_SPLIT
    timing_reason: str = ""
    words: tuple = ()


def split_alignment(cue: StudioCue, project: SubtitleProject | None) -> tuple[tuple, str]:
    """Measured words for razor previews and commits (see cue_words)."""
    from .cue_word_alignment import cue_words
    return cue_words(project, cue)


_SPLIT_EDGE_SPACE = r"[\s\u200b\u200c\u200d\u2060\ufeff]+"


def trim_cut_pieces(pieces: Iterable[str]) -> list[str]:
    """Consecutive slices of one text; whitespace on each cut is the boundary.

    2026-10-12: a razor/AI cut at a pause space left "这里怎么办 " on the
    left.  The space now belongs to neither part; the outer edges of the
    original text are untouched.  Word alignment is content-indexed (and
    re-derived from the parent's tokens for the new cues), so no timing
    moves.  A piece that would become whitespace-only keeps its raw slice
    (callers already refuse an empty side).
    """
    import re
    raw = [str(piece) for piece in pieces]
    result = []
    for index, piece in enumerate(raw):
        trimmed = piece
        if index:
            trimmed = re.sub(r"\A" + _SPLIT_EDGE_SPACE, "", trimmed)
        if index < len(raw) - 1:
            trimmed = re.sub(_SPLIT_EDGE_SPACE + r"\Z", "", trimmed)
        result.append(trimmed if trimmed.strip() else piece)
    return result


def split_texts_at(text: str, position: int) -> tuple[str, str]:
    """Cut ``text`` at ``position`` (see ``trim_cut_pieces``)."""
    left, right = trim_cut_pieces((text[:position], text[position:]))
    return left, right


def describe_split(
    cue: StudioCue,
    split_ms: int,
    *,
    min_duration_ms: int = SPLIT_MIN_CUE_DURATION_MS,
    project: SubtitleProject | None = None,
    alignment: tuple[tuple, str] | None = None,
) -> SplitPreview | SplitBlocked:
    """Resolve a razor cut exactly the way the split command commits it.

    The timeline preview and the cue controller both call this, so what the
    user sees is by construction what the split produces.  ``alignment`` lets
    the timeline reuse words it already resolved for this cue revision.
    """
    clamped = min(
        cue.end_ms - min_duration_ms,
        max(cue.start_ms + min_duration_ms, int(split_ms)),
    )
    words, reason = alignment if alignment is not None else split_alignment(cue, project)
    source = reason if words else ESTIMATED_SPLIT
    if len(cue.text) < 2:
        return SplitBlocked(clamped, 'single_character', source, reason, tuple(words))
    if not (cue.start_ms < clamped < cue.end_ms):
        return SplitBlocked(clamped, 'too_short', source, reason, tuple(words))
    if not words:
        # No measured words: an explicit, labelled estimate, never presented
        # as a word-level split.
        duration = max(1, cue.end_ms - cue.start_ms)
        ratio = (clamped - cue.start_ms) / duration
        position = min(len(cue.text) - 1, max(1, round(len(cue.text) * ratio)))
        left_text, right_text = split_texts_at(cue.text, position)
        return SplitPreview(clamped, left_text, right_text, cue.start_ms, clamped,
                            clamped, cue.end_ms, ESTIMATED_SPLIT, reason)
    # A word whose sound has started belongs to the left. The media cut stays
    # where the user put it; the text boundary follows the measured onsets, so
    # moving inside one pause never moves text.
    right = [word for word in words if word.start_ms >= clamped]
    left = [word for word in words if word.start_ms < clamped]
    if not left or right and right[0].char_start == 0:
        return SplitBlocked(clamped, 'before_first_word', source, reason, tuple(words))
    if not right:
        return SplitBlocked(clamped, 'after_last_word_onset', source, reason, tuple(words))
    position = right[0].char_start
    straddled = left[-1] if left[-1].end_ms > clamped else None
    left_text, right_text = split_texts_at(cue.text, position)
    return SplitPreview(
        split_ms=clamped,
        left_text=left_text,
        right_text=right_text,
        left_start_ms=cue.start_ms,
        left_end_ms=clamped,
        right_start_ms=clamped,
        right_end_ms=cue.end_ms,
        timing_source=source,
        timing_reason='inside_token_kept_left' if straddled else 'manual_time_preserved',
        right_word_start_ms=right[0].start_ms,
        left_word_end_ms=left[-1].end_ms,
        straddled=straddled,
        words=tuple(words),
    )


def resolve_split(
    cue: StudioCue,
    split_ms: int,
    *,
    min_duration_ms: int = SPLIT_MIN_CUE_DURATION_MS,
    project: SubtitleProject | None = None,
    alignment: tuple[tuple, str] | None = None,
) -> SplitPreview | None:
    """``describe_split`` for callers that only need a committable cut."""
    result = describe_split(cue, split_ms, min_duration_ms=min_duration_ms,
                            project=project, alignment=alignment)
    return result if isinstance(result, SplitPreview) else None


def merge_neighbor_allowed(anchor: StudioCue, cue: StudioCue) -> bool:
    """A merge neighbour: same track, or another track not speaking at once."""
    if cue.speaker_id == anchor.speaker_id:
        return True
    return min(anchor.end_ms, cue.end_ms) <= max(anchor.start_ms, cue.start_ms)


def word_boundary_times(words) -> list[tuple[int, int]]:
    """(time, right word index) for every measured text boundary in a cue."""
    values = []
    for index in range(1, len(words)):
        values.append((int(words[index].start_ms), index))
        if words[index - 1].end_ms < words[index].start_ms:
            values.append((int(words[index - 1].end_ms), index))
    return values


def snap_candidates(project: SubtitleProject, cue: StudioCue, value_ms: int, *, edge: str = "start", playhead_ms: int | None = None, threshold_ms: int = 100) -> list[tuple[int, str]]:
    values: list[tuple[int, str]] = []
    for other in project.cues:
        if other.id == cue.id:
            continue
        values.append((other.start_ms if edge == "start" else other.end_ms, "相邻字幕边界"))
    words, speech, _labels = _evidence(project, cue)
    if words:
        values.append((words[0][0] if edge == "start" else words[-1][1], "首字/末字时间"))
    if speech:
        values.append((speech[0][0] if edge == "start" else speech[-1][1], "语音起点/终点"))
    if playhead_ms is not None:
        values.append((int(playhead_ms), "播放头"))
    return sorted(values, key=lambda pair: abs(pair[0] - value_ms))[:1] if values and abs(min(values, key=lambda pair: abs(pair[0] - value_ms))[0] - value_ms) <= threshold_ms else []


class CueSelectionModel:
    """Active + selected IDs shared by Timeline and Subtitle List."""
    def __init__(self) -> None:
        self.active_id = ""
        self.selected_ids: list[str] = []
        self.scope = SelectionScope.empty()

    def set_scope(self, scope: SelectionScope) -> None:
        self.scope = scope
        self.active_id = str(scope.active_id)
        self.selected_ids = (
            list(scope.explicit_ids)
            if scope.mode == SelectionMode.EXPLICIT_IDS
            else []
        )

    def selected_count(self) -> int:
        return self.scope.count() if self.scope.count() else len(self.selected_ids)

    def materialize(self, ordered_ids: Iterable[str]) -> list[str]:
        values = list(ordered_ids)
        if self.scope.count() or self.scope.mode != SelectionMode.EMPTY:
            return self.scope.materialize(values)
        chosen = set(self.selected_ids)
        return [item for item in values if item in chosen]

    def click(self, cue_id: str, *, ctrl: bool = False, shift: bool = False, ordered_ids: Iterable[str] = ()) -> list[str]:
        cue_id = str(cue_id)
        ids = list(ordered_ids)
        if shift and self.active_id in ids and cue_id in ids:
            left, right = sorted((ids.index(self.active_id), ids.index(cue_id)))
            self.selected_ids = ids[left:right + 1]
        elif ctrl:
            self.selected_ids = [item for item in self.selected_ids if item != cue_id]
            if cue_id not in self.selected_ids:
                self.selected_ids.append(cue_id)
        else:
            self.selected_ids = [cue_id]
        self.active_id = cue_id
        self.scope = SelectionScope.explicit(self.selected_ids, self.active_id)
        return list(self.selected_ids)
