import io
import json
import hashlib
import threading
from pathlib import Path
import pytest

from twobyteasr.system import processes
from twobyteasr.exports import export_run_log
from twobyteasr.exports.studio_render import RenderJob, RenderSettings


class FakeProcess:
    pid = 123
    returncode = 0
    def __init__(self, command, **kwargs):
        self.command = command
        self.stdout = io.StringIO('frame=9564\nprogress=end\n')
        self.stderr = io.StringIO('x264: rc=abr bitrate=10000\nlast stderr\n')
    def poll(self): return 0
    def wait(self, *args, **kwargs): return 0
    def communicate(self, *args, **kwargs): return self.stdout.read(), self.stderr.read()


def test_actual_launch_and_full_pipe_output_survive_drain_thread_and_session(tmp_path, monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path/'logs'))
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'ffmpeg test version')
    binary = tmp_path/'ffmpeg.exe'; binary.write_bytes(b'fake')
    job = RenderJob('source.mp4', '', str(tmp_path/'final.mp4'),
        RenderSettings(encoder='libx264', quality_mode='target', bitrate_kbps=10000),
        export_context=dict(job_id='test-job', project_revision='sha256:fixed', requested_encoder='auto'))
    logger, token = export_run_log.begin_export_log(binary, job)
    argv = [str(binary), '-i', '中文 源.mp4', '-filter_complex', 'actual-preview-rewritten',
            '-c:v', 'libx264', '-b:v', '10000k', 'stage.mp4']
    try:
        child = processes.popen_hidden_subprocess(argv, purpose='ffmpeg studio render', process_factory=FakeProcess, text=True)
        thread = threading.Thread(target=lambda:list(child.stderr))
        thread.start(); thread.join()
        assert list(child.stdout) == ['frame=9564\n', 'progress=end\n']
        child.wait()
    finally:
        export_run_log.end_export_log(logger, token)
    records = [json.loads(x) for x in (logger.path/'processes.jsonl').read_text(encoding='utf-8').splitlines()]
    started = next(x['payload'] for x in records if x['event']=='process_started')
    assert started['argv'] == child._process.command
    assert started['filter_scripts'] == []  # Inline graphs are not file references.
    assert started['purpose'] == 'ffmpeg studio render'
    assert started['rate_control'] == 'target'
    assert (logger.path/'001.stderr.log').read_text(encoding='utf-8') == 'x264: rc=abr bitrate=10000\nlast stderr\n'
    assert job.completion_metadata['actual_encoder'] == 'libx264'
    assert export_run_log.current_export_log() is None


def test_thumbnail_encoder_cannot_replace_final_video_identity(tmp_path, monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path))
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'v')
    job = RenderJob('', '', str(tmp_path/'final.mp4'), RenderSettings(quality_mode='target'))
    logger, token = export_run_log.begin_export_log(tmp_path/'ffmpeg.exe', job)
    try:
        for codec in ('ffv1', 'libx264', 'mjpeg'):
            child = processes.popen_hidden_subprocess(['ffmpeg.exe', '-c:v', codec, '-b:v', '8000k', 'file'],
                purpose='advanced preview/render child', process_factory=FakeProcess, text=True)
            child.communicate()
        assert job.completion_metadata['actual_encoder'] == 'libx264'
        assert logger.manifest['last_encoding']['actual_encoder'] == 'libx264'
    finally:
        export_run_log.end_export_log(logger, token)


