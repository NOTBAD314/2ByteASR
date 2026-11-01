from types import SimpleNamespace
import pytest
from twobyteasr.local_mcp.production_recognition import RecognitionOperations
from twobyteasr.local_mcp.mcp_bridge import BridgeError

class Service(RecognitionOperations):
    def __init__(self):
        self.window = SimpleNamespace(_run_in_progress=True)
    def require_project(self, project_id, revision):
        return SimpleNamespace(), SimpleNamespace()

def test_busy_native_recognition_never_starts_another_task():
    with pytest.raises(BridgeError) as exc:
        Service().op_start_recognition('p', 1)
    assert exc.value.code == 'busy'

def test_recognition_binds_native_job_and_cancels_only_owned_worker(tmp_path, monkeypatch):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    class Signal:
        def __init__(self): self.callbacks = []
        def connect(self, fn): self.callbacks.append(fn)
        def disconnect(self, fn): self.callbacks.remove(fn)
        def emit(self, value):
            for fn in tuple(self.callbacks): fn(value)
    class Worker:
        def __init__(self):
            self.event_received, self.result_ready = Signal(), Signal()
            self.unexpected_error, self.finished = Signal(), Signal()
        def isRunning(self): return True
    class Stack:
        def count(self): return 0
    media = tmp_path / 'test.mp4'; media.write_bytes(b'x')
    path = tmp_path / 'test.2byteproj'; path.write_text('{}')
    project = SimpleNamespace(project_id='p', media=SimpleNamespace(path=str(media)), cues=[])
    page = SimpleNamespace(project=project, session=SimpleNamespace(project_path=path), undo_stack=Stack())
    worker = Worker()
    cancelled = []
    window = SimpleNamespace(_run_in_progress=False, worker=None, _active_job_id='',
        _asr_config_dirty=False, _ai_has_draft=True,
        legacy=SimpleNamespace(RUNTIME_SETTINGS={'models': {'primary_asr_backend': 'moss',
            'firered_asr_backend': 'local', 'qwen_asr_backend': 'local'},
            'switches': {'enable_ai_polish': False, 'use_ai_grouping': False}}))
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
    monkeypatch.setattr(OpenAICompatibleProvider, 'validate', lambda *a, **kw: pytest.fail('unexpected provider request'))
    def start(*args, **kwargs):
        assert kwargs['noninteractive'] is True
        window.guard, window.done = kwargs['handoff_guard'], kwargs['handoff_done']
        window.worker, window._active_job_id = worker, 'native-1'
        window._studio_recognition_context = {'snapshot': {'project_id': 'p', 'project_revision': 'r'}}
    window._handle_studio_recognition_request = start
    window._cancel_run = lambda: cancelled.append('native-1')
    class Working(RecognitionOperations):
        def __init__(self):
            self.window, self.cancel_callbacks = window, {}
            self.jobs, self._closed = {}, False
            self.bridge = SimpleNamespace(settings={'enabled': True, 'allow_edits': True})
        def require_project(self, project_id, revision): return page, project
        def snapshot(self, *_): return {'project_id': 'p', 'revision': 1}
        def new_job(self, kind, snapshot):
            job = {'job_id': 'j', 'kind': kind, 'status': 'running'}
            self.jobs['j'] = job
            return job
        def update_job(self, job, **kw): job.update(kw)
        def public_job(self, job): return job
        def fail_job(self, job, exc): job.update(status='failed', error=exc.code, error_message=str(exc))
        def finish_job(self, job, result, status='completed'): job.update(status=status, result=result)
    service = Working()
    job = service.op_start_recognition('p', 1)
    assert job['result']['native_job_id'] == 'native-1'
    assert window.guard() is True
    worker.event_received.emit(SimpleNamespace(job_id='other', label='wrong', stage_index=3, stage_total=4))
    assert 'progress' not in job
    worker.event_received.emit(SimpleNamespace(job_id='native-1', label='识别', stage_index=1, stage_total=4))
    assert job['progress']['done'] == 1
    window._active_job_id = 'someone-else'
    service.cancel_callbacks['j']()
    assert cancelled == []
    assert window.guard() is False
    window._active_job_id = 'native-1'
    service.cancel_callbacks['j']()
    assert cancelled == ['native-1']

