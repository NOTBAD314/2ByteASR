"""Home page: whole-file recognition of a multi-track file hears the picked track.

2026-10-24 (user): dropping a multi-track MP4/MKV on the home page and
recognizing it let FFmpeg pick the audio stream (``-vn`` without ``-map``),
while the incremental chunks always read ``0:a:0``. These tests use real
FFmpeg media whose two audio streams carry different tones (the second one
starting 2 s late), so a wrong stream is caught by what is heard, not only by
a command string: the queue entry per picked track, the shared 16 kHz audio,
the incremental chunks, separate caches and outputs, the combined result
grouped by source, a failed track and its retry.
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

from tests.test_service_layer import FakeLegacy, FakePipeline

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG.is_file() and FFPROBE.is_file()), reason="bundled FFmpeg missing")
RATE = 16000


def _two_tracks(folder: Path) -> Path:
    """MKV: video, 440 Hz stereo, a subtitle stream, 1320 Hz 'Dub' starting 2 s late."""
    srt = folder / "s.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:01,500\nx\n", encoding="utf-8")
    target = folder / "两条音轨.mkv"
    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=10:d=6",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-i", str(srt),
                    "-itsoffset", "2", "-f", "lavfi", "-i", "sine=frequency=1320:duration=4",
                    "-map", "0:v", "-map", "1:a", "-map", "2:s", "-map", "3:a", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac:a:0", "2", "-c:s", "srt",
                    "-metadata:s:a:1", "title=Dub", "-metadata:s:a:1", "language=chi",
                    "-disposition:a:0", "default", "-disposition:a:1", "0", str(target)], check=True)
    return target


def _stereo_only(folder: Path) -> Path:
    target = folder / "single.mp4"
    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=10:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=660:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ac", "2", str(target)], check=True)
    return target


def _dominant_hz(samples, start_s: float, length_s: float = 0.5) -> float:
    piece = np.asarray(samples[int(start_s * RATE): int((start_s + length_s) * RATE)], dtype=np.float32)
    if not len(piece) or np.abs(piece).max() < 0.01:
        return 0.0
    spectrum = np.abs(np.fft.rfft(piece * np.hanning(len(piece))))
    return float(np.fft.rfftfreq(len(piece), 1 / RATE)[int(np.argmax(spectrum))])


def _onset_s(samples) -> float:
    loud = np.flatnonzero(np.abs(np.asarray(samples, dtype=np.float32)) > 0.05)
    return float(loud[0]) / RATE if len(loud) else -1.0


def _wav(path: Path):
    with wave.open(str(path)) as stream:
        data = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return data


@pytest.fixture
def media_env(tmp_path, monkeypatch):
    """Bundled FFmpeg on PATH, a private media service, cache and project library."""
    import twobyteasr.media.media_service as media_service
    import twobyteasr.projects.studio_project as storage
    import twobyteasr.recognition.cache as cache
    monkeypatch.setenv("PATH", str(FFMPEG.parent) + os.pathsep + os.environ.get("PATH", ""))
    service = media_service.MediaService(ffprobe_path=FFPROBE, ffmpeg_path=FFMPEG, cache_root=tmp_path / "m")
    monkeypatch.setattr(media_service, "GLOBAL_MEDIA_SERVICE", service)
    monkeypatch.setattr(cache, "CACHE_ROOT", str(tmp_path / "asr-cache"))
    monkeypatch.setattr(storage, "project_library_root", lambda *a, **k: tmp_path / "Projects")
    folder = tmp_path / "media"
    folder.mkdir()
    return SimpleNamespace(root=tmp_path, folder=folder, service=service)


class HearingPipeline(FakePipeline):
    """process_media that decodes through the real shared-audio path and
    writes what it heard as the caption: '<dominant Hz>Hz' at the onset."""

    def __init__(self, failing_streams=()):
        super().__init__()
        self.failing_streams = set(failing_streams)
        self.heard = []

    def process_media(self, media_path, file_index, file_total, legacy, runtime_context=None):
        from twobyteasr.projects.studio_project import create_studio_outputs
        from twobyteasr.recognition.audio_stream_choice import active_choice
        from twobyteasr.recognition.cache import load_shared_audio, media_cache_context
        choice = active_choice(media_path, runtime_context)
        if choice.get("ordinal") in self.failing_streams:
            raise RuntimeError("模型不可用")
        context = media_cache_context(media_path)
        audio = np.asarray(load_shared_audio(media_path, context))
        onset = _onset_s(audio)
        hz = _dominant_hz(audio, onset + 0.1)
        self.heard.append(dict(ordinal=choice.get("ordinal"), cache_dir=context["cache_dir"], onset=onset, hz=hz,
                               peak_440=_dominant_hz(audio, 0.5), samples=len(audio)))
        cues = [SimpleNamespace(cue_id="c1", start=onset, end=onset + 1.0, text=f"{round(hz / 10) * 10}Hz", speaker="S00")]
        result = create_studio_outputs(media_path, cues, txt_path="",
                                       target_project_path=runtime_context.studio_project_path,
                                       generation_metadata={"job_id": runtime_context.job_id,
                                                            "media_identity": runtime_context.media_identity})
        runtime_context.committed_result_ref = json.loads(result["result_ref_json"])
        return "", "", 0.01


def _run(media_env, paths, request, pipeline, job="home-tracks"):
    from twobyteasr.recognition.service import RunOptions, run_media_queue
    return run_media_queue([str(p) for p in paths], RunOptions(job_id=job, audio_streams_json=request),
                           _legacy=FakeLegacy(media_env.root), _pipeline=pipeline, _skip_environment_preflight=True)


# ------------------------------------------------------------------ choice and decoding

@needs_ffmpeg
def test_probe_names_both_tracks_and_the_late_start(media_env):
    from twobyteasr.recognition.audio_stream_choice import make_choice
    media = _two_tracks(media_env.folder)
    streams = media_env.service.metadata(media).audio_streams
    assert [(r["ordinal"], r["index"], r["channels"], round(r["start_ms"])) for r in streams] == [
        (0, 1, 2, 0), (1, 3, 1, 2000)]
    choice = make_choice(str(media), streams, 1)
    assert (choice["ordinal"], choice["stream_index"], round(choice["offset_ms"]), choice["lead_ms"]) == (1, 3, 2000, 0.0)
    with pytest.raises(ValueError):
        make_choice(str(media), streams, 2)


@needs_ffmpeg
def test_shared_audio_and_chunks_hear_only_the_picked_track_on_the_video_clock(media_env, tmp_path):
    from twobyteasr.recognition.audio_stream_choice import make_choice
    from twobyteasr.recognition.cache import decode_audio_to_array
    from twobyteasr.recognition.incremental_asr import ASRChunkSpec, IncrementalASRPipeline
    media = _two_tracks(media_env.folder)
    streams = media_env.service.metadata(media).audio_streams
    second, first = make_choice(str(media), streams, 1), make_choice(str(media), streams, 0)

    dub = decode_audio_to_array(str(media), audio_stream=second)
    # Silent until the dub starts 2 s in, then 1320 Hz only — the 440 Hz track never.
    assert _dominant_hz(dub, 0.5) == 0.0 and abs(_onset_s(dub) - 2.0) < 0.05
    assert abs(_dominant_hz(dub, 3.0) - 1320) < 20 and abs(_dominant_hz(dub, 5.0) - 1320) < 20
    original = decode_audio_to_array(str(media), audio_stream=first)
    assert abs(_dominant_hz(original, 0.5) - 440) < 20 and abs(_dominant_hz(original, 3.0) - 440) < 20
    assert abs(len(dub) - len(original)) < RATE // 10  # both on the same 6 s clock

    pipeline = IncrementalASRPipeline(str(media), duration_ms=6000, backend="t", model_revision="1",
                                      settings={"sample_rate": RATE}, ffmpeg_path=FFMPEG,
                                      cache_root=tmp_path / "inc", recognize_chunk=lambda *_a: [],
                                      chunk_ms=5000, audio_stream=second)
    head, tail = pipeline.specs()
    assert (head.start_ms, tail.start_ms) == (0, 4500)
    pipeline._extract_chunk(head, tmp_path / "head.wav")
    pipeline._extract_chunk(tail, tmp_path / "tail.wav")
    head_pcm, tail_pcm = _wav(tmp_path / "head.wav"), _wav(tmp_path / "tail.wav")
    assert _dominant_hz(head_pcm, 0.5) == 0.0 and abs(_onset_s(head_pcm) - 2.0) < 0.05
    assert abs(_dominant_hz(head_pcm, 3.0) - 1320) < 20
    assert abs(_dominant_hz(tail_pcm, 0.2) - 1320) < 20  # chunk time 0 = 4.5 s on the video clock
    plain = IncrementalASRPipeline(str(media), duration_ms=6000, backend="t", model_revision="1",
                                   settings={"sample_rate": RATE}, ffmpeg_path=FFMPEG,
                                   cache_root=tmp_path / "inc", recognize_chunk=lambda *_a: [], chunk_ms=5000)
    assert plain.identity.key != pipeline.identity.key  # its own chunk cache
    plain._extract_chunk(ASRChunkSpec(0, 0, 5000), tmp_path / "plain.wav")
    assert abs(_dominant_hz(_wav(tmp_path / "plain.wav"), 0.5) - 440) < 20  # without a pick: as before


@needs_ffmpeg
def test_a_pick_gets_its_own_identity_and_cache(media_env):
    from twobyteasr.recognition.audio_stream_choice import make_choice
    from twobyteasr.recognition.cache import media_cache_context
    from twobyteasr.recognition.recognition_result import media_identity_for_task
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    media = _two_tracks(media_env.folder)
    streams = media_env.service.metadata(media).audio_streams
    seen = {}
    for name, choice in (("whole", {}), ("a1", make_choice(str(media), streams, 0)),
                         ("a2", make_choice(str(media), streams, 1))):
        context = RuntimeContext(identity_task_active=True, audio_stream=choice)
        with activate_runtime_context(context):
            cache_context = media_cache_context(str(media))
            seen[name] = (media_identity_for_task(str(media), context), cache_context)
    assert seen["whole"][0]["selection"] == {} and "audio_stream" not in seen["whole"][1]
    assert seen["a2"][0]["selection"] == {"audio_stream": 1, "audio_stream_index": 3}
    assert len({value[1]["cache_dir"] for value in seen.values()}) == 3
    assert len({value[0]["fingerprint"] for value in seen.values()}) == 3
    assert seen["a2"][1]["audio_stream"]["ordinal"] == 1
    # Another file is never mistaken for the picked one.
    other = RuntimeContext(identity_task_active=True, audio_stream=make_choice(str(media), streams, 1))
    assert media_identity_for_task(str(_stereo_only(media_env.folder)), other)["selection"] == {}


# ------------------------------------------------------------------ the queue

@needs_ffmpeg
def test_only_the_second_track_is_recognized_when_only_it_is_picked(media_env):
    from twobyteasr.recognition.audio_lane_results import SOURCES_KEY
    from twobyteasr.recognition.audio_stream_choice import request_json
    from twobyteasr.recognition.recognition_result import verify_result_reference
    media = _two_tracks(media_env.folder)
    pipeline = HearingPipeline()
    result = _run(media_env, [media], request_json({str(media): [{"ordinal": 1, "stream_index": 3}]}), pipeline)
    assert [(h["ordinal"], round(h["hz"] / 10) * 10, round(h["onset"], 1)) for h in pipeline.heard] == [(1, 1320, 2.0)]
    assert pipeline.heard[0]["peak_440"] == 0.0
    (item,) = result.results
    assert item.status == "success" and item.audio_stream == -1 and item.media_path == str(media.resolve())
    project = verify_result_reference(item.result_ref_json)
    assert [(c.text, c.speaker_id, round(c.start_ms / 100)) for c in project.cues] == [("1320Hz", "A2-S00", 20)]
    assert {s.id: s.name for s in project.speakers} == {"A2-S00": "Dub · S00"}
    source = project.studio_state[SOURCES_KEY]["A2-S00"]
    assert (source["lane_id"], source["ordinal"], source["stream_index"]) == ("A2", 1, 3)


@needs_ffmpeg
def test_two_picked_tracks_are_recognized_apart_and_grouped_by_source(media_env):
    from twobyteasr.recognition.audio_lane_results import SOURCES_KEY, SUMMARY_KEY
    from twobyteasr.recognition.audio_stream_choice import request_json
    from twobyteasr.recognition.recognition_result import verify_result_reference
    from twobyteasr.timeline.audio_stream_lanes import recognizable_lanes, source_key
    media = _two_tracks(media_env.folder)
    single = _stereo_only(media_env.folder)
    pipeline = HearingPipeline()
    events = []
    from twobyteasr.recognition.service import RunOptions, run_media_queue
    request = request_json({str(media): [{"ordinal": 0, "stream_index": 1}, {"ordinal": 1, "stream_index": 3}]})
    result = run_media_queue([str(media), str(single)], RunOptions(job_id="two-tracks", audio_streams_json=request),
                             events.append, _legacy=FakeLegacy(media_env.root), _pipeline=pipeline,
                             _skip_environment_preflight=True)
    heard = [(h["ordinal"], round(h["hz"] / 10) * 10, round(h["onset"], 1)) for h in pipeline.heard]
    assert heard == [(0, 440, 0.0), (1, 1320, 2.0), (None, 660, 0.0)]
    assert len({h["cache_dir"] for h in pipeline.heard}) == 3
    assert [(r.status, Path(r.media_path).name, r.audio_stream) for r in result.results] == [
        ("success", media.name, -1), ("success", single.name, -1)]
    combined = verify_result_reference(result.results[0].result_ref_json)
    assert sorted((c.text, c.speaker_id) for c in combined.cues) == [("1320Hz", "A2-S00"), ("440Hz", "A1-S00")]
    assert {s.id: s.name for s in combined.speakers} == {"A1-S00": "音轨 1 · S00", "A2-S00": "Dub · S00"}
    lanes = {row["lane_id"]: source_key(row) for row in recognizable_lanes(combined)}
    sources = combined.studio_state[SOURCES_KEY]
    assert {sid: row["source_key"] for sid, row in sources.items()} == {"A1-S00": lanes["A1"], "A2-S00": lanes["A2"]}
    assert [lane["status"] for lane in combined.generation_metadata[SUMMARY_KEY]["lanes"]] == ["success", "success"]
    assert combined.render_settings["_cue_domain"] == "timeline"
    # The single-track file stayed one whole-file run without a choice.
    plain = verify_result_reference(result.results[1].result_ref_json)
    assert [c.text for c in plain.cues] == ["660Hz"] and SOURCES_KEY not in plain.studio_state
    started = [e.payload for e in events if e.kind == "audio_lane_started"]
    assert [(p["lane_index"], p["lane_total"], p["audio_stream_ordinal"]) for p in started] == [(1, 2, 0), (2, 2, 1)]


@needs_ffmpeg
def test_a_failed_track_is_named_and_its_retry_keeps_the_finished_one(media_env):
    from twobyteasr.recognition.audio_stream_choice import parse_request, request_json
    from twobyteasr.recognition.recognition_result import verify_result_reference
    media = _two_tracks(media_env.folder)
    both = request_json({str(media): [{"ordinal": 0, "stream_index": 1}, {"ordinal": 1, "stream_index": 3}]})
    result = _run(media_env, [media], both, HearingPipeline(failing_streams={0}), job="fails-a1")
    assert [(r.status, r.audio_stream) for r in result.results] == [("degraded_success", -1), ("failed", 0)]
    combined_item, failed = result.results
    assert failed.error.startswith("音轨 1") and "模型不可用" in failed.error
    assert "模型不可用" in combined_item.error
    combined = verify_result_reference(combined_item.result_ref_json)
    assert [c.text for c in combined.cues] == ["1320Hz"]

    # 重试失败项: only track 1 runs again; the finished dub stays in the new result.
    retry = request_json({str(media): [{"ordinal": 0, "stream_index": 1}]}, {str(media): combined_item.project_path})
    assert list(parse_request(retry).values()) == [[{"ordinal": 0, "stream_index": 1}]]
    pipeline = HearingPipeline()
    again = _run(media_env, [media], retry, pipeline, job="retry-a1")
    assert [h["ordinal"] for h in pipeline.heard] == [0]
    (item,) = again.results
    project = verify_result_reference(item.result_ref_json)
    assert sorted((c.text, c.speaker_id) for c in project.cues) == [("1320Hz", "A2-S00"), ("440Hz", "A1-S00")]


@needs_ffmpeg
def test_a_changed_file_is_refused_instead_of_hearing_another_track(media_env):
    from twobyteasr.recognition.audio_stream_choice import request_json
    media = _two_tracks(media_env.folder)
    pipeline = HearingPipeline()
    result = _run(media_env, [media], request_json({str(media): [{"ordinal": 1, "stream_index": 5}]}), pipeline)
    assert pipeline.heard == [] and result.results[0].status == "failed"
    assert "选择音轨后素材已改变" in result.results[0].error


# ------------------------------------------------------------------ the home picker

class _ModalHost:
    def __init__(self):
        self.shown, self.hidden, self.on_closed = [], 0, None

    def show_content(self, content, title="", size=None, min_size=None, on_closed=None, **_kw):
        self.shown.append((content, title))
        self.on_closed = on_closed

    def hide_content(self):
        self.hidden += 1


@needs_ffmpeg
def test_home_picker_only_for_multi_track_files_and_reports_the_ticked_tracks(media_env):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app.home_audio_tracks import HomeTrackChoice, picker_sources
    from twobyteasr.studio.audio_track_picker import AudioTrackPicker
    app = QApplication.instance() or QApplication([])
    media = _two_tracks(media_env.folder)
    single = _stereo_only(media_env.folder)
    sources = picker_sources([str(single), str(media)])
    assert [(Path(path).name, [(r["lane_id"], r["ordinal"], r["stream_index"]) for r in rows])
            for path, _project, rows in sources] == [(media.name, [("A1", 0, 1), ("A2", 1, 3)])]
    assert not any(row["muted"] for row in sources[0][2])  # no timeline mute note on the home page
    window = SimpleNamespace(_modal_host=_ModalHost(), height=lambda: 900)
    done, cancelled = [], []
    flow = HomeTrackChoice(window, sources, on_done=done.append, on_cancel=lambda: cancelled.append(True))
    flow.start()
    picker, title = window._modal_host.shown[-1]
    assert isinstance(picker, AudioTrackPicker) and title == "选择要识别的音轨"
    assert [lane for lane, box in picker.checks.items() if box.isChecked()] == ["A1"]  # the file's default
    picker.checks["A1"].setChecked(False)
    assert not picker.start_button.isEnabled()
    picker.checks["A2"].setChecked(True)
    picker.start_button.click()
    app.processEvents()
    assert done == [{str(media): [{"ordinal": 1, "stream_index": 3}]}] and not cancelled
    assert window._modal_host.hidden == 1
    # The next run preselects what was picked for this file.
    again = HomeTrackChoice(window, picker_sources([str(media)]), on_done=done.append,
                            on_cancel=lambda: cancelled.append(True))
    again.start()
    picker, _title = window._modal_host.shown[-1]
    assert [lane for lane, box in picker.checks.items() if box.isChecked()] == ["A2"]
    picker.cancel_button.click()
    assert cancelled == [True] and len(done) == 1
