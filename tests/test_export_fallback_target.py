"""Recovery proposals preserve settings; failures require an explicit user retry."""
from copy import deepcopy
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import subprocess

import pytest

from twobyteasr.exports import export_run_log, export_validation, studio_render
from twobyteasr.system import processes
from twobyteasr.exports.studio_render import RenderJob, RenderSettings


def _job(tmp_path, target, requested_encoder, *, audio=False, graph=True):
    source = tmp_path/'source.mp4'; source.write_bytes(b'fake input; never decode')
    ass = tmp_path/'字幕.ass'; ass.write_text('fake ASS; never render', encoding='utf-8')
    project_graph = {'duration_ms': 159400, 'fps': 60, 'tracks': [
        {'id': 'user-track', 'clips': [{'id': 'user-clip', 'source': str(source),
            'source_start_ms': 8700, 'start_ms': 3000, 'end_ms': 26700}]}]}
    return RenderJob(str(source), str(ass), str(tmp_path/'out.mp4'),
        RenderSettings(codec='h264', encoder=requested_encoder, quality_mode='target',
            bitrate_kbps=target, max_bitrate_kbps=target+7000,
            width=1920, height=1080, fps=60, preset='fast' if audio else 'p4',
            audio_codec='copy' if audio else 'none'),
        start_seconds=12.3, duration_seconds=23.4, composition_resolved=True,
        direct_video_graph=deepcopy(project_graph) if graph else None,
        export_project_data={'media': {'path': str(source)}, 'studio_state': {
            'project_revision': 'user-revision'}, 'video_graph': deepcopy(project_graph)},
        export_context={'job_id': 'fallback-job', 'project_revision': 'sha256:frozen',
            'requested_encoder': requested_encoder})


@pytest.mark.parametrize('target', [5000, 10000, 20000])
@pytest.mark.parametrize('requested_encoder', ['auto', 'h264_nvenc'])
def test_fallback_job_preserves_all_frozen_fields_after_resolved_hardware_failure(
        tmp_path, target, requested_encoder):
    job = _job(tmp_path, target, requested_encoder)
    # Auto is resolved by run_render_job before render_fallback_job is called.
    resolved = replace(job, settings=replace(job.settings, encoder='h264_nvenc'),
        video_graph=deepcopy(job.export_project_data['video_graph']))
    before = deepcopy(asdict(resolved))
    fallback, notice = studio_render.render_fallback_job(resolved,
        RuntimeError('injected nvenc: no capable devices found'))
    expected = deepcopy(before)
    expected['settings'].update(encoder='libx264', preset='fast')
    assert asdict(fallback) == expected
    assert asdict(resolved) == before
    assert fallback.export_context is resolved.export_context
    assert fallback.completion_metadata is resolved.completion_metadata
    assert fallback.video_graph is resolved.video_graph
    assert fallback.direct_video_graph is resolved.direct_video_graph
    assert fallback.export_project_data is resolved.export_project_data
    assert 'libx264' in notice


@pytest.mark.parametrize('target', [5000, 10000, 20000])
@pytest.mark.parametrize('encoder,audio', [('h264_nvenc', False), ('libx264', True)])
def test_failed_job_never_automatically_changes_encoder_or_audio(tmp_path, monkeypatch, target, encoder, audio):
    from twobyteasr.exports.export_failure import ExportFailure
    job = _job(tmp_path, target, encoder, audio=audio, graph=False)
    before = deepcopy(asdict(job.settings))
    attempts = []
    failure = ExportFailure('injected encoder or mux failure', stage='encode', category='nvenc' if not audio else 'audio_mux')
    def attempt(ffmpeg, current, **kwargs):
        attempts.append(deepcopy(asdict(current.settings)))
        raise failure
    monkeypatch.setattr(studio_render, '_run_render_attempt', attempt)
    monkeypatch.setattr(export_run_log, '_version', lambda *a: 'test')
    with pytest.raises(ExportFailure) as caught:
        studio_render.run_render_job(tmp_path/'ffmpeg.exe', job)
    assert caught.value is failure
    assert attempts == [before] and asdict(job.settings) == before
    assert not Path(job.output_path).exists()
