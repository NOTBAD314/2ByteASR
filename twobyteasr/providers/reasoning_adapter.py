"""Resolve the thinking controls that go on the wire and evaluate response evidence."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

POLICY_VERSION = "reasoning-v2"
THINKING_PROTOCOLS = (
    "auto", "deepseek", "reasoning_effort", "deepseek_combined",
    "enable_thinking", "openrouter", "anthropic",
)
EFFORT_LEVELS = ("low", "medium", "high", "max")
THINKING_KEYS = frozenset({
    "thinking", "reasoning", "reasoning_effort", "enable_thinking",
    "thinking_budget", "output_config", "extra_body", "generationConfig",
})
_CUSTOM_LEAVES = {
    "thinking": {"type", "budget_tokens", "display"},
    "reasoning": {"enabled", "effort", "max_tokens", "exclude"},
    "output_config": {"effort"},
}
_GEMINI_CHAT = ("extra_body", "google", "thinking_config")
_GEMINI_NATIVE = ("generationConfig", "thinkingConfig")
_REJECT_FIELDS = ("thinking", "reasoning", "enable_thinking", "output_config")


def profile_key(provider, base_url, model, protocol):
    from .asr_provider_snapshot import endpoint_identity
    identity = [str(provider).lower(), endpoint_identity(base_url), str(model).strip(), protocol]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def profile_from_settings(settings, endpoint):
    profiles = settings.get("models", {}).get("reasoning_profiles", {})
    if not isinstance(profiles, dict):
        return ""
    key = profile_key(*(endpoint.get(k, "") for k in ("provider", "base_url", "model", "protocol")))
    return profiles.get(key, "") if isinstance(profiles.get(key), str) else ""


def _nested_controls(controls, path):
    value = controls
    for name in path:
        value = value.get(name, {}) if isinstance(value, dict) else {}
    return value


def _safe_value(key, value):
    if key in {"enabled", "exclude", "enable_thinking", "include_thoughts", "includeThoughts"}:
        return type(value) is bool
    if key in {"budget_tokens", "max_tokens", "thinking_budget", "thinkingBudget"}:
        return type(value) is int and -1 <= value <= 1_000_000
    if not isinstance(value, str):
        return False
    if key == "type":
        return value in {"enabled", "disabled", "adaptive", "between_tools"}
    if key == "display":
        return value in {"summarized", "omitted"}
    if key == "thinkingLevel":
        return value in {"MINIMAL", "LOW", "MEDIUM", "HIGH"}
    return value in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}


def validate_custom(controls):
    """Allow provider thinking fields only. Prevent tokens, prompts and arbitrary strings in receipts."""
    if not isinstance(controls, dict) or set(controls) - THINKING_KEYS:
        raise ValueError("自定义 JSON 只能包含思考控制字段。")
    for key, value in controls.items():
        if key in _CUSTOM_LEAVES:
            allowed = _CUSTOM_LEAVES[key]
        elif key in {"extra_body", "generationConfig"}:
            path = _GEMINI_CHAT if key == "extra_body" else _GEMINI_NATIVE
            leaf = _nested_controls({key: value}, path)
            if (not isinstance(leaf, dict) or not leaf
                    or any(set(_nested_controls({key: value}, path[:i])) != {path[i]}
                           for i in range(1, len(path)))):
                raise ValueError("自定义 Gemini 思考参数结构无效。")
            value = leaf
            allowed = ({"thinking_budget", "thinking_level", "include_thoughts"} if key == "extra_body"
                       else {"thinkingBudget", "thinkingLevel", "includeThoughts"})
        else:
            if not _safe_value(key, value):
                raise ValueError("思考控制参数值无效。")
            continue
        if not isinstance(value, dict) or not value or set(value) - allowed or not all(_safe_value(name, entry) for name, entry in value.items()):
            raise ValueError("思考控制参数内容无效。")
    return controls


def encode_profile(mode, dialect, custom):
    if mode not in {"off", "default", "low", "high", "medium", "max"} or dialect not in THINKING_PROTOCOLS:
        raise ValueError("思考模式或控制协议无效。")
    validate_custom(custom)
    if mode == "default" and custom:
        raise ValueError("使用服务商默认设置时，请清空自定义思考参数。")
    return json.dumps({"mode": mode, "dialect": dialect, "custom": custom}, sort_keys=True, separators=(",", ":"))


def requested_mode(enabled):
    if enabled is None:
        return "default"
    if enabled is False:
        return "off"
    if enabled is True:
        return "high"
    if enabled in EFFORT_LEVELS:
        return enabled
    raise ValueError("思考模式无效。")


def _known_host(base_url):
    return (urlsplit(str(base_url)).hostname or "").lower()


def _official_dialect(host, model, api):
    if host == "api.deepseek.com" and (not model or model.startswith("deepseek-")):
        return "deepseek"
    if host == "openrouter.ai":
        return "openrouter"
    if host == "api.anthropic.com" and api == "anthropic":
        return "anthropic"
    if host == "generativelanguage.googleapis.com" and model.startswith("gemini-"):
        return "gemini_native" if api == "gemini" else "gemini_chat" if api == "chat" else "unknown"
    if re.fullmatch(r"dashscope(?:-[a-z-]+)?\.aliyuncs\.com", host):
        if model.endswith(("-thinking", "-thinking-preview")) or "-thinking-" in model:
            return "required"
        if model.startswith(("qwen3-coder", "qwen2", "qwen-long", "qwen-mt")) or "-instruct" in model:
            return "plain"
        if not model or re.match(r"qwen(?:3|4|-(?:plus|turbo|flash|max)(?:-|$))", model) or model.startswith("deepseek-v4"):
            return "enable_thinking" if api == "chat" else "reasoning_effort"
        if model.startswith(("qwq", "qvq")):
            return "required"
    if host == "api.x.ai":
        if re.match(r"grok-4\.3(?:-|$)", model):
            return "reasoning_effort"
        if re.match(r"grok-4\.[5-7](?:-|$)", model):
            return "required_effort"
    if host == "api.openai.com":
        if re.match(r"gpt-(?:5\.[1-9]|6)(?:[.-]|$)", model) and not re.search(r"-(pro|codex)(?:-|$)", model):
            return "reasoning_effort"
        if re.match(r"(?:o[134]|gpt-5)(?:[.-]|$)", model):
            return "required_effort"
        if model.startswith(("gpt-4", "gpt-3.5")):
            return "plain"
    if api == "chat" and model.startswith("deepseek-") and (
        "workbuddy" in host.split(".") or "codebuddy" in host.split(".")
    ):
        return "deepseek"
    return "unknown"


def _gemini_has_minimal(model):
    return model.startswith(("gemini-3-flash", "gemini-3.1-flash-lite",
                             "gemini-3.5-flash-lite", "gemini-3.6-flash"))


def _effort_fields(api, mode):
    effort = "none" if mode == "off" else mode
    return {"reasoning": {"effort": effort}} if api == "responses" else {"reasoning_effort": effort}


def _dialect_controls(dialect, model, mode, api, max_tokens, has_tools):
    off = mode == "off"
    if dialect == "plain":
        return {}, "fixed_non_reasoning" if off else "unsupported_mode"
    if dialect == "required" or dialect == "required_effort" and off:
        return {}, "disable_not_supported" if off else "unsupported_mode"
    if dialect in {"reasoning_effort", "required_effort"} and api in {"chat", "responses"}:
        return _effort_fields(api, mode), "requested_unverified"
    if dialect == "enable_thinking" and api == "chat":
        return {"enable_thinking": not off}, "requested_unverified" if off else "ungraded_thinking"
    if dialect in {"deepseek", "deepseek_combined"}:
        if api == "responses" and dialect == "deepseek":
            return _effort_fields(api, mode), "requested_unverified"
        if api == "chat" or dialect == "deepseek" and api == "anthropic":
            controls = {"thinking": {"type": "disabled" if off else "enabled"}}
            if off and dialect == "deepseek_combined":
                controls["reasoning_effort"] = "none"
            elif not off:
                controls.update({"output_config": {"effort": mode}} if api == "anthropic" else _effort_fields(api, mode))
            return controls, "requested_unverified"
    if dialect == "openrouter":
        if api == "anthropic":
            return ({"thinking": {"type": "disabled"}} if off else
                    {"thinking": {"type": "adaptive"}, "output_config": {"effort": mode}}), "requested_unverified"
        if api in {"chat", "responses"}:
            controls = {"reasoning": {"enabled": False} if off else {"effort": mode}}
            if api == "chat":
                controls["provider"] = {"require_parameters": True}
            return controls, "requested_unverified"
    if dialect == "anthropic" and api == "anthropic":
        if off:
            if model.startswith("claude-sonnet-5-5"):
                if has_tools:
                    return {}, "disable_not_supported"
                return {"thinking": {"type": "between_tools"}}, "requested_unverified"
            if model.startswith(("claude-opus-5-5", "claude-fable-", "claude-mythos-5")):
                return {}, "disable_not_supported"
            if re.match(r"claude-(?:opus|sonnet|haiku)-(?:[45]|[34]-[57])(?:-|$)", model):
                return {"thinking": {"type": "disabled"}}, "requested_unverified"
        elif re.match(r"claude-(?:opus|sonnet|haiku)-4(?:-[015])?(?:-|$)", model) and not re.match(
                r"claude-(?:opus|sonnet|haiku)-4-[6-9](?:-|$)", model):
            budget = min(1024 if mode == "low" else 8192, max_tokens - 1)
            if budget < 1024:
                return {}, "unsupported_mode"
            return {"thinking": {"type": "enabled", "budget_tokens": budget}}, "requested_unverified"
        elif model.startswith("claude-"):
            return {"thinking": {"type": "adaptive"}, "output_config": {"effort": mode}}, "requested_unverified"
    if dialect in {"gemini_chat", "gemini_native"}:
        if not re.match(r"gemini-(?:2\.5|3[.-]|4[.-])", model):
            return {}, "unsupported_or_unknown"
        if off and not model.startswith("gemini-2.5-flash"):
            return {}, "disable_not_supported"
        if dialect == "gemini_chat":
            if mode == "low" and _gemini_has_minimal(model):
                mode = "minimal"
            return _effort_fields(api, "high" if mode == "max" else mode), "requested_unverified"
        if model.startswith("gemini-2.5"):
            config = {"thinkingBudget": 0 if off else 1024 if mode == "low" else 8192}
        else:
            level = "MINIMAL" if mode == "low" and _gemini_has_minimal(model) else mode.upper()
            config = {"thinkingLevel": "HIGH" if mode == "max" else level}
        return {"generationConfig": {"thinkingConfig": config}}, "requested_unverified"
    return {}, "unsupported_or_unknown"


def _is_disable(controls):
    thinking = controls.get("thinking") or {}
    reasoning = controls.get("reasoning") or {}
    gemini = _nested_controls(controls, _GEMINI_CHAT) or _nested_controls(controls, _GEMINI_NATIVE)
    signals = []
    if "type" in thinking:
        signals.append(thinking["type"] in {"disabled", "between_tools"})
    if "reasoning_effort" in controls:
        signals.append(controls["reasoning_effort"] == "none")
    if "effort" in reasoning:
        signals.append(reasoning["effort"] == "none")
    if "enabled" in reasoning:
        signals.append(reasoning["enabled"] is False)
    if "max_tokens" in reasoning or "thinking_level" in gemini or "thinkingLevel" in gemini:
        signals.append(False)
    if "enable_thinking" in controls:
        signals.append(controls["enable_thinking"] is False)
    for value in (controls.get("thinking_budget"), gemini.get("thinking_budget"), gemini.get("thinkingBudget")):
        if value is not None:
            signals.append(type(value) is int and value == 0)
    return bool(signals) and all(signals)


def resolve(*, provider, base_url, model, enabled=False, protocol="auto", api="chat",
            profile="", custom=None, max_tokens=10000, has_tools=False):
    mode = requested_mode(enabled)
    if profile:
        saved = json.loads(profile)
        mode, protocol = saved["mode"], saved["dialect"]
        custom = saved["custom"]
        encode_profile(mode, protocol, custom)
    model = str(model or "").casefold().rsplit("/", 1)[-1]
    dialect = _official_dialect(_known_host(base_url), model, api) if protocol == "auto" else protocol
    if mode == "default" and not custom:
        return {}, mode, dialect, "not_requested"
    if custom:
        controls = validate_custom(custom)
        containers = set(controls) - {"output_config"}
        if len(containers) > 1 and containers != {"thinking", "reasoning_effort"}:
            raise ValueError("请为当前 API 选择一种思考控制格式。")
        if mode == "off" and (not _is_disable(controls) or
                              has_tools and controls.get("thinking", {}).get("type") == "between_tools"):
            raise ValueError("关闭思考需要明确的关闭参数。")
        if mode in EFFORT_LEVELS and _is_disable(controls):
            raise ValueError("自定义关闭参数与所选思考模式冲突。")
        return controls, mode, dialect, "requested_unverified"
    controls, capability = _dialect_controls(dialect, model, mode, api, int(max_tokens or 10000), has_tools)
    if enabled is True and not profile and api == "chat" and dialect == "deepseek":
        controls.pop("reasoning_effort", None)
    return controls, mode, dialect, capability


def wire_identity(endpoint):
    api = {"anthropic_messages": "anthropic", "gemini_native": "gemini",
           "responses": "responses"}.get(endpoint.get("protocol"), "chat")
    controls, mode, dialect, capability = resolve(
        provider=endpoint.get("provider"), base_url=endpoint.get("base_url") or endpoint.get("url", ""),
        model=endpoint.get("model"), enabled=endpoint.get("enable_thinking", False),
        protocol=endpoint.get("thinking_protocol", "auto"), api=api,
        profile=endpoint.get("reasoning_profile", ""), max_tokens=endpoint.get("max_output_tokens"))
    return {"version": POLICY_VERSION, "mode": mode, "dialect": dialect,
            "capability": capability, "parameters": controls}


def apply_thinking(body, *, provider, base_url, enabled=False, protocol="auto", extra_body=None,
                   api="chat", reasoning_profile=""):
    from .llm_adapter import LLMRequestError
    extra = dict(extra_body or {})
    budget = body.get("max_tokens", body.get("max_output_tokens"))
    custom = {key: extra.pop(key) for key in THINKING_KEYS if key in extra}
    try:
        for key in ("max_tokens", "max_output_tokens", "max_completion_tokens"):
            if key in extra and extra.pop(key) != budget:
                raise ValueError("扩展参数不能覆盖任务输出预算。")
        controls, mode, dialect, capability = resolve(
            provider=provider, base_url=base_url, model=body.get("model"), enabled=enabled,
            protocol=protocol, api=api, profile=reasoning_profile, custom=custom,
            max_tokens=budget, has_tools=bool(body.get("tools") or extra.get("tools")))
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMRequestError(str(exc), category="reasoning_invalid_configuration") from exc
    diagnostics = dict(max_tokens=budget, output_budget_kind="maximum_output_tokens",
                       thinking_requested=False if mode == "off" else None if mode == "default" else mode,
                       thinking_mode="disabled" if mode == "off" and controls else mode,
                       thinking_compatibility=capability, reasoning_dialect=dialect,
                       reasoning_parameters_sent={k: v for k, v in controls.items() if k != "provider"},
                       thinking_sent=controls.get("thinking"), enable_thinking_sent=controls.get("enable_thinking"),
                       reasoning_tokens=None, reasoning_tokens_status="unknown")
    if capability in {"disable_not_supported", "unsupported_mode"}:
        raise LLMRequestError("该模型不支持当前思考模式。请选择该模型支持的档位后重试。",
                              category="reasoning_not_supported", diagnostics=diagnostics)
    body.update({key: value for key, value in extra.items()
                 if key not in body and key not in {"model", "messages", "input", "stream"}})
    body.update(controls)
    if _known_host(base_url) == "api.openai.com" and dialect in {"reasoning_effort", "required_effort"}:
        if api == "chat":
            body["max_completion_tokens"] = body.pop("max_tokens")
        if mode != "off":
            body.pop("temperature", None)
    return diagnostics


def has_reasoning(message):
    if not isinstance(message, dict):
        return False
    if any(message.get(key) for key in ("reasoning_content", "reasoning", "reasoning_details", "reasoning_summary")):
        return True
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and (block.get("type") in {
            "thinking", "redacted_thinking", "reasoning", "reasoning_content", "reasoning_summary",
        } or block.get("thought") is True) for block in content)


def rejected_reasoning(status, error, diagnostics):
    if status not in {400, 422} or not diagnostics.get("reasoning_parameters_sent"):
        return False
    if not isinstance(error, dict):
        return False
    text = " ".join(str(error.get(key) or "").casefold() for key in ("param", "parameter", "message", "code"))
    return any(field in text for field in _REJECT_FIELDS)


def observe_reasoning(diagnostics):
    tokens = diagnostics.get("reasoning_tokens")
    diagnostics["reasoning_tokens_status"] = "provided" if tokens is not None else "unknown"
    if diagnostics.get("thinking_requested") is not False:
        return
    state = diagnostics.get("thinking_compatibility")
    if state in {"disable_not_supported", "request_rejected"}:
        return
    if not diagnostics.get("reasoning_parameters_sent"):
        if state != "fixed_non_reasoning":
            diagnostics["thinking_compatibility"] = "disable_not_configured"
        return
    if (tokens or 0) > 0 or diagnostics.get("reasoning_content_present") or diagnostics.get("reasoning_chars"):
        diagnostics["thinking_compatibility"] = "reasoning_returned_despite_disable"
    elif tokens == 0 and diagnostics.get("reasoning_parameters_sent"):
        diagnostics["thinking_compatibility"] = "reported_zero"
    else:
        diagnostics["thinking_compatibility"] = "disable_unverified"

