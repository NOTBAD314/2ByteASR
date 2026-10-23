"""D03: saved recognition profiles own the complete non-secret endpoint."""
import copy
import json
import os
from types import SimpleNamespace, MethodType
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel
import subtitle_core as legacy
from twobyteasr.app import ui
from twobyteasr.providers import endpoint_editor_ui
from twobyteasr.providers import llm_config
from twobyteasr.recognition.recognition_profiles import ProjectProfile, ProjectProfileStore
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot

APP = QApplication.instance() or QApplication([])

def config(service="deepseek", base="https://api.deepseek.com", model="deepseek-chat", unified=True, grouping=True):
    spec = llm_config.AI_SERVICE_SPECS[service]
    endpoint = dict(service=service, provider=spec["provider"], transport=spec["transport"],
                    base_url=base, model=model, protocol="openai_compatible_chat", key="secret-must-not-persist")
    return dict(polish=copy.deepcopy(endpoint), group=endpoint, unified=unified, use_ai_grouping=grouping)

class Host:
    def __getattr__(self, name):
        method = getattr(ui.MainWindow, name)
        return MethodType(method, self)

@pytest.fixture
def host(monkeypatch, tmp_path):
    # A profile save exercises production persistence; redirect it before any
    # test can reach the author's real AppData or provider secret store.
    from twobyteasr.storage.settings import save_runtime_settings
    monkeypatch.setattr(legacy, 'save_runtime_settings', lambda values: save_runtime_settings(values, project_root=tmp_path))
    monkeypatch.setattr(legacy, 'save_api_keys', lambda **kwargs: None)
    monkeypatch.setattr(ui, 'save_api_key_for', lambda *args: None)
    monkeypatch.setattr(ui, "read_api_key", lambda *a: ("", "test"))
    monkeypatch.setattr(ui, "resolve_api_key", lambda *a: ("", "test"))
    monkeypatch.setattr(endpoint_editor_ui, "read_api_key", lambda *a: ("", "test"))
    monkeypatch.setattr(endpoint_editor_ui, "resolve_api_key", lambda *a: ("", "test"))
    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a: ("", "test"))
    monkeypatch.setattr(ui.EndpointEditor, "_queue_model_discovery", lambda *a: None)
    monkeypatch.setattr(legacy, "RUNTIME_SETTINGS", copy.deepcopy(legacy.RUNTIME_SETTINGS))
    h = Host()
    h.legacy = legacy
    h.worker = None
    h._applying_profile = True
    h._asr_config_dirty = False
    h.profile_store = ProjectProfileStore(tmp_path / "profiles.json")
    h.current_project_profile = None
    h.polish_editor = ui.EndpointEditor("polish", "#345678", "polish", legacy.RUNTIME_SETTINGS)
    h.group_editor = ui.EndpointEditor("group", "#345678", "group", legacy.RUNTIME_SETTINGS)
    h.ai_polish, h.ai_grouping, h.unified_glm, h.share_key = QCheckBox(), QCheckBox(), QCheckBox(), QCheckBox()
    h.ai_save_status, h.profile_recommendation = QLabel(), QLabel()
    h.ai_panel = SimpleNamespace(set_expanded=lambda *a: None)
    h._refresh_ai_summary = lambda: None
    h._apply_profile_asr_config = lambda *a, **k: None
    h._set_backend_combo = lambda *a: None
    h._asr_values = lambda: {}
    h._enabled_glossary_ids = lambda: []
    for name in ("recognition_mode_combo", "primary_asr_backend", "firered_asr_backend", "qwen_asr_backend"):
        # 2026-10-23: the plan menu adds / removes 自定义 itself (MainWindow._show_plan_choice).
        setattr(h, name, SimpleNamespace(currentData=lambda: "custom", findData=lambda v: -1,
                                         blockSignals=lambda *_: False, addItem=lambda *_: None,
                                         removeItem=lambda *_: None, setCurrentIndex=lambda *_: None))
    yield h
    h.polish_editor.deleteLater(); h.group_editor.deleteLater()

def profile(values):
    return ProjectProfile.from_dict(dict(id="p", name="P", llm_enabled=values["use_ai_grouping"],
                                         llm_config_ref=values["group"]["model"], llm_config=values))

def test_failed_endpoint_save_does_not_mutate_nested_runtime(host, monkeypatch):
    host._apply_profile_llm_config(config())
    before = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    monkeypatch.setattr(legacy, 'configure_runtime_llms', lambda *a, **k: (_ for _ in ()).throw(PermissionError('locked')))
    with pytest.raises(PermissionError):
        host._apply_profile_llm_config(config(base='https://new.example/v1'))
    assert legacy.RUNTIME_SETTINGS == before

def test_failed_profile_switch_preserves_active_identity_and_controls(host, monkeypatch):
    host._apply_profile_llm_config(config())
    a = profile(config()); a.id = 'a'
    host.current_project_profile = a
    host._refresh_project_profile_combo = lambda *a: None
    before = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    values = host._llm_profile_configuration()
    monkeypatch.setattr(ui, 'save_runtime_settings', lambda *a, **k: (_ for _ in ()).throw(PermissionError('locked')))
    monkeypatch.setattr(legacy, 'save_runtime_settings', ui.save_runtime_settings)
    assert host._apply_project_profile(profile(config(service='gemini', model='gemini-2.5-flash')), mark_used=False) is False
    assert host.current_project_profile is a
    assert legacy.RUNTIME_SETTINGS == before
    assert host._llm_profile_configuration() == values

