"""Current cloud Qwen policy, exact migration and credential ownership."""
import copy
from types import SimpleNamespace
import pytest
from twobyteasr.settings import DEFAULT_SETTINGS, _merge_known_settings
from twobyteasr import llm_config

LATEST = "qwen-audio-3.1-asr-flash-filetrans"
PATH = "/api/v1/services/audio/asr/transcription"
OLD_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
HOST = "https://fixture-workspace.cn-beijing.maas.aliyuncs.com"

@pytest.mark.parametrize("primary,review", [("moss", "local"), ("api", "api")])
def test_exact_legacy_short_migration_keeps_roles_workspace_oss_and_is_idempotent(primary,review):
    old = {"models": dict(primary_asr_backend=primary, qwen_asr_backend=review,
        qwen_asr_model="Qwen/Qwen3-ASR-1.7B", firered_asr_backend="qwen_aligner",
        qwen_asr_api_provider="dashscope", qwen_asr_api_protocol="dashscope_multimodal",
        qwen_asr_api_model="qwen3-asr-flash", qwen_asr_api_url=HOST+OLD_PATH,
        oss_bucket="owned-fixture", oss_prefix="only-owned/", speaker_source="moss")}
    original=copy.deepcopy(old)
    result,warnings=_merge_known_settings(DEFAULT_SETTINGS,old)
    again,second=_merge_known_settings(DEFAULT_SETTINGS,result)
    assert old==original and result==again
    models=result["models"]
    assert (models["qwen_asr_api_provider"], models["qwen_asr_api_protocol"], models["qwen_asr_api_model"]) == ("qwen31_filetrans", "dashscope_filetrans", LATEST)
    assert models["qwen_asr_api_url"]==HOST+PATH
    for key in ("primary_asr_backend","qwen_asr_backend","qwen_asr_model","firered_asr_backend","oss_bucket","oss_prefix","speaker_source"):
        assert models[key]==original["models"][key]
    assert any("cloud ASR dashscope migrated" in w for w in warnings)
    assert not any("cloud ASR dashscope migrated" in w for w in second)

@pytest.mark.parametrize("provider,model",[("dashscope","unrelated-deployment"),("custom","qwen3-asr-flash"),("openai","gpt-4o-transcribe"),("dashscope","qwen3-asr-flash-filetrans")])
def test_migration_never_renames_other_provider_or_other_model(provider,model):
    old={"models":dict(qwen_asr_api_provider=provider,qwen_asr_api_model=model,
       qwen_asr_api_protocol="openai_transcription",qwen_asr_api_url="https://fixture.invalid/custom")}
    result,_=_merge_known_settings(DEFAULT_SETTINGS,old)
    assert all(result["models"][k]==v for k,v in old["models"].items())

def test_workspace_key_remains_in_existing_provider_host_scope_without_writes(monkeypatch):
    secret_id=llm_config._provider_key_id("dashscope",HOST+OLD_PATH)
    payload={secret_id:"fixture-secret", "API__openai__other.invalid":"other-secret"}
    original=copy.deepcopy(payload)
    monkeypatch.setattr(llm_config,"_read_secrets",lambda:copy.deepcopy(payload))
    monkeypatch.setattr(llm_config,"_write_encrypted_secrets",lambda *a:pytest.fail("migration must never write credentials"))
    for name in set(llm_config.STAGE_SECRET_NAMES["qwen_asr"]) | set(llm_config._STANDARD_PROVIDER_KEY_ENV.values()) | {"POLISH_LLM_API_KEY", "GROUP_LLM_API_KEY"}:
        monkeypatch.delenv(name,raising=False)
    value,_=llm_config.read_asr_api_key("qwen31_filetrans",HOST+PATH)
    assert value=="fixture-secret" and payload==original
    assert not bool(llm_config.read_asr_api_key("qwen31_filetrans","https://other.invalid"+PATH)[0])
    assert not bool(llm_config.read_asr_api_key("openai",HOST+PATH)[0])
    assert llm_config._provider_key_id("dashscope",HOST+OLD_PATH)==llm_config._provider_key_id("dashscope",HOST+PATH)

