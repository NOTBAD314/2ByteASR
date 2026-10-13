import pytest

from twobyteasr import forced_alignment as fa


def test_word_units_map_normalised_tokens_back_to_original_text():
    text = "私が本当に天才だって？ ＡＢＣ123、ｽﾄﾘｰﾄファイター６を2024年に。"
    # nagisa's actual output for this text (normalised: ABC, ストリート, digits split)
    words = ['私', 'が', '本当', 'に', '天才', 'だ', 'って', '?', '　', 'ABC', '1', '2', '3', '、',
             'ストリート', 'ファイター', '6', 'を', '2', '0', '2', '4', '年', 'に', '。']
    units = fa.word_units(text, words)
    spans = [text[u.char_start:u.char_end] for u in units]
    assert spans == ['私', 'が', '本当', 'に', '天才', 'だ', 'って', 'ＡＢＣ', '123', 'ｽﾄﾘｰﾄ', 'ファイター',
                     '６', 'を', '2024', '年', 'に']
    assert [u.text for u in units][7:10] == ['ABC', '123', 'ストリート']
    assert units[8].kind == "number" and units[13].kind == "number"   # digit runs are one unit
    assert [u.word_index for u in units] == list(range(len(units)))


def test_word_units_reject_tokenizer_output_that_does_not_match():
    with pytest.raises(fa.UnitMappingError):
        fa.word_units("恐ろしいわ", ["恐ろしい", "よ"])


def test_char_units_keep_numbers_whole_and_split_words_per_original_char():
    text = "天才ｶﾞ2024年"
    words = fa.word_units(text, ["天才", "ガ", "2", "0", "2", "4", "年"])
    chars = fa.char_units(text, words)
    assert [text[u.char_start:u.char_end] for u in chars] == ["天", "才", "ｶﾞ", "2024", "年"]
    assert [u.text for u in chars] == ["天", "才", "ガ", "2024", "年"]


def test_monotonic_repair_kinds_mirror_the_official_fix():
    raw = [0, 80, 160, 80, 240, 320]           # one out-of-order slot
    assert fa.monotonic_repair_kinds(raw) == ["model", "model", "model", "nearest", "model", "model"]
    raw = [0, 400, 480, 560, 80, 160, 240, 320, 640]   # three anomalies in a row are interpolated
    assert fa.monotonic_repair_kinds(raw) == ["model"] + ["interpolated"] * 3 + ["model"] * 5


def _unit(text, a, b, start, end, index, *, sb="model", eb="model", sl=0.9, el=0.9, kind="word"):
    return fa.TimedUnit(text, a, b, kind, index, start, end, start, end, sb, eb, 0.9, 0.9, sl, el, 40.0, 40.0)


def test_repaired_or_degenerate_word_boundaries_are_not_offered():
    words = [_unit("恐ろしい", 0, 4, 0, 700, 0), _unit("わ", 4, 5, 700, 940, 1, eb="nearest"),
             _unit("すえ", 5, 7, 1200, 1500, 2), _unit("が", 7, 8, 1500, 1500, 3), _unit("ね", 8, 9, 1500, 1700, 4)]
    segments, stats = fa.reliable_segments(words)
    # the repaired end of わ and the zero-length が each remove one boundary
    assert [(s.char_start, s.char_end) for s in segments] == [(0, 4), (4, 8), (8, 9)]
    assert stats["word_boundaries_repaired"] == 1 and stats["word_boundaries_degenerate"] == 1


def test_compressed_alignment_offers_no_inner_boundary():
    words = [_unit("天気", 0, 2, 1000, 1080, 0), _unit("いい", 2, 4, 1080, 1080, 1),
             _unit("買っちゃおうかな", 4, 12, 1080, 1160, 2)]
    segments, stats = fa.reliable_segments(words)
    assert stats["compressed"] and len(segments) == 1 and (segments[0].char_start, segments[0].char_end) == (0, 12)


def test_char_slot_cut_needs_confident_measured_slots_inside_the_word():
    word = _unit("恐ろしい", 0, 4, 1000, 1720, 0)
    chars = [_unit("恐", 0, 1, 1000, 1080, 0, kind="char"), _unit("ろ", 1, 2, 1080, 1480, 0, kind="char", sl=0.31),
             _unit("し", 2, 3, 1480, 1640, 0, kind="char"), _unit("い", 3, 4, 1640, 1720, 0, kind="char")]
    segments, stats = fa.reliable_segments([word], chars)
    assert [(s.char_start, s.char_end, s.start_ms) for s in segments] == [(0, 2, 1000), (2, 3, 1480), (3, 4, 1640)]
    assert stats["char_boundaries_rejected"] == {"low_posterior": 1}
    assert all(s.granularity == "char_slot" for s in segments)


