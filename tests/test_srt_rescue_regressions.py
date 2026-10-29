"""Lossless SRT framing and independent read-back, including adversarial writes."""
import copy
from dataclasses import asdict

import pytest

from twobyteasr.exports import studio_subtitle_export as export
from twobyteasr.exports.srt_codec import normalize_srt_text, parse_srt
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject


def fixture_project():
    texts = ["中文、日文 日本語 😀 <>&{}\\N", "第一行\n第二行", "上半句\n", "第二句话",
             "空行\n\n123\n数字后正文\n\n", "", "  两侧空格 \t\n \n末行  "]
    ids = ["S00", "S01", "S02", "S02", "S03", "S02", "S03"]
    p = SubtitleProject(StudioMedia("missing.mp4", duration_ms=20000),
        cues=[StudioCue(f"cue-{i}", 1000+i*2000, 1800+i*2000, t, s) for i,(t,s) in enumerate(zip(texts,ids))],
        speakers=[StudioSpeaker(f"S{i:02d}", f"S{i:02d}") for i in range(5)])
    p.validate()
    return p


@pytest.mark.parametrize("text", ["上半句\n", "\n", "\n\n", "", "甲\r\n乙\r", "甲\n\n123\n乙",
                                     "  甲 \t\n \n乙  ", "中文 日本語 😀 <>&{}\\N\u2028\u2029", "123", "\n\n开头"])
def test_exact_text_roundtrip_first_and_last(text, tmp_path):
    p = fixture_project()
    p.cues = [StudioCue("first", 1000, 1800, text), StudioCue("last", 2000, 2800, text)]
    original = copy.deepcopy(p.cues)
    path = tmp_path / "字幕 (1).srt"
    path.write_text(export.compile_srt(p.cues), encoding="utf-8", newline="\n")
    rows, errors = parse_srt(path.read_text(encoding="utf-8"))
    assert not errors and len(rows) == 2
    assert [row.text for row in rows] == [normalize_srt_text(text)] * 2
    assert export.verify_subtitle_artifact(export.SubtitleExportArtifact(path, "srt", "", 2), p).valid
    assert p.cues == original


def test_four_speakers_chinese_spaces_and_parentheses(tmp_path):
    p = fixture_project()
    before = copy.deepcopy(p.cues)
    artifacts = export.export_subtitle_artifacts(p, tmp_path / "剪映 10月20日 (1)", "10月20日 (1)",
        export.SubtitleExportOptions(frozenset({"srt"}), "per_speaker"))
    assert len(artifacts) == 4 and sum(a.cue_count for a in artifacts) == len(p.cues)
    for a in artifacts:
        expected = copy.copy(p)
        expected.cues = [c for c in p.cues if c.speaker_id == a.speaker_id]
        assert export.verify_subtitle_artifact(a, expected).valid
    assert p.cues == before


@pytest.mark.parametrize("change,field", [
    (lambda s: s.replace("第二句话", "第二句话多出内容"), "text"),
    (lambda s: s.replace("00:00:07,000", "00:00:07,001"), "timestamps"),
    (lambda s: s.replace("2\n00:00:07", "8\n00:00:07"), "structure"),
    (lambda s: s.split("\n\n2\n")[0] + "\n", "count"),
])
def test_corruption_identifies_cue_and_is_not_self_verification(change, field, tmp_path):
    p = fixture_project()
    p.cues = [c for c in p.cues if c.speaker_id == "S02"][:2]
    path = tmp_path / "S02.srt"
    path.write_text(change(export.compile_srt(p.cues)), encoding="utf-8")
    result = export.verify_subtitle_artifact(export.SubtitleExportArtifact(path, "srt", "S02", 2), p)
    assert not result.valid
    assert result.first_mismatch["field"] == field
    assert result.first_mismatch["cue_id"] == "cue-3"
    assert result.first_mismatch["subtitle_number"] == 2
    error = export.SubtitleVerificationError(path, "S02", result)
    assert "S02 第 2 条字幕" in str(error)
    assert '"expected_cue_count": 2' in error.details()


def test_speaker_scope_and_extra_records_are_independently_rejected(tmp_path):
    p = fixture_project()
    path = tmp_path / "S02.srt"
    path.write_text(export.compile_srt(p.cues), encoding="utf-8")
    a = export.SubtitleExportArtifact(path, "srt", "S02", len(p.cues))
    result = export.verify_subtitle_artifact(a, p)
    assert not result.speaker_mapping_valid and result.first_mismatch["field"] == "speaker"
    p.cues = []
    result = export.verify_subtitle_artifact(a, p)
    assert not result.valid and not result.count_valid


def test_s02_failure_cannot_replace_s00_s01_or_existing_s02(tmp_path, monkeypatch):
    p = fixture_project()
    originals = {}
    for i in range(4):
        path = tmp_path / f"已有_S{i:02d}.srt"
        path.write_bytes(b"old user output")
        originals[path] = path.read_bytes()
    writer = export._atomic_text_write
    def corrupt(path, content):
        writer(path, content.replace("第二句话", "损坏") if "S02" in path.name else content)
    monkeypatch.setattr(export, "_atomic_text_write", corrupt)
    with pytest.raises(export.SubtitleVerificationError) as caught:
        export.export_subtitle_artifacts(p, tmp_path, "已有", export.SubtitleExportOptions(frozenset({"srt"}), "per_speaker"))
    assert caught.value.verification.first_mismatch["cue_id"] == "cue-3"
    assert all(path.read_bytes() == value for path, value in originals.items())


def test_complete_header_in_body_fails_explicitly_instead_of_losing_text(tmp_path):
    p = fixture_project()
    p.cues = [StudioCue("ambiguous", 0, 1000, "正文\n\n2\n00:00:01,000 --> 00:00:02,000\n像标头")]
    with pytest.raises(export.SubtitleVerificationError):
        export.export_subtitle_artifacts(p, tmp_path, "ambiguous", export.SubtitleExportOptions())
    assert not list(tmp_path.glob("*.srt"))


def test_empty_track_and_language_layer_whitespace(tmp_path):
    p = fixture_project()
    p.cues = []
    a, = export.export_subtitle_artifacts(p, tmp_path, "empty", export.SubtitleExportOptions())
    assert a.cue_count == 0 and a.path.read_bytes() == b""
    p.cues = [StudioCue("cue", 0, 1000, "  中文\n\n123\n日文\n")]
    a, = export.export_language_layers(p, tmp_path, "layer", ("original",)).artifacts
    assert parse_srt(a.path.read_text(encoding="utf-8"))[0][0].text == p.cues[0].text
