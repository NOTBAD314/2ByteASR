"""Forced alignment of final caption text (Japanese) and its project evidence.

Every final cue is aligned with its current text, so the stored timing
always belongs to the effective transcript. Adjacent cues of one speaker are
aligned together as one *run* (their texts joined, one audio window) and the
result is split back per cue: aligned alone on a padded window, a cue's
first word was forced onto the previous cue's last word inside the padding
(both cues then claimed the same audio). A run's window is padded only up to
other speakers' cues; overlapping speakers are still aligned independently.
The project keeps one evidence row per aligned cue: the reliable pieces
Studio may cut at, plus the raw slot predictions, the official monotonic
repair and the slot posteriors of both passes, so every millisecond can be
traced to the model.
"""
from __future__ import annotations

import copy

CUE_ALIGNMENT_PREFIX = "cue-align:"
UNIT_FIELDS = ("text", "char_start", "char_end", "kind", "word_index", "raw_start_ms", "raw_end_ms",
               "start_ms", "end_ms", "start_basis", "end_basis", "start_p", "end_p",
               "start_local", "end_local", "start_spread_ms", "end_spread_ms")
WINDOW_PAD_MS = 300
# Same-speaker cues closer than this share one alignment run.
RUN_GAP_MS = 2 * WINDOW_PAD_MS
RUN_MAX_MS = 30_000
RUN_MAX_CUES = 8
RUN_SEPARATOR = " "
# A pause of this length (voice activity) between two lines ends a run even
# when display tails and short-gap bridging made the lines touch.
RUN_PAUSE_BREAK_MS = 700


def _compact(units):
    if not units:
        return []
    return [[unit.get(name) for name in UNIT_FIELDS] for unit in units]


def expand_units(rows):
    return [dict(zip(UNIT_FIELDS, row)) for row in rows or ()]


def plan_runs(rows, *, pad_ms=WINDOW_PAD_MS):
    """Group captions into alignment runs and give each run its audio window.

    ``rows``: dicts with ``key, start_ms, end_ms, speaker, text``. Captions of
    one speaker that follow each other (gap <= RUN_GAP_MS, nobody else in
    between) form a run; its text is the members' texts joined by a space
    (a tokenizer and alignment break), ``spans`` give each member's range in
    it. The window is padded by ``pad_ms`` but never into another run that
    lies before/after it; truly overlapping speech cannot be excluded.
    """
    order = sorted((row for row in rows if int(row["end_ms"]) > int(row["start_ms"]) and str(row["text"]).strip()),
                   key=lambda row: (int(row["start_ms"]), int(row["end_ms"])))
    runs = []
    for row in order:
        last = runs[-1] if runs else None
        if (last and last["speaker"] == row["speaker"] and int(row["start_ms"]) - last["end_ms"] <= RUN_GAP_MS
                and not row.get("break_before")
                and len(last["members"]) < RUN_MAX_CUES and int(row["end_ms"]) - last["start_ms"] <= RUN_MAX_MS):
            last["members"].append(row)
            last["end_ms"] = max(last["end_ms"], int(row["end_ms"]))
        else:
            runs.append({"speaker": row["speaker"], "members": [row], "start_ms": int(row["start_ms"]),
                         "end_ms": int(row["end_ms"])})
    for run in runs:
        left, right = max(0, run["start_ms"] - pad_ms), run["end_ms"] + pad_ms
        for other in runs:
            if other is run:
                continue
            if left < other["end_ms"] <= run["start_ms"]:
                left = other["end_ms"]
            if run["end_ms"] <= other["start_ms"] < right:
                right = other["start_ms"]
        run["window_start_ms"], run["window_end_ms"] = left, right
        texts, spans, cursor = [], [], 0
        for member in run["members"]:
            text = str(member["text"])
            spans.append((cursor, cursor + len(text)))
            texts.append(text)
            cursor += len(text) + len(RUN_SEPARATOR)
        run["text"] = RUN_SEPARATOR.join(texts)
        run["spans"] = spans
    return runs


