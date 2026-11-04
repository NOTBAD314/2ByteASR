"""Local review spans belong to processing cues and complete current tokens."""
import copy
import json
import os
from pathlib import Path
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TWOBYTEASR_TEST_ROOT", str(
    Path(__file__).resolve().parents[1] / "tmp" / "real-repair-20261006"
    / "glossary" / ("candidate-spans-standalone-" + uuid.uuid4().hex),
))
os.environ.setdefault("TWOBYTEASR_STARTUP_TRACE", str(
    Path(os.environ["TWOBYTEASR_TEST_ROOT"]) / "startup-trace.jsonl",
))
from twobyteasr.test_isolation import install

install()

import pytest
from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry


@pytest.fixture
def no_cloud(monkeypatch):
    import subtitle_core
    import twobyteasr.providers.asr_provider_snapshot as providers
    import twobyteasr.subtitle_rules.polishing as polishing

    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("provider")
        raise AssertionError("Local candidate review must not invoke a provider")

    monkeypatch.setattr(providers, "resolve_provider_snapshot", forbidden)
    monkeypatch.setattr(polishing, "call_correction_api", forbidden)
    return calls


def library(*terms):
    return GlossarySnapshot((GlossaryLibrary(
        "span-proof-library", "瓦罗兰特", "span-proof-r1", terms=terms,
        profile_json=json.dumps({"_content_domain": {
            "id": "v", "name": "瓦罗兰特", "source": "saved_library_game",
        }}),
    ),))


def project(*rows):
    value = SubtitleProject(
        media=StudioMedia(path="owned-candidate-span-fixture.mp4"),
        glossary_ids=["span-proof-library"],
        cues=[StudioCue(cue_id, index * 2000, index * 2000 + 1700, text,
                       original_text=text, speaker_id="S01")
              for index, (cue_id, text) in enumerate(rows, 1)],
    )
    value.validate()
    return value


def test_actual_canonical_offsets_never_borrow_another_cue_span(no_cloud):
    # These are the three real failure strings, with opaque stable IDs. The
    # retriever's processing IDs are 1/2/3, not integers parsed from these IDs.
    value = project(
        ("caption-twelve", "而且CHIOCHOO能奶自己"),
        ("caption-forty", "CHIOCHOO被挡住"),
        ("caption-forty-one", "CHIOCHOO完全帮不到"),
    )
    before = copy.deepcopy(value)
    snapshot = library(
        TermEntry("CHIOCHOO", ("球球",), category="选手ID"),
        TermEntry("CHICHOO", ("CHICHOO",), category="选手ID"),
    )
    preview = preview_glossary_correction(
        value, [cue.id for cue in value.cues], snapshot, {}, use_ai=False,
    )
    # Keep the full-batch trace; scope each match when turning it into a hit.
    for row in preview.receipt["segments"]:
        candidate = next(v for v in row["retrieved_candidates"]
                         if v["canonical"] == "CHICHOO")
        matches = [v for v in candidate["matches"] if v["asr_source"] == "text"]
        assert {(v["cue_id"], v["start"], v["end"]) for v in matches} == {
            (1, 2, 10), (2, 0, 8), (3, 0, 8),
        }
        assert row["final_diff"] == []
    assert not preview.hits
    assert preview.receipt["proposed_changes"] == 0
    assert value == before and no_cloud == []


def test_valid_stu_near_shape_is_visible_unselected_at_its_own_offsets(no_cloud):
    value = project(("opaque-first", "stu守住"), ("opaque-second", "前面stu撤回"))
    before = copy.deepcopy(value)
    preview = preview_glossary_correction(
        value, [cue.id for cue in value.cues],
        library(TermEntry("Stuu", category="选手ID")), {}, use_ai=False,
    )
    assert {(hit.cue_id, hit.original, hit.replacement, hit.span) for hit in preview.hits} == {
        ("opaque-first", "stu", "Stuu", (0, 3)),
        ("opaque-second", "stu", "Stuu", (2, 5)),
    }
    assert all(hit.source == "local_review" and not hit.default_selected
               for hit in preview.hits)
    assert preview.receipt["automatic_changes"] == 0
    assert preview.receipt["confirmation_changes"] == 2
    assert value == before and no_cloud == []


@pytest.mark.parametrize("patch", [
    {"start": -1, "end": 3},
    {"start": 0, "end": 99},
    {"start": 0, "end": 0},
    {"start": 3, "end": 0},
    {"start": True, "end": 3},
    {"start": "0", "end": 3},
    {"heard": "different"},
    {"heard": "stu ", "start": 0, "end": 3},
    {"start": 1, "end": 3, "heard": "tu"},
    {"cue_id": True},
    {"asr_source": "moss_text"},
])
def test_malformed_retrieved_span_cannot_become_checkable(no_cloud, monkeypatch, patch):
    import twobyteasr.glossary.terminology_retrieval as retrieval

    actual_retrieve = retrieval.retrieve_candidates

    def damaged_match(*args, **kwargs):
        rows = actual_retrieve(*args, **kwargs)
        candidate = next(row for row in rows if row["canonical"] == "Stuu")
        match = next(v for v in candidate["matches"]
                     if v["asr_source"] == "text" and v["method"] == "latin_identifier")
        match.update(patch)
        return rows

    monkeypatch.setattr(retrieval, "retrieve_candidates", damaged_match)
    value = project(("opaque-caption", "stu守住"))
    before = copy.deepcopy(value)
    preview = preview_glossary_correction(
        value, ["opaque-caption"], library(TermEntry("Stuu", category="选手ID")),
        {}, use_ai=False,
    )
    assert not preview.hits
    assert preview.receipt["segments"][0]["final_diff"] == []
    assert value == before and no_cloud == []