def test_failed_home_restore_does_not_publish_another_identity(host):
    host.profile_store.create('A')
    host._home_profile_selection=None
    host._asr_config_dirty=True
    host._apply_project_profile=lambda *a,**kw:False
    updates=[]
    host._refresh_project_profile_combo=lambda value:updates.append(value)
    host._restore_global_recognition_plan_for_home()
    assert updates==[] and host._asr_config_dirty

@pytest.mark.parametrize('kind', ['detect', 'login', 'connection'])
def test_old_cli_callbacks_cannot_touch_restored_profile(host, monkeypatch, kind):
    from PySide6.QtCore import QObject, Signal
    class Worker(QObject):
        finished_status = Signal(bool, str)
        login_progress = Signal(str)
        models = ('old-provider-model',)
        def __init__(self, *a, **k): super().__init__()
        def start(self): pass
        def isRunning(self): return True
        def requestInterruption(self): pass
    monkeypatch.setattr(endpoint_editor_ui, 'ProviderConnectionTester', Worker)
    monkeypatch.setattr(endpoint_editor_ui, 'ProviderLoginWorker', Worker)
    editor = host.polish_editor
    editor.restore_profile_values(config(service='grok_account', model='')['polish'], legacy.RUNTIME_SETTINGS)
    if kind == 'login': editor.start_login(); worker = editor._login_worker
    elif kind == 'detect': editor.detect_cli(); worker = editor._tester
    else: editor.test_connection(); worker = editor._tester
    editor.restore_profile_values(config(service='codex_cli', model='')['polish'], legacy.RUNTIME_SETTINGS)
    editor.discover_models = lambda **k: pytest.fail('stale login started discovery')
    before = (editor.model.currentText(), editor.status.text(), editor.account_status.text())
    worker.login_progress.emit('stale login')
    worker.finished_status.emit(True, 'stale success')
    assert (editor.model.currentText(), editor.status.text(), editor.account_status.text()) == before

def test_store_keeps_nonsecret_snapshot_and_independent_save_as(tmp_path):
    store = ProjectProfileStore(tmp_path / "profiles.json")
    original = profile(config())
    from dataclasses import asdict
    payload = asdict(original); payload.pop("id"); payload.pop("name")
    a = store.create("A", **payload)
    b = store.save_as(a.id, "B")
    reloaded = ProjectProfileStore(store.path).get(a.id)
    assert reloaded.llm_config["polish"]["service"] == "deepseek"
    b.llm_config["group"]["base_url"] = "https://changed.example"
    assert store.get(a.id).llm_config["group"]["base_url"] == "https://api.deepseek.com"
    assert "secret-must-not-persist" not in store.path.read_text(encoding="utf8")

@pytest.mark.parametrize("unified,grouping", [(True, True), (False, True), (False, False)])
def test_switch_restores_ui_and_actual_task_identity(host, unified, grouping):
    a = config(unified=unified, grouping=grouping)
    b = config("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-custom", unified, grouping)
    for values in (a, b, a):
        host._apply_profile_controls(profile(values))
        endpoint = host.polish_editor.values()
        assert (endpoint["service"], endpoint["base_url"], endpoint["model"]) == tuple(values["polish"][k] for k in ("service", "base_url", "model"))
        assert host.polish_editor._settings_ref is legacy.RUNTIME_SETTINGS
        snapshot = resolve_provider_snapshot(legacy.RUNTIME_SETTINGS)
        assert (snapshot.profile_id, snapshot.model, snapshot.endpoint()["base_url"]) == (endpoint["service"], endpoint["model"], endpoint["base_url"])
        captured = host._profile_configuration()["llm_config"]
        assert captured["unified"] == unified
        assert captured["use_ai_grouping"] == grouping
        assert "key" not in captured["polish"]

def test_same_provider_same_model_different_endpoint_survives_restart(host):
    for label, url in [("A", "https://first.example/v1"), ("B", "https://second.example/v1")]:
        host._apply_profile_controls(profile(config("custom", url, "shared-model")))
        host.profile_store.create(label, **host._profile_configuration())
    for p in ProjectProfileStore(host.profile_store.path).list():
        host._apply_profile_controls(p)
        assert resolve_provider_snapshot(legacy.RUNTIME_SETTINGS).endpoint()["base_url"] == p.llm_config["polish"]["base_url"]

def test_legacy_model_only_bookmark_does_not_change_provider_model(host):
    host.group_editor.model.addItem("old-other-provider")
    host.group_editor.model.setCurrentText("current-model")
    host._apply_profile_controls(ProjectProfile(id="old", name="old", llm_config_ref="old-other-provider"))
    assert host.group_editor.model.currentText() == "current-model"

def test_endpoint_changes_mark_profile_dirty(host):
    host._applying_profile = False
    host._mark_ai_configuration_dirty()
    assert host._asr_config_dirty

def test_profile_restore_invalidates_pending_discovery(host):
    worker = SimpleNamespace(isRunning=lambda: True, requestInterruption=lambda: setattr(worker, "cancelled", True), cancelled=False)
    host.group_editor._model_discovery_worker = worker
    host._apply_profile_controls(profile(config()))
    assert worker.cancelled
    host.group_editor._model_discovery_worker = None
