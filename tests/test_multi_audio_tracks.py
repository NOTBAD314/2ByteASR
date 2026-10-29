"""Multi-track MP4/MKV: every audio stream visible, the picked one recognized.

2026-10-24 (user): a file with several audio streams showed one waveform and
was recognized from whatever the timeline mix was. These tests pin the data
path probe -> project lanes -> graphs -> recognition input -> combined result,
with real FFmpeg media whose streams carry different tones, so a wrong stream
is caught by its frequency and not only by a command string.
"""
from __future__ import annotations

import json
import os
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from twobyteasr.media.audio_streams import (primary_ordinal, probe_audio_streams,
                                            stream_caption, stream_label)
from twobyteasr.playback.audio_graph import capture_audio_graph, capture_lane_audio_graph
from twobyteasr.projects.studio_project import (StudioMedia,
                                                SubtitleProject, hydrate_media_contract, load_project,
                                                save_project)
from twobyteasr.timeline.audio_stream_lanes import (has_multitrack_source, recognizable_lanes, source_key,
                                                    split_waveform_job, waveform_job)

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG.is_file() and FFPROBE.is_file()), reason="bundled FFmpeg missing")


def _streams(*specs):
    """ffprobe-like stream rows: ('v'|'a'|'s', extra fields)."""
    kinds = {"v": "video", "a": "audio", "s": "subtitle"}
    return [{"index": index, "codec_type": kinds[kind], "codec_name": "aac" if kind == "a" else "h264", **extra}
            for index, (kind, extra) in enumerate(specs)]


SOURCE = str(Path("x.mkv").resolve())


def _identity(streams, *, has_video=True):
    return {"source_path": SOURCE, "duration_ms": 10_000, "has_video": has_video, "has_audio": True,
            "width": 64, "height": 36, "fingerprint": "fp-x", "audio_streams": list(streams)}


def _project_with(streams, *, has_video=True):
    """A project made the way import makes it: one probe applied to a new project."""
    project = SubtitleProject(media=StudioMedia(path=SOURCE))
    hydrate_media_contract(project, _identity(streams, has_video=has_video), source_path=SOURCE)
    project.validate()
    return project


# ------------------------------------------------------------------ probing

def test_probe_keeps_absolute_and_relative_indexes_apart_and_labels_honestly():
    rows = probe_audio_streams(_streams(
        ("v", {}),
        ("a", {"channels": 2, "channel_layout": "stereo", "tags": {"language": "jpn", "title": "日语原音"},
               "disposition": {"default": 1}, "start_time": "0.000"}),
        ("s", {}),
        ("a", {"channels": 2, "tags": {"language": "chi", "name": "中文配音"}, "start_time": "3.000"}),
        ("a", {"channels": 1, "tags": {"handler_name": "SoundHandler", "DURATION": "00:00:05.760000000"}}),
        ("a", {"codec_name": "", "channels": 6, "channel_layout": "5.1(side)"}),
    ), container_start_ms=0)
    assert [(r["ordinal"], r["index"]) for r in rows] == [(0, 1), (1, 3), (2, 4), (3, 5)]
    assert rows[0]["default"] and not rows[1]["default"]
    assert rows[1]["start_ms"] == 3000.0 and rows[1]["title"] == "中文配音"
    # A generic handler name is no title; a missing language is not guessed.
    assert rows[2]["title"] == "" and rows[2]["language"] == "" and rows[2]["duration_ms"] == 5760
    assert not rows[3]["decodable"] and rows[3]["problem"]
    assert str(stream_label(rows[0])) == "音轨 1｜日语原音｜日语｜立体声"
    assert str(stream_label(rows[2])) == "音轨 3｜语言未标示｜单声道"
    assert str(stream_label(rows[3])).endswith("5.1 多声道")
    assert str(stream_caption(rows[1])) == "音轨 2｜中文配音"
    assert primary_ordinal(rows) == 0


