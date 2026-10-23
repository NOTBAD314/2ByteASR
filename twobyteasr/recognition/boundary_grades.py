"""How reliable every cut position of a caption is (2026-10-22, MFA plan step 3).

The user asked that a position in the text may be cut on its own only when
it maps to the sound reliably; other positions stay whole or ask for a new
alignment. One aligner's boundary is no proof: MFA has no confidence, and
on a real clip some of its line starts were hundreds of milliseconds off
(“哇 她会喷火”: 230 ms after the sound). A boundary therefore counts as
independent only when a second piece
of evidence agrees within ``AGREE_MS``: the other aligner (Qwen3 for MFA,
MFA for Qwen3) measuring the same text position, or a clear pause in the
speech band at that time.

Each position is an index into the caption text (a cut goes before that
character); 0 is the line start and ``len(text)`` the line end:

* ``independent`` - measured on both sides and confirmed;
* ``whole`` - inside one aligned unit (a word the aligner did not split, a
  merged span): cut at a neighbouring word boundary instead;
* ``unreliable`` - a boundary the aligner offered but did not measure
  (window or caption edge, interpolated), or one nothing confirmed, or one
  the two aligners place apart: re-align before cutting there.
"""
from __future__ import annotations

AGREE_MS = 50
POLICY = "boundary-grades-v1"
GRADES = ("independent", "whole", "unreliable")
# Speech-band pause evidence (same measure as cue_boundary_refine).
PAUSE_CONTEXT_MS = 600
PAUSE_MIN_RANGE_DB = 12.0
PAUSE_LEVEL = 0.3
PAUSE_MIN_MS = 60


def _content_starts(text: str) -> list[int]:
    from ..forced_alignment import content_char_map
    return [start for _char, start, _end in content_char_map(text)]


def _boundaries(pieces) -> dict:
    """``{position: (interval_ms, measured, basis)}`` of one alignment's pieces, edges included."""
    pieces = sorted(pieces or (), key=lambda piece: int(piece["char_start"]))
    if not pieces:
        return {}
    out = {}
    first, last = pieces[0], pieces[-1]
    out["start"] = ((int(first["start_ms"]), int(first["start_ms"])), first.get("start_basis") == "model",
                    str(first.get("start_basis")))
    out["end"] = ((int(last["end_ms"]), int(last["end_ms"])), last.get("end_basis") == "model", str(last.get("end_basis")))
    for left, right in zip(pieces, pieces[1:]):
        a, b = int(left["end_ms"]), int(right["start_ms"])
        measured = left.get("end_basis") == "model" and right.get("start_basis") == "model"
        basis = "model" if measured else f"{left.get('end_basis')}/{right.get('start_basis')}"
        out[int(right["char_start"])] = ((min(a, b), b), measured, basis)
    return out


def _distance(one, other) -> int:
    return max(0, other[0] - one[1], one[0] - other[1])


def _find(bounds: dict, low: int, high: int):
    """The boundary whose position lies in ``(low, high]`` (punctuation may sit between)."""
    for position, value in bounds.items():
        if position not in ("start", "end") and low < position <= high:
            return value
    return None


def grade_caption(text: str, primary, second=None, pause=None, *, agree_ms: int = AGREE_MS) -> list[dict]:
    """One row per cut position of ``text`` (see the module docstring).

    ``primary`` / ``second``: aligned pieces (``char_start``, ``char_end``,
    ``start_ms``, ``end_ms``, ``*_basis``) of this text on one clock.
    ``pause(a_ms, b_ms, side)`` returns a pause ``(start_ms, end_ms)`` that
    ends at the span (``side="start"``: silence before a line onset), starts
    at it (``"end"``) or touches it (``"gap"``), or None.
    """
    starts = _content_starts(text)
    first_bounds, second_bounds = _boundaries(primary), _boundaries(second)
    if not starts or not first_bounds:
        return []
    positions = [("start", 0, None)]
    positions += [("gap", starts[j], starts[j - 1]) for j in range(1, len(starts))]
    positions.append(("end", len(text), None))
    rows = []
    for key, position, previous in positions:
        if key == "gap":
            found, other = _find(first_bounds, previous, position), _find(second_bounds, previous, position)
        else:
            found, other = first_bounds.get(key), second_bounds.get(key)
        row = {"pos": position}
        if key == "gap" and found is None:
            row.update(grade="whole", reason="inside_unit")
            rows.append(row)
            continue
        interval, measured, basis = found
        row["at_ms"] = list(interval)
        if not measured:
            row.update(grade="unreliable", reason=f"unmeasured:{basis}")
            rows.append(row)
            continue
        if other is not None and other[1]:
            row["second_ms"] = list(other[0])
            row["delta_ms"] = _distance(interval, other[0])
            if row["delta_ms"] <= agree_ms:
                row.update(grade="independent", reason="second_aligner")
                rows.append(row)
                continue
        heard = pause(*interval, key) if pause is not None else None
        if heard is not None:
            row.update(grade="independent", reason="pause", pause_ms=list(heard))
        elif "delta_ms" in row:
            row.update(grade="unreliable", reason="aligners_disagree")
        else:
            row.update(grade="unreliable", reason="unconfirmed")
        rows.append(row)
    return rows


