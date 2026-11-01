"""Native media adapters preserve identity, explicit candidates and outputs."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.local_mcp import production_media as media
from twobyteasr.local_mcp.mcp_bridge import BridgeError


@pytest.fixture(autouse=True)
def media_library_root(tmp_path, monkeypatch):
    from twobyteasr.projects import studio_project
    monkeypatch.setattr(studio_project, 'project_library_root', lambda: tmp_path)


class Harness(media.MediaOperations):
    def __init__(self, tmp_path):
        self.project = SimpleNamespace(project_id='p1', audio_tracks=[], media=SimpleNamespace(path='clip.mp4'))
        self.page = SimpleNamespace(project=self.project, session=SimpleNamespace(project_path=tmp_path / 'p.2byteproj'),
                                    undo_stack=SimpleNamespace(isClean=lambda: True, push=self.push))
        self.bridge = SimpleNamespace(settings={'enabled': True, 'allow_edits': True, 'allow_export': True, 'scope': 'library'},
                                      _page=lambda: self.page)
        self.window = SimpleNamespace()
        self.jobs = {}
        self.job_payloads = {}
        self.cancel_callbacks = {}
        self.revision = 2
        self.pushed = []
        self._closed = False

    def push(self, command):
        self.pushed.append(command)
        self.revision += 1

    def snapshot(self, page, project):
        return {'project_id': project.project_id, 'revision': self.revision}

    def check_snapshot(self, snap):
        if snap != self.snapshot(self.page, self.project):
            raise BridgeError('stale', '工程已变化')
        return self.page, self.project

    def require_project(self, project_id, revision, **kwargs):
        return self.check_snapshot({'project_id': project_id, 'revision': revision})

    def require_idle(self, exclude_job_id=None):
        if any(j.get('status') in ('running', 'queued', 'cancelling') and k != exclude_job_id for k,j in self.jobs.items()):
            raise BridgeError('busy', '已有任务')

    def require_access(self, permission=None):
        if not self.bridge.settings.get('enabled') or (permission and not self.bridge.settings.get(permission)):
            raise BridgeError('not_permitted', '原生权限拒绝')

    def new_job(self, kind, snapshot):
        job = {'job_id': 'open1', 'kind': kind, 'status': 'running', **snapshot}
        self.jobs[job['job_id']] = job
        return job

    def finish_job(self, job, result, status='completed'):
        job.update(status=status, result=result)
        self.cancel_callbacks.pop(job['job_id'], None)

    def fail_job(self, job, exc):
        job.update(status='failed', error=str(exc))
        self.cancel_callbacks.pop(job['job_id'], None)

    def public_job(self, job):
        return dict(job)

    def get_owned_job(self, job_id, kind=None):
        job = self.jobs[job_id]
        assert kind is None or job['kind'] == kind
        return job

    def run_job(self, kind, snapshot, work, apply=None, existing_job=None):
        job = existing_job or {'job_id': 'job1', 'kind': kind, 'status': 'running'}
        self.jobs[job['job_id']] = job
        result = work(SimpleNamespace(is_cancelled=False), lambda *args: None)
        job['result'] = apply(result, job) if apply else result
        job['status'] = 'completed'
        return job


def test_output_cannot_escape_or_overwrite(tmp_path):
    host = Harness(tmp_path)
    with pytest.raises(BridgeError, match='名称'):
        media._output(host.bridge.settings, host.page, '../overwrite', '')
    root, target = media._output(host.bridge.settings, host.page, 'new', '')
    assert target == tmp_path / media.common.EXPORT_FOLDER / 'new.mp4'
    target.parent.mkdir()
    target.write_bytes(b'preserve')
    with pytest.raises(BridgeError) as exc:
        media._check_output(root, target)
    assert exc.value.code == 'output_exists'
    assert target.read_bytes() == b'preserve'


def test_open_does_not_discard_dirty_project(tmp_path):
    host = Harness(tmp_path)
    host.page.undo_stack.isClean = lambda: False
    (tmp_path / 'absent.2byteproj').write_text('{}')
    with pytest.raises(BridgeError) as exc:
        host.op_open_project(str(tmp_path / 'absent.2byteproj'))
    assert exc.value.code == 'unsaved_changes'


def test_open_preserves_disabled_mcp(tmp_path):
    host = Harness(tmp_path)
    host.bridge.settings['enabled'] = False
    with pytest.raises(BridgeError) as exc:
        host.op_open_project(str(tmp_path / 'absent.2byteproj'))
    assert exc.value.code == 'not_permitted'


@pytest.mark.parametrize('operation', ['create', 'open'])
@pytest.mark.parametrize('has_current_project', [False, True])
def test_current_scope_rejects_external_transitions_before_studio_or_io(tmp_path, operation, has_current_project):
    host = Harness(tmp_path)
    host.bridge.settings['scope'] = 'current'
    if not has_current_project:
        host.page.project = None
        host.bridge._page = lambda: None
    host.window.open_studio_project = lambda *args, **kwargs: pytest.fail('refused call must not construct Studio')
    host._prepare_media_page = lambda *args, **kwargs: pytest.fail('scope must be checked before page preparation')
    target = tmp_path / 'another.2byteproj'
    target.write_text('{}')
    source = tmp_path / 'sample.mp4'
    source.write_bytes(b'unit-test-placeholder')
    with pytest.raises(BridgeError) as exc:
        if operation == 'create':
            host.op_create_media_project(str(source), 'new-target')
        else:
            host.op_open_project(str(target))
    assert exc.value.code == 'out_of_scope'
    assert '应用设置' in str(exc.value) and 'MCP' in str(exc.value)
    assert host.bridge.settings['scope'] == 'current'
    assert not host.jobs
    assert not (tmp_path / 'new-target').exists()


def test_current_scope_can_reopen_only_current_path(tmp_path):
    host = Harness(tmp_path)
    host.bridge.settings['scope'] = 'current'
    current = host.page.session.project_path
    current.write_text('{}')
    opened = []
    host._open_media_project = lambda page, path, job=None: opened.append(path) or {'accepted': True}
    assert host.op_open_project(str(current)) == {'accepted': True}
    assert opened == [current.resolve()]
    assert host.bridge.settings['scope'] == 'current'


def test_library_open_rejects_outside_target_before_page_build(tmp_path, monkeypatch):
    from twobyteasr.projects import studio_project
    root = tmp_path / 'library'
    root.mkdir()
    monkeypatch.setattr(studio_project, 'project_library_root', lambda: root)
    host = Harness(tmp_path)
    host._prepare_media_page = lambda *args, **kwargs: pytest.fail('outside target must not build Studio')
    outside = tmp_path / 'outside.2byteproj'
    outside.write_text('{}')
    with pytest.raises(BridgeError) as exc:
        host.op_open_project(str(outside))
    assert exc.value.code == 'out_of_scope'
    assert not host.jobs


def test_library_create_checks_real_target_boundary_before_page_build(tmp_path, monkeypatch):
    host = Harness(tmp_path)
    host._prepare_media_page = lambda *args, **kwargs: pytest.fail('outside target must not build Studio')
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'unit-test-placeholder')
    monkeypatch.setattr(media.common, 'inside', lambda root, target: False)
    with pytest.raises(BridgeError) as exc:
        host.op_create_media_project(str(source), 'new-target')
    assert exc.value.code == 'out_of_scope'
    assert not (tmp_path / 'new-target').exists()
    assert not host.jobs


@pytest.mark.parametrize('minimum,padding', [(float('nan'), .2), (0, .2), (1, -1), (1, 61)])
def test_detection_invalid_parameters_never_start_native(tmp_path, minimum, padding):
    host = Harness(tmp_path)
    with pytest.raises(BridgeError):
        host.op_detect_speech_pauses('p1', 2, minimum_s=minimum, padding_s=padding)
    assert not host.jobs


def test_detection_uses_detached_native_project_and_returns_explicit_ids(tmp_path, monkeypatch):
    from twobyteasr.studio import studio_speech_cut
    host = Harness(tmp_path)
    seen = []
    def analyze(project, work, **kwargs):
        seen.append((project, kwargs))
        return {'candidates': [{'start_ms': 1000, 'end_ms': 2000}]}
    monkeypatch.setattr(studio_speech_cut, 'analyze_speech_pauses', analyze)
    job = host.op_detect_speech_pauses('p1', 2)
    assert seen[0][0] is not host.project
    assert seen[0][1]['mode'] == 'smart'
    assert job['result']['candidates'][0]['candidate_id'] == '1'
    assert host.job_payloads['job1']['snapshot'] == {'project_id': 'p1', 'revision': 2}
    assert not host.pushed


def pause_host(tmp_path):
    host = Harness(tmp_path)
    host.jobs['detect'] = {'kind': 'detect_speech_pauses', 'status': 'completed'}
    host.job_payloads['detect'] = {'snapshot': host.snapshot(host.page, host.project), 'applied': False,
        'analysis': {'candidates': [{'candidate_id': '1', 'start_ms': 1000, 'end_ms': 2000}]}}
    return host


@pytest.mark.parametrize('ids', [[], ['missing'], ['1', '1'], [1]])
def test_apply_rejects_missing_unknown_or_duplicate_candidates(tmp_path, ids):
    host = pause_host(tmp_path)
    with pytest.raises(BridgeError):
        host.op_apply_pause_cuts('p1', 2, 'detect', ids)
    assert not host.pushed


def test_apply_rejects_stale_detection(tmp_path):
    host = pause_host(tmp_path)
    host.job_payloads['detect']['snapshot']['revision'] = 1
    with pytest.raises(BridgeError):
        host.op_apply_pause_cuts('p1', 2, 'detect', ['1'])
    assert not host.pushed


def test_apply_uses_one_native_undoable_command(tmp_path, monkeypatch):
    from twobyteasr.timeline import studio_clip_edit, studio_edit_sequence
    host = pause_host(tmp_path)
    command = object()
    calls = []
    monkeypatch.setattr(studio_clip_edit, 'ripple_ranges_command',
                        lambda project, ranges, **kwargs: calls.append(ranges) or command)
    monkeypatch.setattr(studio_edit_sequence, 'timeline_duration_ms', lambda project: 10000 - len(host.pushed) * 1000)
    result = host.op_apply_pause_cuts('p1', 2, 'detect', ['1'])
    assert calls == [[(1000, 2000)]]
    assert host.pushed == [command]
    assert result['removed_ms'] == 1000
    assert result['revision'] == 3
    assert host.job_payloads['detect']['applied'] is True


def test_export_uses_native_worker_and_frozen_project(tmp_path, monkeypatch):
    host = Harness(tmp_path)
    def render(project, project_path, root, target, token, progress):
        assert project is not host.project
        assert project_path == str(host.page.session.project_path)
        return {'output_path': str(target), 'size_bytes': 42}
    monkeypatch.setattr(media, '_render', render)
    job = host.op_export_video('p1', 2, name='result')
    assert job['kind'] == 'export_video'
    assert job['result']['output_path'].endswith('result.mp4')


def test_save_calls_controller_and_reads_real_project(tmp_path):
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    host = Harness(tmp_path)
    host.project = host.page.project = SubtitleProject(media=StudioMedia('', duration_ms=1000))
    host.project.project_id = 'p1'
    calls = []
    def save(**kwargs):
        calls.append('native-controller')
        save_project(host.project, host.page.session.project_path)
    host.page.project_controller = SimpleNamespace(save=save)
    result = host.op_save_project('p1', 2)
    assert calls == ['native-controller']
    assert result['saved'] is True
    assert result['size_bytes'] > 0


def test_save_does_not_claim_success_when_controller_rejects(tmp_path):
    host = Harness(tmp_path)
    host.page.project_controller = SimpleNamespace(save=lambda **kwargs: kwargs['message_box_fn']('保存失败', 'disk full'))
    with pytest.raises(BridgeError) as exc:
        host.op_save_project('p1', 2)
    assert exc.value.code == 'save_failed'


def test_create_uses_native_creation_primitives_and_preserves_original(tmp_path, monkeypatch):
    from twobyteasr.projects import studio_project
    from twobyteasr.media import media_service
    from twobyteasr.local_mcp import production
    host = Harness(tmp_path)
    clip = tmp_path / 'source.mp4'
    clip.write_bytes(b'unit-test-placeholder')
    root = tmp_path / 'library'
    root.mkdir()
    monkeypatch.setattr(studio_project, 'project_library_root', lambda: root)
    seen = []
    native_save = studio_project.save_project
    def save(project, path):
        seen.append((project, path))
        return native_save(project, path)
    monkeypatch.setattr(studio_project, 'save_project', save)
    monkeypatch.setattr(media_service, 'GLOBAL_MEDIA_SERVICE',
        SimpleNamespace(ffprobe_path=clip, metadata=lambda path: SimpleNamespace(duration_ms=1000,
            width=64, height=64, fingerprint='unit-fixture', to_dict=lambda: dict(duration_ms=1000,
            width=64, height=64, has_video=True, has_audio=True, fingerprint='unit-fixture'))))
    host.require_access = lambda *args: None
    host._open_media_project = lambda page, path, job=None: seen.append(('opened', path, job['job_id']))
    result = host.op_create_media_project(str(clip), 'new-project')
    assert seen[0][0].media.path == str(clip)
    assert seen[0][0].cues == []
    assert not seen[0][0].video_tracks[0].locked
    assert seen[0][1] == root / 'new-project' / 'new-project.2byteproj'
    assert seen[1][0] == 'opened'
    assert result['result'] is production.DEFERRED
    assert clip.read_bytes() == b'unit-test-placeholder'


def test_create_preserves_existing_project_directory(tmp_path, monkeypatch):
    from twobyteasr.projects import studio_project
    host = Harness(tmp_path)
    clip = tmp_path / 'source.mp4'
    clip.write_bytes(b'input')
    root = tmp_path / 'library'
    (root / 'same').mkdir(parents=True)
    monkeypatch.setattr(studio_project, 'project_library_root', lambda: root)
    with pytest.raises(BridgeError) as exc:
        host.op_create_media_project(str(clip), 'same')
    assert exc.value.code == 'output_exists'


def test_create_real_native_media_project_has_duration_and_no_fake_cues(tmp_path, monkeypatch):
    import os, shutil, wave
    from twobyteasr.projects import studio_project
    from twobyteasr.media import media_service
    ffprobe = os.environ.get('TWOBYTEASR_TEST_FFPROBE') or shutil.which('ffprobe')
    if not ffprobe or not Path(ffprobe).is_file():
        pytest.skip('real FFprobe integration requires TWOBYTEASR_TEST_FFPROBE or FFprobe on PATH')
    monkeypatch.setattr(media_service.GLOBAL_MEDIA_SERVICE, 'ffprobe_path', Path(ffprobe))
    host = Harness(tmp_path)
    source = tmp_path / 'speech.wav'
    with wave.open(str(source), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * 32000)
    root = tmp_path / 'library'
    root.mkdir()
    monkeypatch.setattr(studio_project, 'project_library_root', lambda: root)
    host.require_access = lambda *args: None
    opened = []
    host._open_media_project = lambda page, path, job=None: opened.append(path)
    host.op_create_media_project(str(source), 'actual-media')
    project = studio_project.load_project(opened[0])
    assert project.media.duration_ms == 2000
    assert project.media.path == str(source)
    assert not project.cues
    assert source.is_file()


def test_native_render_produces_decodable_video_without_gui_input(tmp_path, monkeypatch):
    import os, shutil, subprocess
    from PySide6.QtWidgets import QApplication
    from twobyteasr.projects import studio_project
    from twobyteasr.media import media_service
    from twobyteasr.media import media_availability
    from twobyteasr.system import platform_media
    from twobyteasr.exports import studio_render
    ffprobe = os.environ.get('TWOBYTEASR_TEST_FFPROBE') or shutil.which('ffprobe')
    if not ffprobe or not Path(ffprobe).is_file():
        pytest.skip('real render integration requires FFprobe/FFmpeg')
    ffmpeg = Path(ffprobe).with_name('ffmpeg' + Path(ffprobe).suffix)
    if not ffmpeg.is_file():
        pytest.skip('real render integration requires FFmpeg beside FFprobe')
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('2BYTEASR_INSTALL_ROOT', str(Path(ffprobe).parents[3]))
    monkeypatch.setattr(media_service.GLOBAL_MEDIA_SERVICE, 'ffprobe_path', Path(ffprobe))
    monkeypatch.setattr(platform_media, 'ffmpeg_tool', lambda: ffmpeg)
    # The separate availability subprocess cannot inherit monkeypatched tool
    # paths. Keep its probe real, in-process, against the explicit test binary.
    def probe(sources, **kwargs):
        return {str(p): {'path': str(p), 'status': 'available', 'reason': '',
                         'identity': media_service.GLOBAL_MEDIA_SERVICE.metadata(p).to_dict()}
                for p in sources}
    monkeypatch.setattr(media_availability, 'probe_sources', probe)
    native_settings = studio_render.RenderSettings
    monkeypatch.setattr(studio_render, 'RenderSettings', lambda: native_settings(encoder='libx264'))
    source = tmp_path / 'synthetic-test-only.mp4'
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=10:d=1',
                    '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono', '-shortest', '-c:v', 'libx264',
                    '-c:a', 'aac', str(source)], check=True, capture_output=True)
    project = studio_project.project_from_runtime_cues(str(source), [])
    target = tmp_path / 'result.mp4'
    result = media._render(project, str(tmp_path / 'work.2byteproj'), tmp_path, target,
                           SimpleNamespace(is_cancelled=False), lambda value: None)
    assert result['size_bytes'] > 0
    subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(target), '-f', 'null', '-'],
                    check=True, capture_output=True)
    assert app is not None


def test_open_completes_only_after_native_commit_and_readiness(tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    host = Harness(tmp_path)
    path = tmp_path / 'next.2byteproj'
    pending = {}
    def open_project(target, on_ready):
        pending['ready'] = on_ready
        pending['handoff'] = host.page._mcp_project_handoff
    host.page.open_project = open_project
    result = host._open_media_project(host.page, path)
    assert result['status'] == 'running'
    guard, done = pending['handoff'][1:]
    assert guard()
    host.page.project = SimpleNamespace(project_id='p2')
    host.page.session.project_path = path
    assert guard()  # Native assignment precedes the final readiness callback.
    done(True)
    assert host.jobs['open1']['status'] == 'running'
    pending['ready']()
    assert host.jobs['open1']['status'] == 'completed'
    assert host.jobs['open1']['result']['project_id'] == 'p2'


def test_open_revocation_latches_before_native_replacement(tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    host = Harness(tmp_path)
    original = host.page.project
    def open_project(target, on_ready):
        _, guard, done = host.page._mcp_project_handoff
        host.bridge.settings['allow_edits'] = False
        assert not guard()
        host.bridge.settings['allow_edits'] = True
        assert not guard()
        done(False)
    host.page.open_project = open_project
    result = host._open_media_project(host.page, tmp_path / 'next.2byteproj')
    assert result['status'] == 'failed'
    assert host.page.project is original


@pytest.mark.parametrize('operation', ['create', 'open', 'superseded'])
def test_actual_mainwindow_pending_studio_creates_one_job_after_ready(tmp_path, monkeypatch, operation):
    """Reproduce the frozen GUI's pending-property failure with the real shell."""
    import os, shutil, time, wave
    from PySide6.QtWidgets import QApplication
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.local_mcp.mcp_bridge import McpBridge
    from twobyteasr.local_mcp.production import make_production_service
    from twobyteasr.media import media_service
    from twobyteasr.projects import studio_project
    ffprobe = os.environ.get('TWOBYTEASR_TEST_FFPROBE') or shutil.which('ffprobe')
    if not ffprobe or not Path(ffprobe).is_file():
        pytest.skip('native MainWindow media integration requires explicit FFprobe')
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, '_background_preload', lambda self: None)
    monkeypatch.setattr(MainWindow, '_restore_last_project_profile', lambda self: None)
    monkeypatch.setattr(media_service.GLOBAL_MEDIA_SERVICE, 'ffprobe_path', Path(ffprobe))
    root = tmp_path / 'library'
    root.mkdir()
    monkeypatch.setattr(studio_project, 'project_library_root', lambda: root)
    source = tmp_path / 'test-only.wav'
    with wave.open(str(source), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * 16000)
    existing = studio_project.create_studio_outputs(str(source), [], txt_path='',
                        target_project_path=str(root / 'existing' / 'existing.2byteproj'))['project']
    window = MainWindow([], legacy, object(), None)
    bridge = McpBridge(window)
    bridge.settings = {'enabled': True, 'allow_edits': True, 'allow_export': True, 'scope': 'library'}
    service = make_production_service(bridge)
    initial_jobs = len(service.jobs)
    window.show()
    try:
        window._queue_studio_construction(None, source='test_pending')
        assert window.built_page('studio') is None
        with pytest.raises(RuntimeError, match='construction is pending'):
            _ = window.studio_page
        result = (service.op_open_project(existing) if operation == 'open'
                  else service.op_create_media_project(str(source), name='real-shell-created'))
        job_id = result['job_id']
        assert result['status'] == 'running'
        assert window._mcp_studio_probe_suppressed == job_id
        assert len(service.jobs) == initial_jobs + 1
        if operation == 'superseded':
            window.open_studio_project(existing, source='test_manual_navigation')
        # Use the actual construction entry; no click, keyboard or fake page.
        window._start_studio_construction()
        deadline = time.monotonic() + 30
        while service.jobs[job_id]['status'] == 'running' and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        job = service.jobs[job_id]
        if operation == 'superseded':
            assert job['status'] == 'failed', job
            assert job['error']['code'] == 'stale_project'
            assert not (root / 'real-shell-created').exists()
            assert not getattr(window, '_mcp_studio_probe_suppressed', None)
            return
        assert job['status'] == 'completed', job
        assert len(service.jobs) == initial_jobs + 1
        page = window.built_page('studio')
        assert page is not None and page.project is not None
        assert page.project.media.path == str(source)
        assert page.project.media.duration_ms == 1000
        assert not page.project.cues
        assert Path(job['result']['project_path']).is_file()
        assert not getattr(window, '_mcp_studio_probe_suppressed', None)
        if operation == 'create':
            from twobyteasr.timeline.studio_edit_sequence import identity_sequence, sequence_of
            assert sequence_of(page.project).video_track_locked == identity_sequence(page.project.media).video_track_locked
            assert all(not track.locked for track in page.project.video_tracks)
        else:
            before = studio_project.load_project(existing)
            assert [t.locked for t in page.project.video_tracks] == [t.locked for t in before.video_tracks]
    finally:
        service.stop('test cleanup')
        window.close()
        window.deleteLater()
        app.processEvents()