def test_single_stereo_and_surround_streams_stay_one_track():
    for channels, layout in ((2, "stereo"), (6, "5.1")):
        rows = probe_audio_streams(_streams(("v", {}), ("a", {"channels": channels, "channel_layout": layout})))
        assert len(rows) == 1
        project = _project_with(rows)
        assert [t.stream_ordinal for t in project.audio_tracks] == [-1]
        assert not has_multitrack_source(project)


# ------------------------------------------------------------------ lanes

def _three_stream_rows(default=0):
    return probe_audio_streams(_streams(
        ("v", {}),
        ("a", {"channels": 2, "tags": {"title": "日语原音", "language": "jpn"}, "disposition": {"default": int(default == 0)}}),
        ("s", {}),
        ("a", {"channels": 2, "tags": {"title": "中文配音", "language": "chi"}, "start_time": "3.0",
               "disposition": {"default": int(default == 1)}}),
        ("a", {"channels": 1}),
    ))


def test_further_streams_become_muted_lanes_that_follow_the_video_clip(tmp_path):
    project = _project_with(_three_stream_rows())
    lanes = [(t.id, t.stream_ordinal, t.muted, t.linked_video_track_id) for t in project.audio_tracks]
    assert lanes == [("A1", -1, False, "V1"), ("A2", 1, True, "V1"), ("A3", 2, True, "V1")]
    assert [c.stream_index for t in project.audio_tracks for c in t.clips] == [0, 1, 2]
    # Trim the video clip: every stream lane follows it.
    clip = project.video_tracks[0].clips[0]
    clip.source_in_ms, clip.timeline_in_ms, clip.timeline_out_ms = 2000, 500, 8500
    project.validate()
    assert {(c.source_in_ms, c.timeline_in_ms, c.timeline_out_ms) for t in project.audio_tracks for c in t.clips} \
        == {(2000, 500, 8500)}
    # Save, reopen, re-probe: same lanes, no duplicates; only stream lanes carry the field.
    path = save_project(project, tmp_path / "multi.2byteproj")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert ["stream_ordinal" in t for t in payload["audio_tracks"]] == [False, True, True]
    reopened = load_project(path)
    hydrate_media_contract(reopened, _identity(_three_stream_rows()), source_path=SOURCE)
    reopened.validate()
    assert [t.id for t in reopened.audio_tracks] == ["A1", "A2", "A3"]
    # A lane the user deleted is not recreated by the next probe.
    reopened.audio_tracks = [t for t in reopened.audio_tracks if t.id != "A3"]
    reopened.validate()
    hydrate_media_contract(reopened, _identity(_three_stream_rows()), source_path=SOURCE)
    reopened.validate()
    assert [t.id for t in reopened.audio_tracks] == ["A1", "A2"]
    # Removing the video track removes its stream lanes with its A lane.
    reopened.video_tracks = []
    reopened.av_track_groups = []
    from twobyteasr.projects.studio_project import sync_linked_av_contract
    sync_linked_av_contract(reopened)
    assert all(t.stream_ordinal < 0 for t in reopened.audio_tracks)


def test_a_fresh_import_plays_the_files_default_stream():
    project = _project_with(_three_stream_rows(default=1))
    a1 = project.audio_tracks[0]
    assert a1.clips[0].stream_index == 1
    assert sorted(t.stream_ordinal for t in project.audio_tracks if t.stream_ordinal >= 0) == [0, 2]


def test_legacy_project_without_streams_gets_lanes_once_and_keeps_its_a1(tmp_path):
    identity = _identity([])
    identity.pop("audio_streams")
    project = SubtitleProject(media=StudioMedia(path=SOURCE))
    hydrate_media_contract(project, identity, source_path=SOURCE)
    project.validate()
    path = save_project(project, tmp_path / "legacy.2byteproj")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert all("stream_ordinal" not in t for t in payload["audio_tracks"])
    legacy = load_project(path)
    assert [t.id for t in legacy.audio_tracks] == ["A1"]
    for _ in range(2):
        hydrate_media_contract(legacy, _identity(_three_stream_rows(default=1)), source_path=SOURCE)
        legacy.validate()
    # A1 keeps what it played before (stream 0); the others are added once.
    assert legacy.audio_tracks[0].clips[0].stream_index == 0
    assert [t.stream_ordinal for t in legacy.audio_tracks] == [-1, 1, 2]


