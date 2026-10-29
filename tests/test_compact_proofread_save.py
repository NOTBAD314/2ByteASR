"""Frequent compact saves preserve the project schema and atomic backup."""
import json

from twobyteasr.projects.studio_project import (SubtitleProject, StudioCue, StudioMedia,
                                              save_project, load_project, project_backup_path)


def test_compact_save_roundtrips_the_same_values_and_retains_previous_backup(tmp_path):
    p = SubtitleProject(StudioMedia("", duration_ms=3000), cues=[StudioCue("stable", 1000, 2000, "中文 日本語 😀")],
                        generation_metadata={"translations": {"stable": "訳文"}},
                        studio_state={"glossary_proofread_decisions": {"stable": [{"state": "ignored", "text_sha": "test"}]}})
    p.validate()
    path = tmp_path / "中文 空格.2byteproj"
    save_project(p, path)
    before = path.read_bytes()
    pretty = json.loads(before)
    save_project(p, path, compact=True)
    compact = json.loads(path.read_bytes())
    for value in (pretty, compact):
        value.pop("updated_at", None)
    assert pretty == compact
    assert path.stat().st_size < len(before)
    assert project_backup_path(path).read_bytes() == before
    loaded = load_project(path)
    assert loaded.cues[0].text == "中文 日本語 😀"
    assert loaded.generation_metadata["translations"]["stable"] == "訳文"
    assert loaded.studio_state["glossary_proofread_decisions"]["stable"][0]["state"] == "ignored"