def test_native_worker_signal_callbacks_run_on_gui_thread():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QEventLoop, QThread, QTimer, Signal
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    class Worker(QThread):
        emitted = Signal(object)
        def run(self): self.emitted.emit('result')
    worker = Worker()
    loop = QEventLoop()
    observed = []
    def callback(value):
        observed.append((value, QThread.currentThread() is app.thread()))
        loop.quit()
    worker.emitted.connect(callback)
    worker.start()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    worker.wait(3000)
    assert observed == [('result', True)]

def test_noninteractive_limits_honor_native_confirmation_without_dialog(monkeypatch):
    from twobyteasr.app.ui import MainWindow
    class Store(dict):
        def value(self, key, default=None, type=None): return self.get(key, default)
    store = Store()
    shell = SimpleNamespace(_run_limit_lines=lambda: ['没有字级时间戳'],
        _text_ai_local_roles=(), _append_console_line=lambda *_: None,
        _progress_settings=lambda: store)
    assert MainWindow._confirm_run_limits(shell, noninteractive=True) is False
    assert shell._run_block_code == 'native_confirmation_required'
    assert not store
    import hashlib
    signature = hashlib.sha256('|1'.encode('utf-8')).hexdigest()[:16]
    store['run_limits_ack/' + signature] = True
    assert MainWindow._confirm_run_limits(shell, noninteractive=True) is True


def test_noninteractive_cloud_disclosure_refuses_unconfirmed_without_storing(monkeypatch):
    from twobyteasr.app.ui import MainWindow
    import twobyteasr.recognition.recognition_choices as choices
    class Store(dict):
        def value(self, key, default=None, type=None): return self.get(key, default)
    store = Store()
    shell = SimpleNamespace(_run_settings_snapshot=lambda: {}, _asr_values=lambda: {},
        _append_console_line=lambda *_: None, _progress_settings=lambda: store)
    monkeypatch.setattr(choices, 'disclosure_text', lambda settings: '云服务')
    monkeypatch.setattr(choices, 'run_disclosure', lambda settings: {'engine': 'fixture', 'uploads': ['音频 fixture']})
    assert MainWindow._confirm_run_disclosure(shell, noninteractive=True) is False
    assert shell._run_block_code == 'native_confirmation_required'
    assert not store
    import hashlib
    signature = hashlib.sha256('fixture|音频 fixture'.encode()).hexdigest()[:24]
    store['cloud_upload_ack/' + signature] = True
    assert MainWindow._confirm_run_disclosure(shell, noninteractive=True) is True

def test_noninteractive_missing_model_reports_configuration_without_dialog(monkeypatch):
    from twobyteasr.app import ui
    class Button:
        def setEnabled(self, _): pass
    shell = SimpleNamespace(_completion_retry_in_progress=False, _run_in_progress=False,
        _retry_run_options=None, _term_library_dialog=None, _prepare_glossary_for_task=lambda: True,
        start_button=Button(), media_paths=['a.mp4'], primary_asr_backend=SimpleNamespace(currentData=lambda: 'none'))
    shell._release_run_state = lambda: setattr(shell, '_run_in_progress', False)
    monkeypatch.setattr(ui, 'QMessageBox', lambda *_: pytest.fail('noninteractive opened a dialog'))
    ui.MainWindow._start_run(shell, noninteractive=True)
    assert shell._run_block_code == 'configuration_required'
    assert '主力转写模型' in shell._run_block_reason
    assert shell._run_in_progress is False


def test_noninteractive_missing_media_returns_without_dialog(tmp_path, monkeypatch):
    from twobyteasr.app import ui
    shell = SimpleNamespace(_ensure_recognition_page=lambda: None,
        studio_page=SimpleNamespace(fail_recognition_runtime=lambda *_: None))
    monkeypatch.setattr(ui, 'QMessageBox', lambda *_: pytest.fail('noninteractive opened a dialog'))
    ui.MainWindow._handle_studio_recognition_request(shell, 'start_final',
        str(tmp_path / 'missing.mp4'), str(tmp_path / 'missing.2byteproj'), noninteractive=True)
    assert shell._run_block_code == 'configuration_required'

