"""Loading and validation for the user-editable, non-secret runtime settings."""

import copy
import json
import os
import sys
import tempfile
from pathlib import Path


SETTINGS_FILENAME = "2byteasr_settings.json"

DEFAULT_SETTINGS = {
    "schema_version": 1,
    "models": {
        "primary_asr_backend": "moss",
        "qwen_asr_backend": "api",
        "qwen_asr_model": "Qwen/Qwen3-ASR-1.7B",
        "qwen_asr_api_provider": "qwen31_filetrans",
        "qwen_asr_api_protocol": "dashscope_filetrans",
        "qwen_asr_api_model": "qwen-audio-3.1-asr-flash-filetrans",
        "qwen_asr_api_url": "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription",
        # 三十九轮：转写风格。clean=去语气词（字幕/纪要，默认）；verbatim=
        # 逐字保留嗯/那个/口误（合规/质检）。API 侧映射 MAI transcribeStyle，
        # 本地侧门控孤立语气词省略。
        "api_transcribe_style": "clean",
        "speaker_source": "moss",
        "asr_vocabulary_id": "",
        "asr_vocabulary_model": "",
        # 四十轮：OSS 临时音频中转（Qwen filetrans 需要公网 URL）。
        # 区域提供示例；存储桶必须由每位用户填写自己的实例。
        # AccessKey ID/Secret 不在这里——走 DPAPI（llm_config.save_oss_credentials）。
        "oss_region": "cn-hangzhou",
        "oss_endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
        "oss_bucket": "",
        "oss_prefix": "asr-temp/",
        "oss_signed_url_ttl": 86400,
        "oss_auto_delete": True,
        "firered_asr_backend": "local",
        "polish_transport": "openai_compatible",
        "polish_protocol": "auto",
        "polish_provider": "bailian",
        "polish_model": "qwen3.7-flash-2026-07-15",
        "polish_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "polish_capabilities": ["text", "structured_output"],
        "polish_json_mode": True,
        "polish_structured_output": True,
        "group_transport": "openai_compatible",
        "group_protocol": "auto",
        "group_provider": "bailian",
        "group_model": "qwen3.7-flash-2026-07-15",
        "group_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "group_capabilities": ["text", "structured_output"],
        "group_json_mode": True,
        "group_structured_output": True,
        "ai_design_timeout_seconds": 150,
        "ai_design_cli_timeout_seconds": 300,
        "ai_design_wait_mode": "long30",
        "ai_design_no_response_seconds": 600,
        "ai_design_read_idle_seconds": 300,
        "ai_service": "",
        "provider_profiles": {},
    },
    "switches": {
        "enable_qwen_asr_reference": True,
        "enable_firered_boundary_refinement": True,
        "show_speaker_labels_in_srt": False,
        "output_review_track": False,
        "output_jianying_txt": False,
        "output_speaker_tracks": False,
        "dialogue_coverage_mode": "all_dialogue",
        "enable_ai_polish": True,
        "use_ai_grouping": True,
        "unified_glm_processing": True,
        "prefer_arabic_numbers": True,
    },
    "cache": {
        "force_refresh_polish": False,
        "force_refresh_group": False,
    },
    "glossary": {
        "content_name": "",
        "selected_glossary": "",
        "enabled_glossary_ids": [],
        "enable_domain_terms": False,
    },
    "ui": {
        "language": "zh",
        "reduce_motion": False,
    },
    # Spoken language of the media and the subtitles to produce (not the UI language).
    "subtitle_language": {
        "recognition_language": "auto",
        "output": "original",
        "translation_script": "zh-Hans",
    },
    "performance": {
        "parallel_cloud_batches": True,
        "cloud_batch_workers": 4,
        "parallel_cpu_vad": True,
        # Compatibility keys retained; MOSS scheduling ignores both legacy values.
        "moss_parallel_workers": 1,
        "moss_parallel_min_vram_gb": 14,
        "qwen_asr_batch_size": 8,
        "parallel_gpu_asr": True,
        "parallel_gpu_asr_min_vram_gb": 14,
    },
}


