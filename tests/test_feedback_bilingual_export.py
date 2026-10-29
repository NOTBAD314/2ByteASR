"""Regression scenarios from Japanese ASR / bilingual export feedback."""
import copy
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker
from twobyteasr.exports.export_timeline import export_project_snapshot
from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def bilingual_project():
    project = SubtitleProject(media=StudioMedia("source.mp4", duration_ms=8000, width=640, height=360),
        speakers=[StudioSpeaker("S01", "First"), StudioSpeaker("S02", "Second")],
        cues=[StudioCue("one", 1000, 3000, "ALPHA", speaker_id="S01"),
              StudioCue("two", 2000, 4000, "BRAVO", speaker_id="S02")],
        generation_metadata={"language": {"code": "en"}, "translations": {"one": "第一句", "two": "第二句"}},
        studio_state={"bilingual": {"mode": "bilingual", "order": "translation_first"}})
    project.validate()
    project.cues[0].transform = {"position_x": 480, "position_y": 950}
    project.cues[1].transform = {"position_x": 1440, "position_y": 950}
    return project


@pytest.mark.parametrize('format_name',['srt','txt'])
def test_native_acceptance_checks_the_expected_bilingual_text_and_rejects_corruption(tmp_path,format_name):
    from twobyteasr.acceptance.home_release_flow_audit import expected_plain_bilingual_project
    from twobyteasr.exports.studio_subtitle_export import verify_subtitle_artifact
    project=bilingual_project()
    artifact=export_subtitle_artifacts(project,tmp_path,'native-bilingual',SubtitleExportOptions(frozenset({format_name}),'combined'))[0]
    expected=expected_plain_bilingual_project(project,format_name)
    assert verify_subtitle_artifact(artifact,expected).valid
    assert project.cues[0].text=='ALPHA'
    artifact.path.write_text(artifact.path.read_text('utf-8-sig').replace('第一句','错误译文'),encoding='utf8')
    assert not verify_subtitle_artifact(artifact,expected).valid


def test_projected_burnin_keeps_both_speakers_translations():
    project = bilingual_project()
    store_sequence(project, EditSequence(source_path=project.media.path, source_duration_ms=8000,
        segments=[VideoSegment("cut", project.media.path, 1000, 6000, 0, 5000)]))
    before = copy.deepcopy(project.to_dict())
    snapshot = export_project_snapshot(project)
    assert all("#cut" in cue.id for cue in snapshot.cues)
    ass = compile_ass(snapshot)
    assert "第一句" in ass and "第二句" in ass
    assert project.to_dict() == before


@pytest.mark.parametrize("mode", ["bilingual", "translation", "original"])
def test_default_files_follow_display_mode_for_both_speakers(tmp_path, mode):
    project = bilingual_project()
    project.studio_state["bilingual"]["mode"] = mode
    before = copy.deepcopy(project.to_dict())
    outputs = export_subtitle_artifacts(project, tmp_path, "dialogue",
        SubtitleExportOptions(frozenset({"srt", "ass", "txt", "json"}), "both"))
    for artifact in outputs:
        text = artifact.path.read_text(encoding="utf8")
        if artifact.format == "json":
            assert "translation" in text
            continue
        for sid, original, translated in [("S01", "ALPHA", "第一句"), ("S02", "BRAVO", "第二句")]:
            if artifact.speaker_id and artifact.speaker_id != sid:
                continue
            assert (translated in text) == (mode != "original")
            assert (original in text) == (mode != "translation")
    assert project.to_dict() == before


def test_mixed_native_advanced_keeps_translation_companions():
    from twobyteasr.rendering.advanced_renderer import compile_composition_data, _native_segment_project
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    project = bilingual_project()
    recipe = StyleRecipe.from_dict({"engine": "remotion", "name": "gradient",
        "colors": {"fill": {"type": "linear", "stops": [
            {"color": "#FF0000", "pos": 0}, {"color": "#FFFF00", "pos": 1}]}}})
    project.style_recipes["gradient"] = recipe.to_dict()
    project.cues[1].style_id = "gradient"
    before = copy.deepcopy(project.to_dict())
    props = compile_composition_data(project, width=640, height=360, fps=24,
                                     start_seconds=0, duration_seconds=5)
    assert {cue["text"] for cue in props["cues"]} == {"BRAVO", "第二句"}
    native = _native_segment_project(project, 0, 5000)
    ass = compile_ass(native)
    assert ass.count("第一句") == 1 and "ALPHA" in ass
    assert "第二句" not in ass
    assert project.to_dict() == before


def test_display_freeze_is_idempotent_and_owns_untranslated_cues():
    from twobyteasr.caption_style.bilingual_layout import materialize_display_project
    project = bilingual_project()
    project.generation_metadata["translations"].pop("two")
    before = copy.deepcopy(project.to_dict())
    frozen = materialize_display_project(project)
    assert materialize_display_project(frozen) is frozen
    assert {cue.id for cue in frozen.cues} == {"one", "one#tr", "two"}
    next(cue for cue in frozen.cues if cue.id == "two").text = "worker copy"
    assert project.to_dict() == before
