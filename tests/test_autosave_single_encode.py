"""Autosave encodes the project once and never re-reads its own last file.

2026-10-22 (report-eb10, 0.8.2): with a 62 MB project every autosave parsed
the previous autosave just to read its generation, and encoded the whole
project a second time for the fingerprint sidecar. Both held the GIL.
"""
import json
from pathlib import Path

import pytest

import twobyteasr.projects.studio_project as persistence
from twobyteasr.projects.studio_project import (
    StudioCue, StudioMedia, SubtitleProject, _canonical_json, _content_fingerprint_payload,
    load_project, project_content_fingerprint, save_autosave_revision,
)
from twobyteasr.projects.studio_revisions import StudioRevisionStore


def _project():
    project = SubtitleProject(
        media=StudioMedia(path="", duration_ms=9000),
        cues=[StudioCue("a", 0, 1000, "第一句 “quoted” \\ slash"),
              StudioCue("b", 1000, 2000, "second\nline", evidence_refs=["seg:1"])],
        asr_evidence={"seg:1": {"words": [{"text": "second", "start_ms": 1000, "end_ms": 1500, "p": 0.5}],
                                "engines": {"moss": (1, 2.5, None, True)}}},
        generation_metadata={"translations": {"a": "first", "b": "第二"}, "history": [{"z": 1, "a": []}]},
        studio_state={"bilingual": {"mode": "bilingual"}, "review_risks": [1], "last_opened": "x"},
    )
    project.validate()
    return project


@pytest.mark.parametrize("value", [
    {}, [], (), "x", 1.5, None, True, float("nan"),
    {"b": {"y": [1, {"k": "é"}], "x": ()}, "a": [], "c": {"2": 1, "10": 2}},
    {"mixed": {1: "int key", 2: "x"}, "list": [[], [{}], ({"z": 0, "a": 1},)]},
    [{"b": 1, "a": 2}, "s", [3, [4, {"c": "，"}]]],
])
@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_canonical_json_matches_the_standard_encoder(value, depth):
    expected = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert _canonical_json(value, depth) == expected


def test_autosave_file_and_fingerprint_are_unchanged(tmp_path):
    project = _project()
    revision = StudioRevisionStore(project).refresh_persistence(1)
    target, phases = save_autosave_revision(revision, tmp_path / "p.2byteproj", session_id="abc")
    text = Path(target).read_text("utf-8")
    payload = json.loads(text)
    assert text == json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    sidecar = json.loads(Path(target).with_name(Path(target).stem + ".fingerprint.json").read_text("utf-8"))
    assert sidecar["generation"] == 1
    assert sidecar["content_fingerprint"] == _content_fingerprint_payload(payload)
    assert sidecar["content_fingerprint"] == project_content_fingerprint(load_project(target))
    assert sidecar["content_fingerprint"] == project_content_fingerprint(project)
    assert {"materialize_ms", "serialize_ms", "persist_ms", "fsync_ms"} <= set(phases)


def test_next_autosave_does_not_read_the_previous_file(tmp_path, monkeypatch):
    project = _project()
    store = StudioRevisionStore(project)
    target, _ = save_autosave_revision(store.refresh_persistence(1), tmp_path / "p.2byteproj", session_id="abc")
    reads = []
    original = Path.read_text

    def spy(self, *args, **kwargs):
        reads.append(Path(self).name)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", spy)
    project.cues[0].text = "changed"
    store = StudioRevisionStore(project)
    again, _ = save_autosave_revision(store.refresh_persistence(2), tmp_path / "p.2byteproj", session_id="abc")
    assert again == target
    assert Path(target).name not in reads
    assert load_project(target).cues[0].text == "changed"


def test_older_generation_never_overwrites_a_newer_autosave(tmp_path, monkeypatch):
    project = _project()
    store = StudioRevisionStore(project)
    project.cues[0].text = "newest"
    newer = StudioRevisionStore(project).refresh_persistence(5)
    target, _ = save_autosave_revision(newer, tmp_path / "p.2byteproj", session_id="abc")
    project.cues[0].text = "stale"
    stale = StudioRevisionStore(project).refresh_persistence(3)
    assert save_autosave_revision(stale, tmp_path / "p.2byteproj", session_id="abc")[0] == target
    assert load_project(target).cues[0].text == "newest"
    # Another process (no memory of the write) learns the generation from the
    # sidecar; a sidecar without one (older build) falls back to the file.
    monkeypatch.setattr(persistence, "_AUTOSAVE_GENERATIONS", {})
    save_autosave_revision(stale, tmp_path / "p.2byteproj", session_id="abc")
    assert load_project(target).cues[0].text == "newest"
    sidecar = Path(target).with_name(Path(target).stem + ".fingerprint.json")
    data = json.loads(sidecar.read_text("utf-8"))
    data.pop("generation")
    sidecar.write_text(json.dumps(data), "utf-8")
    monkeypatch.setattr(persistence, "_AUTOSAVE_GENERATIONS", {})
    save_autosave_revision(stale, tmp_path / "p.2byteproj", session_id="abc")
    assert load_project(target).cues[0].text == "newest"
    del store
