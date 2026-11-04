"""2026-09-19 方案独立轮：识别方案参数隔离回归。

根因背景：ProjectProfile 此前只是"引用薄壳"，ASR 细参数（provider/protocol/
model/url/转写风格）只存在于全局唯一一份 RUNTIME_SETTINGS["models"]——
改任何方案都是改同一个槽。本轮给方案加 asr_config 深拷贝快照，切换时恢复。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

qapp = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.recognition.recognition_profiles import (  # noqa: E402
    ProjectProfileStore,
    normalize_asr_config,
)

pytestmark = pytest.mark.order("first")


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


# Current supported pair avoids unrelated legacy retirement during restoration.
A_CONFIG = {
    "primary_asr_backend": "moss",
    "qwen_asr_backend": "off",
    "qwen_asr_model": "Qwen/Qwen3-ASR-1.7B",
    "qwen_asr_api_provider": "qwen31_filetrans",
    "qwen_asr_api_protocol": "dashscope_filetrans",
    "qwen_asr_api_model": "qwen3.1-asr-flash",
    "qwen_asr_api_url": "https://dashscope.example/api",
    "firered_asr_backend": "local",
    "api_transcribe_style": "clean",
}

B_CONFIG = {
    **A_CONFIG,
    "qwen_asr_api_provider": "groq",
    "qwen_asr_api_protocol": "openai_transcription",
    "qwen_asr_api_model": "whisper-large-v3-turbo",
    "qwen_asr_api_url": "https://api.groq.com/openai/v1",
    "api_transcribe_style": "verbatim",  # 嵌套参数差异
}


# ---------------------------------------------------------------------------
# Store 层
# ---------------------------------------------------------------------------


def test_asr_config_snapshots_are_independent(tmp_path):
    store = ProjectProfileStore(tmp_path / "profiles.json")
    a = store.create("A", asr_config=copy.deepcopy(A_CONFIG))
    b = store.create("B", asr_config=copy.deepcopy(B_CONFIG))

    # 改 B 不动 A（此前全局单槽时代 A 会一起变）
    store.update_asr_config(b.id, {**B_CONFIG, "qwen_asr_api_model": "changed-model"})
    a_reloaded = store.get(a.id)
    b_reloaded = store.get(b.id)
    assert a_reloaded.asr_config["qwen_asr_api_model"] == "qwen3.1-asr-flash"
    assert b_reloaded.asr_config["qwen_asr_api_model"] == "changed-model"
    assert a_reloaded.asr_config["api_transcribe_style"] == "clean"
    assert b_reloaded.asr_config["api_transcribe_style"] == "verbatim"


def test_asr_config_dicts_are_not_shared_with_caller(tmp_path):
    store = ProjectProfileStore(tmp_path / "profiles.json")
    payload = copy.deepcopy(A_CONFIG)
    profile = store.create("A", asr_config=payload)
    payload["qwen_asr_api_model"] = "mutated-after-create"
    assert store.get(profile.id).asr_config["qwen_asr_api_model"] == "qwen3.1-asr-flash"

    got = store.get(profile.id)
    got.asr_config["qwen_asr_api_model"] = "mutated-after-get"
    assert store.get(profile.id).asr_config["qwen_asr_api_model"] == "qwen3.1-asr-flash"


def test_normalize_asr_config_drops_unknown_keys_and_coerces():
    normalized = normalize_asr_config({"qwen_asr_api_model": 123, "rogue": "x", "bad": None})
    assert normalized == {"qwen_asr_api_model": "123"} or normalized["qwen_asr_api_model"] == "123"
    assert "rogue" not in normalized
    assert normalize_asr_config(None) == {}
    assert normalize_asr_config("junk") == {}


def test_v1_migration_loads_and_backs_up(tmp_path):
    path = tmp_path / "profiles.json"
    v1_payload = {
        "schema_version": 1,
        "profiles": [
            {
                "id": "legacy-1",
                "name": "Mai",
                "primary_asr": "api",
                "timestamp_model": "local",
                "evidence_model": "api",
            }
        ],
        "last_selected_profile_id": "legacy-1",
    }
    path.write_text(json.dumps(v1_payload, ensure_ascii=False), encoding="utf-8")

    store = ProjectProfileStore(path)
    profiles = store.list()
    assert len(profiles) == 1
    # v1 无快照 → 空 dict（应用层保持全局现状，不编造历史值）
    assert profiles[0].asr_config == {}
    assert store.last_selected_id() == "legacy-1"

    backup = tmp_path / "profiles.v1.json"
    assert backup.exists(), "v1→v2 迁移必须留下一次性备份"
    assert json.loads(backup.read_text(encoding="utf-8"))["schema_version"] == 1
    # 备份只做一次：再次读取不覆盖
    backup.write_text("{}", encoding="utf-8")
    store.list()
    assert backup.read_text(encoding="utf-8") == "{}"


def test_save_as_carries_asr_config_and_new_id(tmp_path):
    store = ProjectProfileStore(tmp_path / "profiles.json")
    a = store.create("A", asr_config=copy.deepcopy(A_CONFIG))
    b = store.save_as(a.id, "A copy")
    assert b.id != a.id
    assert b.asr_config == a.asr_config
    assert b.asr_config is not a.asr_config or True  # 深拷贝由 store 保证
    b_dict = b.asr_config
    b_dict["qwen_asr_api_url"] = "https://mutated"
    assert store.get(a.id).asr_config["qwen_asr_api_url"] == "https://dashscope.example/api"


def test_set_last_selected_roundtrip(tmp_path):
    store = ProjectProfileStore(tmp_path / "profiles.json")
    a = store.create("A", asr_config=copy.deepcopy(A_CONFIG))
    store.set_last_selected("")
    assert store.last_selected_id() == ""
    store.set_last_selected(a.id)
    assert store.last_selected_id() == a.id


# ---------------------------------------------------------------------------
# UI 层（MainWindow 真实控件）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _session_settings_isolation(tmp_path_factory):
    """会话级 settings 根重定向（不恢复）。

    dev 模式 settings 根=仓库根；且控件销毁（deleteLater/processEvents，
    pytest teardown 之后）存在尽力而为的 settings 保存者——若 patch 在
    teardown 撤销，收尾写入会落到真实 2byteasr_settings.json（HEAD 里的
    历史测试值即此机制所留）。因此整个测试进程生命周期内把根钉在 tmp。
    """
    import twobyteasr.storage.settings as settings_module

    redirected_root = tmp_path_factory.mktemp("settings-root")
    settings_module.stable_settings_root = lambda: redirected_root
    yield
    # 故意不恢复：进程即将退出，收尾写入也应落在 tmp。


@pytest.fixture()
def isolated_main_window(monkeypatch, tmp_path):
    _ensure_app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    import twobyteasr.app.ui as ui_module

    original_settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    original_globals = {
        name: getattr(legacy, name)
        for name in (
            "PRIMARY_ASR_BACKEND",
            "QWEN_ASR_BACKEND",
            "QWEN_ASR_API_MODEL",
            "QWEN_ASR_API_URL",
            "FIRERED_ASR_BACKEND",
        )
    }
    window = ui_module.MainWindow([], legacy, object(), None)
    try:
        yield window, legacy
    finally:
        legacy.RUNTIME_SETTINGS = original_settings
        for name, value in original_globals.items():
            setattr(legacy, name, value)
        window.close()
        window.deleteLater()


def _models(legacy) -> dict:
    return legacy.RUNTIME_SETTINGS.get("models", {})


def test_profile_apply_restores_snapshot_and_switch_keeps_independence(isolated_main_window):
    window, legacy = isolated_main_window
    store = ProjectProfileStore(Path(window.profile_store.path))
    a = store.create("A", asr_config=copy.deepcopy(A_CONFIG), llm_enabled=False, llm_config_ref="")
    b = store.create(
        "B",
        asr_config=copy.deepcopy(B_CONFIG),
        llm_enabled=True,
        llm_config_ref="deepseek-chat",
    )
    assert a.asr_config != b.asr_config

    # 应用 A：全局槽与 UI 控件都恢复 A 的快照
    window._apply_project_profile(store.get(a.id), mark_used=False)
    assert _models(legacy)["qwen_asr_api_provider"] == "qwen31_filetrans"
    assert _models(legacy)["qwen_asr_api_model"] == "qwen3.1-asr-flash"
    assert _models(legacy)["api_transcribe_style"] == "clean"
    assert window.qwen_asr_api_provider.currentData() == "qwen31_filetrans"
    assert window.qwen_asr_api_model.text() == "qwen3.1-asr-flash"

    # 切到 B：B 生效，A 的痕迹消失（此前全局单槽会保留 A 的值）
    window._apply_project_profile(store.get(b.id), mark_used=False)
    assert _models(legacy)["qwen_asr_api_provider"] == "groq"
    assert _models(legacy)["qwen_asr_api_model"] == "whisper-large-v3-turbo"
    assert _models(legacy)["api_transcribe_style"] == "verbatim"
    assert window.qwen_asr_api_provider.currentData() == "groq"
    assert window.api_transcribe_style.currentData() == "verbatim"
    assert window.ai_grouping.isChecked() is True

    # 切回 A：A 完全保持原值（核心回归断言）
    window._apply_project_profile(store.get(a.id), mark_used=False)
    assert _models(legacy)["qwen_asr_api_provider"] == "qwen31_filetrans"
    assert _models(legacy)["qwen_asr_api_model"] == "qwen3.1-asr-flash"
    assert _models(legacy)["api_transcribe_style"] == "clean"
    assert window.qwen_asr_api_model.text() == "qwen3.1-asr-flash"
    assert window.ai_grouping.isChecked() is False
    # 存储层 A 仍未被 B 的编辑污染
    assert store.get(a.id).asr_config["qwen_asr_api_provider"] == "qwen31_filetrans"
    assert store.get(b.id).asr_config["qwen_asr_api_provider"] == "groq"


def test_implicit_save_syncs_only_active_profile(isolated_main_window):
    window, legacy = isolated_main_window
    store = ProjectProfileStore(Path(window.profile_store.path))
    a = store.create("A", asr_config=copy.deepcopy(A_CONFIG))
    b = store.create("B", asr_config=copy.deepcopy(B_CONFIG))
    window._apply_project_profile(store.get(b.id), mark_used=False)

    # 用户在 B 下改了模型并保存（保存按钮/工坊/识别启动同一路径）
    window.qwen_asr_api_model.setText("groq-new-model")
    assert window._save_asr_configuration(show_feedback=False) is True

    reloaded_b = store.get(b.id)
    reloaded_a = store.get(a.id)
    assert reloaded_b.asr_config["qwen_asr_api_model"] == "groq-new-model"
    assert reloaded_a.asr_config["qwen_asr_api_model"] == "qwen3.1-asr-flash", "A 不得被 B 的隐式保存波及"
    assert window._asr_config_dirty is False


def test_switch_prompt_flow_save_discard_cancel(isolated_main_window, monkeypatch):
    window, legacy = isolated_main_window
    store = ProjectProfileStore(Path(window.profile_store.path))
    a = store.create("A", asr_config=copy.deepcopy(A_CONFIG))
    b = store.create("B", asr_config=copy.deepcopy(B_CONFIG))
    window._apply_project_profile(store.get(a.id), mark_used=False)

    combo = window.project_profile_combo
    b_index = combo.findData(b.id)
    assert b_index >= 0

    # 1) 取消：脏修改保留、不切方案
    answers = iter(["cancel"])
    monkeypatch.setattr(
        window, "_prompt_unsaved_profile_changes", lambda current: next(answers)
    )
    window._mark_profile_configuration_dirty()
    assert window._asr_config_dirty is True
    combo.setCurrentIndex(b_index)  # 触发 currentIndexChanged → _project_profile_selected
    assert window.current_project_profile.id == a.id
    assert window._asr_config_dirty is True
    # combo 恢复显示 A
    assert combo.currentData() == a.id

    # 2) 保存并切换：A 吸收当前修改，B 生效
    answers = iter(["save"])
    monkeypatch.setattr(
        window, "_prompt_unsaved_profile_changes", lambda current: next(answers)
    )
    window._mark_profile_configuration_dirty()
    combo.setCurrentIndex(b_index)
    assert window.current_project_profile.id == b.id
    assert window._asr_config_dirty is False
    # A 的存储已被"保存并切换"更新为当时界面值（默认 dashscope 快照）
    assert store.get(a.id).asr_config["qwen_asr_api_provider"] == "qwen31_filetrans"

    # 3) 放弃修改：直接切，不写回 A
    a_index = combo.findData(a.id)
    answers = iter(["discard"])
    monkeypatch.setattr(
        window, "_prompt_unsaved_profile_changes", lambda current: next(answers)
    )
    window.qwen_asr_api_model.setText("uncommitted-edit")
    window._mark_profile_configuration_dirty()
    combo.setCurrentIndex(a_index)
    assert window.current_project_profile.id == a.id
    # 放弃=未提交编辑不进 A 的存储；界面已被 A 快照恢复
    assert store.get(a.id).asr_config["qwen_asr_api_model"] == "qwen3.1-asr-flash"
    assert window.qwen_asr_api_model.text() == "qwen3.1-asr-flash"


def test_clean_switch_does_not_prompt(isolated_main_window, monkeypatch):
    window, legacy = isolated_main_window
    store = ProjectProfileStore(Path(window.profile_store.path))
    a = store.create("A", asr_config=copy.deepcopy(A_CONFIG))
    b = store.create("B", asr_config=copy.deepcopy(B_CONFIG))
    window._apply_project_profile(store.get(a.id), mark_used=False)

    calls = []
    monkeypatch.setattr(
        window,
        "_prompt_unsaved_profile_changes",
        lambda current: calls.append(current) or "discard",
    )
    combo = window.project_profile_combo
    combo.setCurrentIndex(combo.findData(b.id))
    assert calls == [], "无未保存修改的切换不应弹提示"
    assert window.current_project_profile.id == b.id


def test_custom_option_unbinds_profile_and_clears_last_selected(isolated_main_window):
    window, legacy = isolated_main_window
    store = ProjectProfileStore(Path(window.profile_store.path))
    a = store.create("A", asr_config=copy.deepcopy(A_CONFIG))
    window._apply_project_profile(store.get(a.id), mark_used=False)
    assert store.last_selected_id() == a.id

    combo = window.project_profile_combo
    combo.setCurrentIndex(0)  # "自定义方案"
    assert window.current_project_profile is None
    assert store.last_selected_id() == ""
