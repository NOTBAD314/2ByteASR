import json
from types import SimpleNamespace

from twobyteasr.recognition import reporting
from twobyteasr.recognition import cache as cache_module
from twobyteasr.storage.settings import DEFAULT_SETTINGS, load_runtime_settings, save_runtime_settings
from twobyteasr.providers.llm_config import (
    endpoint_from_settings, resolve_api_key, save_api_keys, update_active_profile,
)


def test_default_cloud_models_use_qwen37_flash_for_both_stages():
    expected = "qwen3.7-flash-2026-07-15"
    assert DEFAULT_SETTINGS["models"]["polish_model"] == expected
    assert DEFAULT_SETTINGS["models"]["group_model"] == expected


def test_default_qwen_asr_uses_api_while_firered_keeps_local_timing():
    assert DEFAULT_SETTINGS["models"]["qwen_asr_backend"] == "api"
    assert DEFAULT_SETTINGS["models"]["qwen_asr_api_model"] == "qwen3-asr-flash"
    assert DEFAULT_SETTINGS["models"]["firered_asr_backend"] == "local"


def test_runtime_settings_load_known_values_and_reject_invalid_switches(tmp_path):
    (tmp_path / "2byteasr_settings.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "models": {"polish_model": "custom-flash"},
                "switches": {"output_review_track": True, "enable_qwen_asr_reference": "yes"},
                "performance": {"cloud_batch_workers": 5},
            }
        ),
        encoding="utf-8",
    )
    settings, path, warnings = load_runtime_settings(tmp_path)
    assert path.endswith("2byteasr_settings.json")
    assert settings["models"]["polish_model"] == "custom-flash"
    assert settings["switches"]["output_review_track"] is True
    assert settings["switches"]["enable_qwen_asr_reference"] is True
    assert settings["performance"]["cloud_batch_workers"] == 5
    assert settings["performance"]["qwen_asr_batch_size"] == 8
    assert any("enable_qwen_asr_reference" in warning for warning in warnings)


def test_legacy_disabled_asr_switches_migrate_to_off(tmp_path):
    (tmp_path / "2byteasr_settings.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "switches": {
                    "enable_qwen_asr_reference": False,
                    "enable_firered_boundary_refinement": False,
                },
            }
        ),
        encoding="utf-8",
    )
    settings, _, _ = load_runtime_settings(tmp_path)
    assert settings["models"]["qwen_asr_backend"] == "off"
    assert settings["models"]["firered_asr_backend"] == "off"


def test_model_endpoints_are_saved_without_api_keys(tmp_path):
    settings, _, _ = load_runtime_settings(tmp_path)
    settings["models"].update(
        {
            "polish_provider": "openai_compatible",
            "polish_model": "custom-polish",
            "polish_base_url": "https://example.test/v1",
            "group_provider": "custom",
            "group_model": "custom-group",
            "group_base_url": "https://group.example.test/v1",
        }
    )
    saved, path, warnings = save_runtime_settings(settings, tmp_path)
    text = (tmp_path / "2byteasr_settings.json").read_text(encoding="utf-8")
    assert not warnings
    assert path.endswith("2byteasr_settings.json")
    assert saved["models"]["polish_model"] == "custom-polish"
    assert "API_KEY" not in text
    assert "secret" not in text.lower()
    reloaded, _, reload_warnings = load_runtime_settings(tmp_path)
    assert not reload_warnings
    assert reloaded["models"]["polish_provider"] == "openai_compatible"
    assert reloaded["models"]["polish_model"] == "custom-polish"
    assert reloaded["models"]["polish_base_url"] == "https://example.test/v1"
    assert reloaded["models"]["group_provider"] == "custom"
    assert reloaded["models"]["group_model"] == "custom-group"


def test_stage_keys_are_dpapi_store_first_environment_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("POLISH_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GROUP_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    secret_path = save_api_keys(
        polish_key="polish-local",
        group_key="group-local",
        qwen_asr_key="qwen-asr-local",
    )
    assert secret_path.name == "secrets.dat"
    assert b"polish-local" not in secret_path.read_bytes()
    assert resolve_api_key("polish") == ("polish-local", "Windows DPAPI / POLISH_LLM_API_KEY")
    assert resolve_api_key("group") == ("group-local", "Windows DPAPI / GROUP_LLM_API_KEY")
    assert resolve_api_key("qwen_asr") == (
        "qwen-asr-local",
        "Windows DPAPI / QWEN_ASR_API_KEY",
    )
    monkeypatch.setenv("POLISH_LLM_API_KEY", "polish-env")
    # P9A-R2 起解析顺序为 DPAPI 存储优先、环境变量兜底。
    assert resolve_api_key("polish") == ("polish-local", "Windows DPAPI / POLISH_LLM_API_KEY")


