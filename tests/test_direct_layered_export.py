"""Transformed/stacked video exports through FFmpeg overlays match the raster compositor."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from twobyteasr.exports import export_filtergraph
from twobyteasr.exports.export_filtergraph import direct_video_layout, simple_video_clips
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
from twobyteasr.exports.video_export import capture_video_graph
from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, VideoTransform
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.timeline.studio_media_pool import add_media_asset, add_video_clip, create_video_track

FFMPEG = Path(__file__).resolve().parents[1] / "tools/ffmpeg/bin/ffmpeg.exe"
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="bundled ffmpeg required")


def _source(tmp_path, name, color, size="320x180"):
    path = tmp_path / f"{name}.mkv"
    run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
                           f"color={color}:s={size}:r=10:d=2", "-c:v", "ffv1", str(path)],
                          purpose="layered export fixture", check=True, timeout=20)
    return path


def _project(tmp_path, transforms):
    base = _source(tmp_path, "base", "red")
    project = SubtitleProject(media=StudioMedia(path=str(base), duration_ms=2000, width=320, height=180))
    project.validate()
    colors = ["blue", "lime", "yellow"]
    for i, transform in enumerate(transforms):
        source = _source(tmp_path, f"layer{i}", colors[i], size=transform.pop("size", "320x180"))
        asset = add_media_asset(project, source, duration_ms=2000,
                                video_metadata={"width": 320, "height": 180, "has_video": True},
                                audio_metadata={"has_audio": False})
        track = create_video_track(project, f"V{i+2}")
        clip = add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=transform.pop("in_ms", 0))
        clip.transform = VideoTransform(**transform)
    return project


def _job(tmp_path, project, name):
    ass = tmp_path / "empty.ass"
    from twobyteasr.rendering.ass_compiler import compile_ass
    ass.write_text(compile_ass(project), encoding="utf-8-sig")
    return RenderJob(str(project.media.path), str(ass), str(tmp_path / f"{name}.mkv"),
                     RenderSettings(container="mkv", encoder="libx264", preset="ultrafast",
                                    audio_codec="none", fps=10, quality=0, pixel_format="yuv444p"),
                     start_seconds=.5, duration_seconds=.5, video_graph=capture_video_graph(project))


def _frame(path, tmp_path):
    target = tmp_path / (Path(path).stem + "-frame.png")
    run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-i", str(path), "-frames:v", "1", str(target)],
                          purpose="layered export pixels", check=True, timeout=20)
    return QImage(str(target))


def _render_both(tmp_path, project, monkeypatch):
    routes = []
    from twobyteasr.exports import export_run_log
    original = export_run_log.note_export
    monkeypatch.setattr(export_run_log, "note_export",
                        lambda key, value: (routes.append(value.get("route")) if key == "export_route" else None, original(key, value))[1])
    direct = run_render_job(FFMPEG, _job(tmp_path, project, "direct"))
    assert "direct_filtergraph" in routes
    monkeypatch.setattr(export_filtergraph, "simple_video_clips", lambda graph: None)
    raster = run_render_job(FFMPEG, _job(tmp_path, project, "raster"))
    return _frame(direct, tmp_path), _frame(raster, tmp_path)


def _close(a, b, x, y, tolerance=12):
    pa, pb = a.pixelColor(x, y), b.pixelColor(x, y)
    return all(abs(u - v) <= tolerance for u, v in zip(pa.getRgb()[:3], pb.getRgb()[:3])), (x, y, pa.getRgb(), pb.getRgb())


def _mismatch_ratio(a, b, tolerance=40):
    assert a.size() == b.size()
    bad = total = 0
    for y in range(0, a.height(), 3):
        for x in range(0, a.width(), 3):
            total += 1
            if not _close(a, b, x, y, tolerance)[0]:
                bad += 1
    return bad / total


def test_picture_in_picture_layers_match_raster(tmp_path, monkeypatch):
    project = _project(tmp_path, [
        dict(scale_x=.4, scale_y=.4, position_x=.78, position_y=.75),
        dict(scale_x=.3, scale_y=.5, position_x=.1, position_y=.1, anchor_x=0., anchor_y=0., opacity=.5),
    ])
    layout = direct_video_layout(capture_video_graph(project))
    assert layout is not None and len(layout["base"]) == 1 and len(layout["layers"]) == 2
    direct, raster = _render_both(tmp_path, project, monkeypatch)
    for x, y in ((10, 170), (250, 135), (60, 40), (300, 10)):
        ok, detail = _close(direct, raster, x, y)
        assert ok, detail
    # Half-transparent green over red.
    assert 100 < direct.pixelColor(60, 40).red() < 160 and direct.pixelColor(60, 40).green() > 100
    assert _mismatch_ratio(direct, raster) < .03


def test_rotation_cover_and_stretch_match_raster(tmp_path, monkeypatch):
    project = _project(tmp_path, [
        dict(scale_x=.5, scale_y=.5, rotation=30., size="320x180"),
        dict(fit_mode="cover", scale_x=.3, scale_y=.3, position_x=.15, position_y=.8, size="160x160"),
        dict(fit_mode="stretch", scale_x=.2, scale_y=.1, position_x=.9, position_y=.1, size="64x64"),
    ])
    direct, raster = _render_both(tmp_path, project, monkeypatch)
    for x, y in ((160, 90), (5, 5), (48, 144), (288, 18), (100, 60)):
        ok, detail = _close(direct, raster, x, y)
        assert ok, detail
    assert _mismatch_ratio(direct, raster) < .04


def test_unsupported_effects_keep_raster_route(tmp_path):
    project = _project(tmp_path, [dict(scale_x=.5, scale_y=.5, rotation=10., anchor_x=0.)])
    assert simple_video_clips(capture_video_graph(project)) is None
    project = _project(tmp_path, [dict(scale_x=.5, scale_y=.5)])
    project.video_tracks[1].clips[0].effects = {"blendMode": "screen"}
    assert simple_video_clips(capture_video_graph(project)) is None


def test_default_nonoverlapping_graph_keeps_concat_only(tmp_path):
    project = _project(tmp_path, [dict(in_ms=2000)])
    layout = direct_video_layout(capture_video_graph(project))
    assert layout is not None and layout["layers"] == [] and len(layout["base"]) == 2


def test_overlay_uses_exact_output_frame_boundaries(tmp_path):
    project = _project(tmp_path, [dict(in_ms=30, scale_x=.5, scale_y=.5)])
    clip = project.video_tracks[1].clips[0]
    clip.source_out_ms = 70
    clip.timeline_out_ms = 100
    job = _job(tmp_path, project, "frame-boundaries")
    job.settings.fps = 30
    job.start_seconds = 0
    job.duration_seconds = .2
    output = run_render_job(FFMPEG, job)
    target = tmp_path / "boundary-pixels.rgb"
    run_hidden_subprocess(
        [str(FFMPEG), "-v", "error", "-y", "-i", str(output), "-vf", "crop=1:1:160:90",
         "-pix_fmt", "rgb24", "-f", "rawvideo", str(target)],
        purpose="inspect both overlay frame boundaries", check=True, timeout=20,
    )
    pixels = target.read_bytes()
    assert len(pixels) == 6 * 3
    assert [pixels[i + 2] > pixels[i] for i in range(0, len(pixels), 3)] == [
        False, True, True, False, False, False,
    ]