def test_cancelled_or_revoked_recognition_never_hands_off_result(tmp_path):
    from twobyteasr.app.ui import MainWindow
    target = tmp_path / 'result.2byteproj'
    target.write_text('kept', encoding='utf-8')
    finished, failures, opened = [], [], []
    page = SimpleNamespace(fail_recognition_runtime=failures.append)
    shell = SimpleNamespace(studio_page=page,
        _studio_recognition_context={'snapshot': {'project_id': 'p'},
                                     'handoff_guard': lambda: False,
                                     'handoff_done': lambda committed: finished.append(committed)},
        open_studio_project=lambda *a, **kw: opened.append(a))
    MainWindow._finish_studio_recognition(shell, str(target))
    assert shell._studio_recognition_context is None
    assert not opened and finished == [False] and failures
    assert target.read_text(encoding='utf-8') == 'kept'


def test_readiness_aborts_revoked_handoff_before_async_project_assignment(tmp_path):
    from twobyteasr.studio.studio_readiness import StudioReadiness
    target = str((tmp_path / 'result.2byteproj').resolve())
    state = {'valid': True}
    done, cancelled = [], []
    original = object()
    page = SimpleNamespace(project=original, _mcp_project_handoff=(target, lambda: state['valid'], lambda committed: done.append(committed)))
    gate = SimpleNamespace(page=page, path=target, active=True, _owns_request=lambda *a: True,
                           cancel=lambda: cancelled.append(True))
    state['valid'] = False
    StudioReadiness._tick(gate)
    assert cancelled == [True] and done == [False]
    assert page.project is original and page._mcp_project_handoff is None

def test_verified_recognition_stays_running_until_guarded_handoff(tmp_path, monkeypatch):
    import json
    from PySide6.QtWidgets import QApplication
    from twobyteasr.recognition.service import MediaResult, QueueResult
    import twobyteasr.recognition.recognition_result as rr
    app = QApplication.instance() or QApplication([])
    class Signal:
        def __init__(self): self.callbacks = []
        def connect(self, fn): self.callbacks.append(fn)
        def disconnect(self, fn): self.callbacks.remove(fn)
        def emit(self, val):
            for fn in list(self.callbacks): fn(val)
    class Worker:
        def __init__(self):
            self.event_received, self.result_ready, self.unexpected_error, self.finished = (Signal() for _ in range(4))
        def isRunning(self): return True
    media = tmp_path / 'a.mp4'; media.write_bytes(b'x')
    path = tmp_path / 'a.2byteproj'; path.write_text('{}')
    result_path = tmp_path / 'result.2byteproj'; result_path.write_text('{}')
    project = SimpleNamespace(project_id='p', media=SimpleNamespace(path=str(media)), cues=[])
    page = SimpleNamespace(project=project, session=SimpleNamespace(project_path=path),
                           undo_stack=SimpleNamespace(count=lambda: 0))
    worker = Worker()
    window = SimpleNamespace(_run_in_progress=False, worker=None, _active_job_id='')
    def start(*args, **kw):
        window.worker, window._active_job_id = worker, 'n'
        window.guard, window.done = kw['handoff_guard'], kw['handoff_done']
        window._studio_recognition_context = {'snapshot': {'project_id': 'p', 'project_revision': 'r'}}
    window._handle_studio_recognition_request, window._cancel_run = start, lambda: None
    result_project = SimpleNamespace(project_id='new', cues=[], generation_metadata={'timeline_recognition': {
        'source_project_id': 'p', 'source_project_path': str(path), 'source_project_revision': 'r', 'fingerprint': 'f'}})
    monkeypatch.setattr(rr, 'verify_result_reference', lambda *a, **kw: result_project)
    class Working(RecognitionOperations):
        def __init__(self):
            self.window, self.jobs, self.cancel_callbacks, self._closed = window, {}, {}, False
            self.bridge = SimpleNamespace(settings={'enabled': True, 'allow_edits': True})
        def require_project(self, *a): return page, project
        def snapshot(self, *a): return {'project_id': 'p', 'revision': 1}
        def new_job(self, kind, snapshot):
            job = {'job_id': 'j', 'status': 'running'}; self.jobs['j'] = job; return job
        def update_job(self, job, **kw): job.update(kw)
        def public_job(self, job): return job
        def fail_job(self, job, exc): job.update(status='failed', error=exc.code, error_message=str(exc))
        def finish_job(self, job, result, status='completed'): job.update(status=status, result=result)
    service = Working()
    job = service.op_start_recognition('p', 1)
    row = MediaResult(str(media), 'success', project_path=str(result_path), job_id='n',
        result_ref_json=json.dumps({'job_id': 'n', 'media_fingerprint': 'f'}))
    worker.result_ready.emit(QueueResult((row,), 1, job_id='n'))
    assert job['status'] == 'running' and job['result']['project_id'] == 'new'
    assert window.guard()
    window.done(True)
    assert job['status'] == 'completed' and not service.recognition_handoffs
    # A revoked task stays invalid even if the setting is later re-enabled.
    other = Working()
    window.worker = None
    job2 = other.op_start_recognition('p', 1)
    worker.result_ready.emit(QueueResult((row,), 1, job_id='n'))
    assert job2['status'] == 'running'
    other.recognition_handoffs['j']['valid'] = False
    other.bridge.settings['allow_edits'] = False
    other.bridge.settings['allow_edits'] = True
    assert window.guard() is False
    window.done(False)
    assert job2['status'] == 'failed' and job2['result']['project_id'] == 'new'
    assert not other.recognition_handoffs
    # Real native failed rows remain queryable with their actionable cause.
    third = Working()
    window.worker = None
    job3 = third.op_start_recognition('p', 1)
    failed = MediaResult(str(media), 'failed', job_id='n', error='缺少运行依赖：qwen-asr')
    worker.result_ready.emit(QueueResult((failed,), 1, job_id='n'))
    assert job3['status'] == 'failed' and job3['error'] == 'configuration_required'
    assert 'qwen-asr' in job3['error_message']

