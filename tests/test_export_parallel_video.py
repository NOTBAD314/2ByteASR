"""Actual NVENC segments: caption seams, exact audio, failure and cancellation."""
from dataclasses import replace
from pathlib import Path
import threading

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.exports.parallel_video_export import frame_partitions
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
from twobyteasr.exports.export_timeline import write_export_ass
from twobyteasr.exports.video_export import capture_video_graph
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.system.platform_media import ffmpeg_tool
from twobyteasr.system.processes import run_hidden_subprocess


@pytest.fixture
def fixture(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path/'source.mp4'
    ffmpeg = ffmpeg_tool()
    run_hidden_subprocess([str(ffmpeg), '-v','error','-f','lavfi','-i',
        "color=c=0x204080:s=320x180:r=30:d=6", '-f','lavfi','-i',
        r"aevalsrc=if(between(mod(t\,1)\,0.4\,0.52)\,0.5*sin(2*PI*800*t)\,0):s=48000:d=6",
        '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac',str(source)],
        purpose='parallel export fixture', capture_output=True, check=True, timeout=20)
    project = SubtitleProject(media=StudioMedia(str(source), duration_ms=6000, width=320, height=180),
        cues=[StudioCue('a', 1000, 1400, 'ORIGINAL'), StudioCue('cross', 2800, 3200, 'CROSS SEAM')])
    project.validate()
    project.styles[0].primary_color = '#FF0000'
    project.styles[0].font_size = 120
    project.styles[0].bold = True
    yield app, ffmpeg, project


def audio(path):
    with av.open(str(path)) as container:
        return np.concatenate([f.to_ndarray() for f in container.decode(audio=0)], axis=1)


@pytest.mark.parametrize('fps,start,duration', [(30, 0, 6), (60000/1001, .137, 4.573)])
def test_parallel_seams_keep_captions_and_continuous_audio(tmp_path, fixture, fps, start, duration):
    app, ffmpeg, project = fixture
    ass = tmp_path/'captions.ass'
    write_export_ass(project, ass, fps=fps)
    common = RenderJob(project.media.path, str(ass), '',
        RenderSettings(encoder='h264_nvenc', preset='p4', quality_mode='cq', quality=12,
            width=320, height=180, fps=fps, audio_codec='aac'),
        start_seconds=start, duration_seconds=duration, video_graph=capture_video_graph(project))
    jobs = [replace(common, output_path=str(tmp_path/f'{count}.mp4'), completion_metadata={},
                    export_context={'parallel_segments':count}) for count in (1,2)]
    for job in jobs:run_render_job(ffmpeg, job)
    before, after = audio(jobs[0].output_path), audio(jobs[1].output_path)
    assert np.array_equal(before, after), 'Audio must be encoded once across the video segment seam'
    with av.open(jobs[1].output_path) as media:
        frames = 0
        for frame in media.decode(video=0):
            frames += 1
            at = start+float(frame.pts*frame.time_base)
            rgb = frame.to_ndarray(format='rgb24')
            visible = np.count_nonzero((rgb[:,:,0]>150)&(rgb[:,:,1]<100)&(rgb[:,:,2]<100))>10
            expected = any(c.start_ms/1000 <= at < c.end_ms/1000 for c in project.cues)
            if visible != expected:
                assert min(abs(at-v/1000) for c in project.cues for v in (c.start_ms,c.end_ms)) <= 1/fps+.002
        assert abs(frames-round(duration*fps)) <= 1
    assert not list(tmp_path.glob('.parallel-video-*'))
    assert jobs[1].completion_metadata['actual_encoder'] == 'h264_nvenc'


def test_parallel_failure_preserves_original_file_and_failure_type(tmp_path, fixture, monkeypatch):
    import twobyteasr.exports.parallel_video_export as parallel
    app, ffmpeg, project = fixture
    ass = tmp_path/'captions.ass'; write_export_ass(project, ass)
    output = tmp_path/'existing.mp4'; output.write_bytes(b'existing verified video')
    job = RenderJob(project.media.path, str(ass), str(output), RenderSettings(encoder='h264_nvenc', fps=30),
        duration_seconds=6, overwrite_existing=True, export_context={'parallel_segments':2})
    monkeypatch.setattr(parallel, '_segment_metadata', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('fixture segment failure')))
    with pytest.raises(RuntimeError, match='fixture segment failure'):
        run_render_job(ffmpeg, job)
    assert output.read_bytes() == b'existing verified video'
    assert job.completion_metadata == {}
    assert not list(tmp_path.glob('.parallel-video-*'))


