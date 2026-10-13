"""Language-layer subtitle export (original / translation / bilingual) and JSON."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr import studio_subtitle_export as export
from twobyteasr import subtitle_translation as st
from twobyteasr.cue_forced_alignment import evidence_row
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject

JA = ["行くぞ！", "ちょっと待って", "やばい", "マジで"]
ZH = {"行くぞ！": "走了！", "ちょっと待って": "等一下", "やばい": "糟了", "マジで": "真的假的"}


class FakeProvider:
    provider_id = "fake-provider"
    model = "fake-model"

    def structured_complete(self, messages, schema, **kwargs):
        payload = json.loads(messages[-1]["content"])
        return {"items": [{"id": line["id"], "translation": ZH[line["text"]]}
                          for line in payload["lines"] if line["translate"]]}


def make_project():
    project = SubtitleProject(
        media=StudioMedia(path="synthetic.mp4", duration_ms=60_000),
        cues=[StudioCue(f"c{index}", index * 1000, index * 1000 + 900, text,
                        speaker_id="S01" if index % 2 else "S00")
              for index, text in enumerate(JA)],
        speakers=[StudioSpeaker("S00", "主播"), StudioSpeaker("S01", "嘉宾")],
    )
    project.validate()
    project.generation_metadata["language"] = {"code": "ja"}
    return project


def translated_project(target="zh-Hans"):
    """c0, c1, c3 translated; c2 untranslated; c3's Japanese edited afterwards."""
    project = make_project()
    result = st.translate(project, ["c0", "c1", "c3"], FakeProvider(), target=target)
    st.apply_translation_result(project, result)
    next(cue for cue in project.cues if cue.id == "c3").text = "マジでか"
    return project


def blocks(path):
    return [block.split("\n", 2)[2] for block in path.read_text(encoding="utf-8").strip().split("\n\n")]


def test_three_layers_names_content_and_counts(tmp_path):
    project = translated_project()
    result = export.export_language_layers(project, tmp_path, "实况")
    names = {artifact.layer: artifact.path.name for artifact in result.artifacts}
    assert names == {"original": "实况.ja.srt", "translation": "实况.zh.srt", "bilingual": "实况.bilingual.srt"}
    paths = {artifact.layer: artifact.path for artifact in result.artifacts}
    assert blocks(paths["original"]) == ["行くぞ！", "ちょっと待って", "やばい", "マジでか"]
    assert blocks(paths["translation"]) == ["走了！", "等一下", "真的假的"]
    assert blocks(paths["bilingual"]) == ["走了！\n行くぞ！", "等一下\nちょっと待って", "やばい", "真的假的\nマジでか"]
    by_layer = {artifact.layer: artifact for artifact in result.artifacts}
    assert by_layer["translation"].cue_count == 3 and by_layer["translation"].missing_translation_ids == ("c2",)
    assert by_layer["bilingual"].cue_count == 4 and by_layer["bilingual"].missing_translation_count == 1
    assert by_layer["original"].missing_translation_count == 0
    assert result.missing_translation_ids == ("c2",) and result.needs_update_ids == ("c3",)
    assert by_layer["bilingual"].needs_update_count == 1
    for artifact in result.artifacts:
        assert artifact.path.read_bytes().count(b"\r") == 0
    # Timestamps survive per layer: translation layer skips c2's slot.
    text = paths["translation"].read_text(encoding="utf-8")
    assert "00:00:03,000 --> 00:00:03,900" in text and "00:00:02,000 --> 00:00:02,900" not in text


def test_bilingual_order_can_be_swapped(tmp_path):
    project = translated_project()
    result = export.export_language_layers(project, tmp_path, "实况", ("bilingual",), translation_first=False)
    [artifact] = result.artifacts
    assert blocks(artifact.path)[:2] == ["行くぞ！\n走了！", "ちょっと待って\n等一下"]


