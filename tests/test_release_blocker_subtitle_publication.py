"""G02: validate every candidate before replacing any user's artifact."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.exports import studio_subtitle_export as export

def project(text="中文😀字幕"):
    p = SubtitleProject(media=StudioMedia(path="synthetic.mp4", duration_ms=3000),
                        cues=[StudioCue("c", 100, 2100, text)])
    p.validate()
    return p

@pytest.mark.parametrize("fmt,text", [("srt", "第一行\r\n第二行"), ("txt", "甲\u2028乙"), ("txt", "甲\u2029乙"), ("ass", "甲\r\n乙{x} C:\\path")])
def test_real_newline_variants_export_and_read_back(tmp_path, fmt, text):
    p = project(text)
    artifacts = export.export_subtitle_artifacts(p, tmp_path, "result", export.SubtitleExportOptions(frozenset({fmt})))
    assert export.verify_subtitle_artifact(artifacts[0], p).valid

def test_verification_failure_preserves_all_old_formats(tmp_path, monkeypatch):
    originals = {fmt: ("旧成果" + fmt).encode("utf8") for fmt in ("json", "srt", "txt")}
    for fmt, data in originals.items(): (tmp_path / f"result.{fmt}").write_bytes(data)
    real = export.verify_subtitle_artifact
    def fail_last(artifact, p):
        if artifact.format == "txt": raise RuntimeError("injected verification failure")
        return real(artifact, p)
    monkeypatch.setattr(export, "verify_subtitle_artifact", fail_last)
    with pytest.raises(RuntimeError):
        export.export_subtitle_artifacts(project(), tmp_path, "result", export.SubtitleExportOptions(frozenset(originals)))
    assert {fmt: (tmp_path / f"result.{fmt}").read_bytes() for fmt in originals} == originals
    assert len(list(tmp_path.iterdir())) == 3

def test_disk_full_during_staging_preserves_previous_outputs(tmp_path, monkeypatch):
    for fmt in ("json", "txt"): (tmp_path / f"result.{fmt}").write_bytes(b"old")
    real = export._atomic_text_write
    def write(path, content):
        if path.suffix == ".txt": raise OSError(28, "disk full")
        real(path, content)
    monkeypatch.setattr(export, "_atomic_text_write", write)
    with pytest.raises(OSError):
        export.export_subtitle_artifacts(project(), tmp_path, "result", export.SubtitleExportOptions(frozenset({"json", "txt"})))
    assert all((tmp_path / f"result.{fmt}").read_bytes() == b"old" for fmt in ("json", "txt"))
    assert len(list(tmp_path.iterdir())) == 2

def test_locked_publish_target_reports_partial_success(tmp_path, monkeypatch):
    target = tmp_path / "result.txt"
    target.write_bytes(b"old-txt")
    real = export.os.replace
    def replace(source, dest):
        if os.fspath(dest) == str(target): raise PermissionError("locked target")
        return real(source, dest)
    monkeypatch.setattr(export.os, "replace", replace)
    with pytest.raises(Exception) as caught:
        export.export_subtitle_artifacts(project(), tmp_path, "result", export.SubtitleExportOptions(frozenset({"json", "txt"})))
    assert target.read_bytes() == b"old-txt"
    assert [a.format for a in caught.value.published] == ["json"]
    assert "1" in str(caught.value)
    assert len(list(tmp_path.iterdir())) == 2

def test_success_all_formats_reopens_with_same_unicode_and_times(tmp_path):
    from twobyteasr.projects.studio_project import save_project, load_project
    p = project()
    loaded = load_project(save_project(p, tmp_path / "input.2byteproj"))
    artifacts = export.export_subtitle_artifacts(loaded, tmp_path / "out", "result", export.SubtitleExportOptions(frozenset({"json", "txt", "srt", "ass"})))
    assert len(artifacts) == 4
    assert all(export.verify_subtitle_artifact(a, loaded).valid for a in artifacts)

def test_speaker_filename_collisions_remain_unique_on_windows(tmp_path):
    from twobyteasr.projects.studio_project import StudioSpeaker
    p = project()
    ids = ["A", "A_3", "a"]
    p.speakers = [StudioSpeaker(s, s) for s in ids]
    p.cues = [StudioCue(str(i), 0, 1000, s, speaker_id=s) for i, s in enumerate(ids)]
    artifacts = export.export_subtitle_artifacts(p, tmp_path, "result", export.SubtitleExportOptions(frozenset({"json"}), "per_speaker"))
    assert len({a.path.name.casefold() for a in artifacts}) == 3
    import json
    assert [json.loads(a.path.read_text(encoding="utf8"))["cues"][0]["speaker_id"] for a in artifacts] == ids

def test_empty_first_srt_cue_does_not_consume_next_record(tmp_path):
    p = project('')
    p.cues.append(StudioCue('second', 2200, 2800, '第二条'))
    artifacts = export.export_subtitle_artifacts(p, tmp_path, 'empty-first', export.SubtitleExportOptions(frozenset({'srt'})))
    assert export.verify_subtitle_artifact(artifacts[0], p).valid