def _units_in(rows, start, end):
    out = []
    for unit in rows or ():
        if start <= int(unit["char_start"]) and int(unit["char_end"]) <= end:
            moved = dict(unit)
            moved["char_start"], moved["char_end"] = int(unit["char_start"]) - start, int(unit["char_end"]) - start
            out.append(moved)
    return out


def _member_pieces(segments, start, end, edge_start_ms, edge_end_ms):
    """Pieces of one member: inside ones as measured; edges completed with the caption's own times.

    A piece crossing the member edge means the model did not measure that
    boundary: the member keeps its own part, with the caption's start/end at
    that side (basis ``cue_edge``), so the text stays fully covered and only
    measured inner boundaries are ever offered as cut points.
    """
    pieces, crossing = [], 0
    for piece in segments or ():
        a, b = int(piece["char_start"]), int(piece["char_end"])
        if b <= start or a >= end:
            continue
        part = dict(piece, char_start=max(a, start) - start, char_end=min(b, end) - start)
        if a < start or b > end:
            crossing += 1
            part["granularity"] = "merged"
            if a < start:
                part["start_ms"], part["start_basis"] = int(edge_start_ms), "cue_edge"
            if b > end:
                part["end_ms"], part["end_basis"] = int(edge_end_ms), "cue_edge"
        pieces.append(part)
    pieces.sort(key=lambda piece: piece["char_start"])
    if pieces and pieces[0].get("start_basis") != "model":
        pieces[0] = dict(pieces[0], start_ms=int(edge_start_ms), start_basis="cue_edge")
    if pieces and pieces[-1].get("end_basis") != "model":
        pieces[-1] = dict(pieces[-1], end_ms=int(edge_end_ms), end_basis="cue_edge")
    measured_inner = any(piece.get("start_basis") == "model" or piece.get("end_basis") == "model"
                         for piece in pieces)
    if not measured_inner or any(int(p["end_ms"]) <= int(p["start_ms"]) for p in pieces) or any(
            int(left["end_ms"]) > int(right["start_ms"]) for left, right in zip(pieces, pieces[1:])):
        return [], crossing
    return pieces, crossing


def split_run_row(row, run, *, edge_shift_ms=0):
    """Per-member parts of one run result.

    ``edge_shift_ms`` converts the members' caption times into the clock of
    ``row`` (0 for the recognition task clock).
    """
    out = []
    for member, (start, end) in zip(run["members"], run["spans"]):
        pieces, crossing = _member_pieces(row.get("segments"), start, end,
                                          int(member["start_ms"]) - edge_shift_ms,
                                          int(member["end_ms"]) - edge_shift_ms)
        stats = dict(row.get("stats") or {})
        stats["run"] = {"members": len(run["members"]), "offset": start, "edge_pieces_split": crossing}
        out.append({"text": row["text"][start:end], "segments": pieces,
                    "stats": stats, "word_units": _units_in(row.get("word_units"), start, end),
                    "char_units": (_units_in(row.get("char_units"), start, end)
                                   if row.get("char_units") is not None else None)})
    return out


def longest_silence_ms(speech_regions, start_ms, end_ms):
    """Longest stretch inside [start_ms, end_ms) not covered by a voice-activity region (seconds dicts)."""
    regions = sorted((max(start_ms, round(float(r["start"]) * 1000)), min(end_ms, round(float(r["end"]) * 1000)))
                     for r in speech_regions or ())
    longest, cursor = 0, start_ms
    for a, b in regions:
        if b <= a:
            continue
        longest = max(longest, a - cursor)
        cursor = max(cursor, b)
    return max(longest, end_ms - cursor)


