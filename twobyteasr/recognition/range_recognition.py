"""Recognize only the in/out range of a Studio project again (2026-10-25).

A stretch came out wrong: the user marks it with the Studio's in/out points
and recognizes just that stretch again, with the same recognition sheet and
pipeline as a whole run. This module holds the rules, free of Qt, shared by
the Studio (menu, sheet, the undoable replacement) and the recognition
worker (which writes the range result project):

* ``range_problem``: why the range cannot be recognized now ('' when it can);
* ``recognition_window``: the stretch actually heard: the in/out range,
  widened to whole captions where a point cuts one;
* ``range_payload``: a recognition result of that stretch on project time.
  Cue ids and evidence keys get a run prefix; caption receipts move onto the
  project clock, while the evidence rows keep their own clock
  (``evidence_clock_offset_ms`` = the window start);
* ``splice_range``: the project's captions with the stretch replaced, plus
  what moves with them (evidence, receipts, archive rows). New captions land
  on the existing speaker tracks: each recognized speaker goes to the old
  speaker it overlaps most, else to the speaker of the nearest caption.

Captions outside the window, styles, the edit and the speaker roster stay
as they were.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import asdict, dataclass, field

MIN_RANGE_MS = 1000
CUE_ALIGNMENT_PREFIX = "cue-align:"
HISTORY_KEY = "range_recognitions"


@dataclass
class RangePayload:
    start_ms: int
    end_ms: int
    cues: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    receipts: dict = field(default_factory=dict)
    archive: list = field(default_factory=list)


@dataclass
class SplicePlan:
    window: tuple
    cues: list
    removed_ids: list
    inserted_ids: list
    evidence: dict
    receipts: dict
    archive: list
    speaker_map: dict


def _overlaps(cue, start_ms: int, end_ms: int) -> bool:
    return cue.end_ms > start_ms and cue.start_ms < end_ms


def requested_range(project):
    """(in, out) when both points are set, else None."""
    if project is None:
        return None
    from ..projects.project_range import range_points
    start, end = range_points(project)
    if start is None or end is None:
        return None
    return int(start), int(end)


def recognition_window(project, start_ms: int, end_ms: int):
    """(start, end, cue ids) actually recognized and replaced.

    Captions overlapping the range join it whole, until no further caption
    overlaps; the result stays inside the timeline.
    """
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    total = int(timeline_duration_ms(project) or 0)
    start, end = max(0, int(start_ms)), int(end_ms)
    if total:
        end = min(total, end)
    while True:
        hit = [cue for cue in project.cues if _overlaps(cue, start, end)]
        wider_start = max(0, min([start] + [cue.start_ms for cue in hit]))
        wider_end = max([end] + [cue.end_ms for cue in hit])
        if total:
            wider_end = min(total, wider_end)
        if (wider_start, wider_end) == (start, end):
            return start, end, [cue.id for cue in sorted(hit, key=lambda c: (c.start_ms, c.end_ms, c.id))]
        start, end = wider_start, wider_end


def edited_cue_ids(project, cue_ids) -> list[str]:
    """Captions whose text differs from what recognition delivered (edited by hand)."""
    wanted = set(cue_ids)
    return [cue.id for cue in project.cues
            if cue.id in wanted and cue.text != (cue.original_text or cue.text)]


def translated_cue_ids(project, cue_ids) -> list[str]:
    view = project.generation_metadata.get("translations") or {}
    return [cue_id for cue_id in cue_ids if str(view.get(cue_id) or "").strip()]


def cue_signature(project, cue_ids) -> dict:
    """What the replaced captions looked like, to notice edits made meanwhile."""
    wanted = set(cue_ids)
    return {cue.id: [cue.start_ms, cue.end_ms, cue.text, cue.speaker_id]
            for cue in project.cues if cue.id in wanted}


def range_problem(project, *, running: bool = False, locked=()) -> str:
    """Why the in/out range cannot be recognized now; '' when it can (Chinese source text)."""
    if project is None:
        return "没有打开工程"
    points = requested_range(project)
    if points is None:
        return "先设好入点和出点"
    start, end = points
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    total = int(timeline_duration_ms(project) or 0)
    if start >= end:
        return "入点要早于出点"
    if start < 0 or (total and end > total):
        return "入出点超出了时间轴"
    if end - start < MIN_RANGE_MS:
        return "这一段太短（至少 1 秒）"
    if running:
        return "正在识别，等这次识别完成"
    from ..timeline.studio_caption_timeline import independent_captions
    if project.cues and not independent_captions(project):
        return "这个工程还没有转换成时间轴字幕"
    from ..timeline.audio_stream_lanes import has_multitrack_source, recognizable_lanes
    if has_multitrack_source(project) and len(recognizable_lanes(project)) >= 2:
        return "多音轨素材暂不支持只识别一段"
    if locked:
        _a, _b, ids = recognition_window(project, start, end)
        wanted = set(ids)
        if any(cue.speaker_id in set(locked) for cue in project.cues if cue.id in wanted):
            return "这一段有锁定的字幕轨，先解锁"
    return ""


def _shift_words(rows, offset: int, evidence_map: dict) -> list:
    out = []
    for row in rows or ():
        moved = dict(row)
        moved["start_ms"] = int(moved["start_ms"]) + offset
        moved["end_ms"] = int(moved["end_ms"]) + offset
        if moved.get("evidence_ref"):
            moved["evidence_ref"] = evidence_map.get(moved["evidence_ref"], moved["evidence_ref"])
        out.append(moved)
    return out


def range_payload(result, start_ms: int, end_ms: int, *, prefix: str, span_project=None) -> RangePayload:
    """Captions of a range result (window-local time) moved onto project time.

    ``span_project`` names the recognition task in each receipt (the result
    project carrying ``timeline_recognition``); evidence rows are copied
    unchanged, on their own clock.
    """
    from ..recognition.cue_word_alignment import cue_words
    from ..timeline.studio_caption_timeline import CLOCK
    start_ms, end_ms = int(start_ms), int(end_ms)
    cue_map = {cue.id: f"{prefix}-{cue.id}" for cue in result.cues}
    evidence_map = {}
    for key in result.asr_evidence:
        if key.startswith(CUE_ALIGNMENT_PREFIX) and key[len(CUE_ALIGNMENT_PREFIX):] in cue_map:
            evidence_map[key] = CUE_ALIGNMENT_PREFIX + cue_map[key[len(CUE_ALIGNMENT_PREFIX):]]
        else:
            evidence_map[key] = f"{prefix}:{key}"
    payload = RangePayload(start_ms, end_ms)
    used_refs = set()
    for cue in sorted(result.cues, key=lambda c: (c.start_ms, c.end_ms, c.id)):
        shifted = copy.deepcopy(cue)
        shifted.id = cue_map[cue.id]
        shifted.start_ms = max(start_ms, min(end_ms, cue.start_ms + start_ms))
        shifted.end_ms = max(start_ms, min(end_ms, cue.end_ms + start_ms))
        if shifted.end_ms <= shifted.start_ms:
            continue
        shifted.evidence_refs = [evidence_map.get(ref, ref) for ref in cue.evidence_refs]
        words, reason = cue_words(result, cue)
        rows = _shift_words([asdict(word) for word in words], start_ms, evidence_map)
        used_refs.update(shifted.evidence_refs)
        used_refs.update(row["evidence_ref"] for row in rows if row.get("evidence_ref"))
        span = _span(shifted, span_project)
        receipt = dict(span, source_spans=[copy.deepcopy(span)], source_path=result.media.path,
                       text=shifted.text, words=rows, word_alignment=reason,
                       word_base_interval=[shifted.start_ms, shifted.end_ms],
                       word_base_words=copy.deepcopy(rows), word_base_alignment=reason)
        # Project time minus the clock of this caption's evidence rows.
        receipt[CLOCK] = start_ms
        payload.cues.append(shifted)
        payload.receipts[shifted.id] = receipt
        payload.archive.append(asdict(shifted))
    reverse = {value: key for key, value in evidence_map.items()}
    payload.evidence = {ref: copy.deepcopy(result.asr_evidence[reverse[ref]])
                        for ref in sorted(used_refs) if ref in reverse}
    return payload


def _span(cue, project) -> dict:
    if project is None:
        return dict(source_cue_id=cue.id, source_start_ms=cue.start_ms, source_end_ms=cue.end_ms,
                    source_text=cue.text, evidence_refs=list(cue.evidence_refs), task_fingerprint="",
                    job_id="", result_revision="", instances=[])
    from ..timeline.caption_source_receipts import source_span
    return source_span(cue, project)


def _speaker_targets(project, window, replaced, new_cues, foreign: bool) -> dict:
    roster = [speaker.id for speaker in project.speakers]
    known = set(roster)
    overlap = defaultdict(lambda: defaultdict(int))
    for new in new_cues:
        for old in replaced:
            amount = min(new.end_ms, old.end_ms) - max(new.start_ms, old.start_ms)
            if amount > 0:
                overlap[new.speaker_id][old.speaker_id] += amount
    totals = defaultdict(int)
    for old in replaced:
        totals[old.speaker_id] += old.end_ms - old.start_ms
    fallback = max(sorted(totals), key=lambda sid: totals[sid]) if totals else ""
    if not fallback:
        start, end = window
        outside = [cue for cue in project.cues if not _overlaps(cue, start, end)]
        if outside:
            nearest = min(outside, key=lambda c: (max(start - c.end_ms, c.start_ms - end, 0), c.start_ms))
            fallback = nearest.speaker_id
    if not fallback:
        fallback = roster[0] if roster else "S00"
    mapping = {}
    for new in new_cues:
        sid = new.speaker_id
        if sid in mapping:
            continue
        if not foreign and (sid in known or not roster):
            mapping[sid] = sid
            continue
        scores = overlap.get(sid) or {}
        best = max(sorted(scores), key=lambda key: scores[key]) if scores else ""
        mapping[sid] = best or fallback
    return mapping


def splice_range(project, window, payload: RangePayload, *, foreign_speakers: bool) -> SplicePlan:
    """The cue list with ``window`` replaced by ``payload`` (``project`` is not changed).

    ``foreign_speakers``: the payload's speaker ids belong to the result run
    (anonymous), so every one is mapped onto this project's tracks; otherwise
    only ids missing from this project are.
    """
    from .audio_lane_results import _rename, _unique
    from ..timeline.studio_caption_timeline import KEY
    start, end = int(window[0]), int(window[1])
    replaced = [cue for cue in project.cues if _overlaps(cue, start, end)]
    removed_ids = [cue.id for cue in replaced]
    archive_ids = {str(row.get("id")) for row in (project.studio_state.get(KEY) or {}).get("source_archive") or ()
                   if isinstance(row, dict)}
    used_cues = {cue.id for cue in project.cues} | archive_ids
    cue_map = {cue.id: _unique(cue.id, used_cues) for cue in payload.cues}
    used_evidence = set(project.asr_evidence)
    evidence_map = {}
    for key in payload.evidence:
        if key.startswith(CUE_ALIGNMENT_PREFIX) and key[len(CUE_ALIGNMENT_PREFIX):] in cue_map:
            evidence_map[key] = _unique(CUE_ALIGNMENT_PREFIX + cue_map[key[len(CUE_ALIGNMENT_PREFIX):]], used_evidence)
        else:
            evidence_map[key] = _unique(key, used_evidence)
    speaker_map = _speaker_targets(project, (start, end), replaced, payload.cues, foreign_speakers)
    inserted = []
    for cue in payload.cues:
        clone = copy.deepcopy(cue)
        clone.id = cue_map[cue.id]
        clone.speaker_id = speaker_map.get(cue.speaker_id, cue.speaker_id)
        clone.evidence_refs = [evidence_map.get(ref, ref) for ref in cue.evidence_refs]
        clone.start_ms = max(start, clone.start_ms)
        clone.end_ms = min(end, clone.end_ms)
        if clone.end_ms <= clone.start_ms:
            continue
        inserted.append(clone)
    kept_ids = {cue.id for cue in inserted}
    receipts = {}
    for old_id, receipt in payload.receipts.items():
        new_id = cue_map.get(old_id)
        if new_id in kept_ids:
            receipts[new_id] = _rename(copy.deepcopy(receipt), cue_map, evidence_map, speaker_map)
    archive = []
    for row in payload.archive:
        renamed = _rename(copy.deepcopy(row), cue_map, evidence_map, speaker_map)
        renamed["id"] = cue_map.get(row.get("id"), row.get("id"))
        if renamed["id"] in kept_ids:
            archive.append(renamed)
    evidence = {evidence_map[key]: copy.deepcopy(value) for key, value in payload.evidence.items()}
    kept = [cue for cue in project.cues if cue.id not in set(removed_ids)]
    cues = sorted([*copy.deepcopy(kept), *inserted], key=lambda c: (c.start_ms, c.end_ms, c.id))
    return SplicePlan((start, end), cues, removed_ids, [cue.id for cue in inserted], evidence,
                      receipts, archive, speaker_map)


def payload_from_result(result, info: dict) -> RangePayload:
    """The new captions of a written range result (``timeline_recognition["range"]``)."""
    from ..timeline.studio_caption_timeline import KEY
    start, end = (int(value) for value in info["window_ms"])
    wanted = list(info.get("cue_ids") or ())
    chosen = set(wanted)
    cues = [copy.deepcopy(cue) for cue in result.cues if cue.id in chosen]
    state = result.studio_state.get(KEY) or {}
    instances = state.get("instances") or {}
    receipts = {cue.id: copy.deepcopy(instances[cue.id]) for cue in cues if cue.id in instances}
    refs = {ref for cue in cues for ref in cue.evidence_refs}
    refs.update(word.get("evidence_ref") for receipt in receipts.values()
                for word in receipt.get("words") or () if isinstance(word, dict) and word.get("evidence_ref"))
    evidence = {ref: copy.deepcopy(result.asr_evidence[ref]) for ref in sorted(refs) if ref in result.asr_evidence}
    archive = [copy.deepcopy(row) for row in state.get("source_archive") or ()
               if isinstance(row, dict) and row.get("id") in chosen]
    return RangePayload(start, end, cues, evidence, receipts, archive)


def history_entry(plan: SplicePlan, requested=None, **extra) -> dict:
    """One line of ``generation_metadata["range_recognitions"]``."""
    return {"window_ms": list(plan.window), "requested_ms": list(requested or plan.window),
            "replaced_cue_ids": list(plan.removed_ids), "cue_ids": list(plan.inserted_ids), **extra}


def apply_plan(project, plan: SplicePlan, entry: dict | None = None) -> None:
    """Write ``plan`` straight into ``project`` (the worker's result project; no undo)."""
    from ..timeline.studio_caption_timeline import KEY
    removed = set(plan.removed_ids)
    project.cues = copy.deepcopy(plan.cues)
    project.asr_evidence.update(copy.deepcopy(plan.evidence))
    state = project.studio_state.setdefault(KEY, {"version": 1, "instances": {}})
    instances = state.setdefault("instances", {})
    for cue_id in removed:
        instances.pop(cue_id, None)
    instances.update(copy.deepcopy(plan.receipts))
    state.setdefault("source_archive", []).extend(copy.deepcopy(plan.archive))
    view = project.generation_metadata.get("translations")
    if isinstance(view, dict):
        for cue_id in removed:
            view.pop(cue_id, None)
    if entry is not None:
        project.generation_metadata.setdefault(HISTORY_KEY, []).append(copy.deepcopy(entry))
