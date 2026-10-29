"""Real files through the language exporter, including filename collisions."""
from pathlib import Path

import pytest

from twobyteasr.exports import studio_subtitle_export as export
from twobyteasr.exports.srt_codec import parse_srt
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
from twobyteasr.subtitle_rules import subtitle_translation as translation


def project(target="ja"):
    p = SubtitleProject(StudioMedia("", duration_ms=10000), cues=[
        StudioCue("stable-90", 1000, 2400, "原文一"),
        StudioCue("stable-3", 4000, 5900, "原文二"),
    ], generation_metadata={"language": {"code": "zh"}})
    p.validate()
    p.generation_metadata[translation.RECORDS_KEY] = translation._empty_container(target)
    for cue, text in zip(p.cues, ("日本語の訳", "最新の訳 😀")):
        translation.set_manual(p, cue.id, text, target=target)
    return p


def read(artifact):
    rows, errors = parse_srt(artifact.path.read_text(encoding="utf-8"))
    assert not errors
    assert artifact.path.stat().st_size > 0
    return rows


@pytest.mark.parametrize("speaker_mode", ["combined", "per_speaker", "both"])
def test_source_and_target_suffix_collision_does_not_overwrite_staged_srt(tmp_path, speaker_mode):
    p = project("zh-Hans")
    # Legacy projects default to zh for the translation target. Two distinct
    # manuscripts must still get distinct filenames when the suffix agrees.
    for cue in p.cues:
        translation.set_manual(p, cue.id, "译文 " + cue.id, target="zh-Hans")
    folder = tmp_path / "中文 空格 (导出)"
    result = export.export_language_layers(p, folder, "实况", speaker_mode=speaker_mode)
    assert len({a.path for a in result.artifacts}) == len(result.artifacts)
    for a in result.artifacts:
        rows = read(a)
        assert [r.start_ms for r in rows] == [1000, 4000]
        if a.layer == "translation":
            assert [r.text for r in rows] == ["译文 stable-90", "译文 stable-3"]
        elif a.layer == "original":
            assert [r.text for r in rows] == ["原文一", "原文二"]
    planned = export.planned_subtitle_files(p, tmp_path / "empty", "实况", export.SubtitleExportOptions(),
                                            ("original", "translation", "bilingual"))
    combined = [a for a in result.artifacts if not a.speaker_id]
    if combined:
        assert {a.path.name for a in combined} == {a.name for a in planned}


def test_latest_manual_translation_saved_reopened_and_exported_by_stable_id(tmp_path):
    p = project()
    translation.set_manual(p, "stable-3", "今変更した訳\n二行目", target="ja")
    path = tmp_path / "工程 中文.2byteproj"
    save_project(p, path)
    reopened = load_project(path)
    for label, source in (("live", p), ("reopened", reopened)):
        result = export.export_language_layers(source, tmp_path / label, "字幕")
        layers = {a.layer: read(a) for a in result.artifacts}
        assert [r.text for r in layers["translation"]] == ["日本語の訳", "今変更した訳\n二行目"]
        assert [(r.start_ms, r.end_ms) for r in layers["translation"]] == [(1000, 2400), (4000, 5900)]
        assert layers["original"][1].text == "原文二"
        assert layers["bilingual"][1].text == "今変更した訳\n二行目\n原文二"


def test_missing_translation_is_reported_and_an_entirely_empty_layer_is_refused(tmp_path):
    p = project()
    translation.set_manual(p, "stable-3", "", target="ja")
    result = export.export_language_layers(p, tmp_path / "partial", "字幕")
    a = next(a for a in result.artifacts if a.layer == "translation")
    assert [r.text for r in read(a)] == ["日本語の訳"]
    assert result.missing_translation_ids == ("stable-3",)
    translation.set_manual(p, "stable-90", "", target="ja")
    with pytest.raises(ValueError, match="译文"):
        export.export_language_layers(p, tmp_path / "empty", "字幕", ("original", "translation"))
    assert not list((tmp_path / "empty").glob("*.srt"))


def test_write_failure_does_not_claim_success_or_replace_existing_file(tmp_path, monkeypatch):
    p = project()
    original = tmp_path / "字幕.zh.srt"
    original.write_text("existing", encoding="utf-8")
    def deny(*args):
        raise PermissionError("write denied for test")
    monkeypatch.setattr(export, "_atomic_text_write", deny)
    with pytest.raises(PermissionError):
        export.export_language_layers(p, tmp_path, "字幕")
    assert original.read_text(encoding="utf-8") == "existing"
    assert not list(tmp_path.glob("*.ja.srt"))


def test_previous_target_language_is_not_written_as_the_new_language(tmp_path):
    with pytest.raises(ValueError, match="目标语言 en"):
        export.export_language_layers(project(), tmp_path, "字幕", ("translation",), target="en")
    assert not list(tmp_path.glob("*.srt"))


def test_canonical_records_are_detected_without_legacy_render_cache():
    p = project()
    p.generation_metadata.pop("translations", None)
    assert export.has_translations(p)


def test_empty_media_uses_saved_project_folder_instead_of_process_cwd(tmp_path):
    from twobyteasr.exports.studio_export_ui import resolve_subtitle_export_destination
    destination, reason = resolve_subtitle_export_destination(project(), tmp_path / "工程.2byteproj", "source")
    assert destination == tmp_path / "exports"
    assert "工程" in reason