def test_real_229_second_new_project_can_cut_and_undo_without_unlocking_existing(tmp_path, monkeypatch):
    import os
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.media import media_service
    from twobyteasr.projects import studio_project
    from twobyteasr.timeline.studio_clip_edit import ripple_ranges_command, video_track_locked
    from twobyteasr.timeline.studio_edit_sequence import sequence_of, timeline_duration_ms
    source_value = os.environ.get('TWOBYTEASR_TEST_MEDIA')
    ffprobe = os.environ.get('TWOBYTEASR_TEST_FFPROBE')
    if not source_value or not ffprobe:
        pytest.skip('real 229s acceptance input and FFprobe must be explicitly supplied')
    source = Path(source_value)
    original_stat = source.stat()
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(media_service.GLOBAL_MEDIA_SERVICE, 'ffprobe_path', Path(ffprobe))
    root = tmp_path / 'library'
    root.mkdir()
    monkeypatch.setattr(studio_project, 'project_library_root', lambda: root)
    host = Harness(tmp_path)
    host._open_media_project = lambda *args, **kwargs: None
    host.op_create_media_project(str(source), 'editable-229s')
    path = root / 'editable-229s' / 'editable-229s.2byteproj'
    project = studio_project.load_project(path)
    assert 229000 <= project.media.duration_ms <= 230000
    assert project.video_tracks and all(not video_track_locked(project, t) for t in project.video_tracks)
    assert not sequence_of(project).video_track_locked
    before = timeline_duration_ms(project)
    stack = QUndoStack()
    stack.push(ripple_ranges_command(project, [(2000, 3000)]))
    assert timeline_duration_ms(project) == before - 1000
    stack.undo()
    assert timeline_duration_ms(project) == before
    assert source.stat().st_size == original_stat.st_size
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert app is not None