def alignment_jobs(cues, *, language="Japanese", pad_ms=WINDOW_PAD_MS, speech_regions=None):
    """Worker jobs (one per run) and the runs they came from (for ``attach_results``).

    With ``speech_regions`` a line whose previous same-speaker line is
    separated from it by RUN_PAUSE_BREAK_MS of silence starts its own run.
    """
    rows = [{"key": index, "start_ms": int(round(float(getattr(cue, "start", 0.0)) * 1000)),
             "end_ms": int(round(float(getattr(cue, "end", 0.0)) * 1000)),
             "speaker": str(getattr(cue, "speaker", "") or "S00"), "text": str(getattr(cue, "text", "") or "")}
            for index, cue in enumerate(cues, 1)]
    if speech_regions:
        ordered = sorted(rows, key=lambda row: (row["start_ms"], row["end_ms"]))
        for left, right in zip(ordered, ordered[1:]):
            if left["speaker"] == right["speaker"]:
                middle = (left["start_ms"] + left["end_ms"]) // 2
                right["break_before"] = longest_silence_ms(speech_regions, middle, right["start_ms"] + 150) >= RUN_PAUSE_BREAK_MS
    runs = plan_runs(rows, pad_ms=pad_ms)
    jobs = [{"id": f"run-{number}", "window_start_ms": run["window_start_ms"], "window_end_ms": run["window_end_ms"],
             "text": run["text"], "language": language} for number, run in enumerate(runs, 1)]
    return jobs, runs


def attach_results(cues, runs, payload):
    """Attach each cue's part of its run result as ``cue.forced_alignment``."""
    by_id = {str(row.get("id")): row for row in payload.get("results") or ()}
    meta = {key: payload.get(key) for key in ("model", "model_revision", "code", "unit_policy", "dtype", "torch_version")}
    attached = 0
    for number, run in enumerate(runs, 1):
        row = by_id.get(f"run-{number}")
        if row is None or row.get("text") != run["text"]:
            continue
        for member, part in zip(run["members"], split_run_row(row, run)):
            cue = cues[member["key"] - 1]
            if part["text"] != str(getattr(cue, "text", "")):
                continue
            cue.forced_alignment = {
                **meta, "language": row.get("language"), "status": row.get("status"), "mapping": row.get("mapping"),
                "text": part["text"], "window_start_ms": row.get("window_start_ms"),
                "window_end_ms": row.get("window_end_ms"),
                "run": {"id": f"run-{number}", "members": len(run["members"]), "text": run["text"]},
                "segments": copy.deepcopy(part["segments"]), "stats": copy.deepcopy(part["stats"]),
                "tokenizer_words": list(row.get("tokenizer_words") or []),
                "units_word": _compact(part["word_units"]), "units_char": _compact(part["char_units"]),
                "unit_fields": list(UNIT_FIELDS)}
            attached += 1
    return attached


def align_final_cues(cues, audio, legacy, *, language="Japanese", speech_regions=None):
    """Align every final cue's own text; failures leave cues without words."""
    cues = list(cues)
    jobs, runs = alignment_jobs(cues, language=language, speech_regions=speech_regions)
    if not jobs:
        return 0
    from twobyteasr.asr import AlignerUnavailableError, run_qwen_aligner_worker, summarize_aligner_payload
    try:
        payload = run_qwen_aligner_worker(audio, jobs)
    except AlignerUnavailableError as exc:
        legacy.add_review_item(0.0, "缺少对齐模型", str(exc), priority=3, severity="warning")
        legacy.record_run_event("forced_alignment_unavailable", stage="final_cues", reason=str(exc))
        return 0
    attached = attach_results(cues, runs, payload)
    legacy.record_run_event("forced_alignment", stage="final_cues", language=language, attached=attached,
                            runs=len(runs), **summarize_aligner_payload(payload))
    return attached


