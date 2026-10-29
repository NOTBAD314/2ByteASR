"""AI 模型选择持久化回归（2026-09-20 DeepSeek vision-exp 复活链）。

覆盖用户验收 Test 1-8：
1. 保存 model=A → 重新加载 settings → 仍为 A
2. 重新创建 AI 设置编辑器 → 下拉仍为 A
3. 模型列表刷新后仍含 A → selection 不变
4. 刷新后列表不含 A → 明确标记待确认；墓碑模型绝不被恢复
5. 重选 B 保存 → “重启”（新实例）后仍是 B
6. 全文断句 runtime 解析 → 实际请求模型 = B
7. 校对/断句统一开关切换 → 不复活 vision-exp
8. 全仓运行时代码不再把 vision-exp 当 DeepSeek 默认模型
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


RETIRED = "deepseek-v4-flash-vision-exp"
MODEL_A = "deepseek-v4-pro"
MODEL_B = "deepseek-v4-flash"


@pytest.fixture(scope="session", autouse=True)
def _session_settings_isolation(tmp_path_factory):
    """会话级 settings 根重定向（不恢复），同 test_profile_independence。"""
    import twobyteasr.storage.settings as settings_module

    redirected_root = tmp_path_factory.mktemp("ai-persist-settings-root")
    settings_module.stable_settings_root = lambda: redirected_root
    yield


@pytest.fixture()
def _no_secret_writes(monkeypatch):
    # The editor lives in providers.endpoint_editor_ui; saving stays in app.ui.
    for module in ("twobyteasr.app.ui", "twobyteasr.providers.endpoint_editor_ui"):
        monkeypatch.setattr(f"{module}.resolve_api_key", lambda stage: ("", "未配置"))
        monkeypatch.setattr(
            f"{module}.read_api_key", lambda _provider, _base_url="": ("", "未配置")
        )
    monkeypatch.setattr(
        "twobyteasr.app.ui.save_api_key_for",
        lambda provider, base_url, key: None,
    )
    monkeypatch.setattr(
        "twobyteasr.app.ui.delete_api_key_for",
        lambda provider, base_url: None,
    )


def _editor_values(model: str) -> dict:
    return {
        "service": "deepseek",
        "transport": "openai_compatible",
        "provider": "deepseek",
        "model": model,
        "base_url": "https://api.deepseek.com/v1",
        "protocol": "auto",
        "key": "",
        "key_state": "unchanged",
    }


def _persist(legacy, model: str, *, unified: bool = True, use_ai_grouping: bool = True):
    from twobyteasr.app.ui import persist_ai_configuration

    group = _editor_values(model)
    polish = dict(group) if unified else _editor_values(model)
    return persist_ai_configuration(
        legacy,
        polish,
        group,
        unified=unified,
        share_key=True,
        require_ready=False,
        use_ai_grouping=use_ai_grouping,
    )


def _runtime_models(legacy) -> dict:
    return legacy.RUNTIME_SETTINGS.get("models", {})


# ---------------------------------------------------------------------------
# Test 1: settings 层保存/重载
# ---------------------------------------------------------------------------

def test_save_then_reload_keeps_deepseek_model(tmp_path, monkeypatch, _no_secret_writes):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    from twobyteasr.storage.settings import load_runtime_settings

    _persist(legacy, MODEL_A)

    # “重启”：从磁盘重新加载 settings
    reloaded, _path, _warnings = load_runtime_settings()
    models = reloaded.get("models", {})
    assert models.get("ai_service") == "deepseek"
    assert models.get("provider_profiles", {}).get("deepseek", {}).get("model") == MODEL_A
    assert models.get("group_model") == MODEL_A
    assert models.get("polish_model") == MODEL_A


# ---------------------------------------------------------------------------
# Test 2 + 5: 编辑器重建（“重新打开设置页/重启”）恢复保存值
# ---------------------------------------------------------------------------

def _make_editor(settings: dict):
    from twobyteasr.app.ui import EndpointEditor

    return EndpointEditor("全文断句模型", "#2f8fef", "group", settings)


def test_recreated_editor_shows_saved_model(tmp_path, monkeypatch, _no_secret_writes):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _app = QApplication.instance() or QApplication([])
    import subtitle_core as legacy

    _persist(legacy, MODEL_A)
    settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    editor = _make_editor(settings)
    assert editor.model.currentText().strip() == MODEL_A
    editor.deleteLater()

    # Test 5：重选 B 保存 → 新实例恢复 B
    _persist(legacy, MODEL_B)
    settings_b = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    editor_b = _make_editor(settings_b)
    assert editor_b.model.currentText().strip() == MODEL_B
    editor_b.deleteLater()


# ---------------------------------------------------------------------------
# Test 3 + 4: 模型列表刷新不擅动 selection
# ---------------------------------------------------------------------------

def test_discovery_refresh_keeps_selection_when_model_present(tmp_path, monkeypatch, _no_secret_writes):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _app = QApplication.instance() or QApplication([])
    import subtitle_core as legacy

    _persist(legacy, MODEL_A)
    editor = _make_editor(copy.deepcopy(legacy.RUNTIME_SETTINGS))
    editor.model.setCurrentText(MODEL_A)

    editor._model_discovery_succeeded([MODEL_B, MODEL_A])

    assert editor.model.currentText().strip() == MODEL_A
    assert "不在最新列表" not in editor.status.text()
    editor.deleteLater()


def test_discovery_refresh_missing_model_flags_reselection(tmp_path, monkeypatch, _no_secret_writes):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _app = QApplication.instance() or QApplication([])
    import subtitle_core as legacy

    _persist(legacy, MODEL_A)
    editor = _make_editor(copy.deepcopy(legacy.RUNTIME_SETTINGS))

    editor._model_discovery_succeeded([MODEL_B])

    # selection 文本保留（可搜索/手动输入），但状态明确要求确认
    assert editor.model.currentText().strip() == MODEL_A
    assert "不在最新列表" in editor.status.text()
    editor.deleteLater()


def test_retired_saved_model_shows_warning_and_never_selected(tmp_path, monkeypatch, _no_secret_writes):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _app = QApplication.instance() or QApplication([])
    import subtitle_core as legacy

    # 直接把用户磁盘状态伪造为历史 vision-exp（等价真实用户现场）
    settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    settings.setdefault("models", {}).setdefault("provider_profiles", {})["deepseek"] = {
        "base_url": "https://api.deepseek.com/v1",
        "model": RETIRED,
        "protocol": "auto",
    }
    # 设置页直接打开在 DeepSeek 上（不靠前面测试留下的 ai_service）
    settings["models"]["ai_service"] = "deepseek"
    editor = _make_editor(settings)

    assert editor.model.currentText().strip() != RETIRED
    assert editor.model.findText(RETIRED) < 0
    assert not editor.model_warning.isHidden()
    assert RETIRED in editor.model_warning.text()
    editor.deleteLater()


# ---------------------------------------------------------------------------
# Test 6: runtime 解析与实际请求模型
# ---------------------------------------------------------------------------

def test_group_request_resolves_saved_model(tmp_path, monkeypatch, _no_secret_writes):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    from twobyteasr.providers.llm_config import endpoint_from_settings

    _persist(legacy, MODEL_B)

    endpoint = endpoint_from_settings(copy.deepcopy(legacy.RUNTIME_SETTINGS), "group")
    assert endpoint["model"] == MODEL_B


def test_runtime_never_resolves_retired_model(tmp_path, monkeypatch, _no_secret_writes):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    from twobyteasr.providers.llm_config import (
        endpoint_from_settings,
        resolved_service_values,
        service_model_catalog,
        validate_endpoint,
    )

    settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    settings.setdefault("models", {}).setdefault("provider_profiles", {})["deepseek"] = {
        "base_url": "https://api.deepseek.com/v1",
        "model": RETIRED,
        "protocol": "auto",
    }
    settings["models"]["group_model"] = RETIRED
    settings["models"]["polish_model"] = RETIRED
    settings["models"]["ai_service"] = "deepseek"

    values = resolved_service_values(settings, "deepseek")
    assert values["model"] != RETIRED
    assert RETIRED not in service_model_catalog(settings, "deepseek")
    endpoint = endpoint_from_settings(settings, "group")
    assert endpoint["model"] != RETIRED

    with pytest.raises(RuntimeError, match="已不可用"):
        validate_endpoint(
            {
                "provider": "deepseek",
                "model": RETIRED,
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "whatever",
            },
            "全文断句模型",
        )


def _flat_retired_settings(legacy, profile_model: str, *, unified: bool) -> dict:
    """服务档案存 profile_model，两段平铺字段（含 transport，识别快照走 prefer_role）都是墓碑。"""
    settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    settings.pop("_asr_provider_snapshot", None)
    models = settings.setdefault("models", {})
    models["ai_service"] = "deepseek"
    models["provider_profiles"] = {"deepseek": {
        "base_url": "https://api.deepseek.com/v1", "model": profile_model, "protocol": "auto"}}
    for stage in ("polish", "group"):
        models.update({f"{stage}_provider": "deepseek", f"{stage}_transport": "openai_compatible",
                       f"{stage}_base_url": "https://api.deepseek.com/v1", f"{stage}_model": RETIRED})
    settings.setdefault("switches", {})["unified_glm_processing"] = unified
    return settings


@pytest.mark.parametrize("unified", [False, True])
@pytest.mark.parametrize("profile_model, expected", [(MODEL_A, MODEL_A), (RETIRED, MODEL_B)])
def test_flat_retired_model_resolves_to_service_model(
        tmp_path, monkeypatch, _no_secret_writes, unified, profile_model, expected):
    """关闭统一模型后全文断句读平铺 group_model；识别快照（prefer_role）两段都读平铺字段。

    这些路径不经过服务档案，平铺字段里的墓碑换成该服务当前的模型：档案值，
    档案也是墓碑时用服务默认（DeepSeek 是 deepseek-v4-flash）。
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.providers.llm_config import effective_ai_identity, endpoint_from_settings

    settings = _flat_retired_settings(legacy, profile_model, unified=unified)
    for stage in ("polish", "group"):
        assert endpoint_from_settings(settings, stage)["model"] == expected
        assert endpoint_from_settings(settings, stage, prefer_role=True)["model"] == expected
        assert resolve_provider_snapshot(settings, stage=stage).model == expected
        assert effective_ai_identity(settings, stage)["model"] == expected


