"""Run the shared Studio boundary refinement on an in-memory downloaded track."""
from __future__ import annotations

from dataclasses import replace
import re


def _compact(text):
    return re.sub(r"\s+", "", text)


def _project(parsed, language):
    from ..projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from ..recognition.cue_word_alignment import DOWNLOADED_WORD_ONSETS
    from ..timeline.link_timing import onset_words
    from ..timeline.studio_caption_timeline import KEY

    project = SubtitleProject(media=StudioMedia(path=""),
        generation_metadata={"language": {"requested": language}})
    instances = project.studio_state.setdefault(KEY, {}).setdefault("instances", {})
    source = {}
    turn, previous_window = 0, None
    for index, row in enumerate(parsed.captions):
        if row.window != previous_window or row.text.lstrip().startswith((">>", "— ")):
            turn += 1
        previous_window = row.window
        identity = f"online-{index}"
        cue = StudioCue(identity, row.start_ms, row.end_ms, row.text, speaker_id=f"S{turn:02}")
        project.cues.append(cue)
        source[identity] = row
        words = onset_words(row.text, row.anchors, row.start_ms, row.end_ms, identity)
        instances[identity] = dict(text=row.text, words=words, word_alignment=DOWNLOADED_WORD_ONSETS if words else "",
            word_base_alignment=DOWNLOADED_WORD_ONSETS if words else "", word_base_words=words,
            word_base_interval=[row.start_ms, row.end_ms], segment_anchors=row.anchors,
            anchor_base_text=row.text, anchor_base_interval=[row.start_ms, row.end_ms])
    return project, source


def _caption(cue, originals):
    from .link_subtitles import Caption

    cursor, anchors = 0, []
    for source in originals:
        for word in source.anchors:
            if not cue.start_ms <= word["start_ms"] < cue.end_ms:
                continue
            text = word["text"].strip()
            start = cue.text.find(text, cursor)
            if not text or start < 0:
                continue
            cursor = start + len(text)
            copy = dict(word, text=text, char_start=start, char_end=cursor)
            if copy.get("end_ms", 0) > cue.end_ms:
                copy.pop("end_ms")
                copy["precision"] = "segment_start"
            anchors.append(copy)
    events = list(dict.fromkeys(ref for row in originals for ref in row.events))
    return Caption(cue.start_ms, cue.end_ms, cue.text, events=events, anchors=anchors,
                   precision="segment_start" if anchors else "sentence", end_basis="ai_boundary_source_time",
                   window=originals[0].window)


def refine_downloaded(parsed, language, settings, *, cancel=None, on_progress=None):
    from ..providers.llm_config import text_ai_key_missing
    from ..subtitle_rules.sentence_refine_contract import RefineError
    from ..subtitle_rules.sentence_refine import refine_cues_with_llm
    from ..subtitle_rules.sentence_refine_ranges import build_range_replacement
    from .link_tools import check_cancel

    if text_ai_key_missing(settings, "group"):
        return parsed, dict(status="missing_settings", applied=0, fallback=len(parsed.captions))
    project, source = _project(parsed, language)
    try:
        outcome = refine_cues_with_llm(project.cues, project=project, runtime_settings=settings,
            boundary_only=True, cancel_check=cancel, max_attempts=3, on_progress=on_progress,
            max_extra_calls=min(32, max(4, len(source) // 20 + 2)),
            max_extra_tokens=min(100000, max(14000, 160 * len(source))))
    except (RefineError, OSError, RuntimeError, ValueError):
        check_cancel(cancel)
        return parsed, dict(status="failed", applied=0, fallback=len(source))
    check_cancel(cancel)
    actions = {action.cue_id: action for action in outcome.actions}
    replacements = {}
    used = set(source)
    invalid = 0
    for unit in outcome.ranges:
        action = actions.get(unit.cue.id)
        if action is None or action.action == "keep":
            continue
        input_rows = [source[cue.id] for cue in unit.originals]
        try:
            candidate = build_range_replacement(unit, action, project, used)
            before = _compact("".join(row.text for row in input_rows))
            after = _compact("".join(row.text for row in candidate))
            if not candidate or before != after:
                invalid += len(input_rows)
                continue
            if [(r.start_ms, r.end_ms, r.text) for r in candidate] == [
                    (r.start_ms, r.end_ms, r.text) for r in input_rows]:
                continue
            replacements[unit.originals[0].id] = [_caption(row, input_rows) for row in candidate]
            for cue in unit.originals[1:]:
                replacements[cue.id] = []
        except (RefineError, ValueError):
            invalid += len(input_rows)
    result = [row for cue in project.cues for row in replacements.get(cue.id, [source[cue.id]])]
    if _compact("".join(row.text for row in result)) != _compact("".join(row.text for row in parsed.captions)):
        return parsed, dict(status="failed", applied=0, fallback=len(source))
    failures = len(outcome.failed_cue_ids) + invalid
    applied = sum(bool(rows) for rows in replacements.values())
    status = ("partial" if applied else "failed") if failures or outcome.llm_status != "completed" else "completed"
    return replace(parsed, captions=result, sentence_ranges=[]), dict(status=status, applied=applied, fallback=failures)
