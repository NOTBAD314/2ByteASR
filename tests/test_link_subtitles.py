import json
from pathlib import Path

import pytest

from twobyteasr.media.link_catalog import subtitle_tracks, youtube_url, video_catalog
from twobyteasr.media.link_subtitles import parse_subtitles, srt_bytes
from twobyteasr.media.link_manifest import preserve_subtitle, resolve_relative, load_bundle, atomic_json, file_receipt, discover_companions


def raw(value):
    return json.dumps(value).encode()


def entry(lang="en", kind="", translated=""):
    query = f"lang={lang}&kind={kind}&fmt=json3&sig=secret"
    if translated:
        query += "&tlang=" + translated
    return dict(ext="json3", url="https://www.youtube.com/api/timedtext?" + query)


def test_track_identity_keeps_manual_auto_translation_and_deduplicates_alias():
    info = dict(id="BaW_jenozKc", subtitles={"en": [entry()]}, automatic_captions={
        "en": [entry(kind="asr")], "en-orig": [entry(kind="asr")],
        "zh-Hans": [entry(kind="asr", translated="zh-Hans")],
        "de": [dict(ext="vtt", url="https://example.test/sub.vtt")]})
    tracks = subtitle_tracks(info)
    assert len(tracks) == 4
    assert {t["source"] for t in tracks} == {"manual", "automatic", "translated", "unknown"}
    automatic = next(t for t in tracks if t["source"] == "automatic")
    assert automatic["aliases"] == ["en", "en-orig"]
    translated = next(t for t in tracks if t["source"] == "translated")
    assert translated["original_language"] == "en"
    assert translated["language"] == "zh-Hans"
    assert translated["parent_track_id"] == automatic["track_id"]
    assert translated["parent_source"] == "automatic"
    changed = json.loads(json.dumps(info).replace("sig=secret", "sig=refreshed"))
    assert [t["track_id"] for t in tracks] == [t["track_id"] for t in subtitle_tracks(changed)]


def test_playlist_parameters_are_removed_and_non_video_urls_rejected():
    assert youtube_url("https://youtu.be/BaW_jenozKc?list=PLfoo&t=2")[0] == "https://www.youtube.com/watch?v=BaW_jenozKc"
    for value in ("https://youtube.com/playlist?list=123", "file:///tmp/a", "https://youtube.com.evil/watch?v=BaW_jenozKc"):
        with pytest.raises(ValueError):
            youtube_url(value)


def test_no_subs_and_incomplete_catalog_are_distinct():
    data = dict(id="BaW_jenozKc", subtitles={}, automatic_captions={})
    assert video_catalog(data)["subtitle_status"] == "none"
    assert video_catalog(data, subtitle_warning=True)["subtitle_status"] == "incomplete"
    assert video_catalog(dict(id="BaW_jenozKc"))["subtitle_status"] == "incomplete"


def test_json3_multi_character_segments_are_start_anchors_not_words():
    parsed = parse_subtitles(raw(dict(events=[dict(tStartMs=1000, dDurationMs=3000,
        segs=[dict(utf8="你好世界", tOffsetMs=0), dict(utf8=" &amp; hello", tOffsetMs=1200)])])))
    cue = parsed.captions[0]
    assert (cue.start_ms, cue.end_ms, cue.text) == (1000, 4000, "你好世界 & hello")
    assert len(cue.anchors) == 2
    assert cue.anchors[0]["text"] == "你好世界"
    assert cue.anchors[1]["start_ms"] == 2200
    assert all("end_ms" not in a for a in cue.anchors)
    assert cue.precision == "segment_start"


def test_json3_missing_fields_and_append_controls():
    parsed = parse_subtitles(raw(dict(events=[
        dict(wWinId=1), dict(tStartMs=0, dDurationMs=2000, wWinId=1, segs=[dict(utf8="hello")]),
        dict(tStartMs=500, wWinId=1, aAppend=1, segs=[dict(utf8="world", tOffsetMs=0)]),
        dict(tStartMs=800, wWinId=1, aAppend=1, segs=[dict(utf8="\n")]),
        dict(segs=[dict(utf8="missing")])])))
    assert len(parsed.captions) == 1
    assert parsed.captions[0].text == "hello world"
    assert parsed.captions[0].end_ms == 2000
    assert parsed.warnings


