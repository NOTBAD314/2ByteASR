import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dataclasses import replace
from pathlib import Path
import pytest
from PySide6.QtGui import QImage
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, VideoTransform
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, add_video_clip
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
from twobyteasr.exports.video_export import capture_video_graph, prepared_video_job

FFMPEG = Path(__file__).resolve().parents[1] / "tools/ffmpeg/bin/ffmpeg.exe"
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="bundled ffmpeg required")


@pytest.fixture
def fixture(tmp_path):
    paths = []
    for i, color in enumerate(("red", "blue", "lime")):
        path = tmp_path / f"clip {i}.mkv"
        run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
                               f"color={color}:s=160x90:r=10:d=1", "-c:v", "ffv1", str(path)],
                              purpose="export fixture", check=True, timeout=10)
        paths.append(path)
    project = SubtitleProject(media=StudioMedia(path=str(paths[0]), duration_ms=1000, width=160, height=90))
    project.validate()
    for i, path in enumerate(paths[1:], 2):
        asset = add_media_asset(project, path, duration_ms=1000,
                                video_metadata={"width": 160, "height": 90, "has_video": True},
                                audio_metadata={"has_audio": False})
        track = create_video_track(project, f"V{i}")
        clip = add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=0)
        clip.transform = VideoTransform(scale_x=.5, scale_y=.5, position_x=.25 if i == 2 else .75)
    ass = tmp_path / "empty.ass"
    from twobyteasr.rendering.ass_compiler import compile_ass
    ass.write_text(compile_ass(project), encoding="utf-8-sig")
    job = RenderJob(str(paths[0]), str(ass), str(tmp_path / "result.mkv"),
                    RenderSettings(container="mkv", encoder="libx264", preset="ultrafast",
                                   audio_codec="none", fps=10, quality=0),
                    start_seconds=.2, duration_seconds=.2, video_graph=capture_video_graph(project))
    return project, job


def frame_at(path, tmp_path):
    target = tmp_path / (path.stem + "-frame.png")
    run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-i", str(path), "-frames:v", "1", str(target)],
                          purpose="export pixel validation", check=True, timeout=10)
    return QImage(str(target))


def test_native_export_consumes_v3_and_range(fixture, tmp_path):
    project, job = fixture
    previews, progress = [], []
    job.preview_callback = lambda image,t,phase: previews.append((image.copy(),t,phase))
    output = run_render_job(FFMPEG, job, progress=progress.append)
    image = frame_at(output, tmp_path)
    assert image.pixelColor(10, 10).red() > 230
    assert image.pixelColor(40, 45).blue() > 230
    assert image.pixelColor(120, 45).green() > 230
    composed = [row for row in previews if row[2].startswith('视频轨合成')]
    assert composed and composed[0][1] >= 200
    assert any(p.get('stage')=='compose_video' and float(p.get('percent',0))>0 for p in progress)
    assert any(row[2]=='已烧录字幕' for row in previews)
    assert not list(tmp_path.glob(".video-composition-*"))


@pytest.mark.parametrize("mode", ["normal", "screen", "multiply", "overlay", "softLight", "addition"])
def test_blend_chroma_and_alpha_use_preview_math(fixture, tmp_path, mode):
    project, job = fixture
    blue, green = project.video_tracks[1].clips[0], project.video_tracks[2].clips[0]
    blue.effects = {"blendMode": mode}
    blue.transform.opacity = .5
    green.effects = {"chromaKey": {"enabled": True, "color": "#00FF00", "similarity": .1,
                                    "smoothness": .1, "spillSuppression": True}}
    job.video_graph = capture_video_graph(project)
    with prepared_video_job(FFMPEG, job) as prepared:
        assert prepared.composition_resolved and not prepared.edit_segments
        image = frame_at(Path(prepared.media_path), tmp_path)
        # Fully keyed V3 reveals V1 red at right, outside V2.
        keyed = image.pixelColor(120, 45)
        assert keyed.red() > 245 and keyed.green() < 5
        # Compare against independent known opaque red/blue blend outcomes.
        pixel = image.pixelColor(40, 45)
        expected = {"normal": (127, 0, 127), "screen": (255, 0, 127),
                    "multiply": (127, 0, 0), "overlay": (255, 0, 0),
                    "softLight": (255, 0, 0), "addition": (255, 0, 127)}[mode]
        assert all(abs(v-e) <= 4 for v,e in zip(pixel.getRgb()[:3], expected)), pixel.getRgb()


def test_cancel_removes_intermediate_and_children(fixture, tmp_path):
    _, job = fixture
    with pytest.raises(InterruptedError):
        with prepared_video_job(FFMPEG, job, cancelled=lambda: True):
            pytest.fail("cancelled export yielded a job")
    assert not list(tmp_path.glob(".video-composition-*"))


