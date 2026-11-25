"""Regression coverage for cases observed in downloaded subtitle representations."""
import json
from pathlib import Path
import re

import pytest

from twobyteasr.media.link_reconstruction import reconstruct
from twobyteasr.media.link_subtitles import parse_subtitles
from twobyteasr.media.link_manifest import preserve_subtitle


def event(start, text, *, end=2000, win=1, **values):
    segments = [dict(utf8=word, tOffsetMs=offset) if offset else dict(utf8=word) for word, offset in text]
    return dict(tStartMs=start, dDurationMs=end, wWinId=win, segs=segments, **values)


def parse(rows):
    return parse_subtitles(json.dumps(dict(events=rows)).encode(), source="automatic")


def plain(parsed):
    return re.sub(r"\s+", " ", " ".join(cue.text for cue in parsed.captions)).strip()


def test_reconstructs_across_rolling_rows_and_preserves_words_and_sound():
    rows = [
        event(100, [("Dr.", 0), (" Chen", 160), (" measured", 400), (" 3.5", 800)]),
        event(1000, [("\n", 0)], aAppend=1),
        event(1010, [("seconds.", 0), (" Yes,", 590), (" yes.", 900)]),
        event(2500, [("[Applause]", 0)]),
        event(4600, [(">>", 0), (" Wait.", 160)]),
    ]
    parsed = parse(rows)
    rebuilt = reconstruct(parsed, language="en", source="automatic")
    texts = [cue.text for cue in rebuilt.captions]
    assert texts == ["Dr. Chen measured 3.5 seconds.", "Yes, yes.", "[Applause]", ">> Wait."]
    assert plain(rebuilt) == plain(parsed)
    assert any(ref.endswith("/roll-control") for ref in rebuilt.captions[0].events)
    assert all(a.end_ms <= b.start_ms for a, b in zip(rebuilt.captions, rebuilt.captions[1:]))
    speech = reconstruct(parsed, language="en", source="automatic", keep_sound=False)
    assert plain(speech) == plain(parsed).replace(" [Applause]", "")
    assert speech.tidy["labels_removed"] == 1


def test_recovers_missing_timestamp_only_with_surrounding_evidence():
    parsed = parse([event(100, [("One", 0)]), event(None, [("two", 0)]), event(1200, [("three.", 0)])])
    assert plain(parsed) == "One two three."
    assert parsed.source_statistics["recovered_events"] == 1
    assert parsed.captions[1].start_ms == 650


@pytest.mark.parametrize(("lang", "first", "second", "expected"), [
    ("zh", "豎起耳朵", "仔細聽。", "豎起耳朵仔細聽。"),
    ("ja", "もう少し", "待ってください。", "もう少し待ってください。"),
])
def test_cjk_can_join_rows_without_inventing_space_or_crossing_windows(lang, first, second, expected):
    rows = [event(100, [(first, 0)]), event(850, [(second, 0)]),
            event(1000, [("別人。", 0)], win=2)]
    smart = reconstruct(parse(rows), language=lang, source="automatic")
    assert smart.captions[0].text == expected
    assert smart.captions[1].text == "別人。"


def test_youtube_vtt_short_clear_rows_do_not_duplicate_speech():
    raw = b"""WEBVTT

00:00:00.080 --> 00:00:01.790 align:start position:0%
@pad
yes<00:00:00.359><c> yes</c>

00:00:01.790 --> 00:00:01.800 align:start position:0%
yes yes
@pad

00:00:01.800 --> 00:00:04.590 align:start position:0%
yes yes
we<00:00:02.280><c> agree.</c>
"""
    parsed = parse_subtitles(raw.replace(b"@pad", b" "), source="automatic")
    assert plain(parsed) == "yes yes we agree."
    assert parsed.display_repeats == 2


def test_ttml_relative_time_and_raw_bytes(tmp_path):
    raw = b'<tt xmlns="http://www.w3.org/ns/ttml"><body begin="2s"><div><p begin="500ms" dur="1.5s">Hi<br/>world</p></div></body></tt>'
    track = dict(track_id="en-manual", language="en", source="manual")
    output = preserve_subtitle(tmp_path, track, raw, "ttml")
    path = tmp_path / output["original"]["path"]
    assert path.suffix == ".ttml" and path.read_bytes() == raw
    row = parse_subtitles((tmp_path / output["srt"]["path"]).read_bytes()).captions[0]
    assert (row.start_ms, row.end_ms, row.text) == (2500, 4000, "Hi\nworld")


@pytest.mark.parametrize("raw", [b"", b'{"events":[]}', b'{"events":[', b'<!DOCTYPE x><tt/>'])
def test_empty_and_damaged_source_fails_cleanly(raw):
    with pytest.raises(ValueError):
        parse_subtitles(raw)


def test_ai_download_reuses_shared_boundary_refinement_and_preserves_source_text(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.media.link_ai import refine_downloaded
    from twobyteasr.providers import llm_config
    from twobyteasr.subtitle_rules import sentence_refine

    parsed = parse([event(100, [("Hello", 0), (" world", 700)], end=1600)])
    monkeypatch.setattr(llm_config, "text_ai_key_missing", lambda settings, stage: False)

    def configured_refine(cues, **options):
        assert options["boundary_only"] and options["project"].cues == cues
        cue = cues[0]
        unit = SimpleNamespace(cue=cue, originals=[cue])
        action = sentence_refine.CueRefineAction(cue.id, "wrap", layout_text="Hello\nworld")
        return sentence_refine.RefineOutcome(actions=[action], ranges=[unit])

    monkeypatch.setattr(sentence_refine, "refine_cues_with_llm", configured_refine)
    result, ai = refine_downloaded(parsed, "en", {})
    assert result.captions[0].text == "Hello\nworld"
    assert plain(result) == plain(parsed)
    assert ai == {"status": "completed", "applied": 1, "fallback": 0}


def test_ai_download_distinguishes_missing_config_from_success(monkeypatch):
    from twobyteasr.media.link_ai import refine_downloaded
    from twobyteasr.providers import llm_config
    monkeypatch.setattr(llm_config, "text_ai_key_missing", lambda settings, stage: True)
    parsed = parse([event(100, [("Hello.", 0)])])
    result, ai = refine_downloaded(parsed, "en", {})
    assert result is parsed and ai == {"status": "missing_settings", "applied": 0, "fallback": 1}


def test_reprocess_rebuilds_from_original_when_derived_file_is_missing(tmp_path):
    from twobyteasr.media.link_manifest import (
        MANIFEST_NAME, atomic_json, load_bundle, reprocess_subtitles,
    )
    rows = [event(100, [("Hello", 0), (" world.", 700)], end=1600)]
    raw = json.dumps(dict(events=rows)).encode()
    identity = "abc123"
    track = dict(track_id=identity, video_id="video1", language="en", source="automatic")
    original = preserve_subtitle(tmp_path, track, raw, "json3")
    path = tmp_path / MANIFEST_NAME
    atomic_json(path, dict(version=1, task_id="my-job", video_id="video1", subtitles=[original],
                          primary_track_id=identity, media=None))
    (tmp_path / original["normalized"]["path"]).unlink()
    reprocess_subtitles(path, "my-job", "original")
    saved = load_bundle(path)
    assert saved["manifest"]["subtitles"][0]["original"] == original["original"]
    assert (tmp_path / original["original"]["path"]).read_bytes() == raw
    assert saved["captions"][identity]["tidy"]["mode"] == "original"
