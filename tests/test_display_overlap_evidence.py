from twobyteasr.subtitle_rules.display_timing import classify_overlap, protect_intervals


def row(label, start, end, speaker=None):
    return dict(id=label, start_ms=start, end_ms=end, speaker=speaker or label)


def test_fifty_ms_turn_gap_does_not_become_150_ms_overlap():
    changes, audit = protect_intervals([row("A", 0, 1200), row("B", 1050, 2000)], {"A": [(0, 1000)], "B": [(1050, 2000)]})
    assert changes == {"A": 1050}
    assert audit[0]["classification"] == "display_compensation"


def test_true_acoustic_overlap_is_kept():
    changes, audit = protect_intervals([row("A", 0, 1200), row("B", 950, 2000)], {"A": [(0, 1000)], "B": [(950, 2000)]})
    assert changes == {} and audit[0]["classification"] == "acoustic"


def test_same_speaker_contiguous_cues_remain_positive_and_ordered():
    rows = [row("1", 0, 1200, "A"), row("2", 1050, 1600, "A"), row("3", 1600, 2000, "A")]
    changes, _ = protect_intervals(rows, {"1": [(0, 1000)], "2": [(1050, 1600)], "3": [(1600, 2000)]})
    assert changes == {"1": 1050}
    assert all(changes.get(r["id"], r["end_ms"]) > r["start_ms"] for r in rows)


def test_missing_or_interleaved_evidence_is_uncertain_and_not_clipped():
    assert classify_overlap([], [(1, 2)]) == "uncertain"
    assert classify_overlap([(0, 500), (1000, 1500)], [(600, 900)]) == "uncertain"
    assert protect_intervals([row("A", 0, 1200), row("B", 1050, 2000)], {})[0] == {}


def test_failed_firered_uses_moss_even_with_stale_positive_alignment():
    from types import SimpleNamespace
    from twobyteasr.subtitle_rules.display_timing import project_acoustics
    project = SimpleNamespace(asr_evidence={"r": dict(moss_start=1., moss_end=2., firered_start=.5,
        firered_end=2.5, firered_alignment_confidence=.9, final_timing_owner="MOSS_DEGRADED")})
    assert project_acoustics(project, SimpleNamespace(evidence_refs=["r"])) == [(1000, 2000)]
