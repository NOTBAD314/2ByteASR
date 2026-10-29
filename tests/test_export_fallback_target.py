"""Fallback contracts with injected children; no native probe/encode is allowed."""
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


@pytest.fixture
def fake_backend(tmp_path, monkeypatch):
    launches = []
    def native_forbidden(*args, **kwargs):
        raise AssertionError('native process/probe/encode forbidden in fake fallback tests')
    monkeypatch.setattr(subprocess, 'Popen', native_forbidden)
    monkeypatch.setattr(subprocess, 'run', native_forbidden)
    monkeypatch.setattr(studio_render, '_run_probe', native_forbidden)
    monkeypatch.setattr(studio_render, 'encoder_choices', native_forbidden)
    monkeypatch.setattr(studio_render, 'probe_encoder', native_forbidden)
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'fake FFmpeg version; no execution')
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path/'logs'))
    monkeypatch.setattr(studio_render, 'select_encoder', lambda ffmpeg, settings:
        'h264_nvenc' if settings.encoder == 'auto' else settings.encoder)
    graph_seen = []
    def compile_graph(ffmpeg, job, ass_filter):
        graph_seen.append(deepcopy(job.direct_video_graph))
        return ['-i', job.media_path, '-map', '0:v:0', '-vf', ass_filter]
    monkeypatch.setattr('twobyteasr.exports.export_filtergraph.compile_video_filtergraph', compile_graph)
    # Validate/publish functions retain normal receipt ownership. Only decoding
    # and packet scanning are replaced with explicit fake validation metadata.
    def fake_validate(ffmpeg, output, **kwargs):
        target = int(launches[-1]['argv'][launches[-1]['argv'].index('-b:v')+1][:-1])*1000
        return {'format': {'duration': '23.4'}, 'streams': [{'codec_type': 'video',
            'codec_name': 'h264', 'width': 1920, 'height': 1080, 'avg_frame_rate': '60/1'}],
            'video_bitrate': {'reliable': True, 'average_bitrate_bps': target,
                'duration_seconds': 23.4, 'duration_source': 'fake fixture'},
            'fake_validation': True}
    monkeypatch.setattr(export_validation, 'validate_output', fake_validate)
    real_hidden = processes.popen_hidden_subprocess
    def start_fake(argv, **kwargs):
        class FakeProcess:
            def __init__(self, command, **options):
                self.command = list(command)
                self.pid = 1000+len(launches)
                encoder = command[command.index('-c:v')+1]
                audio = command[command.index('-c:a')+1] if '-c:a' in command else 'none'
                failure = ('injected nvenc no capable devices found' if encoder == 'h264_nvenc'
                    else 'injected muxer does not support audio codec' if audio == 'copy' else None)
                self.returncode = 1 if failure else 0
                self.stdout = io.StringIO('frame=1404\nprogress=end\n')
                self.stderr = io.StringIO((failure or 'fake x264 rc=abr target accepted')+'\nfinal fake stderr\n')
                launches.append({'argv': self.command, 'purpose': kwargs['purpose'],
                    'returncode': self.returncode, 'failure': failure})
                if not failure:
                    Path(command[-1]).write_bytes(b'fake published video; not an encoded stream')
            def poll(self): return self.returncode
            def wait(self, *args, **kwargs): return self.returncode
            def kill(self): self.returncode = -1
        return real_hidden(argv, process_factory=FakeProcess, **kwargs)
    monkeypatch.setattr(studio_render, 'popen_hidden_subprocess', start_fake)
    binary = tmp_path/'ffmpeg.exe'; binary.write_bytes(b'fake non-executable')
    return binary, launches, graph_seen