def test_same_temporal_token_is_display_duplicate_new_time_is_real_repeat():
    parsed = parse_subtitles(raw(dict(events=[
        dict(tStartMs=0, dDurationMs=2000, wWinId=1, segs=[dict(utf8="yes", tOffsetMs=1000)]),
        dict(tStartMs=500, dDurationMs=1500, wWinId=1, segs=[dict(utf8="yes", tOffsetMs=500)]),
        dict(tStartMs=2000, dDurationMs=1000, wWinId=1, segs=[dict(utf8="yes", tOffsetMs=0)])])))
    assert [c.text for c in parsed.captions] == ["yes", "yes"]
    assert parsed.display_repeats == 1
    assert "event:1/seg:0" in parsed.captions[0].events


def test_vtt_rollup_keeps_real_repetition_and_extracts_inline_times_first():
    data = """WEBVTT

00:00:01.000 --> 00:00:04.000
<c>hello</c> <00:00:02.000>world

00:00:03.500 --> 00:00:06.000
hello world
yes <00:00:04.000>yes

00:00:06.000 --> 00:00:08.000
yes yes
"""
    parsed = parse_subtitles(data.encode(), source="automatic")
    assert [c.text for c in parsed.captions] == ["hello world", "yes yes", "yes yes"]
    assert parsed.display_repeats == 1
    assert parsed.captions[0].anchors[1]["start_ms"] == 2000
    assert parsed.captions[2].precision == "sentence"
    manual = parse_subtitles(data.encode(), source="manual")
    assert manual.display_repeats == 0
    assert manual.captions[1].text == "hello world\nyes yes"


def test_bom_srt_and_real_conversion_and_format_fallback():
    data = "\ufeff1\r\n00:00:01,000 --> 00:00:02,000\r\n<i>A &amp; B</i>\r\n".encode()
    parsed = parse_subtitles(data, expected_format="vtt")
    assert parsed.captions[0].text == "A & B"
    assert parsed.format == "srt" and parsed.warnings
    assert parse_subtitles(srt_bytes(parsed)).captions[0].text == "A & B"


def test_actual_json3_roll_control_shape_ends_display_hold_without_deleting_speech():
    parsed = parse_subtitles(raw(dict(events=[
        dict(tStartMs=0,dDurationMs=10000,id=1,wpWinPosId=1),
        dict(tStartMs=800,dDurationMs=3700,wWinId=1,
             segs=[dict(utf8="yes"),dict(utf8=" yes",tOffsetMs=400)]),
        dict(tStartMs=2350,dDurationMs=2150,wWinId=1,aAppend=1,segs=[dict(utf8="\n")]),
        dict(tStartMs=2360,dDurationMs=4000,wWinId=1,segs=[dict(utf8="yes yes")])])))
    assert [c.text for c in parsed.captions]==["yes yes","yes yes"]
    assert parsed.captions[0].end_ms==2360
    assert parsed.captions[0].display_end_ms==4500
    assert parsed.captions[0].anchors[0]["start_ms"]==800
    assert parsed.captions[0].end_basis=="next_row_start_after_roll_control"


def test_portable_manifest_does_not_import_three_representations(tmp_path):
    media = tmp_path / "中文 日本語 [BaW_jenozKc].mp4"
    media.write_bytes(b"video")
    track = subtitle_tracks(dict(id="BaW_jenozKc", subtitles={"en": [entry()]}))[0]
    data = raw(dict(events=[dict(tStartMs=0, dDurationMs=1000, segs=[dict(utf8="hello")])]))
    sub = preserve_subtitle(tmp_path, track, data, "json3")
    original = (tmp_path/sub["original"]["path"]).read_bytes()
    assert b"sig=secret" not in json.dumps(sub).encode()
    manifest = tmp_path / "download.2byte-download.json"
    atomic_json(manifest, dict(version=1, task_id="a", video_id="BaW_jenozKc",
        media=file_receipt(tmp_path, media), subtitles=[sub], primary_track_id=track["track_id"]))
    assert len(load_bundle(manifest)["captions"]) == 1
    assert discover_companions(media)["automatic"] == str(manifest)
    moved = tmp_path.parent / (tmp_path.name + "-moved")
    tmp_path.rename(moved)
    assert len(load_bundle(moved/manifest.name, verify_media=True)["captions"]) == 1
    assert (moved/sub["original"]["path"]).read_bytes() == original
    with pytest.raises(ValueError):
        resolve_relative(moved, "../outside.srt")


def test_ambiguous_sidecars_require_choice(tmp_path):
    media = tmp_path/"a.mp4"
    media.write_bytes(b"video")
    for lang in ("en", "ja"):
        (tmp_path/f"a.{lang}.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi")
    found = discover_companions(media)
    assert not found["automatic"] and len(found["candidates"]) == 2