def test_plaintext_secret_file_is_migrated_to_dpapi(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for name in ("POLISH_LLM_API_KEY", "GROUP_LLM_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    legacy = tmp_path / "2ByteASR" / "secrets.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"POLISH_LLM_API_KEY":"legacy-secret"}', encoding="utf-8")

    assert resolve_api_key("polish")[0] == "legacy-secret"
    assert not legacy.exists()
    encrypted = legacy.with_name("secrets.dat")
    assert encrypted.is_file()
    assert b"legacy-secret" not in encrypted.read_bytes()


def test_unified_glm_routes_polish_to_group_endpoint_and_key(tmp_path, monkeypatch):
    # P8C-R3/P9A-R2 后统一 GLM 的契约：路由发生在写入时——activate/update_active_profile
    # 以 unified=True 把同一 profile 事务写入 polish 与 group 两组 flat 字段；
    # 读取时 endpoint_from_settings 以 active profile 为真相源，凭据取 credential_stage=group。
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("POLISH_LLM_API_KEY", "unused-polish")
    monkeypatch.setenv("GROUP_LLM_API_KEY", "working-glm")
    settings, _, _ = load_runtime_settings(tmp_path)
    settings["switches"]["unified_glm_processing"] = True
    update_active_profile(
        settings,
        stage="polish",
        base_url="https://group.example/v1",
        model="glm-5.2",
        unified=True,
    )
    # 写入时扇出：两组前缀承载同一统一模型
    assert settings["models"]["polish_model"] == settings["models"]["group_model"] == "glm-5.2"
    for stage in ("polish", "group"):
        endpoint = endpoint_from_settings(settings, stage)
        assert endpoint["model"] == "glm-5.2"
        assert endpoint["base_url"] == "https://group.example/v1"
    endpoint = endpoint_from_settings(settings, "polish")
    assert endpoint["api_key"] == "working-glm"
    assert "GROUP_LLM_API_KEY" in endpoint["key_source"]


def test_fully_local_asr_configuration_never_requires_a_cloud_key(
    tmp_path, monkeypatch
):
    # KI-5 P1-05（2026-08-13 审查遗留）回归锁定：完全本地后端组合下，
    # 保存/开始任务不得强制要求任何云密钥——密钥要求只条件化于显式选择 API 后端。
    from twobyteasr.app.ui import persist_asr_configuration

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for name in ("DASHSCOPE_API_KEY", "QWEN_ASR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    legacy = SimpleNamespace(configure_runtime_asr=lambda *_a, **_k: None,
                             RUNTIME_SETTINGS={"models": {"speaker_source": "single"}})
    values = {
        "primary_asr_backend": "moss",
        "qwen_asr_backend": "local",
        "firered_asr_backend": "local",
    }
    result = persist_asr_configuration(legacy, values, qwen_key="", require_ready=True)
    assert result["missing_keys"] == ()


def test_separate_model_mode_keeps_polish_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("POLISH_LLM_API_KEY", "polish-key")
    monkeypatch.setenv("GROUP_LLM_API_KEY", "group-key")
    settings, _, _ = load_runtime_settings(tmp_path)
    settings["models"]["polish_model"] = "custom-polish"
    settings["switches"]["unified_glm_processing"] = False
    endpoint = endpoint_from_settings(settings, "polish")
    assert endpoint["model"] == "custom-polish"
    assert endpoint["api_key"] == "polish-key"


def test_media_task_report_records_stages_cache_and_no_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path)
    media_path = tmp_path / "sample.mp3"
    media_path.write_bytes(b"audio")
    settings = {
        "models": {
            "qwen_asr_model": "qwen",
            "polish_model": "flash",
            "group_model": "glm",
            "group_base_url": "https://example.invalid",
        },
        "switches": {},
        "cache": {},
        "performance": {
            "parallel_cloud_batches": True,
            "cloud_batch_workers": 3,
            "parallel_cpu_vad": True,
            "moss_parallel_workers": 2,
            "moss_parallel_min_vram_gb": 14,
            "qwen_asr_batch_size": 8,
            "parallel_gpu_asr": True,
            "parallel_gpu_asr_min_vram_gb": 14,
        },
    }
    reporting.begin_media_report(media_path, {"cache_dir": str(tmp_path / "cache")}, settings)
    reporting.record_media_event("stage_started", index=1, label="audio", resource="CPU")
    reporting.record_media_event("cache_hit", stage="audio")
    reporting.record_media_event(
        "cloud_correction_applied",
        cue_id=1,
        edits=[{"from": "阿辉", "to": "阿晖", "basis": "voice context"}],
    )
    reporting.record_media_event(
        "host_voiceprint_mapping",
        assignments={
            "S03": {"label": "S02", "name": "主播B", "score": 0.843, "margin": 0.421}
        },
    )
    reporting.record_media_event(
        "domain_term_search_started",
        game="原神",
        candidate_count=12,
    )
    reporting.record_media_event(
        "domain_term_search_completed",
        game="原神",
        accepted_count=2,
        rejected_count=1,
    )
    reporting.record_media_event(
        "domain_term_mapping_applied",
        count=3,
    )
    reporting.record_media_event("stage_completed", label="audio", elapsed_seconds=0.4)
    json_path, text_path = reporting.finish_media_report(
        "success",
        elapsed_seconds=0.4,
        audio_seconds=1.0,
        cue_count=3,
        review_items=[{"category": "low confidence"}],
        outputs={"txt": "out.txt", "srt": "out.srt"},
    )
    payload = json.loads((tmp_path / "sample_字幕任务报告.json").read_text(encoding="utf-8"))
    assert json_path.endswith("_字幕任务报告.json")
    assert (tmp_path / "sample_字幕任务报告.txt").exists()
    assert text_path.endswith("_字幕任务报告.txt")
    assert payload["cache"]["hits"] == ["audio"]
    assert payload["stages"][0]["status"] == "completed"
    assert payload["result"]["cue_count"] == 3
    text_report = (tmp_path / "sample_字幕任务报告.txt").read_text(encoding="utf-8")
    assert "已采纳云端校对：1 处" in text_report
    assert "处理倍率：0.40x 实时" in text_report
    assert "云端批次：并行，最多 3 路" in text_report
    assert "联网术语：联网核验" in text_report
    assert "S03 -> S02 主播B" in text_report
    assert "DASHSCOPE_API_KEY" not in text_report


