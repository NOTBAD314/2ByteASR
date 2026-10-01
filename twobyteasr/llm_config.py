"""Non-secret endpoint settings and local-only LLM credential storage."""

from __future__ import annotations

import copy
import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

_SESSION_SECRETS: dict[str, dict] = {}
_SESSION_SECRETS_LOCK = threading.RLock()


def session_credentials_enabled() -> bool:
    return sys.platform == 'darwin'


def clear_session_secrets() -> None:
    with _SESSION_SECRETS_LOCK:
        _SESSION_SECRETS.clear()


def credential_storage_notice(language: str | None = None) -> str:
    if not session_credentials_enabled():
        return '密钥使用 Windows DPAPI 加密保存在本机。'
    if language is None:
        from .i18n import current_language
        language = current_language()
    return {
        'en': 'Keys are kept for this session only and are cleared when the app quits. Keychain is not available yet.',
        'ja': 'キーは今回のセッションのみ保持し、アプリ終了時に消去します。Keychain 保存は未対応です。',
    }.get(language, '密钥仅保留在本次会话，退出软件后清除；Keychain 持久保存尚未实现。')


PROVIDER_PRESETS = {
    "deepseek": {
        "label": "DeepSeek API",
        "base_url": "https://api.deepseek.com/v1",
    },
    "openai": {
        "label": "OpenAI API",
        "base_url": "https://api.openai.com/v1",
    },
    "gemini": {
        "label": "Gemini API",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    },
    "xai": {
        "label": "xAI API",
        "base_url": "https://api.x.ai/v1",
    },
    "bailian": {
        "label": "阿里云百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "openai_compatible": {
        "label": "OpenAI 兼容",
        "base_url": "https://api.openai.com/v1",
    },
    "custom": {
        "label": "自定义服务",
        "base_url": "",
    },
}


# Shared by the Settings endpoint editor and the compact Studio AI Design
# selector.  Endpoint credentials remain provider-scoped in the existing
# secret store; this catalog contains non-secret connection defaults only.
AI_SERVICE_SPECS = {
    "deepseek": {
        "label": "DeepSeek API", "transport": "openai_compatible",
        "provider": "deepseek", "base_url": "https://api.deepseek.com/v1",
        # Registry fallback only. Live Studio selectors merge the provider's
        # own /models listing (discover_models) on top of this list.
        "model": "deepseek-v4-flash",
        "models": ("deepseek-v4-flash", "deepseek-v4-pro"),
        "capabilities": ("text", "vision", "structured_output"),
    },
    "openai": {
        "label": "OpenAI API", "transport": "openai_compatible",
        "provider": "openai", "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini", "models": ("gpt-4.1-mini",),
        "capabilities": ("text", "vision", "structured_output"),
    },
    "gemini": {
        "label": "Gemini API", "transport": "openai_compatible",
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.7-flash-high",
        "models": ("gemini-3.7-flash-high", "gemini-2.5-flash"),
        "capabilities": ("text", "vision", "structured_output"),
    },
    "antigravity": {
        "label": "Google Antigravity", "transport": "antigravity_cli",
        "provider": "google_antigravity", "base_url": "", "model": "",
        "models": ("gemini-3.8-flash-high", "gemini-3.7-flash-high"),
        "capabilities": ("text", "vision", "structured_output"),
    },
    "grok_account": {
        "label": "Grok Account", "transport": "grok_cli",
        "provider": "grok_oauth", "base_url": "", "model": "",
        "models": (), "capabilities": ("text", "structured_output"),
    },
    "codex_cli": {
        "label": "OpenAI Codex CLI", "transport": "codex_cli",
        "provider": "openai_codex_cli", "base_url": "", "model": "",
        "models": (), "capabilities": ("text", "structured_output"),
    },
    "xai": {
        "label": "xAI API", "transport": "openai_compatible",
        "provider": "xai", "base_url": "https://api.x.ai/v1",
        "model": "grok-4-latest", "models": ("grok-4-latest",),
        "capabilities": ("text", "structured_output"),
    },
    "custom": {
        "label": "自定义 OpenAI-Compatible", "transport": "openai_compatible",
        "provider": "custom", "base_url": "", "model": "", "models": (),
        "capabilities": ("text", "structured_output"),
    },
    "bailian": {
        "label": "阿里云百炼（保留）", "transport": "openai_compatible",
        "provider": "bailian",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.7-flash-2026-07-15",
        "models": ("qwen3.7-flash-2026-07-15", "qwen3-max"),
        "capabilities": ("text", "vision", "structured_output"),
    },
}

STAGE_SECRET_NAMES = {
    "polish": ("POLISH_LLM_API_KEY", "DASHSCOPE_API_KEY", "2BYTEASR_DASHSCOPE_API_KEY"),
    "group": ("GROUP_LLM_API_KEY", "DASHSCOPE_API_KEY", "2BYTEASR_DASHSCOPE_API_KEY"),
    "qwen_asr": ("QWEN_ASR_API_KEY", "DASHSCOPE_API_KEY", "2BYTEASR_DASHSCOPE_API_KEY"),
}


def secrets_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "2ByteASR" / "secrets.dat"


def legacy_secrets_path() -> Path:
    return secrets_path().with_name("secrets.json")


def old_project_secrets_path() -> Path:
    """项目改名前（QwenASR 目录）保存的 DPAPI 密钥文件，用于一次性迁移。"""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "QwenASR" / "secrets.dat"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return (
        _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))),
        buffer,
    )


