import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from twobyteasr.projects.subtitle_consistency import validate_export_view, validate_project

FIXTURES = Path(__file__).parent / "fixtures" / "subtitle_consistency"


def payload(name="edited_stale_words"):
    return json.loads((FIXTURES / (name + ".2byteproj")).read_text("utf-8"))


def codes(issues):
    return {issue.code for issue in issues}


def test_manual_text_is_preserved_and_word_alignment_only_warns():
    project = payload()
    before = copy.deepcopy(project)
    result = validate_project(project)
    assert result.ok and codes(result.warnings) == {"stale_word_alignment"}
    assert result.warnings[0].cue_id == "edited" and result.warnings[0].cue_index == 0
    assert project == before
    assert project["cues"][0]["text"] == "手動保留的新文字🙂"
    assert "手動" not in json.dumps(result.to_dict(), ensure_ascii=False)


@pytest.mark.parametrize("name,code", [
    ("broken_source_reference", "source_reference_missing"),
    ("invalid_sentence_time", "sentence_time_invalid"),
])
def test_invalid_committed_rows_are_located_without_repair(name, code):
    project = payload(name)
    before = copy.deepcopy(project)
    result = validate_project(project, stage="load")
    assert not result.ok and code in codes(result.errors)
    assert all(issue.cue_id == "other" and issue.cue_index == 1 for issue in result.errors)
    assert result.errors[0].stage == "load"
    assert project == before


@pytest.mark.parametrize("start,end", [(float("nan"), 2), (0, float("inf")), (-1, 2),
                                       (10, 10), (20, 10), (True, 10), ("1", 3),
                                       (0.5, 2), (0, 10**400)])
def test_bad_sentence_times_cannot_escape_by_coercion(start, end):
    project = payload()
    project["cues"][0].update(start_ms=start, end_ms=end)
    assert "sentence_time_invalid" in codes(validate_project(project).errors)


def test_selected_export_does_not_validate_hidden_or_unselected_bad_rows():
    project = payload("broken_source_reference")
    result = validate_export_view(project, [project["cues"][0]])
    assert result.ok
    assert codes(result.warnings) == {"stale_word_alignment"}
    assert validate_export_view(project, []).ok


def test_project_and_translated_export_allow_simultaneous_speakers():
    project = payload()
    view = copy.deepcopy(project["cues"])
    view[0].update(id="edited#tr", text="The current translated text.")
    assert validate_project(project).ok
    assert validate_export_view(project, view).ok
    # A different timeline placement is allowed; scope creation owns mapping.
    view[0].update(start_ms=4000, end_ms=5000)
    assert validate_export_view(project, view).ok


def test_derived_legacy_ids_and_independent_caption_ids_are_both_understood():
    project = payload()
    view = copy.deepcopy(project["cues"][:1])
    view[0]["id"] = "edited#clip-id#tr"
    assert validate_export_view(project, view).ok
    project["cues"][0]["id"] = "edited#clip-id"
    assert validate_export_view(project, view).ok


def test_export_cannot_change_speaker_or_invent_source():
    project = payload()
    view = copy.deepcopy(project["cues"][:1])
    view[0]["speaker_id"] = "S02"
    assert "export_speaker_mismatch" in codes(validate_export_view(project, view).errors)
    view[0]["id"] = "unknown#tr"
    assert "export_source_missing" in codes(validate_export_view(project, view).errors)


@pytest.mark.parametrize("speaker,code", [([], "speaker_id_invalid"), ("", "speaker_id_invalid"),
                                        ("S03", "speaker_reference_missing")])
def test_speaker_reference_type_and_membership(speaker, code):
    project = payload()
    project["cues"][0]["speaker_id"] = speaker
    assert code in codes(validate_project(project).errors)


def test_empty_legacy_roster_preserves_cue_local_speaker_ids():
    project = payload()
    project["speakers"] = []
    assert validate_project(project).ok


def test_wrong_original_caption_reference_is_not_stale_alignment():
    project = payload()
    receipt = project["studio_state"]["caption_timeline"]["instances"]["edited"]
    receipt["source_cue_id"] = "absent"
    result = validate_project(project)
    assert "caption_source_missing" in codes(result.errors)
    assert "stale_word_alignment" in codes(result.warnings)


def test_invalid_word_indices_warn_and_do_not_block_sentence_export():
    project = payload("malformed_word_receipt")
    result = validate_export_view(project, project["cues"])
    assert result.ok and "word_index_invalid" in codes(result.warnings)


def test_corrupt_unrelated_receipts_do_not_block_empty_or_sentence_export():
    project = payload()
    project["studio_state"]["caption_timeline"]["instances"]["unselected"] = []
    assert validate_export_view(project, project["cues"]).ok
    project["studio_state"]["caption_timeline"]["instances"] = []
    assert not validate_project(project).ok
    assert validate_export_view(project, []).ok
    result = validate_export_view(project, project["cues"])
    assert result.ok and "caption_receipts_unavailable" in codes(result.warnings)


def test_new_manual_caption_has_no_required_asr_reference():
    project = {"cues": [{"id": "manual", "start_ms": 0, "end_ms": 1000,
                         "speaker_id": "S00", "text": "手工新加"}]}
    assert validate_project(project).ok
    assert validate_export_view(project, project["cues"]).ok


