import copy
import json

import pytest

from twobyteasr.exports import subtitle_rescue as rescue
from twobyteasr.exports.srt_codec import parse_srt
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
from twobyteasr.timeline.studio_edit_sequence import VideoSegment, sequence_of, replace_runtime_sequence


def saved_fixture(tmp_path, domain="source"):
    p = SubtitleProject(StudioMedia("missing-video.mp4", duration_ms=50000),
        cues=[StudioCue("edited", 11000, 11800, "最后修改\n", "S02", original_text="旧 ASR"),
              StudioCue("outside", 31000, 32000, "剪辑外原文", "S03")],
        speakers=[StudioSpeaker("S02", "S02", hidden=True), StudioSpeaker("S03", "S03"), StudioSpeaker("EMPTY", "空轨")])
    p.validate()
    seq = copy.deepcopy(sequence_of(p))
    seq.segments = [VideoSegment("cut", "missing-video.mp4", 10000, 20000, 0, 5000),
                    VideoSegment("repeat", "missing-video.mp4", 10000, 20000, 7000, 17000)]
    replace_runtime_sequence(p, seq)
    if domain == "timeline":
        p.render_settings["_cue_domain"] = "timeline"
        p.cues[0].start_ms, p.cues[0].end_ms = 1200, 2000
    return save_project(p, tmp_path / "10月20日 (1).2byteproj")


def test_recovery_maps_cut_speed_and_repeat_without_player_or_input_write(tmp_path, monkeypatch):
    import subprocess
    source = saved_fixture(tmp_path)
    before = source.read_bytes()
    def prohibited(*args, **kwargs):
        raise AssertionError("rescue must not launch a player, recognizer or other process")
    monkeypatch.setattr(subprocess, "Popen", prohibited)
    output = rescue.rescue_subtitles(source, tmp_path / "中文 输出 (1)")
    manifest = json.loads((output / "rescue-manifest.json").read_text(encoding="utf-8"))
    assert source.read_bytes() == before == (output / "input-copy.json").read_bytes()
    assert manifest["timeline_cue_count"] == 2
    assert manifest["outside_current_timeline_ids"] == ["outside"]
    assert manifest["hidden_speakers_included"] == ["S02"]
    entry = next(f for f in manifest["files"] if f["speaker_id"] == "S02")
    rows, errors = parse_srt((output / entry["name"]).read_text(encoding="utf-8"))
    assert not errors
    assert [(r.start_ms,r.end_ms,r.text) for r in rows] == [(500,900,"最后修改\n"),(8000,8800,"最后修改\n")]
    assert all(f["cue_count"] == 0 for f in manifest["files"] if f["speaker_id"] in {"EMPTY","S03"})
    again = rescue.rescue_subtitles(source, output.parent)
    assert again != output and (output / entry["name"]).exists()


def test_independent_caption_time_is_not_reprojected(tmp_path):
    source = saved_fixture(tmp_path, "timeline")
    out = rescue.rescue_subtitles(source, tmp_path / "out")
    rows, _ = parse_srt(next(out.glob("*_S02.srt")).read_text(encoding="utf-8"))
    assert [(r.start_ms,r.end_ms,r.text) for r in rows] == [(1200,2000,"最后修改\n")]


def test_recognition_snapshot_uses_current_edit_clock(tmp_path):
    source = saved_fixture(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    old_seq = copy.deepcopy(payload["edit_sequence"])
    old_seq["segments"] = [old_seq["segments"][0]]
    old_seq["segments"][0]["timeline_out_ms"] = 10000
    payload["generation_metadata"]["timeline_recognition"] = {"sequence": old_seq}
    payload["cues"] = [dict(payload["cues"][0], start_ms=1000, end_ms=1800)]
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = rescue.rescue_subtitles(source, tmp_path / "out")
    rows, _ = parse_srt(next(out.glob("*_S02.srt")).read_text(encoding="utf-8"))
    # Captured cut has the same instance id. A same-source unrelated repeat
    # must not multiply recognized cues.
    assert [(r.start_ms,r.end_ms) for r in rows] == [(500,900)]


@pytest.mark.parametrize("payload", [
    {"schema_version":1,"job_id":"job","result":{"cue_count":548}},
    [{"text":"ASR","start":1,"end":2}],
    {"kind":"2byteasr-subtitle-export","schema_version":1,"cues":[{"id":"c","text":"x","start_ms":1.2,"end_ms":2}]},
])
def test_ambiguous_or_invalid_json_does_not_fake_timeline(payload, tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(rescue.RescueInputError):
        rescue.rescue_subtitles(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_export_json_manuscript_and_explicit_timeline(tmp_path):
    source = tmp_path / "export.json"
    source.write_text(json.dumps({"kind":"2byteasr-subtitle-export","schema_version":1,
        "cues":[{"id":"c","text":"已加标点。","original_text":"最后编辑\n", "speaker_id":"S02",
                 "start_ms":1000,"end_ms":1800}]}), encoding="utf-8")
    out = rescue.rescue_subtitles(source, tmp_path)
    rows, _ = parse_srt(next(out.glob("*_S02.srt")).read_text(encoding="utf-8"))
    assert rows[0].text == "最后编辑\n" and rows[0].start_ms == 1000


def test_rescue_publication_failure_reports_every_file(tmp_path, monkeypatch):
    source = saved_fixture(tmp_path)
    publish = rescue._publish_new
    def fail(candidate, target):
        if target.name.endswith("_S02.srt"):
            raise PermissionError("injected locked target")
        publish(candidate,target)
    monkeypatch.setattr(rescue,"_publish_new",fail)
    with pytest.raises(rescue.RescueExportError) as caught:
        rescue.rescue_subtitles(source,tmp_path / "out")
    error = caught.value
    assert len(error.published) == 1 and error.pending
    report = json.loads((error.directory / "rescue-failure.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["published"] == error.published
    assert len(report["not_published"]) == 5