def test_pure_audio_file_with_two_streams_gets_two_lanes():
    from twobyteasr.timeline.studio_media_pool import add_media_asset
    project = SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    add_media_asset(project, "x.mka", duration_ms=10_000, video_metadata={"has_video": False},
                    audio_metadata={"has_audio": True, "streams": list(_three_stream_rows()[:2])})
    assert [(t.muted, [c.stream_index for c in t.clips]) for t in project.audio_tracks] == [(False, [0]), (True, [1])]


# ------------------------------------------------------------------ graphs

def test_stream_lanes_route_by_their_own_mute_and_solo():
    project = _project_with(_three_stream_rows())
    project.studio_state["audio_master_mode"] = "mix_all"
    assert {s["track_id"] for s in capture_audio_graph(project)["segments"]} == {"V1"}
    # Switch dub: mute A1 (stored on V1), unmute A2. Export hears only A2.
    project.video_tracks[0].muted = True
    project.audio_tracks[1].muted = False
    segments = capture_audio_graph(project)["segments"]
    assert [(s["track_id"], s["stream_index"], s["stream_start_ms"]) for s in segments] == [("A2", 1, 3000.0)]
    project.video_tracks[0].muted = False
    project.studio_state["audio_solo_track_ids"] = ["A2"]
    assert {s["track_id"] for s in capture_audio_graph(project)["segments"]} == {"A2"}


def test_lane_graph_ignores_monitoring_but_keeps_the_edit():
    project = _project_with(_three_stream_rows())
    project.studio_state["audio_solo_track_ids"] = ["V1"]
    graph = capture_lane_audio_graph(project, "A3")
    assert [(s["track_id"], s["stream_index"]) for s in graph["segments"]] == [("A3", 2)]
    graph = capture_lane_audio_graph(project, "A1")
    assert [(s["audio_track_id"], s["stream_index"]) for s in graph["segments"]] == [("A1", 0)]
    project.video_tracks[0].clips[0].enabled = False
    assert capture_lane_audio_graph(project, "A2")["segments"] == []


def test_late_stream_is_padded_only_before_its_first_sample():
    from twobyteasr.exports.audio_export import compile_audio_mix
    from twobyteasr.playback.audio_engine import build_audio_decode_command, stream_lead_filter
    assert stream_lead_filter(3000.0, 1000) == "adelay=2000:all=1,"
    assert stream_lead_filter(3000.0, 4000) == "" and stream_lead_filter(0.0, 0) == ""
    layer = dict(source_path="x.mkv", stream_index=1, timeline_in_ms=0, timeline_out_ms=8000, source_in_ms=1000,
                 source_out_ms=9000, playback_rate=1.0, gain_db=0.0, audio_envelopes=[], stream_start_ms=3000.0,
                 media_time_contract="v2-content-clock")
    job = SimpleNamespace(start_seconds=0, duration_seconds=8, video_graph={"duration_ms": 8000})
    import twobyteasr.exports.studio_render as render
    original = render.media_has_audio
    render.media_has_audio = lambda *_args: True
    try:
        _inputs, filters, _label = compile_audio_mix("ffmpeg", job, [layer])
    finally:
        render.media_has_audio = original
    assert "[1:a:1]" in filters[0] and "adelay=2000:all=1," in filters[0]
    command = build_audio_decode_command("ffmpeg", "x.mkv", source_ms=0, rate=1.0, stream_index=1,
                                         stream_start_ms=3000.0)
    assert "0:a:1" in command and any("adelay=3000:all=1" in part for part in command)
    # The first stream keeps its earlier command exactly.
    assert not any("adelay" in part for part in build_audio_decode_command("ffmpeg", "x.mkv", source_ms=0, rate=1.0))


