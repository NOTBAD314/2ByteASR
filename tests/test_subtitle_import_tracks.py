"""SRT import contracts: independent sources, exact manuscript and atomic edits."""
import copy
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker,
    SubtitleProject, save_project, load_project)
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.projects.subtitle_import import (IMPORT_KEY, filename_metadata, imported_track,
    prepare_import, read_subtitles, sidecar_path)
from twobyteasr.timeline.subtitle_import_command import ImportSubtitlesCommand
from twobyteasr.exports.studio_subtitle_export import (compile_srt, export_subtitle_artifacts,
    export_language_layers, SubtitleExportOptions, planned_subtitle_files)


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def project():
    return SubtitleProject(StudioMedia(""), render_settings={"_cue_domain": "timeline"},
                           edit_sequence={"empty_timeline": True})


def srt(folder, name, text="正文 S00、IT（台词）\n  第二行  ", number=1):
    path = folder / (name + ".srt")
    path.write_text(compile_srt([StudioCue("external", 123, 2345, text)]).replace("1\n", f"{number}\n", 1), "utf-8")
    return path


def apply(p, paths, stack=None, **kwargs):
    stack = stack if stack is not None else QUndoStack()
    plan = prepare_import(p, paths, **kwargs)
    assert plan.cues and not plan.failures
    stack.push(ImportSubtitlesCommand(p, plan))
    return plan, stack


def contents(p):
    return sorted((imported_track(p, c.speaker_id).get("speaker"),
                   imported_track(p, c.speaker_id).get("language"), c.start_ms, c.end_ms, c.text)
                  for c in p.cues)


@pytest.mark.parametrize("name, expected", [
    ("S00zh", ("S00", "zh")), ("s01IT", ("S01", "it")),
    ("实况_S00.it", ("S00", "it")), ("实况-S01_zh-Hant", ("S01", "zh-Hant")),
    ("实况_s01-ZH_hans", ("S01", "zh-Hans")), ("字幕_S01 (2).it", ("S01", "it")),
    ("S00_zh_CN", ("S00", "zh-CN")), ("字幕_S00", ("S00", "")),
    ("subtitle", ("", "")), ("visit", ("", "")), ("IT", ("", "")),
    ("字幕_S00.translation.zh", ("S00", "zh")),
    ("S00剧情", ("", "")), ("S00itinerary", ("", "")), ("字幕.ru", ("", "ru")),
])
def test_terminal_filename_fields_only(name, expected):
    assert filename_metadata(Path(name + ".srt")) == expected


@pytest.mark.parametrize("order", [("S00it", "S00zh", "S01it", "S01zh"),
                                   ("S01zh", "S00zh", "S01it", "S00it")])
def test_four_language_speaker_tracks_without_pairing_or_time_shift(tmp_path, order):
    p = project()
    plan, stack = apply(p, [srt(tmp_path, name, name) for name in order])
    assert {s.name for s in p.speakers} == {"S00 · 中文", "S00 · 意大利语", "S01 · 中文", "S01 · 意大利语"}
    assert len({c.id for c in p.cues}) == len({c.speaker_id for c in p.cues}) == 4
    assert {(c.start_ms, c.end_ms) for c in p.cues} == {(123, 2345)}
    assert all(x["file_number"] == 1 for x in plan.cue_sources.values())
    assert "translation_records" not in p.generation_metadata
    assert state_for(p).commit_count == 1
    stack.undo()
    assert not p.cues and not p.speakers
    stack.redo()
    assert len(p.cues) == len(p.speakers) == 4


def test_empty_import_example_and_duplicate_ids_are_isolated(tmp_path):
    p = project()
    apply(p, [srt(tmp_path, "S00zh"), srt(tmp_path, "s01IT")])
    assert [s.name for s in p.speakers] == ["S00 · 中文", "S01 · 意大利语"]
    before = copy.deepcopy(p.cues)
    apply(p, [tmp_path / "S00zh.srt"])
    assert p.speakers[-1].name == "S00 · 中文（2）"
    assert p.cues[:2] == before and len({c.id for c in p.cues}) == 3


