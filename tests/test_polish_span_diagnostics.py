"""Safe unique-quote repair; ambiguous/overlapping edits still fail closed."""
import subtitle_core  # initialize the facade before polishing
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules import polishing


def validated(text, edits):
    value = {"checked_ids": [1], "cues": [{"id": 1, "edits": edits}]}
    errors = polishing.CueValidationFailures()
    result = polishing._validate_polish_response(value, [SpeechSegment(1, 0, 2, text, .9, [])], 6, errors)
    return result, errors


def edit(source, target, start, end):
    return {"from": source, "to": target, "start": start, "end": end, "type": "asr_correction"}


def test_unique_exact_quote_repairs_wrong_coordinates_without_rewriting_the_quote():
    result, errors = validated("这里古龙来了", [edit("古龙", "骨龙", 9, 99)])
    assert not errors
    assert result["cues"][0]["edits"] == [edit("古龙", "骨龙", 2, 4)]


def test_repeated_quote_is_not_guessed():
    result, errors = validated("古龙然后古龙", [edit("古龙", "骨龙", 1, 3)])
    assert result["cues"] == []
    assert errors == {1: "semantic_validation"}
    assert errors.details[1]["reason"] == "ambiguous_source_quote"


def test_overlapping_occurrences_are_not_mistaken_for_one_unique_quote():
    _, errors = validated("哈哈哈", [edit("哈哈", "呵呵", 0, 99)])
    assert errors.details[1]["reason"] == "ambiguous_source_quote"
    assert errors.details[1]["quote_occurrences"] == 2


def test_missing_quote_and_overlapping_ranges_remain_rejected():
    value, missing = validated("这里没有那个词", [edit("古龙", "骨龙", 0, 2)])
    assert not missing
    assert value['cues'][0]['edits'] == []
    assert missing.protected[1][0]['rule_id'] == 'source_quote_not_found'
    _, overlap = validated("古龙来了", [edit("古龙", "骨龙", 0, 2), edit("龙", "笼", 1, 2)])
    assert overlap.details[1]["reason"] == "overlapping_edits"


def test_missing_quote_does_not_discard_an_independent_valid_edit():
    value, errors = validated('古龙来了', [edit('不存在', '错误建议', 10, 12), edit('古龙', '骨龙', 0, 2)])
    assert not errors
    assert value['cues'][0]['edits'] == [edit('古龙', '骨龙', 0, 2)]
    assert len(errors.protected[1]) == 1


def test_invalid_cue_schema_records_the_field_and_retains_valid_neighbor():
    value = {"checked_ids": [1, 2], "cues": [{"id": 1, "edits": []},
             {"id": 2, "edits": [{"from": "原文", "to": "改文", "type": "unknown"}]}]}
    errors = polishing.CueValidationFailures()
    segments = [SpeechSegment(i, i, i+1, "原文", .9, []) for i in (1, 2)]
    result = polishing._validate_polish_response(value, segments, 7, errors)
    assert result["cues"] == [{"id": 1, "edits": []}]
    assert errors == {2: "structured_schema_error"}
    assert errors.details[2]["field"] == "edits.0.type"