def test_flv_seek_copy_is_used_for_the_first_stream_only(tmp_path):
    from twobyteasr.playback.audio_engine import _decode_input
    copy = tmp_path / "copy.mka"
    copy.write_bytes(b"x")
    decode = {"path": str(copy), "offset_ms": 0}
    assert _decode_input("a.flv", 1000, 0, decode)[0] == str(copy)
    assert _decode_input("a.flv", 1000, 1, decode) == ("a.flv", 1000, 1)


def test_waveform_jobs_and_caches_are_per_stream():
    from twobyteasr.playback.waveform_cache import WaveformMetadata, stream_suffix
    assert waveform_job("C:/m.mkv", 0) == "C:/m.mkv" and split_waveform_job("C:/m.mkv") == ("C:/m.mkv", 0)
    assert split_waveform_job(waveform_job("C:/m.mkv", 2)) == ("C:/m.mkv", 2)
    assert stream_suffix(0) == "" and stream_suffix(2) == "-a2"
    from twobyteasr.playback.waveform_cache import WAVEFORM_SCHEMA_VERSION
    meta = WaveformMetadata(schema_version=WAVEFORM_SCHEMA_VERSION, source_path="m", source_size=1,
                            source_mtime_ns=1, sample_rate=1, window_samples=1, duration_ms=1, levels=(),
                            audio_stream=2)
    assert meta.to_dict()["audio_stream"] == 2
    assert "audio_stream" not in WaveformMetadata(**{**meta.__dict__, "audio_stream": 0}).to_dict()
    assert WaveformMetadata.from_dict(meta.to_dict()).audio_stream == 2


# ------------------------------------------------------------------ picker rules

def test_default_choice_order_and_binding_to_the_source():
    from twobyteasr.studio.audio_track_picker import default_choice
    project = _project_with(_three_stream_rows())
    rows = [dict(row, problem="") for row in recognizable_lanes(project)]
    assert [r["lane_id"] for r in rows] == ["A1", "A2", "A3"]
    assert [(r["ordinal"], r["stream_index"]) for r in rows] == [(0, 1), (1, 3), (2, 4)]
    assert default_choice(rows) == ["A1"]
    assert default_choice(rows, remembered=[source_key(rows[1])]) == ["A2"]
    assert default_choice(rows, selected_lanes=["A3", "A2"], remembered=[source_key(rows[1])]) == ["A2", "A3"]
    # A remembered choice of another file's second track does not apply here.
    other = dict(rows[1], fingerprint="other-file")
    assert default_choice(rows, remembered=[source_key(other)]) == ["A1"]
    broken = [dict(rows[0], problem="FFmpeg 不认识这条音轨的编码，无法解码"), *rows[1:]]
    assert default_choice(broken) == ["A2"]


def test_picker_counts_explains_and_blocks_an_empty_start():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio.audio_track_picker import AudioTrackPicker
    project = _project_with(_three_stream_rows())
    rows = [dict(row, problem="") for row in recognizable_lanes(project)]
    picker = AudioTrackPicker(project, rows, ["A1"])
    accepted = []
    picker.accepted.connect(accepted.append)
    assert picker.start_button.isEnabled() and picker.note.isHidden()
    picker.checks["A2"].setChecked(True)
    assert "将分别识别所选音轨，并按来源保留字幕结果。" in picker.note.text()
    picker.checks["A1"].setChecked(False)
    picker.checks["A2"].setChecked(False)
    assert not picker.start_button.isEnabled()
    picker.checks["A2"].setChecked(True)
    picker.start_button.click()
    assert [[r["lane_id"] for r in rows] for rows in accepted] == [["A2"]]
    single = AudioTrackPicker(project, rows, ["A1"], single=True)
    single.checks["A3"].setChecked(True)
    assert [r["lane_id"] for r in single.chosen()] == ["A3"]
    picker.deleteLater(); single.deleteLater(); app.processEvents()


# ------------------------------------------------------------------ real media