def caption_boundaries(project, cue, refs=None) -> tuple[list[dict], str]:
    """``(rows, reason)``: the graded cut positions of ``cue``'s current text, for Studio.

    Read from the caption's alignment row (``cue-align:<id>``, or one named in
    ``refs`` / its evidence refs). A caption split in Studio reads its own
    slice of the row (positions shifted; the split point becomes its start or
    end). No rows when the caption has none, was never graded, or its text
    is no longer (exactly once) in the aligned text: every position then
    needs a new alignment. Times stay on the evidence clock.
    """
    from .cue_forced_alignment import CUE_ALIGNMENT_PREFIX
    evidence = getattr(project, "asr_evidence", None) or {}
    named = cue.evidence_refs if refs is None else refs
    keys = [CUE_ALIGNMENT_PREFIX + str(cue.id), *(str(ref) for ref in named or () if str(ref).startswith(CUE_ALIGNMENT_PREFIX))]
    reason = "no_caption_alignment"
    for key in dict.fromkeys(keys):
        row = evidence.get(key)
        if not isinstance(row, dict):
            continue
        alignment = (row.get("caption_arbitration") or {}).get("forced_alignment") or {}
        graded = alignment.get("boundaries")
        if not graded:
            reason = "not_graded"
            continue
        text, mine = str(row.get("text") or ""), str(cue.text)
        if text == mine:
            return [dict(item) for item in graded], str(alignment.get("boundary_policy") or POLICY)
        rows = slice_rows(graded, text, mine)
        if rows is None:
            reason = "text_changed"
            continue
        return rows, "evidence_slice"
    return [], reason


def slice_rows(graded, text: str, part: str):
    """The rows of ``part`` (found exactly once in ``text``) with positions on ``part``, or None.

    The cut that made ``part`` is its line start or end: the graded position
    there becomes ``0`` / ``len(part)``. A cut that trimmed whitespace or
    punctuation ends ``part`` before the next graded position, which is then
    its end.
    """
    offset = text.find(part) if part.strip() else -1
    if offset < 0 or text.find(part, offset + 1) >= 0:
        return None
    end = offset + len(part)
    rows = [dict(item, pos=int(item["pos"]) - offset) for item in graded or () if offset <= int(item["pos"]) <= end]
    if not any(item["pos"] == len(part) for item in rows):
        later = sorted((item for item in graded or () if int(item["pos"]) > end), key=lambda item: int(item["pos"]))
        if later:
            rows.append(dict(later[0], pos=len(part)))
    return rows


def counts(rows) -> dict:
    out = {grade: 0 for grade in GRADES}
    for row in rows or ():
        out[row["grade"]] = out.get(row["grade"], 0) + 1
    return out


class SpeechBand:
    """Speech-band (300-3400 Hz) energy of a whole track, computed once in chunks."""

    def __init__(self, pcm, sample_rate: int = 16000):
        import numpy as np
        from .cue_boundary_refine import HOP_MS, speech_band_db
        self.hop_ms = HOP_MS
        total_ms = int(len(pcm) * 1000 // sample_rate)
        parts, cursor = [], 0
        while cursor < total_ms:  # one minute at a time keeps the FFT frames small
            end = min(total_ms, cursor + 60_000)
            origin, db = speech_band_db(pcm, sample_rate, cursor, end)
            parts.append(db[: max(0, (end - cursor) // HOP_MS)])
            cursor = end
        self.db = np.concatenate(parts) if parts else np.zeros(0)

    def pause(self, a_ms: int, b_ms: int, side: str = "gap"):
        """A clear pause (``start_ms``, ``end_ms``) at ``[a_ms, b_ms]`` within ``AGREE_MS``, or None.

        ``side``: ``"start"`` - the pause ends there (a line onset after
        silence); ``"end"`` - it starts there; ``"gap"`` - it touches the span.
        """
        import numpy as np
        lo = max(0, (a_ms - PAUSE_CONTEXT_MS) // self.hop_ms)
        hi = min(self.db.size, (b_ms + PAUSE_CONTEXT_MS) // self.hop_ms + 1)
        window = self.db[lo:hi]
        if window.size < 20:
            return None
        peak, floor = np.percentile(window, 90), np.percentile(window, 10)
        if peak - floor < PAUSE_MIN_RANGE_DB:
            return None
        quiet = window < floor + PAUSE_LEVEL * (peak - floor)
        run = None
        for index in range(window.size + 1):
            if index < window.size and quiet[index]:
                run = index if run is None else run
                continue
            if run is not None and (index - run) * self.hop_ms >= PAUSE_MIN_MS:
                start, end = (lo + run) * self.hop_ms, (lo + index) * self.hop_ms
                touching = {"start": a_ms - AGREE_MS <= end <= b_ms + AGREE_MS,
                            "end": a_ms - AGREE_MS <= start <= b_ms + AGREE_MS}.get(
                    side, start <= b_ms + AGREE_MS and end >= a_ms - AGREE_MS)
                if touching:
                    return start, end
            run = None
        return None