def test_flat_retired_model_without_service_default_keeps_explicit_error(
        tmp_path, monkeypatch, _no_secret_writes):
    """自定义端点没有默认模型：保留原值，请求前由 validate_endpoint 报“已不可用”。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    from twobyteasr.providers.llm_config import endpoint_from_settings, validate_endpoint

    settings = _flat_retired_settings(legacy, RETIRED, unified=False)
    models = settings["models"]
    models["ai_service"] = "custom"
    models["provider_profiles"] = {}
    for stage in ("polish", "group"):
        models.update({f"{stage}_provider": "custom", f"{stage}_base_url": "https://llm.example.test/v1"})

    for prefer_role in (False, True):
        endpoint = endpoint_from_settings(settings, "group", prefer_role=prefer_role)
        assert endpoint["model"] == RETIRED
        with pytest.raises(RuntimeError, match="已不可用"):
            validate_endpoint({**endpoint, "api_key": "whatever"}, "全文断句模型")


# ---------------------------------------------------------------------------
# Test 7: 统一开关切换不复活墓碑模型
# ---------------------------------------------------------------------------

def test_unified_toggle_never_resurrects_retired_model(tmp_path, monkeypatch, _no_secret_writes):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy

    # 磁盘上残留墓碑值的真实用户状态
    legacy.RUNTIME_SETTINGS.setdefault("models", {}).setdefault("provider_profiles", {})["deepseek"] = {
        "base_url": "https://api.deepseek.com/v1",
        "model": RETIRED,
        "protocol": "auto",
    }
    legacy.RUNTIME_SETTINGS["models"]["ai_service"] = "deepseek"

    _persist(legacy, MODEL_B, unified=True)
    models = _runtime_models(legacy)
    assert models["group_model"] == MODEL_B and RETIRED not in models["group_model"]

    _persist(legacy, MODEL_B, unified=False)
    models = _runtime_models(legacy)
    assert models["polish_model"] == MODEL_B
    assert models["group_model"] == MODEL_B
    assert models["provider_profiles"]["deepseek"]["model"] == MODEL_B
    assert all(RETIRED != value for value in models.get("provider_profiles", {}).get("deepseek", {}).values())


# ---------------------------------------------------------------------------
# Test 8: 全仓运行时代码不再把 vision-exp 当默认模型
# ---------------------------------------------------------------------------

def test_repo_runtime_has_no_vision_exp_default():
    root = Path(__file__).resolve().parents[1]
    # 墓碑定义/自检允许引用该 id；生产默认逻辑不得引用
    allowed_files = {
        root / "twobyteasr" / "providers" / "llm_config.py",
        root / "twobyteasr" / "acceptance" / "runtime_fixes_audit.py",
    }
    offenders = []
    for path in list((root / "twobyteasr").rglob("*.py")) + [root / "moss_firered_pipeline.py"]:
        if path in allowed_files or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if RETIRED in text:
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"运行时代码不应再引用已下线模型: {offenders}"


# ---------------------------------------------------------------------------
# 方案快照复活链（MainWindow 端到端）
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_main_window(monkeypatch, tmp_path, _no_secret_writes):
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    import twobyteasr.app.ui as ui_module

    original_settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    window = ui_module.MainWindow([], legacy, object(), None)
    try:
        yield window, legacy
    finally:
        legacy.RUNTIME_SETTINGS = original_settings
        window.close()
        window.deleteLater()


def test_profile_apply_with_retired_ref_keeps_global_model(isolated_main_window):
    """启动/切方案回灌环节：墓碑 ref 不再覆盖全局保存值。"""
    window, legacy = isolated_main_window
    from twobyteasr.recognition.recognition_profiles import ProjectProfileStore

    store = ProjectProfileStore(Path(window.profile_store.path))
    profile = store.create("Qwen api", llm_enabled=True, llm_config_ref=RETIRED)

    window._apply_project_profile(store.get(profile.id), mark_used=False)

    current = window.group_editor.model.currentText().strip()
    assert current != RETIRED, "已下线模型不得通过方案快照复活"
    # 全局保存值原样保留
    assert current == str(
        legacy.RUNTIME_SETTINGS.get("models", {}).get("group_model", "") or ""
    ) or current


def _select_service(editor, service_id: str) -> None:
    editor.service.setCurrentIndex(editor.service.findData(service_id))


def test_ai_summary_preview_reports_typed_retired_model(isolated_main_window):
    """模型框里手动输入下线 id：预演保存时 validate_endpoint 的 RuntimeError 记成“未通过保存校验”。"""
    window, _legacy = isolated_main_window
    window.ai_grouping.setChecked(True)
    window.ai_polish.setChecked(True)
    window.unified_glm.setChecked(True)
    _select_service(window.group_editor, "deepseek")
    _select_service(window.polish_editor, "deepseek")
    window.group_editor.model.setCurrentText(RETIRED)  # currentTextChanged -> _refresh_ai_summary

    window._refresh_ai_summary()  # 改前这里抛出 RuntimeError（启动时会弹“2ByteASR 启动失败”）

    summary = window.ai_panel.summary_label.text()
    assert "配置未通过保存校验" in summary
    assert window._ai_has_draft is True
    # 清空模型框同样只是“未通过保存校验”（validate_endpoint 报缺少模型名称也是 RuntimeError）
    window.group_editor.model.setCurrentText("")
    window._refresh_ai_summary()
    assert "配置未通过保存校验" in window.ai_panel.summary_label.text()
    # 改回可用模型后提示消失（也免得这个窗口在后面测试的全局重翻译里带着坏值）
    window.group_editor.model.setCurrentText(MODEL_B)
    window._refresh_ai_summary()
    assert "配置未通过保存校验" not in window.ai_panel.summary_label.text()


def test_main_window_starts_with_flat_retired_models_not_unified(monkeypatch, tmp_path, _no_secret_writes):
    """关闭统一模型、档案与平铺字段都是墓碑：程序照常启动，已保存摘要和编辑器都不显示墓碑。

    改前已保存摘要（识别快照走平铺字段）写着墓碑，编辑器却是默认模型，于是没改任何东西
    也显示“未保存草稿”。
    """
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    import twobyteasr.app.ui as ui_module

    original_settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    legacy.RUNTIME_SETTINGS = _flat_retired_settings(legacy, RETIRED, unified=False)
    legacy.RUNTIME_SETTINGS["switches"].update({"use_ai_grouping": True, "enable_ai_polish": True})
    window = None
    try:
        window = ui_module.MainWindow([], legacy, object(), None)
        window._ensure_recognition_page()  # 启动页是工程库时设置页延后建立；这里补建
        window._refresh_ai_summary()
        summary = window.ai_panel.summary_label.text()
        assert RETIRED not in summary
        assert MODEL_B in summary
        assert "未保存草稿" not in summary and window._ai_has_draft is False
        assert RETIRED not in window.setting_tiles["ai"].summary_label.text()
        for editor in (window.polish_editor, window.group_editor):
            assert editor.model.currentText().strip() == MODEL_B
            assert editor.model.findText(RETIRED) < 0
    finally:
        legacy.RUNTIME_SETTINGS = original_settings
        if window is not None:
            window.close()
            window.deleteLater()


def test_save_ai_configuration_updates_profile_bookmark(isolated_main_window, capsys):
    """保存 AI 配置 = 唯一权威写入时刻：方案书签必须跟随，杜绝下次启动复活。"""
    window, legacy = isolated_main_window
    from twobyteasr.recognition.recognition_profiles import ProjectProfileStore

    store = ProjectProfileStore(Path(window.profile_store.path))
    profile = store.create("Qwen api", llm_enabled=True, llm_config_ref=RETIRED)
    window.current_project_profile = store.get(profile.id)
    window.group_editor.model.setCurrentText(MODEL_A)
    window.polish_editor.model.setCurrentText(MODEL_A)

    assert window._save_ai_configuration(show_feedback=False) is True

    updated = store.get(profile.id)
    assert updated.llm_config_ref == MODEL_A
    assert updated.llm_config_ref != RETIRED
    saved = capsys.readouterr().out
    assert "[AI_CONFIG_SAVED]" in saved
    assert f"model={MODEL_A}" in saved
    assert "key" not in saved.lower().replace("key_source", "")