def _tone_file(tmp_path: Path) -> Path:
    """MKV: video, 440 Hz audio, a subtitle stream, 1320 Hz audio starting 2 s late."""
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:01,500\nx\n", encoding="utf-8")
    target = tmp_path / "tones.mkv"
    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=10:d=6",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-i", str(srt),
                    "-itsoffset", "2", "-f", "lavfi", "-i", "sine=frequency=1320:duration=4",
                    "-map", "0:v", "-map", "1:a", "-map", "2:s", "-map", "3:a", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "srt",
                    "-metadata:s:a:1", "title=Dub", "-disposition:a:0", "default", "-disposition:a:1", "0",
                    str(target)], check=True)
    return target


def _dominant_hz(path: Path, start_s: float, length_s: float = 0.5) -> float:
    with wave.open(str(path)) as stream:
        rate = stream.getframerate()
        data = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32)
    piece = data[int(start_s * rate): int((start_s + length_s) * rate)]
    if not len(piece) or np.abs(piece).max() < 200:
        return 0.0
    spectrum = np.abs(np.fft.rfft(piece * np.hanning(len(piece))))
    return float(np.fft.rfftfreq(len(piece), 1 / rate)[int(np.argmax(spectrum))])


@needs_ffmpeg
def test_only_the_second_track_reaches_the_recognition_input(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.media.media_service import MediaService
    from twobyteasr.recognition.recognition_input import (capture_recognition_snapshot, lane_snapshots,
                                                          prepare_recognition_input)
    media = _tone_file(tmp_path)
    identity = MediaService(ffprobe_path=FFPROBE, ffmpeg_path=FFMPEG, cache_root=tmp_path / "m").metadata(media).to_dict()
    assert [(r["ordinal"], r["index"], round(r["start_ms"])) for r in identity["audio_streams"]] == [(0, 1, 0), (1, 3, 2000)]
    project = SubtitleProject(media=StudioMedia(path=str(media)))
    hydrate_media_contract(project, identity, source_path=media)
    project.validate()
    rows = recognizable_lanes(project)
    assert [(r["lane_id"], r["stream_index"]) for r in rows] == [("A1", 1), ("A2", 3)]
    snapshot = capture_recognition_snapshot(project, "", lanes=[rows[1]])
    (run,) = lane_snapshots(snapshot)
    wav = Path(prepare_recognition_input(run, tmp_path / "cache", FFMPEG))
    # Silence before the late start, then the second track's 1320 Hz — never 440 Hz.
    assert _dominant_hz(wav, 0.5) == 0.0
    assert abs(_dominant_hz(wav, 3.0) - 1320) < 20
    both = lane_snapshots(capture_recognition_snapshot(project, "", lanes=rows))
    assert [s["audio_source"]["lane_id"] for s in both] == ["A1", "A2"]
    assert len({s["fingerprint"] for s in both}) == 2
    first = Path(prepare_recognition_input(both[0], tmp_path / "cache", FFMPEG))
    assert first != wav and abs(_dominant_hz(first, 3.0) - 440) < 20


# ------------------------------------------------------------------ combined results

def _lane_result(snapshot_run, tmp_path, name, cues, translations=None):
    """A per-track result project as the queue writes it (attach_timeline_result)."""
    from twobyteasr.projects.studio_project import StudioCue, StudioSpeaker
    from twobyteasr.recognition.recognition_input import attach_timeline_result
    result = SubtitleProject(media=StudioMedia(path=snapshot_run["project"]["media"]["path"]))
    result.cues = [StudioCue(cue_id, start, end, text, speaker_id=speaker) for cue_id, start, end, text, speaker in cues]
    result.speakers = [StudioSpeaker(id=sid) for sid in dict.fromkeys(c.speaker_id for c in result.cues)]
    from twobyteasr.recognition.recognition_result import media_identity_for_task
    result.generation_metadata = {"translations": dict(translations or {}), "input_source_identities": {
        source: media_identity_for_task(source) for source in snapshot_run["sources"]}}
    project = attach_timeline_result(result, snapshot_run)
    return save_project(project, tmp_path / name / "识别结果.2byteproj")


@needs_ffmpeg
def test_picked_tracks_combine_without_overwriting_other_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.media.media_service import MediaService
    from twobyteasr.projects.studio_project import StudioCue, StudioSpeaker
    from twobyteasr.recognition.audio_lane_results import (CHOICE_KEY, SOURCES_KEY, SUMMARY_KEY, caption_counts,
                                                           combine_lane_results)
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot, lane_snapshots
    from twobyteasr.recognition.recognition_result import verify_result_reference
    media = _tone_file(tmp_path)
    identity = MediaService(ffprobe_path=FFPROBE, ffmpeg_path=FFMPEG, cache_root=tmp_path / "m").metadata(media).to_dict()
    project = SubtitleProject(media=StudioMedia(path=str(media)))
    hydrate_media_contract(project, identity, source_path=media)
    project.validate()
    # Captions from an older run (no source): they heard A1.
    project.cues = [StudioCue("old-1", 100, 900, "原音旧字幕", speaker_id="S00")]
    project.speakers = [StudioSpeaker(id="S00", name="S00")]
    project.generation_metadata["translations"] = {"old-1": "old line"}
    project.render_settings["_cue_domain"] = "timeline"
    rows = recognizable_lanes(project)
    a1, a2 = rows
    assert caption_counts(project, {source_key(a2)}) == (0, 1)
    assert caption_counts(project, {source_key(a1)}) == (1, 0)

    # 1) Only A2: the old A1 caption stays, A2's speaker is its own person.
    snapshot = capture_recognition_snapshot(project, str(tmp_path / "p.2byteproj"), lanes=[a2])
    (run,) = lane_snapshots(snapshot)
    lane = _lane_result(run, tmp_path, "lane-a2", [("1", 2100, 3000, "配音第一句", "S00")], {"1": "dub one"})
    reference = combine_lane_results(snapshot, [(run, lane)], tmp_path / "out" / "识别结果.2byteproj", job_id="job-1")
    combined = verify_result_reference(reference)
    assert [(c.id, c.text, c.speaker_id) for c in combined.cues] == [
        ("old-1", "原音旧字幕", "S00"), ("1", "配音第一句", "A2-S00")]
    names = {s.id: s.name for s in combined.speakers}
    assert names == {"S00": "S00", "A2-S00": "Dub · S00"}
    sources = combined.studio_state[SOURCES_KEY]
    assert set(sources) == {"A2-S00"} and sources["A2-S00"]["stream_index"] == 3 and sources["A2-S00"]["ordinal"] == 1
    assert combined.generation_metadata["translations"] == {"old-1": "old line", "1": "dub one"}
    assert combined.studio_state[CHOICE_KEY] == [source_key(a2)]
    assert combined.render_settings["_cue_domain"] == "timeline"

    # 2) A1 and A2 again on the combined project: the old A1 caption and the
    #    first A2 caption are both replaced; the two "S00" stay two people.
    combined.validate()
    snapshot = capture_recognition_snapshot(combined, str(tmp_path / "p.2byteproj"), lanes=[a1, a2])
    runs = lane_snapshots(snapshot)
    lane1 = _lane_result(runs[0], tmp_path, "lane-a1", [("1", 100, 900, "原音新字幕", "S00")])
    lane2 = _lane_result(runs[1], tmp_path, "lane-a2b", [("1", 2100, 3000, "配音新一句", "S00")])
    reference = combine_lane_results(snapshot, [(runs[0], lane1), (runs[1], lane2)],
                                     tmp_path / "out2" / "识别结果.2byteproj", job_id="job-2")
    twice = verify_result_reference(reference)
    assert sorted((c.text, c.speaker_id) for c in twice.cues) == [("原音新字幕", "A1-S00"), ("配音新一句", "A2-S00")]
    assert len({c.id for c in twice.cues}) == 2
    assert twice.generation_metadata[SUMMARY_KEY]["kept_cue_count"] == 0

    # 3) A1 fails: its captions stay, A2's are replaced, A1 is offered for a retry.
    snapshot = capture_recognition_snapshot(twice, str(tmp_path / "p.2byteproj"), lanes=[a1, a2])
    runs = lane_snapshots(snapshot)
    lane2 = _lane_result(runs[1], tmp_path, "lane-a2c", [("1", 2200, 3100, "配音第三版", "S00")])
    reference = combine_lane_results(snapshot, [(runs[1], lane2)], tmp_path / "out3" / "识别结果.2byteproj",
                                     job_id="job-3", problems=[(runs[0], "failed", "模型不可用")])
    third = verify_result_reference(reference)
    assert sorted(c.text for c in third.cues) == ["原音新字幕", "配音第三版"]
    summary = third.generation_metadata[SUMMARY_KEY]
    assert summary["problems"][0]["error"] == "模型不可用" and summary["problems"][0]["lane_id"] == "A1"
    assert third.studio_state[CHOICE_KEY] == [source_key(a1)]


@needs_ffmpeg
def test_queue_delivers_finished_tracks_and_names_the_cancelled_one(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.media.media_service import MediaService
    from twobyteasr.recognition.audio_lane_results import SUMMARY_KEY
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot, lane_snapshots
    from twobyteasr.recognition.recognition_result import verify_result_reference
    from twobyteasr.recognition.service import MediaResult, _deliver_audio_lanes
    media = _tone_file(tmp_path)
    identity = MediaService(ffprobe_path=FFPROBE, ffmpeg_path=FFMPEG, cache_root=tmp_path / "m").metadata(media).to_dict()
    project = SubtitleProject(media=StudioMedia(path=str(media)))
    hydrate_media_contract(project, identity, source_path=media)
    project.validate()
    snapshot = capture_recognition_snapshot(project, str(tmp_path / "p.2byteproj"), lanes=recognizable_lanes(project))
    runs = lane_snapshots(snapshot)
    runs[0]["input_path"], runs[1]["input_path"] = "in-1.wav", "in-2.wav"
    lane = _lane_result(runs[0], tmp_path, "lane-a1", [("1", 100, 900, "原音字幕", "S00")])
    events = []
    legacy = SimpleNamespace(record_run_event=lambda kind, **payload: events.append((kind, payload)))
    results = [MediaResult("in-1.wav", "success", project_path=str(lane)),
               MediaResult("in-2.wav", "cancelled", error="用户取消了任务。")]
    delivered = _deliver_audio_lanes(legacy, SimpleNamespace(job_id="job-cancel"), snapshot, runs, results,
                                     tmp_path / "result", ["in-1.wav", "in-2.wav"])
    assert [r.status for r in delivered] == ["degraded_success", "cancelled"]
    assert delivered[0].media_path == str(media) and "音轨 2" in delivered[1].error
    combined = verify_result_reference(json.loads(delivered[0].result_ref_json))
    assert [c.text for c in combined.cues] == ["原音字幕"]
    assert combined.generation_metadata[SUMMARY_KEY]["problems"][0]["status"] == "cancelled"
    assert [k for k, _p in events if k.startswith("audio_lane")] == [
        "audio_lane_finished", "audio_lane_finished", "audio_lanes_combined"]


def test_a_late_streams_waveform_origin_moves_once_even_without_a_saved_origin():
    from twobyteasr.timeline.audio_stream_lanes import stream_time_mapping
    project = _project_with(_three_stream_rows())
    project.studio_state["media_time_mapping"] = {"audio_start_ms": 0.0}  # a dropped file: no origin key
    mapping = stream_time_mapping(project, SOURCE, 1)
    assert (mapping["audio_start_ms"], mapping["sample_timeline_origin_ms"]) == (3000.0, 3000.0)
    project.studio_state["media_time_mapping"] = {"audio_start_ms": 21.0, "sample_timeline_origin_ms": 21.0}
    mapping = stream_time_mapping(project, SOURCE, 1)
    assert (mapping["audio_start_ms"], mapping["sample_timeline_origin_ms"]) == (3021.0, 3021.0)
    assert stream_time_mapping(project, SOURCE, 0)["sample_timeline_origin_ms"] == 21.0