def _legacy_settings_candidates():
    """Old settings locations, checked only to migrate into the stable root."""
    if os.environ.get('TWOBYTEASR_TEST_ROOT'):
        return []
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parents[1] / SETTINGS_FILENAME)
    except OSError:
        pass
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / SETTINGS_FILENAME)
    return candidates


def stable_settings_root():
    """Mutable config root shared by source, frozen GUI and workers.

    A packaged install directory is rewritten by every build/update, so the
    user's provider configuration must not live there. The frozen root follows
    runtime_paths.user_data_root() (honors 2BYTEASR_USER_DATA_ROOT) so tests,
    audits and the runtime registry share one data root.
    """
    if os.environ.get('TWOBYTEASR_TEST_ROOT'):
        from .test_isolation import isolation_root
        return isolation_root() / 'config'
    try:
        from twobyteasr.runtime_paths import user_data_root

        return Path(user_data_root())
    except Exception:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "2ByteASR"


def project_settings_path(project_root=None):
    root = Path(project_root) if project_root else stable_settings_root()
    return root / SETTINGS_FILENAME


def _migrate_settings_into_stable_root(path):
    """Idempotently import intact legacy bytes; retain the source as recovery.

    A partial write (for example ENOSPC) must never become a settings file that
    the next startup mistakes for an empty/default configuration.
    """
    if path.is_file():
        return
    stable_root = stable_settings_root()
    for candidate in _legacy_settings_candidates():
        if not candidate.is_file() or candidate.parent == stable_root:
            continue
        temporary = None
        try:
            raw = candidate.read_bytes()
            if not isinstance(json.loads(raw.decode("utf-8-sig")), dict):
                raise ValueError("settings file root must be a JSON object")
            stable_root.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(
                prefix=f".{path.name}.legacy-", suffix=".tmp", dir=path.parent,
            )
            with os.fdopen(handle, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Another startup may have completed the same import meanwhile.
            if not path.exists():
                os.replace(temporary, path)
            return
        except (OSError, ValueError, UnicodeError) as exc:
            raise RuntimeError(
                f"无法迁移旧设置 {candidate} 到 {path}：{exc}。旧设置保留；未写入默认值。"
            ) from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass


def _merge_known_settings(defaults, payload):
    result = copy.deepcopy(defaults)
    if not isinstance(payload, dict):
        return result, ["settings file root must be a JSON object"]
    warnings = []
    for section, values in defaults.items():
        if section == "schema_version":
            continue
        supplied = payload.get(section, {})
        if not isinstance(supplied, dict):
            warnings.append(f"{section} must be a JSON object; defaults were used")
            continue
        for key, default in values.items():
            value = supplied.get(key, default)
            if isinstance(default, bool):
                if isinstance(value, bool):
                    result[section][key] = value
                else:
                    warnings.append(f"{section}.{key} must be true or false; default was used")
            elif isinstance(default, str):
                if isinstance(value, str) and value.strip():
                    result[section][key] = value.strip()
                elif isinstance(value, str) and default == "":
                    result[section][key] = ""
                elif section == "glossary" and key in {"content_name", "selected_glossary"}:
                    # 可空字符串字段：允许空（未选择内容/词库是合法状态）。
                    result[section][key] = str(value or "")
                elif key == "ai_service":
                    # 活动 Provider 服务 id：空表示尚未显式选择（按旧字段推导）。
                    result[section][key] = str(value or "").strip()
                elif section == "models" and key in {
                    "group_model", "group_base_url", "polish_model", "polish_base_url", "qwen_asr_api_model", "asr_vocabulary_id", "asr_vocabulary_model"
                } and isinstance(value, str):
                    # Empty is an explicit endpoint choice (including the CLI's
                    # default model), not permission to resurrect an API default.
                    result[section][key] = value.strip()
                else:
                    warnings.append(f"{section}.{key} must be a non-empty string; default was used")
            elif isinstance(default, dict):
                # Provider profile 等结构化字段：只接受字符串键的对象，值保持原样。
                if isinstance(value, dict):
                    result[section][key] = {
                        str(item_key): item_value
                        for item_key, item_value in value.items()
                    }
                elif value == default:
                    pass
                else:
                    warnings.append(f"{section}.{key} must be a JSON object; default was used")
            elif isinstance(default, int):
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    result[section][key] = value
                else:
                    warnings.append(f"{section}.{key} must be a positive integer; default was used")
            elif isinstance(default, list):
                # 多词库等 list[str] 字段：只接受非空字符串元素，去重保序。
                if isinstance(value, list):
                    cleaned = []
                    seen = set()
                    for item in value:
                        if isinstance(item, str) and item.strip() and item not in seen:
                            cleaned.append(item.strip())
                            seen.add(item)
                    result[section][key] = cleaned
                else:
                    warnings.append(f"{section}.{key} must be a list; default was used")
    # 迁移：旧设置没有 glossary 段。enabled_glossary_ids 为空时从
    # selected_glossary / content_name 派生单元素列表，保持旧用户行为不变。
    supplied_glossary = payload.get("glossary", {}) if isinstance(payload, dict) else {}
    if isinstance(supplied_glossary, dict):
        if "enabled_glossary_ids" not in supplied_glossary:
            legacy_selection = str(supplied_glossary.get("selected_glossary", "") or "").strip()
            if not legacy_selection:
                legacy_selection = str(supplied_glossary.get("content_name", "") or "").strip()
            if legacy_selection:
                result["glossary"]["enabled_glossary_ids"] = [legacy_selection]
        if "enable_domain_terms" not in supplied_glossary:
            result["glossary"]["enable_domain_terms"] = bool(
                result["glossary"]["enabled_glossary_ids"]
            )
    # Resolve legacy shared profiles before filling missing role fields can make
    # an invented default look like a complete, explicitly saved role. Once the
    # role has been saved, ordinary loads never reapply the shared profile.
    supplied_models = payload.get("models", {})
    if isinstance(supplied_models, dict) and supplied_models.get("ai_service"):
        from .llm_config import AI_SERVICE_SPECS, active_service_values
        if supplied_models["ai_service"] in AI_SERVICE_SPECS:
            for role in ("polish", "group"):
                if all(f"{role}_{key}" in supplied_models for key in
                       ("provider", "model", "transport", "base_url")):
                    continue
                endpoint = active_service_values(payload, stage=role)
                for key in ("provider", "model", "transport", "base_url", "protocol", "capabilities"):
                    result["models"][f"{role}_{key}"] = copy.deepcopy(endpoint[key])
                warnings.append(f"models.{role}_* migrated from the saved legacy AI service")
    allowed_backends = {
        "primary_asr_backend": {
            "moss",
            "firered",
            "qwen_local",
            "firered_llm",
            "whisper_turbo",
            "sensevoice",
            "paraformer",
            "funasr_nano",
            "glm_asr_nano",
            "canary_qwen",
            "api",
            "none",
        },
        "qwen_asr_backend": {
            "api", "local", "firered_llm", "whisper_turbo", "sensevoice", "funasr_nano", "off"
        },
        "firered_asr_backend": {"local", "qwen_aligner", "whisper_turbo", "paraformer", "off"},
    }
    for key, allowed in allowed_backends.items():
        value = result["models"][key]
        if value not in allowed:
            result["models"][key] = defaults["models"][key]
            warnings.append(
                f"models.{key} must be one of {sorted(allowed)}; default was used"
            )
    allowed_language = {"recognition_language": {"auto", "zh", "ja"},
                        "output": {"original", "translation", "bilingual"},
                        "translation_script": {"zh-Hans", "zh-Hant"}}
    for key, allowed in allowed_language.items():
        if result["subtitle_language"].get(key) not in allowed:
            result["subtitle_language"][key] = defaults["subtitle_language"][key]
            warnings.append(f"subtitle_language.{key} must be one of {sorted(allowed)}; default was used")
    allowed_transports = {"openai_compatible", "antigravity_cli", "grok_cli", "codex_cli"}
    for key in ("polish_transport", "group_transport"):
        if result["models"][key] not in allowed_transports:
            result["models"][key] = defaults["models"][key]
            warnings.append(f"models.{key} has an unsupported AI transport; default was used")
    allowed_llm_protocols = {"auto", "responses", "chat_completions", "openai_compatible_chat"}
    for key in ("polish_protocol", "group_protocol"):
        if result["models"][key] not in allowed_llm_protocols:
            result["models"][key] = defaults["models"][key]
            warnings.append(f"models.{key} has an unsupported API protocol; default was used")
    allowed_api_protocols = {
        "dashscope_multimodal",
        "openai_transcription",
        "azure_transcription",
        "openrouter_verbose_json",
        "dashscope_filetrans",
        "dashscope_asr_flash",
        "spark_wss",
    }
    # 三十八轮：旧 openrouter multipart 通道已删除——存量配置迁移到字级通道
    # （同模型同端点，请求体升级为 JSON input_audio + word 粒度）。
    if result["models"]["qwen_asr_api_provider"] == "openrouter":
        result["models"]["qwen_asr_api_provider"] = "openrouter_word"
        if result["models"]["qwen_asr_api_protocol"] == "openai_transcription":
            result["models"]["qwen_asr_api_protocol"] = "openrouter_verbose_json"
        warnings.append(
            "models.qwen_asr_api_provider openrouter was migrated to openrouter_word"
            " (word-level timestamps channel)"
        )
    # Retired choices migrate only the cloud-ASR role. Existing endpoint,
    # workspace, OSS, main ASR choice and provider-owned credentials stay owned.
    # Idempotent recognition policy migration. Old speaker_enabled/single/
    # independent-backend values cannot overwrite newly returned ASR labels.
    # The chosen ASR itself is never changed.
    from .speaker_strategy import resolve
    result["models"]["speaker_source"] = resolve(result)
    cloud = result["models"]
    retired_qwen = {"qwen_filetrans", "qwen31_flash", "dashscope_qwen_audio"}
    # Only this former preset/model pair is automatically upgraded. A user
    # supplied deployment or an unrelated provider is never renamed here.
    legacy_short = (cloud.get("qwen_asr_api_provider") == "dashscope"
                    and cloud.get("qwen_asr_api_model") == "qwen3-asr-flash")
    if cloud.get("qwen_asr_api_provider") in retired_qwen or legacy_short:
        old_provider = cloud["qwen_asr_api_provider"]
        cloud["qwen_asr_api_provider"] = "qwen31_filetrans"
        cloud["qwen_asr_api_protocol"] = "dashscope_filetrans"
        cloud["qwen_asr_api_model"] = "qwen-audio-3.1-asr-flash-filetrans"
        # A short-audio multimodal endpoint cannot accept asynchronous jobs.
        # Keep the same service host/workspace and only change its protocol path.
        url = str(cloud.get("qwen_asr_api_url") or "")
        suffix = "/api/v1/services/aigc/multimodal-generation/generation"
        if url.endswith(suffix):
            cloud["qwen_asr_api_url"] = url[:-len(suffix)] + "/api/v1/services/audio/asr/transcription"
        warnings.append(f"cloud ASR {old_provider} migrated to Qwen Audio 3.1 Filetrans; endpoint ownership retained")
    if cloud.get("qwen_asr_api_provider") in {"openrouter_word", "azure"} and cloud.get("qwen_asr_api_model") == "microsoft/mai-transcribe-2":
        cloud["qwen_asr_api_model"] = ""
        warnings.append("MAI 2.1 requires a provider-confirmed model ID; former 2 ID is not claimed as latest")
    if result["models"]["qwen_asr_api_protocol"] not in allowed_api_protocols:
        result["models"]["qwen_asr_api_protocol"] = defaults["models"]["qwen_asr_api_protocol"]
        warnings.append(
            "models.qwen_asr_api_protocol must be dashscope_multimodal, openai_transcription,"
            " azure_transcription, openrouter_verbose_json or dashscope_filetrans; default was used"
        )
    # 四十轮：OSS 临时中转配置（非密钥字段；凭据在 DPAPI）。
    for key in ("oss_region", "oss_endpoint", "oss_bucket"):
        value = str(result["models"].get(key, "") or "").strip()
        if value != result["models"].get(key):
            result["models"][key] = value
    prefix = str(result["models"].get("oss_prefix") or "asr-temp/").strip().lstrip("/")
    result["models"]["oss_prefix"] = prefix if prefix.endswith("/") else prefix + "/"
    endpoint_value = str(result["models"].get("oss_endpoint") or "").strip()
    if endpoint_value and not endpoint_value.lower().startswith("https://"):
        result["models"]["oss_endpoint"] = defaults["models"]["oss_endpoint"]
        warnings.append("models.oss_endpoint must be an https URL; default was used")
    try:
        ttl = int(result["models"].get("oss_signed_url_ttl") or 86400)
    except (TypeError, ValueError):
        ttl = 86400
    result["models"]["oss_signed_url_ttl"] = min(604800, max(300, ttl))
    raw_auto_delete = result["models"].get("oss_auto_delete", True)
    if not isinstance(raw_auto_delete, bool):
        result["models"]["oss_auto_delete"] = (
            str(raw_auto_delete).strip().lower() not in {"false", "0", "no", "off"}
        )
    if result["models"].get("api_transcribe_style") not in {"clean", "verbatim"}:
        result["models"]["api_transcribe_style"] = "clean"
        warnings.append(
            "models.api_transcribe_style must be clean or verbatim; default was used"
        )
    allowed_dialogue_modes = {"all_dialogue", "host_priority", "host_only"}
    if result["switches"]["dialogue_coverage_mode"] not in allowed_dialogue_modes:
        result["switches"]["dialogue_coverage_mode"] = defaults["switches"][
            "dialogue_coverage_mode"
        ]
        warnings.append(
            "switches.dialogue_coverage_mode must be all_dialogue, host_priority or host_only; default was used"
        )

    # 旧设置只有布尔开关。首次升级时保留用户原来的开/关意图。
    supplied_models = payload.get("models", {}) if isinstance(payload, dict) else {}
    supplied_switches = payload.get("switches", {}) if isinstance(payload, dict) else {}
    if "qwen_asr_backend" not in supplied_models and supplied_switches.get(
        "enable_qwen_asr_reference"
    ) is False:
        result["models"]["qwen_asr_backend"] = "off"
    if "firered_asr_backend" not in supplied_models and supplied_switches.get(
        "enable_firered_boundary_refinement"
    ) is False:
        result["models"]["firered_asr_backend"] = "off"
    return result, warnings


def load_runtime_settings(project_root=None):
    """Return validated settings, source path and non-fatal validation warnings."""
    path = project_settings_path(project_root)
    if not project_root:
        _migrate_settings_into_stable_root(path)
    if not path.is_file():
        return copy.deepcopy(DEFAULT_SETTINGS), str(path), ["settings file was not found; defaults were used"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return copy.deepcopy(DEFAULT_SETTINGS), str(path), [f"settings file could not be read: {exc}"]
    settings, warnings = _merge_known_settings(DEFAULT_SETTINGS, payload)
    if not isinstance(payload, dict):
        return settings, str(path), warnings
    if payload.get("schema_version", 1) != 1:
        warnings.append("unsupported schema_version; known settings were loaded")
    return settings, str(path), warnings


def save_runtime_settings(settings, project_root=None):
    """Persist validated non-secret settings with an atomic replace."""
    validated, warnings = _merge_known_settings(DEFAULT_SETTINGS, settings)
    validated["schema_version"] = 1
    path = project_settings_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(validated, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return validated, str(path), warnings