def _dpapi(operation: str, data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("本机密钥存储只支持 Windows DPAPI。")
    source, source_buffer = _blob(data)
    destination = _DataBlob()
    # use_last_error=True 让 ctypes.get_last_error() 返回真实错误码；
    # 默认 windll 不带错误追踪，失败时错误码恒为 0，排障信息失真。
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if operation == "protect":
        ok = crypt32.CryptProtectData(
            ctypes.byref(source),
            "2ByteASR local secrets",
            None,
            None,
            None,
            flags,
            ctypes.byref(destination),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(destination),
        )
    del source_buffer
    if not ok:
        raise OSError(ctypes.get_last_error(), "Windows DPAPI operation failed")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


def _decode_payload(data: bytes) -> dict:
    payload = json.loads(data.decode("utf-8"))
    return payload if isinstance(payload, dict) else {"schema": 2}


def _write_encrypted_secrets(payload: dict) -> Path:
    path = secrets_path()
    if session_credentials_enabled():
        with _SESSION_SECRETS_LOCK:
            _SESSION_SECRETS[str(path)] = copy.deepcopy(payload)
        # Preserve the public API's return type without creating a file.
        # macOS callers display the explicit session-only storage notice.
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        protected = _dpapi("protect", plaintext)
        with os.fdopen(handle, "wb") as stream:
            stream.write(protected)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            legacy_secrets_path().unlink()
        except OSError:
            pass
    except BaseException:
        try:
            os.close(handle)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def _read_secrets(*, read_only_path: Path | None = None) -> dict:
    if session_credentials_enabled():
        # Never import or migrate a plaintext/Windows secrets file on Mac.
        if read_only_path is not None:
            return {'schema': 2}
        with _SESSION_SECRETS_LOCK:
            return copy.deepcopy(_SESSION_SECRETS.get(str(secrets_path()), {'schema': 2}))
    try:
        if read_only_path is not None:
            # Isolated acceptance can use the application's existing store
            # without copying credentials or migrating/modifying its source.
            return _decode_payload(_dpapi("unprotect", Path(read_only_path).read_bytes()))
        path = secrets_path()
        if path.is_file():
            return _decode_payload(_dpapi("unprotect", path.read_bytes()))
        old_path = old_project_secrets_path()
        if old_path.is_file():
            # 项目改名（QwenASR -> 2ByteASR）后的密钥迁移；DPAPI 为当前用户级加密，可直接复制。
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(old_path.read_bytes())
            payload = _decode_payload(_dpapi("unprotect", path.read_bytes()))
            try:
                old_path.unlink()
            except OSError:
                pass
            return payload
        payload = json.loads(legacy_secrets_path().read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["schema"] = 2
            _write_encrypted_secrets(payload)
    except (OSError, ValueError, TypeError):
        return {"schema": 2}
    return payload if isinstance(payload, dict) else {"schema": 2}


def read_secret_value(*names: str) -> tuple[str, str]:
    # The per-user encrypted store is authoritative.  Environment variables
    # are an explicit deployment fallback, never an override for a credential
    # the user saved in 2ByteASR.
    payload = _read_secrets()
    for name in names:
        value = str(payload.get(name, "") or "").strip()
        if value:
            label = '当前会话' if session_credentials_enabled() else 'Windows DPAPI'
            return value, f"{label} / {name}"
    for name in names:
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value, f"环境变量 {name}"
    return "", "未配置"


def resolve_api_key(stage: str) -> tuple[str, str]:
    return read_secret_value(*STAGE_SECRET_NAMES[stage])


def save_api_keys(
    *,
    polish_key: str = "",
    group_key: str = "",
    qwen_asr_key: str = "",
    share_key: bool = False,
) -> Path:
    """Save only values explicitly entered by the user; blank fields preserve current keys."""
    payload = _read_secrets()
    payload["schema"] = 2
    polish_key = str(polish_key or "").strip()
    group_key = str(group_key or "").strip()
    qwen_asr_key = str(qwen_asr_key or "").strip()
    if polish_key:
        payload["POLISH_LLM_API_KEY"] = polish_key
    if share_key and polish_key:
        payload["GROUP_LLM_API_KEY"] = polish_key
    elif group_key:
        payload["GROUP_LLM_API_KEY"] = group_key
    if qwen_asr_key:
        payload["QWEN_ASR_API_KEY"] = qwen_asr_key

    return _write_encrypted_secrets(payload)


def asr_api_display(endpoint: dict) -> str:
    """User-facing name for the active ASR API in logs: 服务商 · 模型."""
    try:
        from .ui import ASR_API_PRESETS

        provider = str(endpoint.get("provider") or "dashscope")
        preset = ASR_API_PRESETS.get(provider, {})
        label = str(preset.get("short") or preset.get("label") or provider)
        model_id = str(endpoint.get("model") or "")
        return f"{label} · {model_id}" if model_id else label
    except Exception:
        return str(endpoint.get("model") or "ASR API")


def read_asr_api_key(provider: str, base_url: str = "") -> tuple[str, str]:
    """Provider-scoped ASR key read.

    三十三轮根因：保存按 save_api_key_for(provider, url) 分存，而读取全走
    resolve_api_key("qwen_asr") 的 legacy 常量桶（QWEN_ASR_API_KEY）——
    切换服务商后运行时带着别家 key（HTTP 401）、工坊状态永远停在
    "configure"（重复弹 key 窗）。统一走本函数；dashscope 保留 legacy
    回填（read_api_key 内置），其余服务商不回退 legacy，避免串 key。
    """

    if provider=='spark_asr_v2':
        values=read_spark_credentials(base_url)
        return (values['api_key'] if all(values.values()) else ''),'Spark scoped credentials'
    return read_api_key(str(provider or "dashscope"), str(base_url or ""))


def qwen_asr_endpoint_from_settings(settings: dict) -> dict:
    models = settings.get("models", {})
    api_key, key_source = read_asr_api_key(
        str(models.get("qwen_asr_api_provider", "dashscope") or "dashscope"),
        str(models.get("qwen_asr_api_url", "") or ""),
    )
    endpoint = {
        "provider": str(models.get("qwen_asr_api_provider", "dashscope") or "dashscope").strip(),
        "protocol": str(models.get("qwen_asr_api_protocol", "dashscope_multimodal") or "dashscope_multimodal").strip(),
        "model": str(models.get("qwen_asr_api_model", "qwen3-asr-flash") or "").strip(),
        "url": str(models.get("qwen_asr_api_url", "") or "").strip().rstrip("/"),
        "api_key": api_key,
        "key_source": key_source,
        # 三十九轮：转写风格（clean|verbatim）。OpenRouter MAI 通道映射为
        # provider.options.azure.modelOptions.transcribeStyle；本地门控语气词省略。
        "style": str(models.get("api_transcribe_style", "clean") or "clean").strip(),
    }
    if endpoint['protocol']=='spark_wss':
        endpoint.update(read_spark_credentials(endpoint['url']))
    return endpoint


def read_spark_credentials(url: str) -> dict:
    scope=_provider_key_id('spark_asr_v2',url)
    return {key:read_secret_value(scope+'__'+key.upper())[0]
            for key in ('app_id','api_key','api_secret')}


def save_spark_credentials(url: str, **values) -> Path:
    payload=_read_secrets();payload['schema']=2
    scope=_provider_key_id('spark_asr_v2',url)
    for key in ('app_id','api_key','api_secret'):
        value=str(values.get(key) or '').strip()
        if value:payload[scope+'__'+key.upper()]=value
    return _write_encrypted_secrets(payload)


def validate_qwen_asr_endpoint(endpoint: dict, *, require_key: bool = True) -> None:
    if endpoint.get('protocol')=='spark_wss':
        from .spark_asr import URL, MODEL
        if endpoint.get('url')!=URL or endpoint.get('model')!=MODEL:
            raise RuntimeError('Spark-ASR V2 需要官方 V2 WSS 地址及 spark_asr_v2 模型。')
        if require_key and not all(endpoint.get(key) for key in ('app_id','api_key','api_secret')):
            raise RuntimeError('Spark-ASR V2 需要 AppID、APIKey 和 APISecret。')
        return
    if endpoint.get("protocol", "dashscope_multimodal") not in {
        "dashscope_multimodal", "openai_transcription", "azure_transcription",
        "openrouter_verbose_json", "dashscope_filetrans", "dashscope_asr_flash",
    }:
        raise RuntimeError("ASR API 协议无效。")
    # Azure 部署地址必须带 ?api-version= 查询参数，其余协议仍禁 query。
    if not str(endpoint.get("model", "")).strip():
        raise RuntimeError("ASR API 缺少模型名称。")
    validate_transport_url(
        str(endpoint.get("url", "")),
        "ASR API",
        allow_query=str(endpoint.get("protocol")) == "azure_transcription",
    )
    if require_key and not str(endpoint.get("api_key", "")).strip():
        provider = str(endpoint.get("provider") or "dashscope")
        raise RuntimeError(
            f"ASR API 缺少密钥。请填写 {provider} 服务商的 API Key。"
        )


def normalize_base_url(value: str) -> str:
    """Normalize the user-facing Base URL, never a concrete chat endpoint.

    Older settings occasionally contained the endpoint itself (including the
    singular ``chat/completion`` typo).  Accept those values for migration,
    while preserving a provider path such as ``/v1``.
    """
    base = str(value or "").strip().rstrip("/")
    lowered = base.lower()
    for suffix in ("/chat/completions", "/chat/completion"):
        if lowered.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            lowered = base.lower()
            break
    # A repeated version segment is never useful for the OpenAI-compatible
    # routes this application supports and otherwise produces /v1/v1/... URLs.
    while lowered.endswith("/v1/v1"):
        base = base[:-3].rstrip("/")
        lowered = base.lower()
    return base


def chat_completion_url(base_url: str) -> str:
    """Build the one canonical chat-completion URL from a Base URL."""
    base = normalize_base_url(base_url)
    return f"{base}/chat/completions" if base else ""


def responses_url(base_url: str) -> str:
    """Build the official OpenAI Responses endpoint from a Base URL."""
    base = normalize_base_url(base_url)
    return f"{base}/responses" if base else ""


def models_url(base_url: str) -> str:
    """Build the OpenAI-compatible model-list URL without duplicating /v1.

    Known version mounts (``/v1``, and Gemini's OpenAI-compat ``.../v1beta/openai``)
    already are the API root: append ``/models`` directly. Anything else gets
    the conventional ``/v1/models``.

    四十二轮：ASR 预设地址保存的是**完整转写端点**（如 openrouter 的
    ``/api/v1/audio/transcriptions``）——直接拼 ``/v1/models`` 会得到
    ``…/audio/transcriptions/v1/models``（用户实录 MAI 测试连接 404）。先剥掉
    已知端点后缀还原挂载点，再走原有判定。
    """
    base = normalize_base_url(base_url)
    if not base:
        return ""
    for suffix in (
        "/audio/transcriptions",
        "/transcriptions",
        "/transcription",
        "/chat/completions",
        "/responses",
        "/embeddings",
    ):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    path = urlsplit(base).path.rstrip("/").lower()
    complete_mount = bool(path)
    return f"{base}/models" if complete_mount else f"{base}/v1/models"


# ------------------------------------------------------------------
# Provider profiles (P8C-R3)
# Each provider owns its own endpoint state. The flat polish_*/group_*
# fields stay as the *resolved active* endpoint consumed by the request
# path, but provider identity can only change through
# activate_ai_service() / update_active_profile() below. Editing these
# helpers is the only sanctioned way to avoid cross-provider state leaks.
# ------------------------------------------------------------------

ACTIVE_SERVICE_KEY = "ai_service"
PROFILES_KEY = "provider_profiles"
PROFILE_FIELDS = ("base_url", "model", "protocol")

# 下线模型的墓碑集合：服务端已删除/永久失效的模型 id。任何运行时解析都
# 不得把它当成可调用模型（2026-09-20 实录：识别方案快照里的
# deepseek-v4-flash-vision-exp 每次启动被回灌，任务实际调用死模型）。
# 只允许出现在：用户磁盘上的历史值（读取时拦截）、测试 fixture。
RETIRED_MODEL_IDS = frozenset({
    "deepseek-v4-flash-vision-exp",
})


def model_is_retired(model: object) -> bool:
    return str(model or "").strip().casefold() in RETIRED_MODEL_IDS


_KNOWN_MODEL_PREFIXES = {
    "deepseek": ("deepseek-",),
    "antigravity": ("gemini-",),
    "gemini": ("gemini-",),
}


def _model_is_cross_provider(service_id: str, model: str) -> bool:
    """Reject a known model family from a different provider profile."""
    value = str(model or "").strip().casefold()
    if not value:
        return False
    own_prefixes = _KNOWN_MODEL_PREFIXES.get(service_id, ())
    if any(value.startswith(prefix) for prefix in own_prefixes):
        return False
    for other_id, prefixes in _KNOWN_MODEL_PREFIXES.items():
        if other_id == service_id:
            continue
        if any(value.startswith(prefix) for prefix in prefixes):
            return True
    return False


_discovered_service_models = {}
_discovered_service_lock = threading.Lock()


def _service_discovery_identity(service_id, settings=None):
    from .model_discovery import identity
    spec=AI_SERVICE_SPECS.get(service_id,AI_SERVICE_SPECS['custom'])
    profile=normalize_provider_profile(get_provider_profiles(settings or {}).get(service_id,{}))
    base=profile.get('base_url') or spec.get('base_url','')
    key=read_api_key(spec['provider'],base)[0] if spec['transport']=='openai_compatible' else ''
    for prefix in ('polish','group'):
        values=(settings or {}).get('models',{})
        if (values.get(prefix+'_provider')==spec['provider']
                and normalize_base_url(values.get(prefix+'_base_url',''))==normalize_base_url(base)
                and values.get(prefix+'_api_key')):
            key=values[prefix+'_api_key']
    return identity(service_id,base,key)


def cache_service_models(service_id: str, models, *, settings=None) -> None:
    values=tuple(dict.fromkeys(str(item).strip() for item in models if str(item).strip()))
    if values:
        with _discovered_service_lock:
            _discovered_service_models[_service_discovery_identity(service_id,settings)] = (values,time.time())


def discovered_service_models(service_id: str, settings=None):
    with _discovered_service_lock:
        hit=_discovered_service_models.get(_service_discovery_identity(service_id,settings), ((),0.0))
        return hit if time.time()-hit[1]<300 else ((),0.0)


def service_model_catalog(settings: dict, service_id: str) -> tuple[str, ...]:
    """Return one canonical, provider-scoped model list for every UI.

    Profile values are included only when they belong to the selected model
    family.  This heals legacy mixed state such as DeepSeek + Gemini without
    mutating settings merely by opening a panel.
    """
    service_id = str(service_id or "custom").strip()
    spec = AI_SERVICE_SPECS.get(service_id, AI_SERVICE_SPECS["custom"])
    profiles = get_provider_profiles(settings)
    profile = normalize_provider_profile(profiles.get(service_id, {}))
    values: list[str] = []
    configured = profile.get("model", "")
    if configured:
        values.append(configured)
    discovered, _ = discovered_service_models(service_id,settings)
    values.extend(discovered or tuple(str(item).strip() for item in spec.get("models", ()) if str(item).strip()))
    default = str(spec.get("model") or "").strip()
    if not discovered and default and not _model_is_cross_provider(service_id, default):
        values.append(default)
    return tuple(dict.fromkeys(values))


def service_for_provider(provider: str, transport: str = "") -> str:
    """Best-effort AI_SERVICE_SPECS id for a stored provider value."""
    wanted_provider = str(provider or "").strip()
    wanted_transport = str(transport or "").strip()
    fallback = ""
    for service_id, spec in AI_SERVICE_SPECS.items():
        if str(spec.get("provider")) != wanted_provider:
            continue
        if not wanted_transport or str(spec.get("transport")) == wanted_transport:
            return service_id
        if not fallback:
            fallback = service_id
    return fallback


def get_active_service(settings: dict) -> str:
    """Active AI service id, migrating the legacy flat provider field."""
    models = settings.get("models", {}) if isinstance(settings, dict) else {}
    stored = str(models.get(ACTIVE_SERVICE_KEY, "") or "").strip()
    if stored in AI_SERVICE_SPECS:
        return stored
    migrated = service_for_provider(
        str(models.get("polish_provider", "") or ""),
        str(models.get("polish_transport", "") or ""),
    )
    # 2026-09-02（用户指定）：无任何历史选择时的默认服务用 Grok 账号
    # （登录后即用；agy CLI 冷启动慢、探测易超时）。已有存储选择的用户不受影响。
    return migrated or "grok_account"


def get_provider_profiles(settings: dict) -> dict:
    models = settings.get("models", {}) if isinstance(settings, dict) else {}
    raw = models.get(PROFILES_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def normalize_provider_profile(profile: dict) -> dict:
    profile = profile if isinstance(profile, dict) else {}
    normalized: dict[str, str] = {}
    for field in PROFILE_FIELDS:
        normalized[field] = str(profile.get(field, "") or "").strip()
    return normalized


def resolved_service_values(settings: dict, service_id: str) -> dict:
    """Profile-over-spec endpoint values for one service (no global writes).

    A configured model in the RETIRED tombstone never resolves: the value
    falls through to the catalog/spec default so the request path can never
    dial a server-side-dead model. The UI surfaces the retirement via
    ``model_is_retired`` on the raw profile instead of a magic value here.
    """
    spec = AI_SERVICE_SPECS.get(service_id, AI_SERVICE_SPECS["custom"])
    profile = normalize_provider_profile(get_provider_profiles(settings).get(service_id, {}))
    catalog = service_model_catalog(settings, service_id)
    configured_model = profile.get("model", "")
    model = (
        configured_model
        if configured_model
        else ""
    )
    model = model or (str(spec.get("model") or "") if str(spec.get("transport")) != "openai_compatible"
                      else (catalog[0] if catalog else ""))
    return {
        "service": service_id,
        "transport": str(spec["transport"]),
        "provider": str(spec["provider"]),
        "base_url": normalize_base_url(profile.get("base_url") or spec.get("base_url") or ""),
        "model": model,
        "models": list(catalog),
        "protocol": (profile.get("protocol") or "auto").strip(),
        "capabilities": list(spec.get("capabilities", ())),
    }


def active_service_values(settings: dict, *, stage: str = "polish") -> dict:
    """Resolved endpoint values for the active service (profile wins)."""
    service_id = get_active_service(settings)
    values = resolved_service_values(settings, service_id)
    models = settings.get("models", {}) if isinstance(settings, dict) else {}
    # A service without a saved profile still honors the flat endpoint the
    # user last saved for it (custom endpoints have no spec base_url).
    if not get_provider_profiles(settings).get(service_id):
        prefix = stage if stage in {"polish", "group"} else "polish"
        flat_base = normalize_base_url(str(models.get(f"{prefix}_base_url", "") or ""))
        flat_model = str(models.get(f"{prefix}_model", "") or "").strip()
        leaked = _flat_base_is_cross_provider_leak(service_id, flat_base)
        if flat_base and not leaked and (
            service_id == "custom"
            or flat_base != normalize_base_url(str(AI_SERVICE_SPECS.get(service_id, {}).get("base_url") or ""))
        ):
            values["base_url"] = flat_base
        if flat_model and not leaked and not _model_is_cross_provider(service_id, flat_model) \
                and not model_is_retired(flat_model):
            values["model"] = flat_model
        values["models"] = list(service_model_catalog(settings, service_id))
    return values


def _flat_base_is_cross_provider_leak(service_id: str, flat_base: str) -> bool:
    """True when the stored base_url belongs to a DIFFERENT known provider.

    Mixed legacy state (for example provider=deepseek with a Google base URL)
    must not be inherited by the profile resolution: heal to the service's own
    spec endpoint instead.
    """
    base = normalize_base_url(flat_base or "")
    if not base or service_id == "custom":
        return False
    try:
        host = (urlsplit(base).netloc or "").lower()
    except Exception:
        return False
    if not host:
        return False
    own = normalize_base_url(str(AI_SERVICE_SPECS.get(service_id, {}).get("base_url") or ""))
    if base == own:
        return False
    for other_id, spec in AI_SERVICE_SPECS.items():
        if other_id == service_id:
            continue
        other = normalize_base_url(str(spec.get("base_url") or ""))
        if other and (urlsplit(other).netloc or "").lower() == host:
            return True
    return False


def supports_model_discovery(service_id: str) -> bool:
    spec = AI_SERVICE_SPECS.get(service_id or "custom", {})
    return str(spec.get("transport") or "") in {
        "openai_compatible",
        "antigravity_cli",
        "grok_cli",
        "codex_cli",
    }


def _stage_write_prefixes(stage: str, *, unified: bool) -> tuple[str, ...]:
    prefixes = [stage if stage in {"polish", "group"} else "polish"]
    if unified and "group" not in prefixes:
        prefixes.append("group")
    return tuple(prefixes)


def activate_ai_service(
    settings: dict,
    service_id: str,
    *,
    stage: str = "polish",
    unified: bool | None = None,
) -> dict:
    """Atomically load one provider profile into the resolved flat fields.

    This is the only function that may change provider identity fields
    (provider/base_url/model/transport/protocol/capabilities). It writes
    every field in one transaction so a switch can never leave a mixed
    provider/base/model state behind.
    """
    if service_id not in AI_SERVICE_SPECS:
        service_id = "custom"
    if unified is None:
        unified = bool(
            settings.get("switches", {}).get("unified_glm_processing", False)
        ) if isinstance(settings, dict) else False
    values = resolved_service_values(settings, service_id)
    models = settings.setdefault("models", {})
    for prefix in _stage_write_prefixes(stage, unified=unified):
        for key, value in values.items():
            if key == "service":
                continue
            models[f"{prefix}_{key}"] = copy.deepcopy(value) if isinstance(value, list) else value
    models[ACTIVE_SERVICE_KEY] = service_id
    return values


def update_active_profile(
    settings: dict,
    *,
    stage: str = "polish",
    base_url: str | None = None,
    model: str | None = None,
    protocol: str | None = None,
    unified: bool | None = None,
) -> dict:
    """Persist explicit edits into the active provider profile and flat fields."""
    if unified is None:
        unified = bool(
            settings.get("switches", {}).get("unified_glm_processing", False)
        ) if isinstance(settings, dict) else False
    service_id = get_active_service(settings)
    spec = AI_SERVICE_SPECS.get(service_id, AI_SERVICE_SPECS["custom"])
    models = settings.setdefault("models", {})
    profiles = models.setdefault(PROFILES_KEY, {})
    if not isinstance(profiles, dict):
        profiles = {}
        models[PROFILES_KEY] = profiles
    profile = normalize_provider_profile(profiles.get(service_id, {}))
    if base_url is not None:
        profile["base_url"] = normalize_base_url(base_url)
    if model is not None:
        profile["model"] = str(model or "").strip()
    if protocol is not None:
        profile["protocol"] = str(protocol or "").strip()
    # Empty profile fields fall back to the catalog spec so the profile never
    # shadows a spec default with an empty string.
    for field in PROFILE_FIELDS:
        if not profile[field]:
            profile[field] = str(spec.get(field if field != "base_url" else "base_url") or "")
    profiles[service_id] = profile
    values = resolved_service_values(settings, service_id)
    for prefix in _stage_write_prefixes(stage, unified=unified):
        for key, value in values.items():
            if key == "service":
                continue
            models[f"{prefix}_{key}"] = copy.deepcopy(value) if isinstance(value, list) else value
    models[ACTIVE_SERVICE_KEY] = service_id
    return values


def endpoint_from_settings(settings: dict, stage: str, *, prefer_role: bool = False) -> dict:
    from .asr_provider_snapshot import snapshot_in_settings
    snapshot = snapshot_in_settings(settings)
    if snapshot is not None:
        return snapshot.endpoint()
    models = settings.get("models", {})
    unified_model = bool(
        settings.get("switches", {}).get("unified_glm_processing", False)
    )
    # 统一模式下，字幕校对与全文断句都使用统一模型栏的模型、地址和密钥。
    # 关闭开关后仍保留原先两套端点的自由配置能力。
    prefix = "group" if stage == "polish" and unified_model else (
        "polish" if stage == "polish" else "group"
    )
    credential_stage = "group" if stage == "polish" and unified_model else stage
    provider = str(models.get(f"{prefix}_provider", "bailian") or "bailian")
    base_url = normalize_base_url(models.get(f"{prefix}_base_url", ""))
    model = str(models.get(f"{prefix}_model", "") or "").strip()
    protocol = str(models.get(f"{prefix}_protocol", "auto") or "auto").strip()
    if protocol == "auto":
        protocol = "responses" if provider == "openai" else "openai_compatible_chat"
    ephemeral_key = str(models.get(f"{prefix}_api_key") or "").strip()
    # Preserve old installations whose Bailian key was saved before scoped
    # provider credentials existed. A custom/OpenAI-compatible endpoint must
    # not fall through to that legacy bucket.
    # The active provider profile is the shared runtime source of truth. Older
    # settings may have a valid provider/base URL but a stale model in the flat
    # fields; resolve it here so Home, Studio and Review invoke identically.
    active_id = get_active_service(settings)
    if not prefer_role and active_id in AI_SERVICE_SPECS:
        active_values = active_service_values(settings, stage=stage)
        if stage == "polish" or unified_model:
            provider = str(active_values.get("provider") or provider)
            if str(active_values.get('transport') or '').endswith('_cli'):
                # Blank is the CLI's default selection. Never resurrect the
                # generic API defaults restored by legacy settings validation.
                base_url = normalize_base_url(str(active_values.get('base_url') or ''))
                model = str(active_values.get('model') or '').strip()
            else:
                base_url = normalize_base_url(str(active_values.get("base_url") or base_url))
                model = str(active_values.get("model") or model).strip()
            protocol = str(active_values.get("protocol") or protocol).strip()
            if protocol == "auto":
                protocol = "responses" if provider == "openai" else "openai_compatible_chat"
    # Credential precedence is deliberately resolved only after the active
    # provider/profile has been selected: provider-scoped DPAPI, matching ENV,
    # then the unsaved editor value.  This keeps Home and Studio on the same
    # provider identity and prevents a stale field from shadowing a saved key.
    if ((not prefer_role and str(AI_SERVICE_SPECS.get(active_id,{}).get('transport') or '').endswith('_cli') and (stage=='polish' or unified_model))
            or (prefer_role and str(models.get(f'{prefix}_transport') or '').endswith('_cli'))):
        return {'provider':provider,'model':model,'base_url':'','protocol':protocol,'url':'',
                'api_key':'','key_source':'CLI manages account'}
    api_key, key_source = ((ephemeral_key, '当前输入') if ephemeral_key else read_scoped_api_key(provider, base_url))
    if not api_key and provider in {"bailian", "dashscope"}:
        api_key, key_source = resolve_api_key(credential_stage)
    if not api_key and ephemeral_key:
        api_key, key_source = ephemeral_key, "当前输入"
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "protocol": protocol,
        "url": responses_url(base_url) if protocol == "responses" else chat_completion_url(base_url),
        "api_key": api_key,
        "key_source": key_source,
    }


def endpoint_requires_key(endpoint: dict) -> bool:
    """Only an explicitly selected custom loopback service may omit auth."""
    provider = str(endpoint.get("provider") or "custom").casefold()
    url = str(endpoint.get("base_url") or endpoint.get("url") or "")
    return not (provider in {"custom", "local", "ollama", "lmstudio"}
                and _is_loopback_host(urlsplit(url).hostname))


def auth_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def validate_endpoint(endpoint: dict, label: str = "大模型", *, require_credentials=True) -> None:
    from .i18n import tr, translate
    label = translate(label)
    provider = str(endpoint.get("provider") or "custom")
    model = str(endpoint.get("model", "")).strip()
    if not model:
        raise RuntimeError(tr('{stage}（{provider}）缺少模型名称。请配置此步骤，或关闭此步骤后重新开始。', stage=label, provider=provider))
    if model_is_retired(model):
        raise RuntimeError(
            f"{label}选择的模型 {model} 已不可用（服务商已下线）。"
            "请重新选择当前可用模型后保存。"
        )
    base_url = str(endpoint.get("base_url", ""))
    validate_transport_url(base_url, label)
    if require_credentials and endpoint_requires_key(endpoint) and not str(endpoint.get("api_key", "")).strip():
        raise RuntimeError(tr('{stage}（{provider}）缺少 API 密钥。请配置此步骤，或关闭此步骤后重新开始。', stage=label, provider=provider))


def validate_transport_url(value: str, label: str = "服务", *, allow_query: bool = False) -> None:
    """Require encrypted transport except for an explicit local loopback service.

    ``allow_query`` exists for Azure deployment endpoints, whose REST shape
    REQUIRES a ``?api-version=`` parameter (userinfo stays forbidden).
    """
    base_url = str(value or "").strip()
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise RuntimeError(f"{label}的 API 地址无效。请填写 OpenAI 兼容的 HTTPS 地址。")
    if parsed.username or parsed.password or parsed.fragment:
        raise RuntimeError(f"{label}的 API 地址不能包含账号、密码或片段。")
    if parsed.query and not allow_query:
        raise RuntimeError(f"{label}的 API 地址不能包含账号、密码、查询参数或片段。")
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise RuntimeError(f"{label}只允许 HTTPS；HTTP 仅可用于本机回环地址。")


# ------------------------------------------------------------------
# Provider-scoped API Key storage (P0-3)
# Keys belong to Provider/Endpoint (base URL), not to a concrete model.
# We store under DPAPI secrets using composite ids so that switching
# models inside the same provider keeps the key.
# ------------------------------------------------------------------

def _provider_key_id(provider: str, base_url: str) -> str:
    p = str(provider or "custom").strip().lower().replace(" ", "_")
    b = normalize_base_url(base_url or "")
    host = ""
    try:
        host = (urlsplit(b).netloc or "").lower()
    except Exception:
        host = ""
    if host:
        return f"API__{p}__{host}"
    return f"API__{p}"


_STANDARD_PROVIDER_KEY_ENV = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
}


def _canonical_provider_host(provider: str) -> str:
    """Host of the provider's catalog base_url ('' when unknown/custom)."""
    spec = AI_SERVICE_SPECS.get(str(provider or "").strip())
    if not spec:
        spec = next(
            (
                item
                for item in AI_SERVICE_SPECS.values()
                if str(item.get("provider") or "") == str(provider or "").strip()
            ),
            None,
        )
    base = str((spec or {}).get("base_url") or "")
    if not base:
        return ""
    try:
        return (urlsplit(normalize_base_url(base)).netloc or "").lower()
    except Exception:
        return ""


def read_scoped_api_key(provider: str, base_url: str = "") -> tuple[str, str]:
    """Return only an exact provider/endpoint or same-host credential.

    A key saved under the provider's canonical catalog host also satisfies a
    request for the same provider on a different base URL (for example after
    an older save recorded the key while the UI showed a mixed endpoint).
    It never crosses providers.
    """
    provider = str(provider or "").strip()
    kid = _provider_key_id(provider, base_url)
    val, src = read_secret_value(kid)
    if val:
        return val, src
    base = normalize_base_url(base_url or "")
    try:
        host = (urlsplit(base).netloc or "").lower()
    except Exception:
        host = ""
    if host:
        val, src = read_secret_value(f"API__{host}")
        if val:
            return val, src
    canonical_host = _canonical_provider_host(provider)
    if canonical_host and canonical_host != host:
        val, src = read_secret_value(f"API__{provider}__{canonical_host}")
        if val:
            return val, src
        val, src = read_secret_value(f"API__{canonical_host}")
        if val:
            return val, src
    standard_name = _STANDARD_PROVIDER_KEY_ENV.get(provider.casefold())
    if standard_name:
        val, src = read_secret_value(standard_name)
        if val:
            return val, src
    return "", "未配置"


def read_api_key(provider: str, base_url: str = "") -> tuple[str, str]:
    """Return (key, source) preferring a provider/endpoint-specific secret.

    Ownership rule (per P0 spec):
    - Keys belong to (Provider, BaseURL/Endpoint), not to a model.
    - When a concrete provider+base is requested and a scoped secret exists
      for that exact scope (or its host), return it and DO NOT fall back to
      any legacy stage buckets. This guarantees a key saved for one provider
      is invisible when the UI asks for another provider.
    - Legacy fallback (QWEN_ASR_API_KEY etc.) is only used for the historical
      "unspecified / dashscope default" case when no scoped key is present.
    """
    # 1/2) Exact provider+endpoint or host-scoped key.
    val, src = read_scoped_api_key(provider, base_url)
    if val:
        return val, src

    # 3) Legacy fallback ONLY for the historical default case.
    # If the caller asked for a specific non-empty provider (other than the
    # historical default "dashscope"), we must NOT return a legacy key that
    # was saved for a different provider. This enforces ownership.
    p = str(provider or "").strip().lower()
    # Treat DashScope's preset alias as the historical default path. Other
    # providers must never receive a legacy global key (for example a DeepSeek
    # Base URL accidentally using DASHSCOPE_API_KEY).
    if not p or p in {"dashscope", "bailian"}:
        for legacy in (
            "QWEN_ASR_API_KEY",
            "DASHSCOPE_API_KEY",
            "2BYTEASR_DASHSCOPE_API_KEY",
            "POLISH_LLM_API_KEY",
            "GROUP_LLM_API_KEY",
        ):
            val, src = read_secret_value(legacy)
            if val:
                return val, src

    # No scoped key for the requested (provider, base), and legacy fallback
    # was not applicable or not present.
    return "", "未配置"


def save_api_key_for(provider: str, base_url: str, key: str) -> Path:
    """Persist a non-empty key under a provider/endpoint id. Blank leaves prior value."""
    payload = _read_secrets()
    payload["schema"] = 2
    k = str(key or "").strip()
    if k:
        kid = _provider_key_id(provider, base_url)
        payload[kid] = k
        # Also store by host so different preset labels for same host share the key
        b = normalize_base_url(base_url or "")
        host = ""
        try:
            host = (urlsplit(b).netloc or "").lower()
        except Exception:
            host = ""
        if host:
            payload[f"API__{host}"] = k
        # Keep a canonical-host alias so a key saved under a mistyped/mixed
        # endpoint is still found for this provider's real base URL later.
        canonical_host = _canonical_provider_host(provider)
        if canonical_host:
            payload[f"API__{provider}__{canonical_host}"] = k
            payload[f"API__{canonical_host}"] = k
    return _write_encrypted_secrets(payload)


def read_oss_credentials() -> tuple[str, str]:
    """OSS AccessKey（ID, Secret）。DPAPI 优先，环境变量回退（CI/无头部署）。

    与 DashScope API Key 同级保密：绝不明文写进 settings/config/log/异常。
    """
    key_id = read_secret_value("OSS_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_ID")[0]
    key_secret = read_secret_value(
        "OSS_ACCESS_KEY_SECRET", "ALIBABA_CLOUD_ACCESS_KEY_SECRET"
    )[0]
    return key_id, key_secret


def save_oss_credentials(access_key_id: str, access_key_secret: str) -> Path:
    """保存 OSS AccessKey（DPAPI 加密）；留空字段保持原值。"""
    payload = _read_secrets()
    payload["schema"] = 2
    kid = str(access_key_id or "").strip()
    secret = str(access_key_secret or "").strip()
    if kid:
        payload["OSS_ACCESS_KEY_ID"] = kid
    if secret:
        payload["OSS_ACCESS_KEY_SECRET"] = secret
    return _write_encrypted_secrets(payload)


def delete_api_key_for(provider: str, base_url: str) -> Path:
    """Explicit CLEAR (P8C-R3.1): remove every scoped alias of this key.

    Only called from the user's explicit "清除密钥" action — an empty input
    field never deletes. Standard environment variables are intentionally
    untouched; they keep providing the secret at runtime.
    """
    payload = _read_secrets()
    payload["schema"] = 2
    kid = _provider_key_id(provider, base_url)
    payload.pop(kid, None)
    b = normalize_base_url(base_url or "")
    try:
        host = (urlsplit(b).netloc or "").lower()
    except Exception:
        host = ""
    if host:
        payload.pop(f"API__{host}", None)
    canonical_host = _canonical_provider_host(provider)
    if canonical_host:
        payload.pop(f"API__{provider}__{canonical_host}", None)
        payload.pop(f"API__{canonical_host}", None)
    return _write_encrypted_secrets(payload)


def _is_loopback_host(hostname: str | None) -> bool:
    host = str(hostname or "").strip().strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


# ------------------------------------------------------------------
# OpenAI-compatible /v1/models fetch + small process cache (P0-4)
# ------------------------------------------------------------------

def fetch_openai_compatible_models(base_url: str, api_key: str, *, timeout: float = 12.0, provider='custom', refresh=True) -> list[str]:
    from .model_discovery import discover
    return [r['id'] for r in discover(provider, base_url, api_key, timeout=timeout, force=refresh)['records']]


def get_cached_models(provider: str, base_url: str, *, max_age=300.0, api_key=''):
    from .model_discovery import cached
    hit=cached(provider,base_url,api_key,max_age=max_age)
    return [r['id'] for r in hit['records']] if hit else None


def set_cached_models(provider: str, base_url: str, models: list[str], *, api_key=''):
    from .model_discovery import cached,remember
    hit=cached(provider,base_url,api_key)
    old={r['id']:r for r in (hit or {}).get('records',[])}
    remember(provider,base_url,api_key,[old.get(mid,{'id':mid}) for mid in models])
