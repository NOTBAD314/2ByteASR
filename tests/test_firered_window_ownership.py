"""FireRed worker windows overlap; each overlap must be decoded once.

2026-10-10, user project 0852f218: segment 112 (~396 s) carried FireRed words
"继续继续有话题他处理不了继续那" twice at overlapping times, so the caption lost
word timing (``overlapping_token_streams``) and grouping aligned to duplicates.
"""
from twobyteasr.recognition.asr_schema import flatten_segment_tokens, normalize_firered_worker_result


def _jobs():
    return [{"segment_id": 1, "offset": 0.0, "duration": 38.0},
            {"segment_id": 2, "offset": 36.0, "duration": 38.0},
            {"segment_id": 3, "offset": 72.0, "duration": 10.0}]


def _row(segment_id, text, stamps):
    return {"segment_id": segment_id, "text": text, "confidence": .8,
            "timestamp": [[token, start, end] for token, start, end in stamps]}


def test_overlap_tokens_are_owned_by_one_window_only():
    # Window 1 hears "继续那" at 36.2-37.9 s; window 2 hears the same words
    # at local 0.2-1.9 s (= 36.2-37.9 s global) and then continues.
    payload = {"results": [
        _row(1, "前面继续那", [("前", 30.0, 30.2), ("面", 30.2, 30.4),
                              ("继", 36.2, 36.4), ("续", 36.4, 36.6), ("那", 37.7, 37.9)]),
        _row(2, "继续那个什么", [("继", .2, .4), ("续", .4, .6), ("那", 1.7, 1.9),
                                ("个", 1.9, 2.1), ("什", 2.1, 2.3), ("么", 2.3, 2.5)]),
        _row(3, "结尾", [("结", 1.0, 1.2), ("尾", 1.2, 1.4)]),
    ]}
    result = normalize_firered_worker_result(payload, _jobs())
    tokens = flatten_segment_tokens(result)
    times = [(t["text"], round(t["start"], 2)) for t in tokens]
    # Seam at 37.0 s: tokens centred before it belong to window 1, after it to 2.
    assert times == [("前", 30.0), ("面", 30.2), ("继", 36.2), ("续", 36.4),
                     ("那", 37.7), ("个", 37.9), ("什", 38.1), ("么", 38.3), ("结", 73.0), ("尾", 73.2)]
    starts = [t["start"] for t in tokens]
    assert starts == sorted(starts)
    assert all(b["start"] >= a["end"] - 1e-9 for a, b in zip(tokens, tokens[1:]))
    # Segment text follows the owned tokens, not the whole window decode.
    assert [segment["text"] for segment in result["segments"]] == ["前面继续", "那个什么", "结尾"]


def test_single_window_keeps_everything():
    payload = {"results": [_row(1, "完整一句", [("完", 0.1, 0.3), ("整", 0.3, 0.5), ("一", 0.5, 0.7), ("句", 0.7, 0.9)])]}
    result = normalize_firered_worker_result(payload, [{"segment_id": 1, "offset": 0.0, "duration": 5.0}])
    assert result["segments"][0]["text"] == "完整一句"
    assert len(flatten_segment_tokens(result)) == 4