def test_handoff_guard_rejects_edit_during_async_load(tmp_path):
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
    from twobyteasr.recognition.recognition_input import project_content_revision
    project = SubtitleProject(media=StudioMedia(path='a.mp4'),
        cues=[StudioCue(id='a', start_ms=0, end_ms=1000, text='原文')])
    studio = SimpleNamespace(project=project, session=SimpleNamespace(project_path=tmp_path / 'source.2byteproj'),
        note_recognition_kept_in_memory=lambda: None)
    target = tmp_path / 'result.2byteproj'
    opened = []
    shell = SimpleNamespace(studio_page=studio, open_studio_project=lambda *a, **kw: opened.append(a),
        _studio_recognition_context={'snapshot': {'project_id': project.project_id,
        'project_revision': project_content_revision(project.to_dict())},
        'handoff_guard': lambda: True, 'handoff_done': lambda committed: None})
    MainWindow._finish_studio_recognition(shell, str(target))
    assert opened and studio._mcp_project_handoff[1]() is True
    project.cues[0].text = '人工修改'
    assert studio._mcp_project_handoff[1]() is False

@pytest.mark.parametrize(('enabled', 'project_ids', 'saved_ids', 'expected'), [
    (True, [], ['saved'], ['saved']),
    (False, [], ['saved'], []),
    (True, ['project'], ['saved'], ['project']),
    (False, ['project'], ['saved'], []),
])
def test_noninteractive_recognition_uses_project_or_saved_glossaries(enabled, project_ids, saved_ids, expected):
    from twobyteasr.app.ui import _noninteractive_recognition_options
    settings = {'glossary': {'enable_domain_terms': enabled, 'enabled_glossary_ids': saved_ids}}
    options = _noninteractive_recognition_options(SimpleNamespace(glossary_ids=project_ids), settings)
    assert options == {'enabled_glossary_ids': expected, 'enable_domain_terms': enabled}
    assert settings['glossary']['enabled_glossary_ids'] == saved_ids


