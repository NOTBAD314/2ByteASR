"""Move an unmeasured cut between two lines of one speaker to the pause between them.

When line breaking splits one speaker's utterance, the cut time comes from the
grouping step. Where Qwen3-ForcedAligner measured the boundary (the new line's
first piece has a model-measured start), that measurement already places the
line. Where it did not (crossing or unreliable slots), the cut was an estimate
and was often late: the new line's first syllable played while the previous
line was still shown (blind-labelled 24 min episode: median +80 ms, up to
+230 ms; model check: up to +657 ms).

The only remaining evidence for such a cut is the audio: a real change of
line usually has a pause. This module looks for one clear speech-band energy
valley just before the cut and moves the cut to the end of that pause. It
does nothing when the dip is not clear (music or noise filling the gap), when
the move would be large, or when either line would become too short. It never
touches cuts the aligner measured, line ends against silence, or other
speakers' lines. Every change is returned with its evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

HOP_MS = 10
WINDOW_MS = 25
SEARCH_BEFORE_MS = 900
SEARCH_AFTER_MS = 150
CONTEXT_AFTER_MS = 600
MIN_PAUSE_MS = 60
MIN_RANGE_DB = 12.0
PAUSE_LEVEL = 0.3          # fraction of the local dynamic range above the floor
MAX_MOVE_MS = 400
MIN_LINE_MS = 300
POLICY = "pause-snap-v1"


@dataclass(frozen=True)
class CutChange:
    left_id: str
    right_id: str
    old_ms: int
    new_ms: int
    pause_start_ms: int
    pause_end_ms: int
    range_db: float

    def receipt(self) -> dict:
        return dict(left=self.left_id, right=self.right_id, old_ms=self.old_ms, new_ms=self.new_ms,
                    pause=[self.pause_start_ms, self.pause_end_ms], range_db=round(self.range_db, 1), policy=POLICY)


def speech_band_db(pcm, sample_rate: int, start_ms: int, end_ms: int):
    """Speech-band (300-3400 Hz) energy in dB per 10 ms hop over [start_ms, end_ms)."""
    import numpy as np
    hop = sample_rate * HOP_MS // 1000
    win = sample_rate * WINDOW_MS // 1000
    a = max(0, start_ms * sample_rate // 1000)
    b = min(len(pcm), end_ms * sample_rate // 1000 + win)
    x = np.asarray(pcm[a:b], dtype=np.float64)
    if x.size < win + hop:
        return a * 1000 // sample_rate, np.zeros(0)
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1)) ** 2
    freqs = np.fft.rfftfreq(win, 1.0 / sample_rate)
    band = spectrum[:, (freqs >= 300) & (freqs <= 3400)].sum(axis=1)
    db = 10 * np.log10(band + 1e-10)
    smooth = np.convolve(db, np.ones(3) / 3, mode="same")
    return a * 1000 // sample_rate, smooth


def find_pause(pcm, sample_rate: int, cut_ms: int, floor_ms: int):
    """The pause (start, end, range_db) nearest before ``cut_ms``, or None when unclear."""
    import numpy as np
    lo = max(floor_ms, cut_ms - SEARCH_BEFORE_MS)
    origin, db = speech_band_db(pcm, sample_rate, lo, cut_ms + CONTEXT_AFTER_MS)
    if db.size < 20:
        return None
    peak, floor = np.percentile(db, 90), np.percentile(db, 10)
    if peak - floor < MIN_RANGE_DB:
        return None
    quiet = db < floor + PAUSE_LEVEL * (peak - floor)
    limit = min(db.size, (cut_ms + SEARCH_AFTER_MS - origin) // HOP_MS)
    best = None
    run_start = None
    for index in range(limit + 1):
        if index < limit and quiet[index]:
            run_start = index if run_start is None else run_start
            continue
        if run_start is not None and (index - run_start) * HOP_MS >= MIN_PAUSE_MS:
            best = (run_start, index)            # the latest clear pause before the cut wins
        run_start = None
    if best is None:
        return None
    # Speech must actually resume after the pause (not a fade into silence).
    after = db[best[1]:best[1] + 20]
    if after.size == 0 or after.max() < floor + 0.6 * (peak - floor):
        return None
    return origin + best[0] * HOP_MS, origin + best[1] * HOP_MS, float(peak - floor)


def propose_for_pair(left, right, pcm, sample_rate: int, *, offset_ms: int = 0, left_measured_end=None):
    """The move for one unmeasured cut between ``left`` and ``right`` (``pcm`` starts at ``offset_ms``)."""
    cut = int(right.start_ms)
    floor = max(int(left.start_ms) + MIN_LINE_MS, left_measured_end or 0)
    pause = find_pause(pcm, sample_rate, cut - offset_ms, max(0, floor - offset_ms))
    if pause is None:
        return None
    start, end, range_db = pause[0] + offset_ms, pause[1] + offset_ms, pause[2]
    if end >= cut:
        return None                                    # the cut already sits in (or before) the pause
    if cut - end > MAX_MOVE_MS or end - int(left.start_ms) < MIN_LINE_MS or int(right.end_ms) - end < MIN_LINE_MS:
        return None
    return CutChange(str(left.id), str(right.id), cut, int(end), int(start), int(end), range_db)


def candidate_pairs(cues, measured_start):
    """Adjacent lines of one speaker whose cut the aligner did not measure."""
    ordered = sorted(cues, key=lambda c: (int(c.start_ms), int(c.end_ms)))
    return [(left, right) for left, right in zip(ordered, ordered[1:])
            if str(left.speaker) == str(right.speaker) and abs(int(left.end_ms) - int(right.start_ms)) <= 1
            and measured_start(right) is None]


def refine_cuts(cues, pcm, sample_rate: int, *, measured_start=None, measured_end=None):
    """Proposed cut moves for adjacent same-speaker lines whose cut was not measured.

    ``cues`` are objects with ``id, start_ms, end_ms, speaker`` (any order);
    ``measured_start(cue)`` / ``measured_end(cue)`` return the model-measured
    first-word start / last-word end in ms, or None.
    """
    measured_start = measured_start or (lambda cue: None)
    measured_end = measured_end or (lambda cue: None)
    changes = []
    for left, right in candidate_pairs(cues, measured_start):
        change = propose_for_pair(left, right, pcm, sample_rate, left_measured_end=measured_end(left))
        if change is not None:
            changes.append(change)
    return changes


def _runtime_measured(cue, side):
    pieces = (getattr(cue, "forced_alignment", None) or {}).get("segments") or ()
    if not pieces:
        return None
    piece = pieces[0] if side == "start" else pieces[-1]
    return int(piece[f"{side}_ms"]) if piece.get(f"{side}_basis") == "model" else None


def apply_to_runtime_cues(cues, audio, legacy, *, sample_rate: int = 16000) -> list[dict]:
    """Recognition: snap unmeasured same-speaker cuts to pauses (after final alignment)."""
    from types import SimpleNamespace
    rows = [SimpleNamespace(id=str(index), start_ms=round(float(cue.start) * 1000), end_ms=round(float(cue.end) * 1000),
                            speaker=str(getattr(cue, "speaker", "") or "S00"), cue=cue)
            for index, cue in enumerate(cues)]
    by_id = {row.id: row for row in rows}
    changes = refine_cuts(rows, audio, sample_rate, measured_start=lambda r: _runtime_measured(r.cue, "start"),
                          measured_end=lambda r: _runtime_measured(r.cue, "end"))
    for change in changes:
        left, right = by_id[change.left_id].cue, by_id[change.right_id].cue
        left.end = right.start = change.new_ms / 1000.0
        # The aligner's edge pieces at this cut were the cue's own (estimated) edges.
        for cue, side in ((left, "end"), (right, "start")):
            pieces = (getattr(cue, "forced_alignment", None) or {}).get("segments") or []
            piece = pieces[-1] if side == "end" and pieces else pieces[0] if pieces else None
            if piece is not None and piece.get(f"{side}_basis") == "cue_edge":
                piece[f"{side}_ms"] = change.new_ms
    receipts = [c.receipt() for c in changes]
    legacy.record_run_event("cut_pause_snap", policy=POLICY, moved=len(receipts), changes=receipts[:50])
    return receipts
