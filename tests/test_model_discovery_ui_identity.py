import copy,json
from PySide6.QtCore import QObject,Signal
from PySide6.QtWidgets import QApplication
from twobyteasr.app.ui import EndpointEditor
from twobyteasr.providers.llm_config import activate_ai_service,update_active_profile,endpoint_from_settings
from twobyteasr.storage.settings import DEFAULT_SETTINGS,save_runtime_settings,_merge_known_settings


def test_finished_edit_not_key_characters_and_late_reply_is_discarded(monkeypatch):
    app=QApplication.instance() or QApplication([]);workers=[]
    class Worker(QObject):
        succeeded=Signal(list);failed=Signal(str);finished=Signal()
        def __init__(self,settings,stage,**kw):
            super().__init__(kw['parent']);self.settings=settings;self.running=False;self.cancelled=False;workers.append(self)
        def isRunning(self):return self.running
        def isInterruptionRequested(self):return self.cancelled
        def requestInterruption(self):self.cancelled=True
        def start(self):self.running=True
        def finish(self):self.running=False;self.finished.emit()
    monkeypatch.setattr('twobyteasr.providers.endpoint_editor_ui.ProviderModelDiscoveryWorker',Worker)
    monkeypatch.setattr('twobyteasr.providers.endpoint_editor_ui.read_api_key',lambda *a:('','missing'))
    settings=copy.deepcopy(DEFAULT_SETTINGS);activate_ai_service(settings,'custom')
    editor=EndpointEditor('AI','#123456','polish',settings)
    editor.base_url.setText('https://first.example/root');editor.key.setText('first-key')
    editor.model.setCurrentText('manually/selected-alias')
    assert not editor._model_discovery_timer.isActive() and not workers
    editor.key.editingFinished.emit();assert editor._model_discovery_timer.isActive()
    editor._model_discovery_timer.stop();editor.discover_models()
    first=workers[-1]
    assert endpoint_from_settings(first.settings,'polish')['api_key']=='first-key'
    editor.key.setText('second-key');editor.base_url.setText('https://second.example/v1')
    first.succeeded.emit(['old-account-model']);assert editor.model.findText('old-account-model')<0
    editor.key.editingFinished.emit();editor._model_discovery_timer.stop();editor.discover_models()
    assert editor._discovery_pending
    first.finish();editor._model_discovery_timer.stop();editor.discover_models()
    second=workers[-1];second.succeeded.emit(['new/prefix-alias'])
    assert editor.model.findText('new/prefix-alias')>=0
    assert editor.model.currentText()=='manually/selected-alias' and '不在最新列表' in editor.status.text()
    second.finish();editor.close();editor.deleteLater();app.processEvents()


def test_selected_discovered_id_survives_settings_reload_registry_and_wire(tmp_path,monkeypatch):
    from twobyteasr.providers.provider_registry import ProviderRegistry
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider,CLIProvider
    from twobyteasr.providers import llm_config
    settings=copy.deepcopy(DEFAULT_SETTINGS);activate_ai_service(settings,'custom')
    model='namespace/new-model:latest'
    update_active_profile(settings,model=model,base_url='https://relay.example/api/v1')
    save_runtime_settings(settings,tmp_path)
    loaded,_=_merge_known_settings(DEFAULT_SETTINGS,json.loads((tmp_path/'2byteasr_settings.json').read_text('utf8')))
    monkeypatch.setattr(llm_config,'read_api_key',lambda *a,**kw:('test-key','test'))
    endpoint=endpoint_from_settings(loaded,'polish');assert endpoint['model']==model
    assert ProviderRegistry().selection(loaded,stage='polish').model==model
    calls=[]
    provider=OpenAICompatibleProvider(endpoint,sender=lambda *a,**kw:calls.append(kw) or '{}')
    provider.complete([dict(role='user',content='JSON')]);assert calls[0]['model']==model
    assert CLIProvider._parse_models('Available models:\n * grok-4.7 (default)\n - custom/grok:latest')==('grok-4.7','custom/grok:latest')