def evidence_row(cue_id, start_ms, end_ms, speaker_id, alignment):
    """Project evidence row for one aligned cue (time = task/recognition clock)."""
    pieces = []
    text = str(alignment.get("text") or "")
    for piece in alignment.get("segments") or ():
        a, b = int(piece["start_ms"]), int(piece["end_ms"])
        fragment = text[int(piece["char_start"]):int(piece["char_end"])]
        if b > a and fragment.strip():
            pieces.append({"text": fragment, "start_ms": a, "end_ms": b, "char_start": int(piece["char_start"]),
                           "char_end": int(piece["char_end"]), "model": "qwen3_forced_aligner",
                           "granularity": piece.get("granularity"), "start_basis": piece.get("start_basis"),
                           "end_basis": piece.get("end_basis")})
    return {
        "start_ms": int(start_ms), "end_ms": int(end_ms), "text": text, "speaker_id": str(speaker_id),
        "primary_source": "qwen3-forced-aligner", "final_timing_owner": "Qwen3-ForcedAligner",
        "final_text_owner": "current caption text",
        "cue_alignment": {key: alignment.get(key) for key in (
            "model", "model_revision", "code", "unit_policy", "language", "status", "mapping", "stats",
            "window_start_ms", "window_end_ms", "run")} | {"cue_id": str(cue_id)},
        "words": [{k: p[k] for k in ("text", "start_ms", "end_ms")} for p in pieces],
        "caption_arbitration": {"acoustic_words": pieces, "forced_alignment": {
            "unit_fields": alignment.get("unit_fields"), "units_word": alignment.get("units_word"),
            "units_char": alignment.get("units_char"), "tokenizer_words": alignment.get("tokenizer_words")}},
    }


def remap_whitespace_only(alignment, text):
    """Alignment re-indexed onto ``text`` when only whitespace differs, else None.

    The delivery step normalises formatting whitespace after alignment; every
    other character must be identical and in the same order.
    """
    old = str(alignment.get("text") or "")
    if old == text:
        return alignment
    old_positions = [i for i, c in enumerate(old) if not c.isspace()]
    new_positions = [i for i, c in enumerate(text) if not c.isspace()]
    if [old[i] for i in old_positions] != [text[i] for i in new_positions]:
        return None
    index = {o: n for o, n in zip(old_positions, new_positions)}

    def start(value):
        following = [o for o in old_positions if o >= value]
        return index[following[0]] if following else len(text)

    def end(value):
        preceding = [o for o in old_positions if o < value]
        return index[preceding[-1]] + 1 if preceding else 0

    moved = copy.deepcopy(alignment)
    moved["text"] = text
    for piece in moved.get("segments") or ():
        piece["char_start"], piece["char_end"] = start(int(piece["char_start"])), end(int(piece["char_end"]))
    for key in ("units_word", "units_char"):
        for row in moved.get(key) or ():
            row[1], row[2] = start(int(row[1])), end(int(row[2]))
    moved["whitespace_remapped"] = True
    return moved


def attach_project_evidence(project, runtime_cues):
    """Give each aligned project cue its own alignment row as preferred evidence."""
    added = 0
    for runtime_cue, cue in zip(runtime_cues, project.cues):
        alignment = getattr(runtime_cue, "forced_alignment", None)
        alignment = remap_whitespace_only(alignment, cue.text) if alignment else None
        if not alignment:
            continue
        reference = CUE_ALIGNMENT_PREFIX + cue.id
        project.asr_evidence[reference] = evidence_row(cue.id, cue.start_ms, cue.end_ms, cue.speaker_id, alignment)
        cue.evidence_refs = [reference, *[ref for ref in cue.evidence_refs if ref != reference]]
        added += 1
    if added:
        project.generation_metadata["cue_forced_alignment"] = {
            "rows": added, "prefix": CUE_ALIGNMENT_PREFIX, "policy": "per-cue current text; reliable pieces only"}
    return added


def is_cue_alignment_row(row) -> bool:
    return isinstance(row, dict) and isinstance(row.get("cue_alignment"), dict)