def test_noninteractive_start_ignores_previous_page_options(tmp_path, monkeypatch):
    from twobyteasr.app.ui import MainWindow
    import twobyteasr.recognition.recognition_input as recognition_input
    media = tmp_path / 'a.mp4'; media.write_bytes(b'x')
    path = tmp_path / 'a.2byteproj'; path.write_text('{}')
    project = SimpleNamespace(project_id='p', glossary_ids=['current'], media=SimpleNamespace(path=str(media)))
    page = SimpleNamespace(project=project, undo_stack=SimpleNamespace(isClean=lambda: True),
        _canvas_editor=None, timeline=SimpleNamespace(_inline_editor=None), _recognition_range=[10, 20],
        recognition_request_options=lambda: pytest.fail('must not use stale page request'))
    combo = SimpleNamespace(findData=lambda _: -1)
    selected = []
    shell = SimpleNamespace(studio_page=page, legacy=SimpleNamespace(RUNTIME_SETTINGS={
        'glossary': {'enable_domain_terms': True, 'enabled_glossary_ids': ['global']}}),
        _ensure_recognition_page=lambda: None, recognition_mode_combo=combo,
        primary_asr_backend=None, firered_asr_backend=None, qwen_asr_backend=None,
        speaker_source=SimpleNamespace(currentData=lambda: 'native'),
        _refresh_media_summary=lambda: None, _run_in_progress=True)
    shell._set_backend_combo = lambda *args: selected.append(args)
    shell._start_run = lambda **kwargs: selected.append(kwargs)
    monkeypatch.setattr(recognition_input, 'capture_recognition_snapshot', lambda *args, **kwargs: {})
    MainWindow._handle_studio_recognition_request(shell, 'start_final', str(media), str(path), noninteractive=True)
    context = shell._studio_recognition_context
    assert context['enabled_glossary_ids'] == ['current'] and context['enable_domain_terms'] is True
    assert context['recognition_plan'] == 'home' and context['models'] == {}
    assert 'recognition_range_ms' not in context and page._recognition_range is None
    assert selected == [{'noninteractive': True}]

def test_interactive_start_keeps_explicit_page_request(tmp_path, monkeypatch):
    from twobyteasr.app.ui import MainWindow
    import twobyteasr.recognition.recognition_input as recognition_input
    media = tmp_path / 'a.mp4'; media.write_bytes(b'x')
    path = tmp_path / 'a.2byteproj'; path.write_text('{}')
    project = SimpleNamespace(project_id='p', media=SimpleNamespace(path=str(media)))
    calls = []
    page = SimpleNamespace(project=project, save=lambda: calls.append('save'),
        recognition_request_options=lambda: {'enabled_glossary_ids': ['chosen'], 'recognition_plan': 'home'})
    shell = SimpleNamespace(studio_page=page, _ensure_recognition_page=lambda: None,
        recognition_mode_combo=SimpleNamespace(findData=lambda _: -1), primary_asr_backend=None,
        firered_asr_backend=None, qwen_asr_backend=None, speaker_source=SimpleNamespace(currentData=lambda: 'native'),
        _refresh_media_summary=lambda: None, _run_in_progress=True, _start_run=lambda: calls.append('start'))
    monkeypatch.setattr(recognition_input, 'capture_recognition_snapshot', lambda *args, **kwargs: {})
    MainWindow._handle_studio_recognition_request(shell, 'start_final', str(media), str(path))
    assert shell._studio_recognition_context['enabled_glossary_ids'] == ['chosen']
    assert 'enable_domain_terms' not in shell._studio_recognition_context
    assert calls == ['save', 'start']

def test_saved_ai_preflight_is_local_and_validates_enabled_stages(monkeypatch):
    from twobyteasr.app.ui import _validate_saved_text_ai_configuration
    import twobyteasr.providers.asr_provider_snapshot as snapshots
    import twobyteasr.providers.llm_config as llm
    calls = []
    class Snapshot:
        transport = 'openai_compatible'
        def endpoint(self): return {'model': 'fixture'}
    monkeypatch.setattr(snapshots, 'resolve_provider_snapshot', lambda settings, stage: (calls.append(('resolve', stage)) or Snapshot()))
    monkeypatch.setattr(llm, 'validate_endpoint', lambda endpoint, label: calls.append(('validate', label)))
    _validate_saved_text_ai_configuration({'switches': {'enable_ai_polish': True, 'use_ai_grouping': True}})
    assert [kind for kind, _ in calls] == ['resolve', 'validate', 'resolve', 'validate']