def test_factory_endpoint_and_catalog_only_offer_latest_cloud_qwen(monkeypatch):
    from twobyteasr.ui import ASR_API_PRESETS
    from twobyteasr.model_workshop import MODELS,CANONICAL_MODEL_ORDER
    calls=[]
    monkeypatch.setattr(llm_config,"read_asr_api_key",lambda p,u:(calls.append((p,u)) or ("fixture-key","fixture")))
    endpoint=llm_config.qwen_asr_endpoint_from_settings({})
    llm_config.validate_qwen_asr_endpoint(endpoint)
    assert endpoint["model"]==LATEST and endpoint["protocol"]=="dashscope_filetrans"
    assert calls==[("qwen31_filetrans",endpoint["url"])]
    assert "dashscope" not in ASR_API_PRESETS and "qwen_api" not in CANONICAL_MODEL_ORDER
    cloud=[m for m in MODELS if m.api_preset and str(ASR_API_PRESETS[m.api_preset]["model"]).startswith("qwen")]
    # Two entries, one model family: Qwen Cloud (official international API)
    # and 百炼, both on the latest Filetrans model.
    assert [m.key for m in cloud]==["qwen_cloud_filetrans","qwen31_filetrans"]
    assert {ASR_API_PRESETS[m.api_preset]["model"] for m in cloud}=={LATEST}
    assert {"qwen_local","qwen_aligner"}<={m.key for m in MODELS}
    from twobyteasr.model_benchmarks import reference_api_model
    assert reference_api_model(LATEST,"accuracy","zh") is None

@pytest.mark.parametrize("model",["qwen3-asr-flash","qwen3-asr-flash-legacy-date","qwen-audio-3.0-asr-flash","qwen-audio-3.1-asr-flash"])
def test_old_short_model_cannot_be_reintroduced_through_custom_provider(model):
    with pytest.raises(RuntimeError,match="Filetrans|长音频"):
        llm_config.validate_qwen_asr_endpoint(dict(provider="custom",protocol="openai_transcription",model=model,url="https://fixture.invalid/asr",api_key="fixture"))

def test_saved_unrelated_deployment_protocol_can_be_retained_without_preset(monkeypatch):
    from twobyteasr.ui import persist_asr_configuration
    old=dict(primary_asr_backend="api",qwen_asr_backend="off",firered_asr_backend="off",
      qwen_asr_api_provider="dashscope",qwen_asr_api_protocol="dashscope_multimodal",
      qwen_asr_api_model="unrelated-deployment",qwen_asr_api_url="https://fixture.invalid/asr")
    received=[]
    legacy=SimpleNamespace(RUNTIME_SETTINGS={"models":copy.deepcopy(old)},configure_runtime_asr=lambda values,**kw:received.append(values))
    monkeypatch.setattr(llm_config,"read_asr_api_key",lambda *a:("fixture", "fixture"))
    result=persist_asr_configuration(legacy,old,require_ready=True)
    assert result["models"]["qwen_asr_api_provider"]=="dashscope"
    assert result["models"]["qwen_asr_api_protocol"]=="dashscope_multimodal"
    assert result["models"]["qwen_asr_api_model"]=="unrelated-deployment"
    assert received