def test_existing_files_are_never_overwritten(tmp_path):
    project = translated_project()
    (tmp_path / "实况.ja.srt").write_bytes(b"old user file")
    first = export.export_language_layers(project, tmp_path, "实况")
    assert {artifact.path.name for artifact in first.artifacts} == {
        "实况 (2).ja.srt", "实况 (2).zh.srt", "实况 (2).bilingual.srt"}
    assert (tmp_path / "实况.ja.srt").read_bytes() == b"old user file"
    assert not (tmp_path / "实况.zh.srt").exists()
    second = export.export_language_layers(project, tmp_path, "实况", ("translation",))
    assert [artifact.path.name for artifact in second.artifacts] == ["实况.zh.srt"]  # was still free
    third = export.export_language_layers(project, tmp_path, "实况", ("translation",))
    assert [artifact.path.name for artifact in third.artifacts] == ["实况 (3).zh.srt"]
    assert not [path for path in tmp_path.iterdir() if path.name.startswith(".subtitle-layers-")]


def test_publish_race_takes_next_free_name(tmp_path, monkeypatch):
    project = translated_project()
    real = export._publish_new
    raced = []

    def racing(candidate, target):
        if not raced:
            raced.append(target.name)
            target.write_bytes(b"appeared meanwhile")
        return real(candidate, target)

    monkeypatch.setattr(export, "_publish_new", racing)
    result = export.export_language_layers(project, tmp_path, "实况", ("original",))
    assert raced == ["实况.ja.srt"] and result.artifacts[0].path.name == "实况 (2).ja.srt"
    assert (tmp_path / "实况.ja.srt").read_bytes() == b"appeared meanwhile"


def test_traditional_target_suffix(tmp_path):
    project = translated_project(target="zh-Hant")
    result = export.export_language_layers(project, tmp_path, "实况", ("translation",))
    assert result.artifacts[0].path.name == "实况.zh-Hant.srt" and result.target == "zh-Hant"
    # Asking for another target than the records were made for flags them all.
    other = export.export_language_layers(project, tmp_path, "其他", ("translation",), target="zh-Hans")
    assert other.artifacts[0].path.name == "其他.zh.srt"
    assert set(other.needs_update_ids) == {"c0", "c1", "c3"}


def test_per_speaker_layers(tmp_path):
    project = translated_project()
    result = export.export_language_layers(project, tmp_path, "实况", ("original", "translation"),
                                           speaker_mode="per_speaker")
    assert {artifact.path.name for artifact in result.artifacts} == {
        "实况_主播.ja.srt", "实况_主播.zh.srt", "实况_嘉宾.ja.srt", "实况_嘉宾.zh.srt"}
    guest = next(a for a in result.artifacts if a.path.name == "实况_嘉宾.zh.srt")
    assert blocks(guest.path) == ["等一下", "真的假的"] and guest.speaker_id == "S01"


def test_legacy_translation_dict_exports_without_migration(tmp_path):
    project = make_project()
    project.generation_metadata["translations"] = {"c0": "走了！"}
    result = export.export_language_layers(project, tmp_path, "旧工程", ("bilingual",))
    assert blocks(result.artifacts[0].path)[0] == "走了！\n行くぞ！"
    assert "translation_records" not in project.generation_metadata  # export never mutates


def aligned_project():
    project = translated_project()
    first = project.cues[0]
    alignment = {
        "text": first.text, "model": "Qwen3-ForcedAligner", "status": "ok",
        "segments": [
            {"start_ms": 100, "end_ms": 420, "char_start": 0, "char_end": 2, "granularity": "word",
             "start_basis": "boundary_peak", "end_basis": "boundary_peak"},
            {"start_ms": 420, "end_ms": 700, "char_start": 2, "char_end": 3, "granularity": "char",
             "start_basis": "boundary_peak", "end_basis": "monotonic_repair"},
        ],
    }
    reference = "cue-align:" + first.id
    project.asr_evidence[reference] = evidence_row(first.id, first.start_ms, first.end_ms, first.speaker_id,
                                                   alignment)
    first.evidence_refs = [reference]
    return project