@pytest.mark.parametrize('option', ['-/filter_complex', '-filter_complex_script'])
def test_actual_filter_script_is_preserved_before_relative_cwd_temp_cleanup(tmp_path, monkeypatch, option):
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path/'logs'))
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'v')
    work = tmp_path/'中文 临时合成'; work.mkdir()
    source = work/'captions.ffgraph'
    original = '[0:a]volume=0.7[a];[a][1:a]amix=inputs=2:normalize=0[out]\n'.encode('utf-8')
    source.write_bytes(original)
    job = RenderJob('', '', str(tmp_path/'final.mp4'))
    logger, token = export_run_log.begin_export_log(tmp_path/'ffmpeg.exe', job)
    argv = ['ffmpeg.exe', option, source.name, '-c:v', 'libx264', '-b:v', '10000k', 'out.mp4']
    try:
        # This is the same actual-boundary method used by Popen, without launching a child.
        logger.process_started(argv, 'ffmpeg studio render', FakeProcess(argv), cwd=work)
        source.unlink(); work.rmdir()
        records = [json.loads(x) for x in (logger.path/'processes.jsonl').read_text(encoding='utf-8').splitlines()]
        started = next(x['payload'] for x in records if x['event']=='process_started')
        assert started['argv'] == argv
        script, = started['filter_scripts']
        assert script['option'] == option and script['argument'] == 'captions.ffgraph'
        assert script['resolved_path'] == str(source.resolve())
        assert script['source_sha256'] == hashlib.sha256(original).hexdigest()
        saved = Path(script['saved_path'])
        assert saved.parent == logger.path and saved.name == '123.filter_complex.txt'
        assert saved.read_bytes() == original
        assert script['saved_sha256'] == hashlib.sha256(saved.read_bytes()).hexdigest()
        assert script['source_bytes'] == script['saved_bytes'] == len(original)
        assert 'read_error' not in script
    finally:
        export_run_log.end_export_log(logger, token)


def test_missing_filter_script_records_error_without_reconstructing_graph(tmp_path, monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path/'logs'))
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'v')
    work = tmp_path/'cwd'; work.mkdir()
    job = RenderJob('', '', str(tmp_path/'final.mp4'))
    logger, token = export_run_log.begin_export_log(tmp_path/'ffmpeg.exe', job)
    argv = ['ffmpeg.exe', '-/filter_complex', 'missing.ffgraph']
    try:
        logger.process_started(argv, 'ffmpeg studio render', FakeProcess(argv), cwd=work)
        records = [json.loads(x) for x in (logger.path/'processes.jsonl').read_text(encoding='utf-8').splitlines()]
        script, = next(x['payload']['filter_scripts'] for x in records if x['event']=='process_started')
        assert script['argument'] == 'missing.ffgraph'
        assert script['resolved_path'] == str((work/'missing.ffgraph').resolve())
        assert script['read_error'].startswith('FileNotFoundError:')
        assert 'saved_path' not in script and 'source_sha256' not in script
        assert not list(logger.path.glob('*.filter_complex.txt'))
    finally:
        export_run_log.end_export_log(logger, token)


def test_filter_script_copy_is_redacted_with_separate_source_and_saved_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path/'logs'))
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'v')
    source = tmp_path/'actual.ffgraph'
    original = ('movie=https://person:private-password@example.org/video?token=private-token[v];\n'
                '# Authorization: Bearer private-bearer\n[0:a]volume=0.7[a]\n').encode('utf-8')
    source.write_bytes(original)
    job = RenderJob('', '', str(tmp_path/'final.mp4'))
    logger, token = export_run_log.begin_export_log(tmp_path/'ffmpeg.exe', job)
    argv = ['ffmpeg.exe', '-filter_complex_script', str(source)]
    try:
        logger.process_started(argv, 'ffmpeg studio render', FakeProcess(argv), cwd=tmp_path)
        records = [json.loads(x) for x in (logger.path/'processes.jsonl').read_text(encoding='utf-8').splitlines()]
        script, = next(x['payload']['filter_scripts'] for x in records if x['event']=='process_started')
        saved = Path(script['saved_path']).read_bytes()
        assert script['source_sha256'] == hashlib.sha256(original).hexdigest()
        assert script['saved_sha256'] == hashlib.sha256(saved).hexdigest()
        assert script['source_sha256'] != script['saved_sha256']
        assert source.read_bytes() == original
        assert b'volume=0.7' in saved and b'[REDACTED]' in saved
        all_evidence = b''.join(path.read_bytes() for path in logger.path.iterdir() if path.is_file())
        for credential in (b'private-password', b'private-token', b'private-bearer'):
            assert credential not in all_evidence
    finally:
        export_run_log.end_export_log(logger, token)