def test_existing_edits_translations_and_unknown_source_survive(tmp_path):
    p = project()
    p.speakers = [StudioSpeaker("S00", "已有主讲")]
    p.cues = [StudioCue("import-1", 123, 2345, "人工改字", original_text="原识别")]
    p.generation_metadata["translations"] = {"import-1": "已有译文"}
    p.generation_metadata["translation_records"] = {"version": 1, "target": "zh-Hans", "records": {"import-1": {"text": "已有译文"}}}
    before = copy.deepcopy((p.cues, p.speakers, p.generation_metadata))
    plan, stack = apply(p, [srt(tmp_path, "visiting", number=47)])
    assert p.cues[0] == before[0][0]
    assert p.cues[0] is not p.cues[1] and p.cues[1].speaker_id != "S00"
    assert p.cues[1].text == "正文 S00、IT（台词）\n  第二行  "
    assert p.speakers[1].name == "visiting · 未指定语言"
    assert plan.cue_sources[p.cues[1].id]["file_number"] == 47
    assert p.generation_metadata["translations"] == before[2]["translations"]
    stack.undo()
    assert (p.cues, p.speakers, p.generation_metadata) == before
    stack.redo()
    assert len(p.cues) == 2


def test_explicit_replace_only_one_track_and_undo_restores_it(tmp_path):
    p = project()
    _, stack = apply(p, [srt(tmp_path, "S00it", "意文"), srt(tmp_path, "S00zh", "旧中文")])
    old = copy.deepcopy((p.cues, p.speakers, p.generation_metadata))
    track = p.cues[-1].speaker_id
    apply(p, [srt(tmp_path, "新_S00zh", "新中文")], stack, replace_track_id=track)
    assert [c.text for c in p.cues] == ["意文", "新中文"]
    assert p.speakers == old[1] and p.cues[-1].speaker_id == track
    stack.undo()
    assert (p.cues, p.speakers, p.generation_metadata) == old
    stack.redo()
    assert [c.text for c in p.cues] == ["意文", "新中文"]
    apply(p, [srt(tmp_path, "s01IT", "新说话人意文")], stack, replace_track_id=track)
    assert p.speakers[-1].id == track and p.speakers[-1].name == "S01 · 意大利语"
    assert imported_track(p, track)["speaker"] == "S01" and imported_track(p, track)["language"] == "it"
    stack.undo()
    assert p.speakers[-1].name == "S00 · 中文"


def test_failures_do_not_mutate_and_successes_commit_once(tmp_path):
    p = project()
    path = srt(tmp_path, "S00zh")
    bad = tmp_path / "broken.srt"
    bad.write_text("1\n00:00:02,000 --> 00:00:01,000\n坏时间\n", "utf-8")
    before = copy.deepcopy(p)
    plan = prepare_import(p, [path, bad, tmp_path / "missing.srt"])
    assert p == before and len(plan.failures) == 2 and len(plan.cues) == 1
    stack = QUndoStack()
    stack.push(ImportSubtitlesCommand(p, plan))
    assert len(p.cues) == 1 and state_for(p).commit_count == 1
    stack.undo()
    assert not p.cues
    invalid = prepare_import(p, [bad])
    assert not invalid.cues
    with pytest.raises(ValueError):
        ImportSubtitlesCommand(p, invalid)


def test_save_reopen_preserves_track_and_cue_sources(tmp_path):
    p = project()
    apply(p, [srt(tmp_path, "S00zh-Hant"), srt(tmp_path, "s01IT")])
    expected = contents(p)
    file = tmp_path / "工程.2byteproj"
    save_project(p, file)
    reopened = load_project(file)
    assert contents(reopened) == expected
    assert reopened.generation_metadata[IMPORT_KEY] == p.generation_metadata[IMPORT_KEY]
    assert [s.name for s in reopened.speakers] == [s.name for s in p.speakers]


def test_mixed_combined_export_restores_all_ownership(tmp_path):
    p = project()
    apply(p, [srt(tmp_path, name, name) for name in ("S00it", "S00zh", "S01it", "S01zh")])
    artifacts = export_subtitle_artifacts(p, tmp_path / "export", "合并字幕", SubtitleExportOptions())
    q = project()
    apply(q, [a.path for a in artifacts])
    assert contents(q) == contents(p)
    assert len(q.speakers) == 4
    again = export_subtitle_artifacts(q, tmp_path / "again", "字幕", SubtitleExportOptions(speaker_mode="per_speaker"))
    r = project()
    apply(r, [a.path for a in reversed(again)])
    assert contents(r) == contents(p)
    assert len(r.cues) == 4


