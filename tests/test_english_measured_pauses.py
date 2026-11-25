import json

import pytest

from twobyteasr.recognition.edited_text_alignment import realign_edited_segments
from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.subtitle_rules.english_segmentation import group_english_with_ai


def _cue():
    return SpeechSegment(12, 0, 3.5, "I thought that... you were gone.", .9, [])


def _words():
    return [
        {"text": text, "start": start, "end": end}
        for text, start, end in [
            ("I", .1, .2), ("thought", .2, .5), ("that", .5, .7),
            ("you", 2.7, 2.9), ("were", 2.9, 3.1), ("gone", 3.1, 3.4),
        ]
    ]


@pytest.mark.parametrize("retry", [False, True])
def test_short_utterance_sends_measured_pause_and_uses_exact_cut(retry):
    requests = []

    def complete(messages):
        row, = json.loads(messages[1]["content"])["utterances"]
        requests.append(row)
        return '{"breaks":{"12":[]}}' if retry and len(requests) == 1 else '{"breaks":{"12":[2]}}'

    result = group_english_with_ai([_cue()], _words(), complete=complete)

    assert len(requests) == (2 if retry else 1)
    assert requests[0]["required_break_after"] == [2]
    assert requests[0]["measured_gap_ms_after"]["2"] == 2000
    assert [cue.grouping_origin for cue in result] == ["ai_accepted", "ai_accepted"]
    assert "".join(cue.text for cue in result) == _cue().text
    assert (result[0].end, result[1].start) == (.7, 2.7)


def test_residual_measured_pause_after_two_rejections_is_local_fallback():
    result = group_english_with_ai([_cue()], _words(), complete=lambda _: '{"breaks":{"12":[999]}}')
    assert [cue.grouping_origin for cue in result] == ["local_measured_pause_fallback"] * 2
    assert (result[0].end, result[1].start) == (.7, 2.7)


def test_unmeasured_pause_does_not_enter_request():
    tokens = _words()
    tokens[2]["end_basis"] = "interpolated"
    result = group_english_with_ai([_cue()], tokens, complete=lambda _: pytest.fail("unmeasured gap"))
    assert len(result) == 1
    assert result[0].timing_basis == "original_source_sentence"


def test_pending_text_revision_cannot_reuse_original_tokens():
    class Recorder:
        def record_run_event(self, *_args, **_kwargs):
            pass

        add_review_item = record_run_event

    segment = _cue()
    segment.words = [WordUnit(row["start"], row["end"], row["text"], .9) for row in _words()]
    realign_edited_segments([segment], None, Recorder(), enabled=False, language="English",
                            evidence_dir=None, previous_text={"12": "I thought that... you were home."})
    assert not segment.words
    assert segment.caption_arbitration["edited_text_alignment"]["status"] == "pending"
    result = group_english_with_ai([segment], _words(), complete=lambda _: pytest.fail("stale tokens"))
    assert len(result) == 1

def test_overlong_english_line_repair_keeps_measured_pause_and_rebases_ids():
    from twobyteasr.subtitle_rules.english_segmentation import RULES, _request_measured_breaks

    tokens = ["red"] * 12
    times = [(i * .3, i * .3 + .2) for i in range(len(tokens))]
    allowed = [0, 5, 9]
    evidence = {"12": (tokens, times, {0: 1200, 5: 100, 9: 100}, [0], allowed, {})}
    requests = []

    def complete(messages):
        row, = json.loads(messages[1]["content"])["utterances"]
        requests.append(row)
        if row["id"] == "12":
            return '{"breaks":{"12":[0,11]}}'
        assert row["allowed_break_after"] == [4, 8]
        assert row["required_break_after"] == []
        assert len(" ".join(row["words"].values())) > RULES.cue_max_chars
        return '{"breaks":{"12~2":[4]}}'

    from twobyteasr.subtitle_rules.english_segmentation import ENGLISH
    assert _request_measured_breaks([("12", tokens)], complete, ENGLISH, evidence, 1) == {"12": [0, 5]}
    assert [row["id"] for row in requests] == ["12", "12", "12~2"]
