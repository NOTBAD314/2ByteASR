"""Output-only budgets and one explicitly supported thinking protocol.

Missing historical settings used constants, so only missing fields migrate.
An explicitly saved value (including 4096) remains a user choice.
"""
from urllib.parse import urlsplit

DEFAULT_OUTPUT_TOKENS = 10000
POLICY_VERSION = "subtitle-output-thinking-v1"
THINKING_PROTOCOLS = ("auto", "deepseek", "enable_thinking", "reasoning_effort")
THINKING_KEYS = {"thinking", "enable_thinking", "reasoning", "reasoning_effort", "include_reasoning"}


def settings_policy(settings, stage="group"):
    models = settings.get("models", {})
    prefix = "group" if stage != "polish" or settings.get("switches", {}).get("unified_glm_processing") else "polish"
    value = models.get(f"{prefix}_max_output_tokens", DEFAULT_OUTPUT_TOKENS)
    budget = int(value)
    if isinstance(value, bool) or budget <= 0:
        raise ValueError("最大输出 Token 必须为正整数。")
    protocol = str(models.get(f"{prefix}_thinking_protocol", "auto"))
    if protocol not in THINKING_PROTOCOLS:
        raise ValueError("未知的思考控制协议。")
    return dict(max_output_tokens=budget,
                enable_thinking=bool(models.get(f"{prefix}_enable_thinking", False)),
                thinking_protocol=protocol)


def provider_policy(provider):
    settings = getattr(provider, "_settings", None)
    if settings is not None:
        return settings_policy(settings, getattr(provider, "_stage", "group"))
    endpoint = getattr(provider, "endpoint", {})
    return dict(max_output_tokens=int(endpoint.get("max_output_tokens", DEFAULT_OUTPUT_TOKENS)),
                enable_thinking=endpoint.get("enable_thinking", False),
                thinking_protocol=endpoint.get("thinking_protocol", "auto"))


def thinking_control(provider, base_url, enabled, protocol="auto"):
    """Return a single wire dialect and an honest compatibility description."""
    host = (urlsplit(str(base_url)).hostname or "").lower()
    if protocol == "auto":
        protocol = ("deepseek" if host == "api.deepseek.com" else
                    "enable_thinking" if host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"} else "unknown")
    if enabled is None:
        return {}, "provider_default", "not_requested"
    if protocol == "deepseek":
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}, "enabled" if enabled else "disabled", "requested_unverified"
    if protocol == "enable_thinking":
        return {"enable_thinking": bool(enabled)}, "enabled" if enabled else "disabled", "requested_unverified"
    if protocol == "reasoning_effort":
        return {"reasoning_effort": "high" if enabled else "none"}, "enabled" if enabled else "disabled", "requested_unverified"
    return {}, "provider_default", "unsupported_or_unknown"


def apply_thinking(body, *, provider, base_url, enabled, protocol="auto", extra_body=None, api="chat"):
    controls, mode, compatibility = thinking_control(provider, base_url, enabled, protocol)
    if api == "responses":
        host = (urlsplit(str(base_url)).hostname or "").lower()
        if enabled is not None and (host == 'api.deepseek.com' or protocol == 'reasoning_effort'):
            controls = {'reasoning': {'effort':'high' if enabled else 'none'}}
            mode, compatibility = ('enabled' if enabled else 'disabled'), 'requested_unverified'
        else:
            controls, mode, compatibility = {}, 'provider_default', 'unsupported_or_unknown' if enabled is not None else 'not_requested'
    extra = dict(extra_body or {})
    for key in ('max_tokens', 'max_output_tokens', 'max_completion_tokens'):
        if key in extra and extra[key] != body.get('max_tokens', body.get('max_output_tokens')):
            raise ValueError("扩展参数不能覆盖任务输出预算。")
    # Caller extensions may describe a verified dialect, but cannot silently
    # contradict the task switch or the one selected dialect.
    supplied = {key: extra[key] for key in THINKING_KEYS if key in extra}
    if supplied and (len(supplied) != 1 or controls and supplied != controls):
        raise ValueError("思考参数与任务设置冲突；请选择中转实际支持的一种协议。")
    if supplied and not controls:
        if enabled is not None:
            key = next(iter(supplied))
            dialect = {"thinking":"deepseek", "enable_thinking":"enable_thinking", "reasoning_effort":"reasoning_effort"}.get(key)
            expected = thinking_control(provider, base_url, enabled, dialect)[0] if dialect else {}
            if supplied != expected:
                raise ValueError("扩展思考参数与任务开关冲突。")
        controls = supplied
        mode = "enabled" if enabled else "disabled" if enabled is not None else "explicit_extension"
        compatibility = "requested_unverified"
    body.update({key: value for key, value in extra.items() if key not in THINKING_KEYS and key not in body and key not in {'max_tokens','max_output_tokens','max_completion_tokens','model','messages','input'}})
    body.update(controls)
    return dict(max_tokens=body.get("max_tokens", body.get("max_output_tokens")),
                output_budget_kind="maximum_output_tokens",
                thinking_requested=enabled, thinking_mode=mode,
                thinking_compatibility=compatibility, reasoning_parameters_sent={k:body[k] for k in THINKING_KEYS if k in body},
                thinking_sent=body.get("thinking"), enable_thinking_sent=body.get("enable_thinking"),
                reasoning_tokens=None, reasoning_tokens_status="unknown")


def observe_response_policy(diagnostics):
    """Do not turn a requested disable into a claim about the server's state."""
    if (diagnostics.get("thinking_requested") is False
            and diagnostics.get("thinking_mode") in {"disabled", "no_upfront_thinking"}
            and diagnostics.get("reasoning_parameters_sent")
            and (diagnostics.get("reasoning_content_present") or diagnostics.get("reasoning_chars")
                 or (diagnostics.get("reasoning_tokens") or 0) > 0)):
        diagnostics["thinking_compatibility"] = "reasoning_returned_despite_disable"
        diagnostics["thinking_mode"] = "disable_requested_but_reasoning_returned"
    if (diagnostics.get("finish_reason") in {"length", "max_tokens"}
            and isinstance(diagnostics.get("completion_tokens"), (int, float))
            and diagnostics["completion_tokens"] < diagnostics.get("max_tokens", 0)):
        diagnostics["output_budget_observation"] = "length_before_requested_maximum; server_limit_unconfirmed"