def test_parallel_cancel_stops_children_and_never_publishes(tmp_path, fixture):
    app, ffmpeg, project = fixture
    ass = tmp_path/'captions.ass'; write_export_ass(project, ass)
    job = RenderJob(project.media.path, str(ass), str(tmp_path/'cancelled.mp4'),
        RenderSettings(encoder='h264_nvenc', fps=30), duration_seconds=6,
        export_context={'parallel_segments':2})
    cancelled = threading.Event()
    timer = threading.Timer(.15, cancelled.set)
    timer.start()
    try:
        with pytest.raises(InterruptedError):run_render_job(ffmpeg, job, cancelled=cancelled.is_set)
    finally:timer.cancel()
    assert not Path(job.output_path).exists() and not list(tmp_path.glob('.parallel-video-*'))


def test_fractional_clock_partitions_cover_every_frame_exactly_once():
    parts = frame_partitions(3600.123, 60000/1001)
    assert parts[0][0] == 0 and parts[0][1] == parts[1][0]
    assert parts[-1][1] == 215792


def test_reserved_header_is_bounded_and_tracks_packet_budget():
    from twobyteasr.exports.parallel_video_export import reserved_moov_bytes
    assert reserved_moov_bytes(8, 30) == 0
    assert 18*1024**2 <= reserved_moov_bytes(3600, 30) <= 24*1024**2
    assert reserved_moov_bytes(3600, 60) > reserved_moov_bytes(3600, 30)
    assert reserved_moov_bytes(360000, 60) == 0


@pytest.mark.parametrize('tiny_reserve', [False, True])
def test_reserved_moov_is_playable_and_insufficient_space_retries_safely(tmp_path, fixture, monkeypatch, tiny_reserve):
    import json
    import struct
    import twobyteasr.exports.parallel_video_export as parallel
    app, ffmpeg, project = fixture
    ass = tmp_path/'captions.ass'; write_export_ass(project, ass)
    if tiny_reserve:monkeypatch.setattr(parallel, 'reserved_moov_bytes', lambda *args: 1024)
    # A real 6s clip followed by the existing graph's black/silent tail creates
    # a 60s sample-table budget without a costly high-resolution test fixture.
    job = RenderJob(project.media.path, str(ass), str(tmp_path/'reserved.mp4'),
        RenderSettings(encoder='h264_nvenc', preset='p4', fps=30, audio_codec='aac'),
        duration_seconds=60, video_graph=capture_video_graph(project), export_context={'parallel_segments':2})
    run_render_job(ffmpeg, job)
    boxes = []
    with Path(job.output_path).open('rb') as stream:
        for _ in range(8):
            raw = stream.read(8)
            if len(raw) < 8:break
            size, kind = struct.unpack('>I4s', raw)
            boxes.append(kind)
            if kind == b'mdat':break
            if size == 1:
                size = struct.unpack('>Q', stream.read(8))[0]
                stream.seek(size-16, 1)
            else:stream.seek(size-8, 1)
    assert boxes.index(b'moov') < boxes.index(b'mdat')
    assert job.completion_metadata['parallel_temporary_media_bytes'] > Path(job.output_path).stat().st_size
    events = Path(job.export_context['diagnostics_path'])/'processes.jsonl'
    retries = [json.loads(line) for line in events.read_text('utf8').splitlines() if '"event": "mux_retry"' in line]
    assert bool(retries) == tiny_reserve


def test_ass_fade_continues_across_the_segment_boundary(tmp_path, fixture):
    app, ffmpeg, project = fixture
    project.cues[1].end_ms = 4200
    ass = tmp_path/'fade.ass'; write_export_ass(project, ass)
    ass.write_text(ass.read_text('utf-8-sig').replace('CROSS SEAM', r'{\fad(600,200)}CROSS SEAM'), encoding='utf-8-sig')
    jobs = []
    for count in (1,2):
        job = RenderJob(project.media.path, str(ass), str(tmp_path/f'fade-{count}.mp4'),
            RenderSettings(encoder='h264_nvenc', preset='p4', quality=12, width=320, height=180,
                           fps=30, audio_codec='none'), duration_seconds=6,
            video_graph=capture_video_graph(project), export_context={'parallel_segments':count})
        run_render_job(ffmpeg, job)
        with av.open(job.output_path) as media:
            jobs.append({round(float(f.pts*f.time_base)*30):f.to_ndarray(format='rgb24') for f in media.decode(video=0)})
    opaque = jobs[0][105]
    glyph = (opaque[:,:,0]>150)&(opaque[:,:,1]<100)&(opaque[:,:,2]<100)
    assert np.count_nonzero(glyph)>10
    for frame in (89,90,92,96,99):
        assert np.abs(jobs[0][frame].astype(float)-jobs[1][frame].astype(float))[glyph].mean()<8