def test_export_preserves_source_fps_audio_and_preview_range(fixture, tmp_path):
    import json
    project, job = fixture
    audio = tmp_path / "with-audio.mkv"
    run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-i", job.media_path,
                           "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                           "-c:v", "copy", "-c:a", "pcm_s16le", str(audio)],
                          purpose="audio fixture", check=True, timeout=10)
    job.media_path = str(audio)
    # The immutable graph, not the legacy media_path alone, owns audio routing.
    project.media.path = str(audio)
    project.media_pool[0].canonical_source = str(audio)
    project.media_pool[0].audio_metadata = {"has_audio": True}
    job.video_graph = capture_video_graph(project)
    job.settings = replace(job.settings, fps=0, audio_codec="copy")
    output = run_render_job(FFMPEG, job)
    probe = run_hidden_subprocess([str(FFMPEG.with_name("ffprobe.exe")), "-v", "error", "-show_streams",
                                   "-show_format", "-of", "json", str(output)],
                                  purpose="export timing validation", capture_output=True, check=True, timeout=10)
    data = json.loads(probe.stdout)
    assert {s["codec_type"] for s in data["streams"]} == {"video", "audio"}
    assert next(s for s in data["streams"] if s["codec_type"] == "video")["r_frame_rate"] == "10/1"
    assert abs(float(data["format"]["duration"]) - .2) < .07


def test_advanced_final_composite_keeps_video_graph(fixture, tmp_path, monkeypatch):
    import twobyteasr.rendering.advanced_renderer as advanced
    from twobyteasr.projects.studio_project import StudioCue, SubtitleStyle
    from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
    project, job = fixture
    previews=[]
    job.preview_callback=lambda image,t,phase:previews.append((image.copy(),t,phase))
    recipe = style_recipe_for_prompt("黄色到青色渐变字幕")
    recipe.engine = "remotion"
    project.styles.append(SubtitleStyle(id="advanced", name="Advanced test"))
    project.style_recipes["advanced"] = recipe.to_dict()
    project.cues = [StudioCue("advanced", 0, 1000, "测试", style_id="advanced")]
    monkeypatch.setattr(advanced.AdvancedRendererBackend, "require_available", lambda self: None)
    def cached_overlay(props, path):
        run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=black@0.0:s=160x90:r=10:d=0.2,format=rgba,drawbox=x=0:y=0:w=20:h=20:color=white@1:t=fill:replace=1",
            "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", str(path)],
            purpose="cached subtitle overlay fixture", check=True, timeout=10)
        return True
    monkeypatch.setattr(advanced, "_restore_overlay_cache", cached_overlay)
    output = advanced.AdvancedRendererBackend().render(project, FFMPEG, job)
    image = frame_at(output, tmp_path)
    assert image.pixelColor(10, 10).green() > 230  # cached subtitle white block
    assert image.pixelColor(40, 45).blue() > 230
    assert image.pixelColor(120, 45).green() > 230  # V3 survives Advanced assembly
    assert any(row[2]=='已烧录字幕' for row in previews)


def test_clip_rate_trim_and_hidden_track(fixture, tmp_path):
    project, job = fixture
    clip = project.video_tracks[1].clips[0]
    clip.source_in_ms = 200
    clip.playback_rate = 2.
    clip.timeline_in_ms = 400
    clip.timeline_out_ms = 800
    project.video_tracks[2].enabled = False
    job.video_graph = capture_video_graph(project)
    job.start_seconds = .1
    with prepared_video_job(FFMPEG, job) as first:
        image = frame_at(Path(first.media_path), tmp_path)
        assert image.pixelColor(40, 45).red() > 230
        assert image.pixelColor(120, 45).red() > 230

    job.start_seconds = .5
    with prepared_video_job(FFMPEG, job) as second:
        image = frame_at(Path(second.media_path), tmp_path)
        assert image.pixelColor(40, 45).blue() > 230
        assert image.pixelColor(120, 45).red() > 230


def test_rotation_anchor_and_graph_tail_duration(fixture, tmp_path):
    project, job = fixture
    project.video_tracks[2].enabled = False
    clip = project.video_tracks[1].clips[0]
    clip.timeline_in_ms = 800
    clip.timeline_out_ms = 1800
    clip.transform.rotation = 90
    job.video_graph = capture_video_graph(project)
    job.start_seconds = 1.2
    job.duration_seconds = None
    with prepared_video_job(FFMPEG, job) as prepared:
        assert prepared.duration_seconds == pytest.approx(.6)
        image = frame_at(Path(prepared.media_path), tmp_path)
        assert image.pixelColor(40, 10).blue() > 230
        assert image.pixelColor(5, 45).blue() < 5