def test_real_layer_writer_unequal_translations_and_per_track_languages(tmp_path):
    from twobyteasr.subtitle_rules import subtitle_translation as st
    p = project()
    p.generation_metadata["language"] = {"code": "it"}
    p.speakers = [StudioSpeaker("S00", "S00"), StudioSpeaker("S01", "S01")]
    p.cues = [StudioCue("one", 123, 2345, "Ciao", "S00"),
              StudioCue("two", 2500, 3500, "Bene", "S00"),
              StudioCue("three", 123, 2345, "Pronto", "S01")]
    st.set_manual(p, "one", "你好", target="zh-Hans")
    st.set_manual(p, "three", "喂", target="zh-Hans")
    result = export_language_layers(p, tmp_path / "first", "字幕", ("original", "translation"), speaker_mode="per_speaker")
    assert {a.path.name for a in result.artifacts} == {"字幕_S00.it.srt", "字幕_S00.zh.srt", "字幕_S01.it.srt", "字幕_S01.zh.srt"}
    q = project()
    apply(q, [a.path for a in reversed(result.artifacts)])
    assert len(q.cues) == 5 and len(q.speakers) == 4
    assert sum(c.text == "Bene" for c in q.cues) == 1
    sources = q.generation_metadata[IMPORT_KEY]["cues"]
    pairs = [s for s in sources.values() if s["source_cue"] == "one"]
    assert len(pairs) == 2 and len({s["export_id"] for s in pairs}) == 1
    assert {s["role"] for s in pairs} == {"original", "translation"}
    assert "translation_records" not in q.generation_metadata  # no forced pairing/duplicate preview
    result2 = export_language_layers(q, tmp_path / "second", "新字幕", ("original",), speaker_mode="per_speaker")
    assert {a.path.suffix for a in result2.artifacts} == {".srt"}
    assert sorted(len(read_subtitles(a.path).rows) for a in result2.artifacts) == [1, 1, 1, 2]
    for a in result2.artifacts:
        assert a.path.stem.endswith(".it" if imported_track(q, a.speaker_id)["language"] == "it" else ".zh-Hans")
    r = project()
    apply(r, [a.path for a in result2.artifacts])
    assert contents(r) == contents(q)
    source_associations = {c.text: q.generation_metadata[IMPORT_KEY]["cues"][c.id]["association"] for c in q.cues}
    restored_associations = {c.text: r.generation_metadata[IMPORT_KEY]["cues"][c.id]["association"] for c in r.cues}
    assert restored_associations == source_associations
    assert source_associations["Ciao"] == source_associations["你好"]
    planned = planned_subtitle_files(q, tmp_path / "new", "新字幕", SubtitleExportOptions(speaker_mode="per_speaker"), ("original",))
    assert {a.name for a in planned} == {a.path.name for a in result2.artifacts}


def test_filename_fallback_stale_sidecar_and_verified_conflict(tmp_path):
    p = project()
    apply(p, [srt(tmp_path, "S00zh", "保留")])
    out, = export_subtitle_artifacts(p, tmp_path / "out", "S01it", SubtitleExportOptions())
    parsed = read_subtitles(out.path)
    assert parsed.rows[0].speaker == "S00" and parsed.rows[0].language == "zh"
    assert any("冲突" in item for item in parsed.warnings)
    out.path.write_text(out.path.read_text("utf-8").replace("保留", "外部编辑"), "utf-8")
    parsed = read_subtitles(out.path)
    assert parsed.rows[0].speaker == "S01" and parsed.rows[0].text == "外部编辑"
    assert parsed.warnings and not parsed.export_id


def test_export_without_companion_still_has_filename_fallback(tmp_path):
    p = project()
    p.generation_metadata["language"] = {"code": "it"}
    p.speakers = [StudioSpeaker("S00", "S00")]
    p.cues = [StudioCue("source", 1000, 2000, "Ciao")]
    result = export_language_layers(p, tmp_path / "out", "视频", ("original",), speaker_mode="per_speaker")
    path = result.artifacts[0].path
    sidecar_path(path).unlink()
    q = project()
    apply(q, [path])
    assert q.speakers[0].name == "S00 · 意大利语"