def _assert_successful_fallback_evidence(job, launches, target, reason):
    receipt = job.completion_metadata
    assert receipt['actual_encoder'] == 'libx264'
    assert receipt['actual_rate_control'] == 'target'
    assert receipt['requested_video_bitrate_bps'] == target*1000
    assert receipt['bitrate_target_met'] is True
    assert receipt['fake_validation'] is True
    assert '_receipt_active' not in receipt
    assert job.export_context['job_id'] == 'fallback-job'
    assert job.export_context['project_revision'] == 'sha256:frozen'
    assert receipt['diagnostics_path'] == job.export_context['diagnostics_path']
    log = Path(receipt['diagnostics_path'])
    manifest = json.loads((log/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['job_id'] == 'fallback-job'
    assert manifest['project_revision'] == 'sha256:frozen'
    assert manifest['requested_settings']['quality_mode'] == 'target'
    assert manifest['requested_settings']['bitrate_kbps'] == target
    assert manifest['requested_settings']['max_bitrate_kbps'] == target+7000
    assert manifest['last_encoding']['actual_encoder'] == 'libx264'
    assert manifest['last_encoding']['bitrate_argument'] == f'{target}k'
    events = [json.loads(line) for line in (log/'processes.jsonl').read_text(encoding='utf-8').splitlines()]
    starts = [event['payload'] for event in events if event['event'] == 'process_started']
    assert len(starts) == len(launches) == 2
    exits = [event['payload'] for event in events if event['event'] == 'process_exited']
    assert [event['returncode'] for event in exits] == [1, 0]
    for entry, launch in zip(starts, launches):
        assert entry['argv'] == launch['argv']
        assert entry['purpose'] == 'ffmpeg studio render'
        assert entry['rate_control'] == 'target'
        assert entry['bitrate_argument'] == f'{target}k'
        assert '-crf' not in entry['argv'] and '-cq' not in entry['argv']
        assert 'final fake stderr' in (log/entry['stderr_log']).read_text(encoding='utf-8')
    fallback = next(event['payload'] for event in events if event['event'] == 'encoder_or_audio_fallback')
    assert reason in fallback['reason']
    assert fallback['target_video_bitrate_bps'] == target*1000
    assert fallback['rate_control'] == 'target'
    assert events[-1]['event'] == 'job_finished' and events[-1]['payload']['published'] is True
    assert export_run_log.current_export_log() is None


@pytest.mark.parametrize('target', [5000, 10000, 20000])
@pytest.mark.parametrize('requested_encoder', ['auto', 'h264_nvenc'])
def test_hardware_failure_retries_x264_target_with_job_snapshot_and_actual_fake_launch_log(
        tmp_path, fake_backend, target, requested_encoder):
    binary, launches, graph_seen = fake_backend
    job = _job(tmp_path, target, requested_encoder)
    frozen_settings, frozen_project, frozen_graph = deepcopy(asdict(job.settings)), deepcopy(job.export_project_data), deepcopy(job.direct_video_graph)
    observed = []
    original_fallback = studio_render.render_fallback_job
    # The spy records real fallback inputs without substituting retry behavior.
    from unittest.mock import patch
    def observe(current, error):
        observed.append((current, original_fallback(current, error)))
        return observed[-1][1]
    with patch.object(studio_render, 'render_fallback_job', observe):
        output = studio_render.run_render_job(binary, job)
    assert output.read_bytes().startswith(b'fake published video')
    assert asdict(job.settings) == frozen_settings
    assert job.export_project_data == frozen_project
    assert job.direct_video_graph == frozen_graph
    assert graph_seen == [frozen_graph, frozen_graph]
    failed, (retry, _) = observed[0]
    assert failed.settings.encoder == 'h264_nvenc' and retry.settings.encoder == 'libx264'
    assert retry.settings.preset == 'fast'
    assert (retry.start_seconds, retry.duration_seconds) == (12.3, 23.4)
    assert retry.export_project_data is job.export_project_data
    assert retry.direct_video_graph is job.direct_video_graph
    assert retry.export_context is job.export_context
    assert retry.completion_metadata is job.completion_metadata
    assert retry.settings.max_bitrate_kbps == target+7000
    _assert_successful_fallback_evidence(job, launches, target, 'nvenc')


@pytest.mark.parametrize('target', [5000, 10000, 20000])
def test_audio_copy_failure_retries_aac_without_changing_video_target_or_identity(
        tmp_path, fake_backend, target):
    binary, launches, graph_seen = fake_backend
    job = _job(tmp_path, target, 'libx264', audio=True, graph=False)
    frozen_project, frozen_settings = deepcopy(job.export_project_data), deepcopy(asdict(job.settings))
    observed = []
    original_fallback = studio_render.render_fallback_job
    from unittest.mock import patch
    def observe(current, error):
        observed.append((current, original_fallback(current, error)))
        return observed[-1][1]
    with patch.object(studio_render, 'render_fallback_job', observe):
        studio_render.run_render_job(binary, job)
    assert [launch['argv'][launch['argv'].index('-c:a')+1] for launch in launches] == ['copy', 'aac']
    assert graph_seen == []
    assert job.export_project_data == frozen_project
    assert asdict(job.settings) == frozen_settings
    assert (job.start_seconds, job.duration_seconds) == (12.3, 23.4)
    failed, (retry, _) = observed[0]
    expected_settings = dict(frozen_settings, audio_codec='aac')
    assert asdict(retry.settings) == expected_settings
    assert failed.settings.audio_codec == 'copy'
    assert (retry.start_seconds, retry.duration_seconds) == (12.3, 23.4)
    assert retry.export_project_data is job.export_project_data
    assert retry.export_context is job.export_context
    assert retry.completion_metadata is job.completion_metadata
    _assert_successful_fallback_evidence(job, launches, target, 'audio codec')