def test_noninteractive_start_does_not_save_or_probe_configuration(monkeypatch):
    from twobyteasr.app import ui
    import twobyteasr.system.environment as environment
    class Button:
        def setEnabled(self, _): pass
    checked = []
    settings = {'models': {'primary_asr_backend': 'moss'}, 'switches': {}}
    shell = SimpleNamespace(_completion_retry_in_progress=False, _run_in_progress=False,
        _retry_run_options=None, _term_library_dialog=None, start_button=Button(), media_paths=['a.mp4'],
        primary_asr_backend=SimpleNamespace(currentData=lambda: 'moss'),
        legacy=SimpleNamespace(RUNTIME_SETTINGS=settings),
        _asr_values=lambda: settings['models'], _subtitle_language_options=lambda: {'recognition_language': 'auto'},
        _save_asr_configuration=lambda **kw: pytest.fail('must not save ASR settings'),
        _save_ai_configuration=lambda **kw: pytest.fail('must not save AI settings or probe provider'),
        _append_console_line=lambda *_: None, _confirm_run_limits=lambda **kw: False)
    shell._release_run_state = lambda: setattr(shell, '_run_in_progress', False)
    shell._studio_recognition_context = {'recognition_purpose': 'final'}
    monkeypatch.setattr(ui, 'missing_selected_local_models', lambda *_: ())
    monkeypatch.setattr(ui, '_language_preflight_values', lambda values, *_: values)
    monkeypatch.setattr(ui, 'persist_asr_configuration', lambda *args, **kw: checked.append(('asr', kw)))
    monkeypatch.setattr(ui, '_validate_saved_text_ai_configuration', lambda value: checked.append(('ai', value)))
    monkeypatch.setattr(environment, 'required_environment_roles', lambda *_: [])
    ui.MainWindow._start_run(shell, noninteractive=True)
    assert checked[0] == ('asr', {'require_ready': True, 'dry_run': True})
    assert checked[1] == ('ai', settings)
    assert shell._run_in_progress is False


def test_native_failure_keeps_real_error_and_classifies_without_secrets():
    from twobyteasr.local_mcp.production_recognition import _native_failure
    error = _native_failure('缺少运行依赖：qwen-asr 请执行 python -m pip install -r requirements-main.txt')
    assert error.code == 'configuration_required' and 'qwen-asr' in str(error)
    secret = 'sk-' + 'x' * 32
    error = _native_failure('401 unauthorized token=' + secret)
    assert error.code == 'authentication_failed' and secret not in str(error)

def test_asr_configuration_dry_run_validates_without_persisting():
    from twobyteasr.app.ui import persist_asr_configuration
    values = {'primary_asr_backend': 'moss', 'qwen_asr_backend': 'local', 'firered_asr_backend': 'local'}
    legacy = SimpleNamespace(RUNTIME_SETTINGS={'models': dict(values)},
        configure_runtime_asr=lambda *args, **kwargs: pytest.fail('must not persist'))
    result = persist_asr_configuration(legacy, values, require_ready=True, dry_run=True)
    assert result['models']['primary_asr_backend'] == 'moss'
    assert legacy.RUNTIME_SETTINGS == {'models': values}

@pytest.mark.parametrize('origin', ['lazy_create', 'open', 'recognition_handoff'])
def test_mcp_studio_show_never_runs_provider_probe(monkeypatch, origin):
    from twobyteasr.studio import studio_ui
    scheduled, refreshes, provider_calls = [], [], []
    owner = SimpleNamespace(_mcp_studio_probe_suppressed='job' if origin != 'recognition_handoff' else None)
    page = SimpleNamespace(window=lambda: owner,
        _mcp_project_handoff=('target', lambda: True, lambda *_: None) if origin == 'recognition_handoff' else None)
    def refresh(*, probe=True):
        refreshes.append(probe)
        if probe: provider_calls.append('validate')
    page._reload_ai_provider_selection = refresh
    monkeypatch.setattr(studio_ui.QTimer, 'singleShot', lambda delay, callback: scheduled.append(callback))
    studio_ui._queue_ai_provider_refresh(page)
    owner._mcp_studio_probe_suppressed = None
    page._mcp_project_handoff = None
    scheduled[0]()
    assert refreshes == [False] and provider_calls == []


def test_manual_studio_show_keeps_native_probe(monkeypatch):
    from twobyteasr.studio import studio_ui
    scheduled, refreshes = [], []
    page = SimpleNamespace(window=lambda: SimpleNamespace(),
        _reload_ai_provider_selection=lambda *, probe=True: refreshes.append(probe))
    monkeypatch.setattr(studio_ui.QTimer, 'singleShot', lambda delay, callback: scheduled.append(callback))
    studio_ui._queue_ai_provider_refresh(page)
    scheduled[0]()
    assert refreshes == [True]

