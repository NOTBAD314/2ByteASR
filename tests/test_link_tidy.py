"""Downloaded captions are tidied (2026-10-26, user: "[music] 這種無意義的詞也可以都刪了，
且斷句都比較奇怪所以需要再嚴格重排", and the downloaded SRT lost YouTube's word timing)."""
import json

from twobyteasr.media.link_subtitles import parse_subtitles, srt_bytes, words_vtt_bytes
from twobyteasr.media.link_tidy import strip_labels, tidy_captions
from twobyteasr.timeline.link_timing import onset_words


def seg(text, offset=None):
    value = {"utf8": text}
    if offset is not None:
        value["tOffsetMs"] = offset
    return value


# YouTube automatic captions: rolling rows, one segment per word, labels and a speaker mark.
AUTO = {"events": [
    {"tStartMs": 0, "dDurationMs": 1500, "wWinId": 1, "segs": [seg("[Music]")]},
    {"tStartMs": 2000, "dDurationMs": 2400, "wWinId": 1, "segs": [
        seg("Breaking"), seg(" people's", 600), seg(" faces", 1120), seg(" in", 1600), seg(" MMA", 1760),
        seg(" has", 2120), seg(" been", 2280)]},
    {"tStartMs": 4440, "dDurationMs": 1500, "wWinId": 1, "segs": [
        seg("America's"), seg(" new", 480), seg(" favorite", 680), seg(" pastime", 1040), seg(" and", 1480)]},
    {"tStartMs": 6000, "dDurationMs": 1200, "wWinId": 1, "segs": [
        seg("that's"), seg(" what", 160), seg(" we", 280), seg(" do.", 400)]},
    {"tStartMs": 7300, "dDurationMs": 900, "wWinId": 1, "segs": [seg(">>"), seg(" Nice", 100), seg(" shot.", 400)]},
    {"tStartMs": 12000, "dDurationMs": 800, "wWinId": 1, "segs": [seg("wearing")]},
]}


def parsed(source="automatic"):
    return parse_subtitles(json.dumps(AUTO).encode("utf-8"), source=source)


def test_labels_are_removed_from_text():
    assert strip_labels("[Music] okay ♪ let's go [Applause]") == ("okay let's go", False, 3)
    assert strip_labels(">> [screaming and groaning]") == ("", True, 2)
    assert strip_labels("plain words") == ("plain words", False, 0)


def test_automatic_captions_are_rebroken_into_sentences_with_word_times():
    tidy = tidy_captions(parsed(), language="en", source="automatic")
    texts = [c.text for c in tidy.captions]
    # 93 characters is over two lines (84): the break goes before "and", not after "been".
    assert texts == ["Breaking people's faces in MMA has been America's new favorite pastime",
                     "and that's what we do.", "Nice shot.", "wearing"]
    assert tidy.tidy["labels_removed"] == 2 and tidy.tidy["regrouped"]
    first = tidy.captions[0]
    words = onset_words(first.text, first.anchors, first.start_ms, first.end_ms, "r")
    assert [w["text"] for w in words][:3] == ["Breaking", "people's", "faces"]
    assert words[0]["start_ms"] == 2000 and words[-1]["text"] == "pastime"
    # The speaker mark and the long pause before "wearing" both end a subtitle.
    assert tidy.captions[2].start_ms == 7400 and tidy.captions[3].start_ms == 12000


def test_uploaded_captions_keep_their_lines_and_lose_only_labels():
    tidy = tidy_captions(parsed(source="manual"), language="en", source="manual")
    assert not tidy.tidy["regrouped"]
    assert all("[" not in c.text and ">>" not in c.text for c in tidy.captions)
    assert len(tidy.captions) == 5        # the [Music]-only row is gone, the rest keep their rows


def test_rows_are_kept_when_regrouping_is_off_or_the_language_has_no_breaker():
    for kwargs in (dict(language="en", regroup=False), dict(language="zh-Hans")):
        tidy = tidy_captions(parsed(), source="automatic", **kwargs)
        assert not tidy.tidy["regrouped"] and len(tidy.captions) == 5


def test_derived_files_have_sentences_and_word_times():
    tidy = tidy_captions(parsed(), language="en", source="automatic")
    srt = srt_bytes(tidy).decode("utf-8")
    assert "[Music]" not in srt and "America's new favorite pastime\n\n2" in srt
    vtt = words_vtt_bytes(tidy).decode("utf-8")
    assert vtt.startswith("WEBVTT\n") and "Breaking<00:00:02.600><c> people's</c>" in vtt
    assert parse_subtitles(vtt.encode("utf-8")).format == "vtt"


def test_preserved_download_writes_tidied_srt_and_word_vtt(tmp_path):
    from twobyteasr.media.link_manifest import preserve_subtitle
    track = dict(track_id="en-auto", platform="Youtube", video_id="BaW_jenozKc", language="en", source="automatic")
    receipt = preserve_subtitle(tmp_path, track, json.dumps(AUTO).encode("utf-8"), "json3")
    srt = (tmp_path / receipt["srt"]["path"]).read_text("utf-8")
    assert "[Music]" not in srt and srt.count("-->") == 4
    assert (tmp_path / receipt["words_vtt"]["path"]).read_text("utf-8").startswith("WEBVTT")
    assert receipt["tidy"]["regrouped"] and receipt["parser_version"] == "3"
    original = (tmp_path / receipt["original"]["path"]).read_bytes()
    assert b"[Music]" in original          # the original stays exactly as downloaded
