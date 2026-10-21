"""Caption preview audio follows the edit, like export and recognition.

2026-10-10 (user project 0852f218): the proofreading page sought the first
FLV with timeline milliseconds; timeline 0 was source 51:28.977, so every
preview played unrelated speech. Measured on the real project: old preview
vs recognized timeline.wav correlation ~0.02, new preview 0.987-1.0.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr.playback.cue_audio_preview import (PreviewUnavailable, caption_timeline_range, plan_cue_preview,  # noqa: E402
                                          preview_command)
from twobyteasr.projects.studio_project import SubtitleProject  # noqa: E402
from twobyteasr.studio.studio_video_track import ffmpeg_executable  # noqa: E402

FFMPEG = ffmpeg_executable()
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="bundled ffmpeg missing")


def _tone(path, pieces):
    """WAV whose frequency changes per (seconds, hz) piece."""
    expression, start = [], 0.0
    for seconds, hz in pieces:
        expression.append(f"between(t,{start},{start + seconds})*sin(2*PI*{hz}*t)")
        start += seconds
    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{'+'.join(expression)}':s=48000:d={start}", "-ac", "2", str(path)], check=True)
    return str(path)


def _project(tmp_path, cues, domain="timeline"):
    """Two sources on V1/A1: timeline 0-3 s = first.wav 10-13 s (600 Hz),
    timeline 3-6 s = second.wav 1-4 s (900 Hz). first.wav 0-10 s is 300 Hz."""
    from twobyteasr.projects.studio_project import StudioMedia
    first = _tone(tmp_path / "first.wav", [(10, 300), (10, 600)])
    second = _tone(tmp_path / "second.wav", [(5, 900), (5, 1200)])
    base = SubtitleProject(media=StudioMedia(path=first, duration_ms=20000))
    base.validate()
    data = base.to_dict()
    asset = dict(data["media_pool"][0], offline=False, audio_metadata={"has_audio": True, "channels": 2,
                 "sample_rate": 48000, "stream_index": 0}, video_metadata={"has_video": False})
    other = dict(asset, asset_id="asset-b", canonical_source=second, display_name="second.wav", duration_ms=10000)
    data["media_pool"] = [asset, other]
    video = data["video_tracks"][0]["clips"][0]
    audio = data["audio_tracks"][0]["clips"][0]
    spans = [("clip-a", asset["asset_id"], (0, 3000), (10000, 13000)),
             ("clip-b", "asset-b", (3000, 6000), (1000, 4000))]
    data["video_tracks"][0]["clips"] = [dict(video, id=cid, asset_id=aid, timeline_in_ms=t[0], timeline_out_ms=t[1],
                                             source_in_ms=s[0], source_out_ms=s[1]) for cid, aid, t, s in spans]
    data["audio_tracks"][0]["clips"] = [dict(audio, id="audio-" + cid, linked_video_clip_id=cid, asset_id=aid,
                                             timeline_in_ms=t[0], timeline_out_ms=t[1], source_in_ms=s[0],
                                             source_out_ms=s[1]) for cid, aid, t, s in spans]
    data["video_tracks"][0]["locked"] = False
    segment = data["edit_sequence"]["segments"][0]
    data["edit_sequence"].update(video_track_locked=False, segments=[
        dict(segment, id=cid, source_path=first if aid != "asset-b" else second, timeline_in_ms=t[0],
             timeline_out_ms=t[1], source_in_ms=s[0], source_out_ms=s[1]) for cid, aid, t, s in spans])
    data["render_settings"] = {"_cue_domain": domain} if domain == "timeline" else {}
    data["cues"] = [dict(id=cue_id, start_ms=a, end_ms=b, text=text) for cue_id, a, b, text in cues]
    project = SubtitleProject.from_dict(data)
    return project


def _decode(plan):
    command, _receipts = preview_command(plan, FFMPEG)
    command = command[:-7] + ["-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    pcm = subprocess.run(command, capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float64)


def _peaks(samples, rate=16000, window=0.2):
    """Dominant frequency per 200 ms window."""
    size = int(rate * window)
    out = []
    for start in range(0, len(samples) - size + 1, size):
        spectrum = np.abs(np.fft.rfft(samples[start:start + size] * np.hanning(size)))
        if spectrum.max() > 1e3:
            out.append(round(float(np.argmax(spectrum) * rate / size), -1))
    return out


def test_timeline_caption_plays_its_own_clip_not_the_first_file_at_timeline_time(tmp_path):
    project = _project(tmp_path, [("early", 1000, 2000, "第一段"), ("late", 4000, 5000, "第二段")])
    early = plan_cue_preview(project, "early")
    assert [(layer["clip_id"], layer["played_source_ms"]) for layer in early.diagnostic()["layers"]] == [
        ("clip-a", [10750, 12350])]
    assert set(_peaks(_decode(early))) == {600}  # source 10.75-12.35 s; the old seek played 300 Hz
    late = plan_cue_preview(project, "late")
    assert [(layer["clip_id"], Path(layer["source_path"]).name) for layer in late.layers] == [("clip-b", "second.wav")]
    assert set(_peaks(_decode(late))) == {900}
    diagnostic = late.diagnostic()
    assert diagnostic["cue_id"] == "late" and diagnostic["cue_domain"] == "timeline"
    assert diagnostic["play_range_ms"] == [3750, 5350] and diagnostic["layers"][0]["played_source_ms"] == [1750, 3350]


def test_caption_across_a_cut_follows_both_clips_in_order(tmp_path):
    project = _project(tmp_path, [("cross", 2400, 3600, "跨剪辑")])
    plan = plan_cue_preview(project, "cross")
    assert [layer["clip_id"] for layer in plan.layers] == ["clip-a", "clip-b"]
    peaks = _peaks(_decode(plan))
    assert peaks[0] == 600 and peaks[-1] == 900
    assert peaks.index(900) >= 3  # 600 Hz for ~0.85 s, then the second clip


def test_missing_or_silent_captions_are_reported_not_played_elsewhere(tmp_path):
    project = _project(tmp_path, [("gap", 6500, 7000, "片段之外")])
    with pytest.raises(PreviewUnavailable):
        plan_cue_preview(project, "gap")
    with pytest.raises(PreviewUnavailable):
        plan_cue_preview(project, "deleted-id")
    project.media_pool[1].canonical_source = str(tmp_path / "moved.wav")
    project.cues.append(type(project.cues[0])("in-b", 4000, 4500, "素材丢失"))
    with pytest.raises(PreviewUnavailable):
        plan_cue_preview(project, "in-b")


def test_legacy_source_domain_caption_outside_the_edit_uses_its_own_source_clock(tmp_path):
    project = _project(tmp_path, [("src", 15000, 16000, "源时间")], domain="source")
    cue, span, domain = caption_timeline_range(project, "src")
    assert domain == "source" and span == (15000, 16000)
    plan = plan_cue_preview(project, "src")
    assert plan.clock == "source" and set(_peaks(_decode(plan))) == {600}


def test_newest_preview_request_wins(tmp_path):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.glossary.glossary_proofread import CuePlayer
    QApplication.instance() or QApplication([])
    player = CuePlayer()
    states = []
    player.state_changed.connect(lambda cue, state: states.append((cue, state)))
    player.request_id, player.cue_id = "new", "b"
    player._start("old", b"\0" * 4800)  # a slower, older decode arrives late
    assert player._sink is None and states == []
    player.stop()
    assert states == [("b", "")]


def test_preview_stops_by_itself_when_the_device_finished(tmp_path):
    """stateChanged never reached Python; the end comes from decoded length and device progress."""
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from twobyteasr.glossary.glossary_proofread import CuePlayer
    QApplication.instance() or QApplication([])
    player = CuePlayer()
    states = []
    player.state_changed.connect(lambda cue, state: states.append((cue, state)))
    progress = {"us": 400_000}
    player._sink = SimpleNamespace(processedUSecs=lambda: progress["us"], stop=lambda: None)
    player.cue_id, player.request_id, player._expected_ms = "a", "r1", 1000
    player._check_finished()  # the device has played 0.4 s of 1.0 s: keep playing
    assert player.cue_id == "a" and player._end_timer.isActive()
    progress["us"] = 1_000_000
    player._check_finished()
    assert player.cue_id == "" and states == [("a", "")]
