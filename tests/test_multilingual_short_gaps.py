"""One end-only short-gap policy regardless of the language's reading limit."""
import copy
from types import SimpleNamespace

import pytest

from twobyteasr.subtitle_rules import timing
from twobyteasr.subtitle_rules.language_rules import language_scope

LANGUAGES = ("zh", "ja", "en", "ko", "es", "fr", "de", "pt", "it", "ru")


def cue(key, start, end, text="a complete sentence", speaker="S1"):
    return SimpleNamespace(cue_id=key, start=start, end=end, text=text, speaker=speaker,
                           forced_alignment={"segments": [{"start": start+.1, "end": end-.1, "text": text}]})


@pytest.mark.parametrize("language", LANGUAGES)
def test_long_cue_short_gap_closes_in_all_languages(language, monkeypatch):
    monkeypatch.setattr(timing, "record_run_event", lambda *args, **kwargs: None)
    rows = [cue(170, 634.0416667, 640.0833333), cue(171, 640.3333333, 644.625),
            cue(172, 645.5, 649.542)]
    evidence = [copy.deepcopy(c.forced_alignment) for c in rows]
    starts = [c.start for c in rows]
    with language_scope(language):
        timing.bridge_short_display_gaps(rows, 1000, 24)
    assert rows[0].end == pytest.approx(rows[1].start)
    assert [c.start for c in rows] == starts
    assert rows[1].end == 644.625  # long silence remains
    assert [c.forced_alignment for c in rows] == evidence


@pytest.mark.parametrize("language", ("en", "ko", "es", "fr", "de", "pt", "it", "ru"))
def test_word_language_finalizer_closes_gaps_after_duration_and_tail_caps(language, monkeypatch):
    from twobyteasr.recognition.pipeline_runtime import finalize_english_cues
    from twobyteasr.subtitle_rules import display_timing
    events = []
    def protect(rows, segments):
        rows[0].end = 5.875
        return []
    monkeypatch.setattr(display_timing, "protect_runtime_display_tails", protect)
    monkeypatch.setattr(timing, "record_run_event", lambda name, **values: events.append((name, values)))
    legacy = SimpleNamespace(
        snap_cue_starts_to_vad_onsets=lambda rows, *args: rows,
        extend_cue_tails_by_speaker=lambda rows, *args: rows,
        bridge_short_display_gaps=timing.bridge_short_display_gaps,
        relock_display_timing=timing.relock_display_timing,
        record_run_event=lambda *args, **kwargs: None,
    )
    rows = [cue(1, 0, 6), cue(2, 6.25, 7.25), cue(3, 8.25, 9.25)]
    texts = [c.text for c in rows]
    with language_scope(language):
        result = finalize_english_cues(rows, [], [], 10, 24, legacy)
    assert result[0].end == result[1].start == 6.25
    assert result[2].start-result[1].end == 1
    assert [c.text for c in result] == texts
    assert events[-1][1]["stage"] == "word_final_display"
    assert events[-1][1]["short_gaps_after"] == 0


def test_closing_late_tail_keeps_real_overlap_and_media_end(monkeypatch):
    monkeypatch.setattr(timing, "record_run_event", lambda *args, **kwargs: None)
    rows = [cue(1, 0, 5.25), cue(2, 5, 6, speaker="S2"), cue(3, 6.25, 7)]
    timing.bridge_short_display_gaps(rows, 6.1, 24)
    assert rows[0].end == 5.25  # genuine overlap is untouched
    assert rows[1].end == 6     # no extension beyond media end


@pytest.mark.parametrize("fps", [24, 25, 30, 60, 24000/1001])
def test_handoff_has_no_empty_frame_at_any_supported_grid(fps, monkeypatch):
    monkeypatch.setattr(timing, "record_run_event", lambda *args, **kwargs: None)
    rows = [cue(1, 0, 5), cue(2, 5.125, 6.5)]
    timing.relock_display_timing(rows, 10, fps)
    boundary = round(rows[1].start*fps)
    assert rows[0].end == rows[1].start
    assert all(sum(c.start <= frame/fps < c.end for c in rows) == 1
               for frame in range(boundary-2, boundary+3))
