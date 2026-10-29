"""Production exports: frame-rate conversion and clip speed keep audio/video/captions together."""
import wave
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence, projected_cues
from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
from twobyteasr.exports.export_timeline import write_export_ass
from twobyteasr.exports.video_export import capture_video_graph
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job

FFMPEG = Path(__file__).resolve().parents[1] / "tools/ffmpeg/bin/ffmpeg.exe"
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="bundled FFmpeg required")


@pytest.mark.parametrize("route", ["native", "static", "composed"])
@pytest.mark.parametrize("source_rate,output_rate,speed", [
    ("24000/1001", "24000/1001", 1), ("24000/1001", "60", 1),
    ("60", "24000/1001", 1), ("30000/1001", "60000/1001", 1),
    ("24", "60", 2), ("60", "24", .5),
    ("24000/1001", "source", 1), ("60", "source", 1),
])
def test_export_content_cadence(tmp_path, source_rate, output_rate, speed, route):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "clock.mkv"
    run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
        f"color=c=0x204080:s=320x180:r={source_rate}:d=4", "-f", "lavfi", "-i",
        r"aevalsrc=if(between(mod(t\,1)\,0.4\,0.52)\,0.5*sin(2*PI*800*t)\,0):s=48000:d=4",
        "-vf", r"drawbox=x=0:y=0:w=30:h=30:color=white:t=fill:enable=between(mod(t\,1)\,0.4\,0.52)",
        "-c:v", "ffv1", "-c:a", "pcm_s16le", str(source)], purpose="clock fixture", check=True, timeout=20)
    duration = 4 / speed
    project = SubtitleProject(media=StudioMedia(str(source), duration_ms=4000, width=320, height=180),
        cues=[StudioCue(str(i), 600+i*1000, 850+i*1000, "SYNC") for i in range(4)])
    project.validate()
    project.styles[0].primary_color = "#FF0000"
    project.styles[0].font_size = 120
    project.styles[0].bold = True
    if route == "static":
        project.style_recipes["default"] = {"name": "Gradient", "engine": "remotion",
            "motion": {"mode": "none"}, "colors": {"fill": {"type": "linear-gradient",
            "angle": 0, "stops": [{"position": 0, "color": "#FFFF0000"},
                                   {"position": 1, "color": "#FFFF3000"}]}}}
    sequence = EditSequence(source_path=str(source), source_duration_ms=4000,
        segments=[VideoSegment("clock", str(source), 0, 4000, 0, round(duration*1000))])
    store_sequence(project, sequence)
    sync_primary_video_track_from_sequence(project, sequence)
    project.media_pool[0].video_metadata["fps"] = float(Fraction(source_rate))
    ass = tmp_path / "clock.ass"
    output_fps = 0 if output_rate == "source" else float(Fraction(output_rate))
    fps = output_fps or float(Fraction(source_rate))
    snapshot = write_export_ass(project, ass, fps=output_fps or None)
    graph = capture_video_graph(project)
    if route == "composed":
        # A real non-default transform takes the raster compositor route.
        # Keep event detection unchanged while exercising its raw-frame clock.
        graph["video_tracks"][0]["clips"][0]["transform"]["opacity"] = .99
    job = RenderJob(str(source), str(ass), str(tmp_path/"export.mp4"),
        RenderSettings(encoder="libx264", preset="ultrafast", quality=12,
                       width=320, height=180, fps=output_fps, audio_codec="aac"),
        duration_seconds=duration, video_graph=graph)
    if route == "static":
        from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend
        AdvancedRendererBackend().render(snapshot, FFMPEG, job)
    else:
        run_render_job(FFMPEG, job)
    expected_cues = projected_cues(project)
    flashes, caption_errors = [], []
    with av.open(job.output_path) as container:
        for frame in container.decode(video=0):
            at = float(frame.pts * frame.time_base)
            rgb = frame.to_ndarray(format="rgb24")
            if rgb[:20, :20].mean() > 210:
                flashes.append(at)
            visible = np.sum((rgb[:, :, 0] > 150) & (rgb[:, :, 1] < 100) & (rgb[:, :, 2] < 100)) > 10
            wanted = any(c.start_ms/1000 <= at < c.end_ms/1000 for c in expected_cues)
            if visible != wanted:
                caption_errors.append(min(abs(at-v/1000) for c in expected_cues for v in (c.start_ms,c.end_ms)))
    assert not caption_errors or max(caption_errors) <= 1/fps + .002
    audio = tmp_path / "audio.wav"
    run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-i", job.output_path,
        "-vn", "-ac", "1", "-ar", "48000", str(audio)], purpose="clock audio evidence", check=True, timeout=15)
    with wave.open(str(audio), "rb") as stream:
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2") / 32768.
    assert abs(len(pcm)/48000-duration) < .07
    for i in range(4):
        onset = (i+.4)/speed
        tolerance = 1/float(Fraction(source_rate))/speed + 1/fps + .025
        visible = min(at for at in flashes if abs(at-onset) < tolerance+.1)
        a, b = max(0, round((onset-.06)*48000)), round((onset+.15)*48000)
        hits = np.flatnonzero(np.abs(pcm[a:b]) > .12)
        assert len(hits), (source_rate, output_rate, speed, i)
        heard = (a+hits[0])/48000
        assert abs(visible-onset) <= tolerance
        assert abs(heard-onset) <= tolerance
        # atempo's time-stretch window can shift a sharp transient by ~60 ms
        # at half speed. Absolute event times above still bound both clocks.
        assert abs(visible-heard) <= tolerance + (.06 if speed < 1 else 0)