def test_degraded_media_report_is_persisted_and_explained(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path)
    media_path = tmp_path / "degraded.mp3"
    media_path.write_bytes(b"audio")
    settings = {
        "models": {
            "qwen_asr_model": "qwen",
            "polish_model": "deepseek-chat",
            "group_model": "deepseek-chat",
        },
        "switches": {},
        "cache": {},
        "performance": {},
    }
    review_items = [
        {"category": "校对回退", "reason": "schema invalid"},
        {"category": "断句回退", "reason": "empty content"},
    ]

    reporting.begin_media_report(media_path, {"cache_dir": str(tmp_path / "cache")}, settings)
    reporting.finish_media_report(
        "degraded_success",
        elapsed_seconds=1.0,
        audio_seconds=2.0,
        cue_count=2,
        review_items=review_items,
        outputs={"txt": "out.txt", "srt": "out.srt"},
    )

    json_report = json.loads(
        (tmp_path / "degraded_字幕任务报告.json").read_text(encoding="utf-8")
    )
    text_report = (tmp_path / "degraded_字幕任务报告.txt").read_text(encoding="utf-8")
    assert json_report["status"] == "degraded_success"
    assert [item["category"] for item in json_report["review_items"]] == [
        "校对回退", "断句回退"
    ]
    assert all(
        item["severity"] == "warning" for item in json_report["review_items"]
    )
    assert json_report["review_severity_counts"]["warning"] == 2
    assert [item["category"] for item in json_report["review_summary"]] == [
        "校对回退", "断句回退"
    ]
    assert "状态：degraded_success" in text_report
    assert "降级说明：AI 校对或断句部分回退到本地" in text_report
    assert "AI 校对部分降级：1 / 1 个批次使用本地结果" in text_report
    assert "AI 智能断句降级：1 / 1 个批次使用本地断句" in text_report
    assert "待复核项：2" in text_report


def test_degraded_success_is_still_a_successful_queue_result():
    from twobyteasr.recognition.service import MediaResult, QueueResult

    degraded = MediaResult("degraded.mp4", "degraded_success")
    result = QueueResult((degraded,), 1.0)

    assert result.successes == (degraded,)
    assert result.failures == ()
    assert result.exit_code == 0


def test_event_redaction_preserves_structured_edits(monkeypatch):
    monkeypatch.setattr(cache_module, "DASHSCOPE_API_KEY", "secret-token")
    value = cache_module._redact_runtime_payload(
        {"edits": [{"from": "secret-token", "to": "主播B"}], "count": 1}
    )
    assert value == {
        "edits": [{"from": "<redacted>", "to": "主播B"}],
        "count": 1,
    }