def test_binary_media_stdout_is_not_logged_but_binary_stderr_is(tmp_path, monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path))
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'v')
    class BinaryProcess(FakeProcess):
        def __init__(self, command, **kwargs):
            self.stdout = io.BytesIO(b'\x00\xff\x01\x02' * 1000000)
            self.stderr = io.BytesIO(b'raw video decoder warning\n')
    job = RenderJob('', '', str(tmp_path/'final.mp4'))
    logger, token = export_run_log.begin_export_log(tmp_path/'ffmpeg.exe', job)
    try:
        child = processes.popen_hidden_subprocess(['ffmpeg.exe', '-f', 'rawvideo', 'pipe:1'],
            purpose='composition raw frame decoder', process_factory=BinaryProcess)
        assert child.stdout is child._process.stdout
        assert len(child.stdout.read()) == 4000000
        with child.stderr as stream:
            assert stream.read() == b'raw video decoder warning\n'
        child.wait()
        assert not (logger.path/'001.stdout.log').exists()
        assert (logger.path/'001.stderr.log').read_text() == 'raw video decoder warning\n'
        assert job.export_context['diagnostics_path'] == str(logger.path)
    finally:
        export_run_log.end_export_log(logger, token, InterruptedError())


def test_failed_record_completion_retains_log_location_in_internal_job_context(tmp_path, monkeypatch):
    from twobyteasr.exports.export_validation import record_completion
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path))
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'v')
    job = RenderJob('', '', str(tmp_path/'failed.mp4'))
    @record_completion
    def render(ffmpeg, job):
        raise InterruptedError('cancelled')
    import pytest
    with pytest.raises(InterruptedError):
        render(tmp_path/'ffmpeg.exe', job)
    assert job.completion_metadata == {}
    assert (Path(job.export_context['diagnostics_path'])/'manifest.json').is_file()


def test_launch_log_failure_does_not_leave_unowned_child(monkeypatch):
    import pytest
    class UnwritableLog:
        def process_started(self, *args, **kwargs):
            raise OSError('diagnostic disk unavailable')
    stopped = []
    monkeypatch.setattr(export_run_log, 'current_export_log', lambda:UnwritableLog())
    monkeypatch.setattr(processes, 'stop_process_tree', stopped.append)
    with pytest.raises(OSError, match='diagnostic disk unavailable'):
        processes.popen_hidden_subprocess(['ffmpeg.exe', '-c:v', 'libx264', 'out.mp4'],
            purpose='ffmpeg studio render', process_factory=FakeProcess, text=True)
    assert len(stopped) == 1
    assert stopped[0].command[-1] == 'out.mp4'


def test_parallel_overlay_segment_launches_inherit_distinct_contexts(tmp_path, monkeypatch):
    from twobyteasr.rendering import advanced_renderer as renderer
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path/'logs'))
    monkeypatch.setattr(export_run_log, '_version', lambda *args:'v')
    monkeypatch.setattr(renderer, '_segment_cache_path', lambda *args:tmp_path/'missing.mov')
    monkeypatch.setattr(renderer, '_copy_verified_overlay', lambda *args:False)
    monkeypatch.setattr(renderer, '_segment_cache_store', lambda *args:None)
    monkeypatch.setattr(renderer, '_web_theme_composition', lambda *args:False)
    monkeypatch.setattr(renderer, 'renderer_node_command', lambda *args:['fake-node'])
    job = RenderJob('', '', str(tmp_path/'final.mp4'))
    logger, token = export_run_log.begin_export_log(tmp_path/'ffmpeg.exe', job)
    barrier = threading.Barrier(2)
    def launch(command, **kwargs):
        assert export_run_log.current_export_log() is logger
        env = processes.renderer_child_environment()
        assert env['TWOBYTEASR_EXPORT_JOB_ID'] == job.export_context['job_id']
        barrier.wait(timeout=5)
        process = processes.popen_hidden_subprocess(command, purpose='fake overlay segment launch',
            process_factory=FakeProcess, text=True)
        process.communicate()
        Path(command[command.index('SubtitleOverlay') + 1]).write_bytes(b'fake segment')
        return 0, 'done'
    monkeypatch.setattr(renderer, '_run_streaming_process', launch)
    try:
        result = renderer.AdvancedRendererBackend()._render_overlay_segments(props={},
            props_path=tmp_path/'props.json', temp=tmp_path, windows=[(0,1),(3,4)],
            cli=tmp_path/'cli', chrome=tmp_path/'chrome', fps=60, progress=None,
            cancelled=None, trace=None, timings={})
        assert len(result) == 2
        records = [json.loads(x) for x in (logger.path/'processes.jsonl').read_text().splitlines()]
        starts = [x['payload'] for x in records if x['event']=='process_started']
        assert len(starts) == 2
        assert {x['process_id'] for x in starts} == {'001','002'}
    finally:
        export_run_log.end_export_log(logger, token)
