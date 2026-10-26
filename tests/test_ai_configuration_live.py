"""Save through the real window: disk, live state and task must agree without restart."""
import copy
import json
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def settle(ms=250):
    from PySide6.QtWidgets import QApplication
    until = time.monotonic() + ms / 1000
    while time.monotonic() < until:
        QApplication.processEvents()
        time.sleep(0.005)


@pytest.fixture
def server():
    received = []
    entered = threading.Event()
    release = threading.Event()
    release.set()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            received.append(body['model'])
            entered.set()
            release.wait(10)
            result = {'choices': [{'message': {'role': 'assistant',
                       'content': json.dumps({'ok': True, 'text': '兔白字幕'}, ensure_ascii=False)},
                       'finish_reason': 'stop'}], 'usage': {'total_tokens': 12}}
            data = json.dumps(result, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{http.server_port}/v1', received, entered, release
    release.set()
    http.shutdown()
    thread.join(2)
    http.server_close()


@pytest.fixture
def window(monkeypatch):
    from PySide6.QtWidgets import QApplication
    import subtitle_core as core
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.providers.endpoint_editor_ui import EndpointEditor
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, save_runtime_settings

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(EndpointEditor, '_queue_model_discovery', lambda *_: None)
    settings, _, _ = save_runtime_settings(copy.deepcopy(DEFAULT_SETTINGS))
    monkeypatch.setattr(core, 'RUNTIME_SETTINGS', settings)
    w = MainWindow([], core, object(), None)
    w.show()
    for _ in range(8):
        app.processEvents()
    yield w
    dialog = getattr(w, '_ai_settings_dialog', None)
    if dialog is not None:
        dialog.reject()
        settle()
    w.close()
    w.deleteLater()
    app.processEvents()


def configure(w, model='live-model-a', key='sk-isolated-live-test-a'):
    w.ai_polish.setChecked(True)
    w.ai_grouping.setChecked(True)
    w.unified_glm.setChecked(True)
    editor = w.group_editor
    editor.service.setCurrentIndex(editor.service.findData('custom'))
    editor.base_url.setText('http://127.0.0.1:19247/v1')
    editor.model.setCurrentText(model)
    editor.key.setText(key)
    return editor


def test_save_applies_disk_home_and_next_task_without_restart(window):
    from twobyteasr.providers import ai_connection_record as record
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.storage.settings import load_runtime_settings
    w = window
    w._open_ai_settings_dialog()
    editor = configure(w)
    # Isolate persistence from network: this result represents this exact draft.
    editor._connection_finished(True, 'fixture response')
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    live = w.legacy.RUNTIME_SETTINGS
    disk = load_runtime_settings()[0]
    assert live == disk
    assert GLOBAL_PROVIDER_REGISTRY.settings() is live
    assert w.polish_editor.model.currentText() == 'live-model-a'
    assert record.feature_gate(live) == record.READY
    assert w.setting_tiles['ai'].view.state == record.READY
    assert w.terms.isEnabled()
    task = w._run_settings_snapshot()
    assert task['switches']['use_ai_grouping']
    assert resolve_provider_snapshot(task).model == 'live-model-a'
    assert resolve_provider_snapshot(task).endpoint()['api_key'] == 'sk-isolated-live-test-a'


def test_old_client_keeps_credential_after_save(window):
    from twobyteasr.providers.ai_providers import provider_for_stage
    from twobyteasr.providers.llm_config import endpoint_from_settings
    w = window
    configure(w)
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    client = provider_for_stage(w._run_settings_snapshot(), 'group')
    configure(w, key='sk-isolated-live-test-b')
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    assert endpoint_from_settings(client._settings, 'group')['api_key'] == 'sk-isolated-live-test-a'


def test_cancel_drops_connection_result_for_unsaved_model(window):
    w = window
    configure(w)
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    w._open_ai_settings_dialog()
    configure(w, model='live-model-b')
    w.group_editor._connection_finished(True, 'fixture response')
    w._ai_settings_dialog.reject()
    settle()
    assert w.group_editor.model.currentText() == 'live-model-a'
    assert w.group_editor.last_connection_ok is None


@pytest.mark.parametrize('initially_enabled', [True, False])
def test_dialog_button_save_then_return_and_second_save(window, initially_enabled):
    from twobyteasr.providers import ai_connection_record as record
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    w = window
    w.ai_polish.setChecked(initially_enabled)
    w.ai_grouping.setChecked(initially_enabled)
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    for model in ('button-model-a', 'button-model-b'):
        w._open_ai_settings_dialog()
        editor = configure(w, model=model)
        editor._connection_finished(True, 'fixture response')
        w.ai_dialog_save_button.click()
        settle()
        assert w._ai_settings_dialog is None
        w._return_to_settings()
        assert w.setting_tiles['ai'].view.state == record.READY
        assert resolve_provider_snapshot(w._run_settings_snapshot()).model == model


def test_real_connection_worker_then_save(window, server):
    from twobyteasr.providers import ai_connection_record as record
    w = window
    w._open_ai_settings_dialog()
    editor = configure(w)
    editor.base_url.setText(server[0])
    editor.test_connection()
    worker = editor._tester
    deadline = time.monotonic() + 10
    while worker.isRunning() and time.monotonic() < deadline:
        settle(25)
    settle(50)
    assert editor.last_connection_ok is True, (editor.status.text(), server[1], worker.isRunning())
    w.ai_dialog_save_button.click()
    settle()
    assert w._ai_settings_dialog is None
    assert server[1] == ['live-model-a']
    assert w.setting_tiles['ai'].view.state == record.READY


def test_group_only_configuration_drives_home_card(window):
    from twobyteasr.providers import ai_connection_record as record
    w = window
    configure(w)
    w.ai_polish.setChecked(False)
    w.group_editor._connection_finished(True, 'fixture response')
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    assert w.setting_tiles['ai'].view.state == record.READY
    assert 'live-model-a' in w.setting_tiles['ai'].title_label.text()


def test_background_test_is_for_its_original_credential(window):
    from twobyteasr.providers.endpoint_editor_ui import ProviderConnectionTester
    from twobyteasr.providers.llm_config import endpoint_from_settings, save_api_key_for
    w = window
    configure(w)
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    editor = w.group_editor
    tester = ProviderConnectionTester(editor._provider_settings(), 'group', prompt_test=True)
    save_api_key_for('custom', editor.base_url.text(), 'sk-isolated-changed-externally')
    assert endpoint_from_settings(tester.settings, 'group')['api_key'] == 'sk-isolated-live-test-a'


def test_new_runtime_is_rebound_before_clearing_saved_fields(window):
    w = window
    configure(w)
    seen = []
    w.group_editor.key.textChanged.connect(
        lambda _: seen.append(w.group_editor._settings_ref is w.legacy.RUNTIME_SETTINGS))
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    assert all(seen)


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        settle(20)
    assert predicate()


def test_save_during_test_keeps_exact_test_and_finishes_without_restart(window, server):
    w = window
    w._open_ai_settings_dialog()
    editor = configure(w)
    editor.base_url.setText(server[0])
    server[3].clear()
    editor.test_connection()
    wait_until(server[2].is_set)
    worker = editor._tester
    w.ai_dialog_save_button.click()
    settle()
    assert editor._tester is worker
    assert w.setting_tiles['ai'].view.state == 'testing'
    server[3].set()
    wait_until(lambda: not worker.isRunning())
    settle(50)
    assert w.setting_tiles['ai'].view.state == 'ready'
    assert editor.last_connection_ok is True


def test_old_test_cannot_mark_a_new_model_ready(window, server):
    from twobyteasr.providers import ai_connection_record as record
    w = window
    w._open_ai_settings_dialog()
    editor = configure(w)
    editor.base_url.setText(server[0])
    server[3].clear()
    editor.test_connection()
    wait_until(server[2].is_set)
    worker = editor._tester
    editor.model.setCurrentText('new-untested-model')
    w.ai_dialog_save_button.click()
    settle()
    server[3].set()
    wait_until(lambda: not worker.isRunning())
    settle(50)
    assert record.result_for(w.legacy.RUNTIME_SETTINGS, 'group') is None
    assert w.setting_tiles['ai'].view.state == 'untested'


def test_switches_repeat_save_cancel_and_task_snapshot(window):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    w = window
    configure(w)
    w.group_editor._connection_finished(True, 'fixture response')
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    old = resolve_provider_snapshot(w._run_settings_snapshot())
    for enabled in (False, True, True):
        w.ai_polish.setChecked(enabled)
        w.ai_grouping.setChecked(enabled)
        assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
        assert w._run_settings_snapshot()['switches']['use_ai_grouping'] is enabled
        assert w.terms.isEnabled()  # Local glossary matching is independent of text-AI switches.
    configure(w, model='next-model', key='sk-next-task')
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    new = resolve_provider_snapshot(w._run_settings_snapshot())
    assert old.model == 'live-model-a'
    assert old.endpoint()['api_key'] == 'sk-isolated-live-test-a'
    assert new.model == 'next-model'
    assert new.endpoint()['api_key'] == 'sk-next-task'


def test_replacing_service_does_not_enable_user_disabled_ai(window):
    w = window
    configure(w)
    w.ai_polish.setChecked(False)
    w.ai_grouping.setChecked(False)
    w.group_editor.model.setCurrentText('disabled-new-model')
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    assert not w._run_settings_snapshot()['switches']['use_ai_grouping']
    assert not w._run_settings_snapshot()['switches']['enable_ai_polish']


def test_secret_write_failure_is_not_reported_as_success(window, monkeypatch):
    from twobyteasr.app import ui
    w = window
    configure(w)
    before = copy.deepcopy(w.legacy.RUNTIME_SETTINGS)
    def fail(*_):
        raise OSError('fixture credential store unavailable')
    monkeypatch.setattr(ui, 'save_api_key_for', fail)
    assert not w._save_ai_configuration(show_feedback=False)
    assert w.legacy.RUNTIME_SETTINGS == before
    assert w.group_editor.key.text()


def test_request_and_configuration_evidence_do_not_expose_credentials(window):
    from twobyteasr.providers.ai_config_state import configuration_state
    from twobyteasr.providers.request_snapshot import freeze_request_settings
    w = window
    editor = configure(w)
    frozen = freeze_request_settings(editor._provider_settings(), 'group')
    assert 'sk-isolated-live-test-a' not in repr(frozen)
    state = configuration_state(frozen)
    assert 'sk-isolated-live-test-a' not in json.dumps(state)
    assert 'api_key' not in json.dumps(state)
    assert state['stages']['group']['source'] == 'models.group_*'


def test_selecting_a_preconfigured_service_unlocks_switch_without_retyping_key(window):
    from twobyteasr.providers.llm_config import save_api_key_for
    w = window
    w._sync_ai_switches_with_keys()
    save_api_key_for('deepseek', 'https://api.deepseek.com/v1', 'sk-preconfigured-fixture')
    w.group_editor.service.setCurrentIndex(w.group_editor.service.findData('deepseek'))
    assert w.ai_grouping.is_shown_on()


def test_clear_saved_key_invalidates_pending_connection_without_text_change(window):
    from twobyteasr.providers.endpoint_editor_ui import ProviderConnectionTester
    w = window
    editor = configure(w)
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    assert not editor.key.text()
    worker = ProviderConnectionTester(editor._provider_settings(), 'group', prompt_test=True)
    editor._tester = worker
    edited = []
    editor.configuration_edited.connect(lambda: edited.append(True))
    callback = editor._endpoint_callback(worker, '_tester', editor._connection_finished)
    editor._request_key_clear()
    callback(True, 'obsolete fixture result')
    assert editor.last_connection_ok is None
    assert editor._tester is None
    assert edited == [True]


def test_home_enable_intent_is_saved_but_cancel_and_settings_keep_off(window):
    from twobyteasr.providers import ai_connection_record as record
    w=window;configure(w);w.group_editor._connection_finished(True,'fixture response')
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    w.ai_polish.setChecked(False);w.ai_grouping.setChecked(False)
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    assert w.setting_tiles['ai'].view.configured
    assert '已配置' in w.setting_tiles['ai'].state_chip.text()
    w._open_ai_settings_dialog();assert not w.ai_grouping.isChecked()
    w._ai_settings_dialog.reject();settle()
    w.setting_tiles['ai'].connect_button.click();settle()
    assert w.ai_grouping.isChecked()
    w._ai_settings_dialog.reject();settle()
    assert not w.ai_grouping.isChecked()
    w.setting_tiles['ai'].connect_button.click();settle()
    w.ai_dialog_save_button.click();settle()
    assert w._run_settings_snapshot()['switches']['use_ai_grouping']
    assert not w._run_settings_snapshot()['switches']['enable_ai_polish']
    assert w.setting_tiles['ai'].view.state==record.READY
    w._open_ai_settings_dialog();w.group_editor.last_connection_ok=None
    w._refresh_ai_dialog_state()
    assert '已连接' in w.ai_dialog_state_label.text()


def test_local_glossary_and_translation_have_independent_dependencies(window,monkeypatch):
    from twobyteasr.providers.ai_connection_record import service_gate,feature_gate,READY,OFF
    from twobyteasr.app.ui import _ai_unlocked
    w=window
    # No service is necessary for confirmed local terms or a content name.
    w.legacy.RUNTIME_SETTINGS['glossary']['enable_domain_terms']=True
    w._refresh_home_process_facts()
    assert w.terms.isEnabled() and w.terms.isChecked()
    monkeypatch.setattr(w,'_enabled_glossary_ids',lambda:['fixture-terms'])
    assert w._task_glossary_selection()==(('fixture-terms',),True)
    configure(w);w.group_editor._connection_finished(True,'fixture response')
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    w.ai_grouping.setChecked(False);w.ai_polish.setChecked(False)
    assert w._save_ai_configuration(show_feedback=False), getattr(w, "_run_block_reason", "save returned false")
    assert feature_gate(w.legacy.RUNTIME_SETTINGS)==OFF
    assert service_gate(w.legacy.RUNTIME_SETTINGS)==READY
    assert _ai_unlocked(w)
    assert w.terms.isEnabled() and not w.content_frost.isVisible()


def test_old_partial_settings_keep_explicit_grouping_choice(tmp_path):
    from twobyteasr.storage.settings import project_settings_path,load_runtime_settings,save_runtime_settings
    for enabled in (False,True):
        old={'models':{'ai_service':'deepseek','group_model':'deepseek-chat'},'switches':{'use_ai_grouping':enabled}}
        path=project_settings_path(tmp_path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(old),'utf8')
        loaded,_,_=load_runtime_settings(tmp_path)
        assert loaded['switches']['use_ai_grouping'] is enabled
        save_runtime_settings(loaded,tmp_path)
        again,_,_=load_runtime_settings(tmp_path)
        assert again['switches']['use_ai_grouping'] is enabled
        assert again['models']['group_model']=='deepseek-chat'