def test_unknown_language_is_not_exported_as_japanese(tmp_path):
    p = project()
    apply(p, [srt(tmp_path, "ordinary")])
    result = export_language_layers(p, tmp_path / "out", "字幕", ("original",))
    assert result.artifacts[0].path.name == "字幕.und.srt"
    assert read_subtitles(result.artifacts[0].path).rows[0].language == ""


def test_large_batch_has_one_transaction(tmp_path):
    p = project()
    path = tmp_path / "S00it.srt"
    path.write_text(compile_srt([StudioCue(f"n{i}", i * 1000, i * 1000 + 900, f"riga {i}") for i in range(5000)]), "utf-8")
    plan, stack = apply(p, [path])
    assert len(p.cues) == 5000 and state_for(p).commit_count == 1
    assert len({c.id for c in p.cues}) == 5000
    stack.undo()
    assert not p.cues
    stack.redo()
    assert len(p.cues) == 5000 and state_for(p).commit_count == 3


def test_unknown_track_labels_can_be_edited_without_changing_ownership(tmp_path):
    from twobyteasr.studio.subtitle_track_metadata import SetSubtitleTrackMetadataCommand
    p = project()
    _, stack = apply(p, [srt(tmp_path, "ordinary")])
    track_id, cue_id = p.speakers[0].id, p.cues[0].id
    stack.push(SetSubtitleTrackMetadataCommand(p, track_id, "s01", "IT-it"))
    assert p.speakers[0].name == "S01 · 意大利语（IT）"
    assert imported_track(p, track_id)["language"] == "it-IT"
    assert (p.cues[0].speaker_id, p.cues[0].id) == (track_id, cue_id)
    stack.undo()
    assert p.speakers[0].name == "ordinary · 未指定语言"
    stack.undo()
    stack.redo()
    stack.redo()
    assert p.speakers[0].name == "S01 · 意大利语（IT）"


def test_old_optional_json_is_used_only_after_complete_body_and_time_match(tmp_path):
    p = project()
    p.generation_metadata["language"] = {"code": "it"}
    p.speakers = [StudioSpeaker("S00", "S00"), StudioSpeaker("S01", "S01")]
    p.cues = [StudioCue("a", 100, 1200, "Ciao", "S00"), StudioCue("b", 100, 1200, "Pronto", "S01")]
    exported = export_subtitle_artifacts(p, tmp_path / "out", "旧字幕", SubtitleExportOptions(frozenset({"srt", "json"})))
    path = next(a.path for a in exported if a.format == "srt")
    sidecar_path(path).unlink()
    q = project()
    apply(q, [path])
    assert {s.name for s in q.speakers} == {"S00 · 意大利语", "S01 · 意大利语"}
    path.write_text(path.read_text("utf-8").replace("Ciao", "外部人工改字"), "utf-8")
    r = project()
    plan, _ = apply(r, [path])
    assert len(r.speakers) == 1 and r.cues[0].text == "外部人工改字" and plan.warnings


def test_recognition_writer_metadata_has_actual_byte_digest_and_row_scope(tmp_path):
    import subtitle_core
    from twobyteasr.recognition.run_context import get_runtime_context
    context = get_runtime_context()
    before_language = context.task_language
    context.task_language = "it"
    try:
        cues = [subtitle_core.SubtitleCue(1, .1, 1.2, "Ciao", speaker="S00"),
                subtitle_core.SubtitleCue(2, 1.3, 2.4, "Pronto", speaker="S01")]
        path = tmp_path / "录音.srt"
        subtitle_core.write_all_outputs_transactional(cues, str(tmp_path / "文稿.txt"), str(path),
                                                     include_review_track=False, include_speaker_tracks=True)
        q = project()
        apply(q, [path])
        assert {s.name for s in q.speakers} == {"S00 · 意大利语", "S01 · 意大利语"}
        assert [c.text for c in q.cues] == ["Ciao", "Pronto"]
        assert {(c.start_ms, c.end_ms) for c in q.cues} == {(100, 1200), (1300, 2400)}
        assert len(list(tmp_path.glob("*.srt.2byte.json"))) == 3
    finally:
        context.task_language = before_language