def test_display_span_covers_symbols_between_units():
    text = "だよね～♪ 行こう"
    segments = [fa.AlignedSegment(0, 3, 0, 300, "word", "model", "model", (0,)),
                fa.AlignedSegment(6, 9, 400, 700, "word", "model", "model", (1,))]
    covered = fa.cover_display_span(text, segments)
    assert [text[s.char_start:s.char_end] for s in covered] == ["だよね～♪", "行こう"]


def test_slots_on_the_window_edge_are_clamped_not_measured():
    units = [fa.AlignUnit("言っ", 0, 2, "word", 0), fa.AlignUnit("た", 2, 3, "word", 1)]
    timed = fa.timed_units(units, [0, 240, 240, 480], [0, 240, 240, 480], 19470, window_ms=2060)
    assert timed[0].start_basis == "window_edge" and timed[0].end_basis == "model"
    timed = fa.timed_units(units, [80, 240, 240, 2000], [80, 240, 240, 2000], 0, window_ms=2060)
    assert timed[0].start_basis == "model" and timed[1].end_basis == "window_edge"
    assert fa.timed_units(units, [0, 240, 240, 480], [0, 240, 240, 480], 0)[0].start_basis == "model"


def test_adjacent_cues_of_one_speaker_are_aligned_as_one_run():
    from twobyteasr.cue_forced_alignment import plan_runs, split_run_row
    rows = [dict(key=1, start_ms=18518, end_ms=19770, speaker="S01", text="昨日は雨降るって"),
            dict(key=2, start_ms=19770, end_ms=21230, speaker="S01", text="言ってたのにね"),
            dict(key=3, start_ms=21300, end_ms=22000, speaker="S02", text="おはよう"),
            dict(key=4, start_ms=22100, end_ms=23000, speaker="S01", text="いやー")]
    runs = plan_runs(rows)
    assert [[m["key"] for m in run["members"]] for run in runs] == [[1, 2], [3], [4]]
    first, second, third = runs
    assert first["text"] == "昨日は雨降るって 言ってたのにね" and first["spans"] == [(0, 8), (9, 16)]
    # Padding stops at other speakers' captions (no foreign words inside the window).
    assert (first["window_start_ms"], first["window_end_ms"]) == (18218, 21300)
    assert (second["window_start_ms"], second["window_end_ms"]) == (21230, 22100)
    assert third["window_start_ms"] == 22000
    model = {"start_basis": "model", "end_basis": "model"}
    row = {"text": first["text"], "segments": [
        {"char_start": 0, "char_end": 3, "start_ms": 18538, "end_ms": 19178, **model},
        {"char_start": 3, "char_end": 11, "start_ms": 19418, "end_ms": 20030, **model},   # crosses the cue edge
        {"char_start": 11, "char_end": 16, "start_ms": 20270, "end_ms": 20590, **model}],
        "word_units": [{"char_start": 9, "char_end": 11, "start_ms": 19818, "end_ms": 19950}], "stats": {}}
    left, right = split_run_row(row, first)
    # The unmeasured member edge takes the caption's own time; inner boundaries stay measured.
    assert left["text"] == "昨日は雨降るって"
    assert [(p["char_start"], p["char_end"], p["start_ms"], p["end_ms"], p["end_basis"]) for p in left["segments"]] == [
        (0, 3, 18538, 19178, "model"), (3, 8, 19418, 19770, "cue_edge")]
    assert right["text"] == "言ってたのにね"
    assert [(p["char_start"], p["start_ms"], p["start_basis"]) for p in right["segments"]] == [
        (0, 19770, "cue_edge"), (2, 20270, "model")]
    assert right["word_units"][0]["char_start"] == 0 and right["stats"]["run"]["edge_pieces_split"] == 1
    # A caption without any measured boundary keeps no pieces (shown as an estimate).
    only = {"text": first["text"], "segments": [
        {"char_start": 0, "char_end": 16, "start_ms": 18300, "end_ms": 20600,
         "start_basis": "window_edge", "end_basis": "interpolated"}], "stats": {}}
    assert [part["segments"] for part in split_run_row(only, first)] == [[], []]


def test_a_real_pause_ends_a_run_even_when_display_times_touch():
    from types import SimpleNamespace
    from twobyteasr.cue_forced_alignment import alignment_jobs, longest_silence_ms
    regions = [{"start": 1.0, "end": 2.0}, {"start": 3.0, "end": 4.0}]
    assert longest_silence_ms(regions, 1500, 3150) == 1000
    cues = [SimpleNamespace(start=1.0, end=2.7, speaker="S01", text="一つ目"),      # display end bridged to 2.7
            SimpleNamespace(start=2.7, end=4.2, speaker="S01", text="二つ目")]
    _jobs, joined = alignment_jobs(cues)
    assert [len(run["members"]) for run in joined] == [2]
    _jobs, split = alignment_jobs(cues, speech_regions=regions)
    assert [len(run["members"]) for run in split] == [1, 1]