def test_results_are_immutable_and_missing_project_is_not_valid():
    result = validate_project(None)
    assert not result.ok and codes(result.errors) == {"project_missing"}
    with pytest.raises(FrozenInstanceError):
        result.errors = ()
    with pytest.raises(FrozenInstanceError):
        result.errors[0].code = "changed"


def test_real_project_load_remains_read_only_and_never_calls_alignment(monkeypatch):
    from twobyteasr.projects.studio_project import load_project
    import twobyteasr.recognition.cue_word_alignment as alignment
    project = load_project(FIXTURES / "edited_stale_words.2byteproj")
    before = {key: value if key.startswith('_') else copy.deepcopy(value)
              for key, value in vars(project).items()}
    monkeypatch.setattr(alignment, "cue_words", lambda *args: pytest.fail("alignment called"))
    monkeypatch.setattr(alignment, "align_text_to_tokens", lambda *args, **kw: pytest.fail("alignment called"))
    assert validate_project(project).ok
    assert validate_export_view(project, project.cues).ok
    assert vars(project) == before



def implicit_alignment_payload():
    project = payload("invalid_implicit_alignment")
    row = project["asr_evidence"]["cue-align:edited"]
    row["caption_arbitration"]["acoustic_words"][0]["char_end"] = len(row["text"])
    return project, row


def test_implicit_source_indices_warn_without_requiring_an_evidence_ref():
    project = payload("invalid_implicit_alignment")
    assert "cue-align:edited" not in project["cues"][0]["evidence_refs"]
    before = copy.deepcopy(project)
    result = validate_export_view(project, project["cues"])
    issue = next(i for i in result.warnings if i.code == "source_word_index_invalid")
    assert result.ok and issue.cue_id == "edited" and issue.cue_index == 0
    assert issue.source_ref == "cue-align:edited"
    assert project == before


@pytest.mark.parametrize("change,code", [
    ({"start_ms": float("nan")}, "source_word_time_invalid"),
    ({"start_ms": True}, "source_word_time_invalid"),
    ({"end_ms": 1000}, "source_word_time_invalid"),
    ({"char_start": True}, "source_word_index_invalid"),
    ({"char_end": 99999}, "source_word_index_invalid"),
    ({"char_end": None}, "source_word_index_invalid"),
    ({"text": "无关字"}, "source_word_text_mismatch"),
])
def test_preferred_acoustic_stream_uses_shared_source_word_rules(change, code):
    project, row = implicit_alignment_payload()
    row["caption_arbitration"]["acoustic_words"][0].update(change)
    result = validate_project(project)
    assert result.ok and code in codes(result.warnings)
    # The raw stream is valid, so this proves the preferred one was inspected.
    assert row["words"][0]["start_ms"] < row["words"][0]["end_ms"]


def test_valid_acoustic_stream_supersedes_invalid_raw_word_stream():
    project, row = implicit_alignment_payload()
    row["words"][0]["end_ms"] = -1
    result = validate_project(project)
    assert result.ok and not any(i.code.startswith("source_word_") for i in result.warnings)


def test_source_words_without_indices_and_second_based_times_are_supported():
    project, row = implicit_alignment_payload()
    row["caption_arbitration"] = {}
    row["words"] = [dict(text=row["text"], start=1.0, end=2.0)]
    assert not any(i.code.startswith("source_word_") for i in validate_project(project).warnings)
    row["words"][0]["start"] = False
    assert "source_word_time_invalid" in codes(validate_project(project).warnings)


def test_implicit_alignment_is_scoped_and_duplicate_refs_are_checked_once():
    project = payload("invalid_implicit_alignment")
    assert not validate_export_view(project, [project["cues"][1]]).warnings
    project["cues"][0]["evidence_refs"].append("cue-align:edited")
    result = validate_project(project)
    assert sum(i.code == "source_word_index_invalid" for i in result.warnings) == 1


def test_stale_implicit_alignment_preserves_manual_text_and_valid_translation():
    project, row = implicit_alignment_payload()
    row["text"] = "旧" + row["text"][1:]
    row["caption_arbitration"]["acoustic_words"][0]["text"] = row["text"]
    result = validate_project(project)
    assert result.ok and "source_word_alignment_stale" in codes(result.warnings)
    assert project["cues"][0]["text"] == "手動保留的新文字🙂"
    row["text"] = project["cues"][0]["text"]
    row["caption_arbitration"]["acoustic_words"][0]["text"] = row["text"]
    view = copy.deepcopy(project["cues"][:1])
    view[0].update(id="edited#tr", text="Current translation")
    assert not any(i.code.startswith("source_word_") for i in validate_export_view(project, view).warnings)
    own = copy.deepcopy(row)
    own["text"] = view[0]["text"]
    own["caption_arbitration"]["acoustic_words"] = [
        dict(text=own["text"], char_start=0, char_end=len(own["text"]), start_ms=1000, end_ms=2000)]
    project["asr_evidence"]["cue-align:edited#tr"] = own
    assert not any(i.code.startswith("source_word_") for i in validate_export_view(project, view).warnings)

