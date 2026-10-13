"""Unmeasured Japanese cuts move to a clear pause; everything else stays (2026-10-12)."""
from types import SimpleNamespace

import numpy as np

from twobyteasr import cue_boundary_refine as cbr

SR = 16000


def audio(segments, total_ms=6000, seed=1):
    """``segments``: (start_ms, end_ms, kind) with kind 'speech' (band noise) or 'music' (steady tones)."""
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.0005, total_ms * SR // 1000)
    t = np.arange(x.size) / SR
    for start, end, kind in segments:
        a, b = start * SR // 1000, end * SR // 1000
        if kind == "speech":
            noise = rng.normal(0, 1, b - a)
            spectrum = np.fft.rfft(noise)
            freqs = np.fft.rfftfreq(b - a, 1 / SR)
            spectrum[(freqs < 300) | (freqs > 3400)] = 0
            x[a:b] += 0.2 * np.fft.irfft(spectrum, n=b - a) / np.std(np.fft.irfft(spectrum, n=b - a))
        else:
            x[a:b] += 0.2 * (np.sin(2 * np.pi * 440 * t[a:b]) + np.sin(2 * np.pi * 1320 * t[a:b]))
    return x.astype(np.float32)


def cue(id, start, end, speaker="S01"):
    return SimpleNamespace(id=id, start_ms=start, end_ms=end, speaker=speaker)


def test_late_cut_moves_to_the_end_of_the_pause():
    pcm = audio([(500, 2000, "speech"), (2200, 4000, "speech")])
    # The next line's speech starts at 2200 ms but the estimated cut is at 2500 ms.
    changes = cbr.refine_cuts([cue("a", 400, 2500), cue("b", 2500, 4200)], pcm, SR)
    assert len(changes) == 1
    assert abs(changes[0].new_ms - 2200) <= 30 and changes[0].old_ms == 2500


def test_measured_cuts_other_speakers_and_cuts_in_the_pause_stay():
    pcm = audio([(500, 2000, "speech"), (2200, 4000, "speech")])
    lines = [cue("a", 400, 2500), cue("b", 2500, 4200)]
    assert cbr.refine_cuts(lines, pcm, SR, measured_start=lambda c: 2210 if c.id == "b" else None) == []
    assert cbr.refine_cuts([cue("a", 400, 2500), cue("b", 2500, 4200, speaker="S02")], pcm, SR) == []
    assert cbr.refine_cuts([cue("a", 400, 2100), cue("b", 2100, 4200)], pcm, SR) == []   # cut already in the pause


def test_gap_filled_by_music_or_a_far_pause_is_not_used():
    music = audio([(500, 2000, "speech"), (2000, 2200, "music"), (2200, 4000, "speech")])
    assert cbr.refine_cuts([cue("a", 400, 2500), cue("b", 2500, 4200)], music, SR) == []
    far = audio([(500, 1500, "speech"), (1700, 4000, "speech")])
    # The pause ends 800 ms before the cut: beyond the 400 ms cap.
    assert cbr.refine_cuts([cue("a", 400, 2500), cue("b", 2500, 4200)], far, SR) == []


def test_runtime_cues_keep_alignment_edges_in_step():
    pcm = audio([(500, 2000, "speech"), (2200, 4000, "speech")])
    left = SimpleNamespace(start=0.4, end=2.5, speaker="S01", forced_alignment={"segments": [
        {"start_ms": 500, "end_ms": 2500, "start_basis": "model", "end_basis": "cue_edge"}]})
    right = SimpleNamespace(start=2.5, end=4.2, speaker="S01", forced_alignment={"segments": [
        {"start_ms": 2500, "end_ms": 4000, "start_basis": "cue_edge", "end_basis": "model"}]})
    events = []
    legacy = SimpleNamespace(record_run_event=lambda name, **values: events.append((name, values)))
    receipts = cbr.apply_to_runtime_cues([left, right], pcm, legacy)
    assert len(receipts) == 1 and left.end == right.start == receipts[0]["new_ms"] / 1000
    assert left.forced_alignment["segments"][-1]["end_ms"] == receipts[0]["new_ms"]
    assert right.forced_alignment["segments"][0]["start_ms"] == receipts[0]["new_ms"]
    assert events[0][0] == "cut_pause_snap" and events[0][1]["moved"] == 1