@pytest.mark.parametrize("persist",[True,False])
@pytest.mark.parametrize("with_url",[True,False])
def test_old_profile_uses_settings_migration_before_refilling_qt_controls(monkeypatch,persist,with_url):
    from PySide6.QtWidgets import QApplication,QComboBox,QLineEdit
    from twobyteasr.ui import MainWindow,ASR_API_PRESETS
    app=QApplication.instance() or QApplication([])
    runtime=copy.deepcopy(DEFAULT_SETTINGS)
    runtime["models"]["qwen_asr_api_url"]=HOST+OLD_PATH
    incoming=dict(qwen_asr_api_provider="dashscope",qwen_asr_api_model="qwen3-asr-flash",
      qwen_asr_api_protocol="dashscope_multimodal",qwen_asr_backend="local",
      primary_asr_backend="moss",qwen_asr_model="Qwen/Qwen3-ASR-1.7B",firered_asr_backend="qwen_aligner")
    if with_url:incoming["qwen_asr_api_url"]=HOST+OLD_PATH
    original=copy.deepcopy(incoming);saved=[]
    provider=QComboBox()
    for key in ASR_API_PRESETS:provider.addItem(key,key)
    host=SimpleNamespace(legacy=SimpleNamespace(RUNTIME_SETTINGS=runtime,configure_runtime_asr=lambda values,**kwargs:saved.append(copy.deepcopy(values))),
      qwen_asr_api_provider=provider,qwen_asr_api_model=QLineEdit(),qwen_asr_api_url=QLineEdit(),
      _refresh_asr_key_placeholder=lambda:None)
    MainWindow._apply_profile_asr_config(host,incoming,persist=persist)
    assert incoming==original
    assert provider.currentData()=="qwen31_filetrans"
    assert host.qwen_asr_api_model.text()==LATEST and host.qwen_asr_api_url.text()==HOST+PATH
    if persist:
        assert saved[0]["qwen_asr_api_protocol"]=="dashscope_filetrans"
        assert saved[0]["primary_asr_backend"]=="moss" and saved[0]["qwen_asr_backend"]=="local"
        assert saved[0]["qwen_asr_model"]=="Qwen/Qwen3-ASR-1.7B" and saved[0]["firered_asr_backend"]=="qwen_aligner"
    else:assert not saved
    for widget in (provider,host.qwen_asr_api_model,host.qwen_asr_api_url):widget.deleteLater()
    app.processEvents()


def test_asr_placeholder_never_uses_unrelated_legacy_stage_secret(monkeypatch):
    from PySide6.QtWidgets import QApplication,QComboBox,QLineEdit
    from twobyteasr import ui
    app=QApplication.instance() or QApplication([])
    provider=QComboBox();provider.addItem("custom","custom")
    field=QLineEdit();url=QLineEdit("https://fixture.invalid/asr")
    host=SimpleNamespace(qwen_asr_api_provider=provider,qwen_asr_api_url=url,qwen_asr_api_key=field)
    calls=[]
    monkeypatch.setattr(ui,"read_asr_api_key",lambda p,u:(calls.append((p,u)) or ("","fixture-unconfigured")))
    monkeypatch.setattr(ui,"resolve_api_key",lambda *a:pytest.fail("ASR UI must not borrow a global stage key"))
    ui.MainWindow._refresh_asr_key_placeholder(host)
    assert calls==[("custom",url.text())]
    assert field.placeholderText()==ui.tr("请输入当前 ASR 服务的 API Key")
    monkeypatch.setattr(ui,"read_asr_api_key",lambda *a:("owned-fixture","fixture-owned-scope"))
    ui.MainWindow._refresh_asr_key_placeholder(host)
    assert "fixture-owned-scope" in field.placeholderText()
    for widget in (provider,url,field):widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("language",["zh","en","ja"])
def test_retired_short_endpoint_error_uses_selected_language(monkeypatch,language):
    from twobyteasr import i18n
    monkeypatch.setattr(i18n,"current_language",lambda:language)
    source="Qwen3-ASR-Flash 短音频聊天接口不回传可用时间戳，请选择 Qwen3-ASR-Flash 录音文件识别（Filetrans）。"
    with pytest.raises(RuntimeError) as error:
        llm_config.validate_qwen_asr_endpoint({"model":"qwen3-asr-flash"})
    assert str(error.value)==i18n.tr(source)
    if language!="zh":assert str(error.value)!=source and "Filetrans" in str(error.value)