def test_json_carries_translation_speaker_and_cue_alignment_pieces(tmp_path):
    project = aligned_project()
    result = export.export_language_layers(project, tmp_path, "实况", ("json",))
    [artifact] = result.artifacts
    assert artifact.path.name == "实况.json"
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1 and payload["kind"] == "2byteasr-subtitle-export"
    assert payload["original_language"] == "ja" and payload["translation_target"] == "zh-Hans"
    rows = {row["id"]: row for row in payload["cues"]}
    first = rows["c0"]
    for key in ("start_ms", "end_ms", "text", "speaker_id", "speaker_name", "style_id"):
        assert key in first  # old keys kept
    assert first["original_text"] == "行くぞ！"
    assert first["speaker"] == {"id": "S00", "name": "主播"}
    assert first["translation"] == {"text": "走了！", "status": "done", "origin": "ai", "target": "zh-Hans"}
    assert rows["c2"]["translation"]["status"] == "untranslated"
    assert rows["c3"]["translation"]["status"] == "needs_update"
    timing = first["word_timing"]
    assert timing["source"] == "cue_alignment"
    assert [(p["text"], p["start_ms"], p["end_ms"], p["granularity"], p["basis"]) for p in timing["pieces"]] == [
        ("行く", 100, 420, "word", "boundary_peak"),
        ("ぞ", 420, 700, "char", "boundary_peak|monotonic_repair"),
    ]
    assert rows["c1"]["word_timing"] == {"source": "", "basis": "", "pieces": []}
    verification = export.verify_subtitle_artifact(
        export.SubtitleExportArtifact(artifact.path, "json", "", 4), project)
    assert verification.valid


def test_stale_alignment_row_is_not_exported(tmp_path):
    project = aligned_project()
    project.cues[0].text = "行くぞー！"  # text changed after alignment
    payload = json.loads(export._compile_json(project))
    assert payload["cues"][0]["word_timing"]["pieces"] == []


def test_json_uses_caption_receipt_words_for_independent_captions():
    project = aligned_project()
    first = project.cues[0]
    project.render_settings["_cue_domain"] = "timeline"
    project.studio_state["caption_timeline"] = {"version": 1, "instances": {first.id: {
        "text": first.text, "word_alignment": "exact_token_text",
        "words": [{"text": "行く", "char_start": 0, "char_end": 2, "start_ms": 150, "end_ms": 470,
                   "evidence_ref": "cue-align:c0"},
                  {"text": "ぞ", "char_start": 2, "char_end": 3, "start_ms": 470, "end_ms": 750,
                   "evidence_ref": "cue-align:c0"}]}}}
    payload = json.loads(export._compile_json(project))
    timing = payload["cues"][0]["word_timing"]
    assert timing["source"] == "caption_receipt" and timing["basis"] == "exact_token_text"
    assert [(p["start_ms"], p["end_ms"], p["granularity"]) for p in timing["pieces"]] == [
        (150, 470, "word"), (470, 750, "char")]


def test_old_export_path_keeps_overwriting_and_gains_json_keys(tmp_path):
    project = aligned_project()
    (tmp_path / "result.json").write_text("old", encoding="utf-8")
    artifacts = export.export_subtitle_artifacts(project, tmp_path, "result",
                                                 export.SubtitleExportOptions(frozenset({"json", "srt"})))
    assert {artifact.path.name for artifact in artifacts} == {"result.json", "result.srt"}
    payload = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert payload["cues"][0]["translation"]["text"] == "走了！"
    assert payload["cues"][0]["word_timing"]["pieces"]
    assert "走了！" not in (tmp_path / "result.srt").read_text(encoding="utf-8")  # SRT stays original