def test_mcp_show_runs_real_provider_refresh_without_validate(monkeypatch):
    from twobyteasr.studio import studio_ui, studio_ai_flow
    queued, refresh = [], []
    class Combo:
        def blockSignals(self, *_): pass
        def setCurrentIndex(self, *_): pass
        def findData(self, *_): return 0
        def clear(self): pass
        def addItems(self, *_): pass
        def setCurrentText(self, *_): pass
    owner = SimpleNamespace(_mcp_studio_probe_suppressed='job', legacy=SimpleNamespace(RUNTIME_SETTINGS={}))
    page = SimpleNamespace(window=lambda: owner, runtime_settings={}, ai_model=Combo(), ai_provider=Combo(),
        _refresh_ai_design_provider_summary=lambda: refresh.append('rendered'),
        _start_ai_provider_probe=lambda *a, **kw: pytest.fail('unexpected network probe'))
    page._reload_ai_provider_selection = lambda *, probe=True: studio_ai_flow.StudioAIFlowMixin._reload_ai_provider_selection(page, probe=probe)
    monkeypatch.setattr(studio_ai_flow, 'active_service_values', lambda *a, **kw: {'service': 'fixture', 'model': 'fixture'})
    monkeypatch.setattr(studio_ai_flow, 'service_model_catalog', lambda *a, **kw: [])
    monkeypatch.setattr(studio_ui.QTimer, 'singleShot', lambda _, callback: queued.append(callback))
    studio_ui._queue_ai_provider_refresh(page)
    owner._mcp_studio_probe_suppressed = None
    queued[0]()
    assert refresh == ['rendered']

def test_fresh_disabled_ai_window_draft_diagnostic(monkeypatch):
    import copy
    from PySide6.QtWidgets import QApplication
    import subtitle_core as legacy
    from twobyteasr.app import ui
    from twobyteasr.providers.endpoint_editor_ui import EndpointEditor
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    app = QApplication.instance() or QApplication([])
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.setdefault('switches', {}).update(enable_ai_polish=False, use_ai_grouping=False, unified_glm_processing=False)
    settings.setdefault('models', {}).update(primary_asr_backend='moss', qwen_asr_backend='local', firered_asr_backend='local',
        polish_model='', group_model='', polish_base_url='', group_base_url='', ai_service='')
    monkeypatch.setattr(legacy, 'RUNTIME_SETTINGS', settings)
    monkeypatch.setattr(ui.MainWindow, '_background_preload', lambda self: None)
    monkeypatch.setattr(EndpointEditor, '_queue_model_discovery', lambda *_: None)
    monkeypatch.setattr(ui, 'installed_model_keys', lambda *_: {'moss', 'firered_vad', 'speaker_embedding', 'firered_aed', 'qwen_asr'})
    window = ui.MainWindow([], legacy, object(), None)
    try:
        assert window._asr_config_dirty is False
        assert window._ai_has_draft is True
        assert all(window._asr_values().get(k) == settings['models'].get(k) for k in ('primary_asr_backend','qwen_asr_backend','firered_asr_backend'))
        assert window.ai_polish.isChecked() is False and window.ai_grouping.isChecked() is False
    finally:
        window.close(); window.deleteLater(); app.processEvents()


@pytest.mark.parametrize(('asr_dirty', 'ai_draft', 'switches', 'message'), [
    (True, False, {'enable_ai_polish': False, 'use_ai_grouping': False}, '识别设置'),
    (False, True, {'enable_ai_polish': True, 'use_ai_grouping': False}, '文字 AI 设置'),
    (False, True, {'enable_ai_polish': False, 'use_ai_grouping': True}, '文字 AI 设置'),
])
def test_recognition_rejects_relevant_unsaved_settings(asr_dirty, ai_draft, switches, message):
    class Service(RecognitionOperations):
        def __init__(self):
            self.window = SimpleNamespace(_run_in_progress=False, _asr_config_dirty=asr_dirty,
                _ai_has_draft=ai_draft, legacy=SimpleNamespace(RUNTIME_SETTINGS={'switches': switches}))
        def require_project(self, *args): return SimpleNamespace(), SimpleNamespace()
    with pytest.raises(BridgeError) as exc:
        Service().op_start_recognition('p', 1)
    assert exc.value.code == 'configuration_required' and message in str(exc.value)
