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


# 2026-11-15 (问问兔白, user: "默认推理等级 high，难的改 max"): ``enabled`` may also name a depth.
# The official DeepSeek endpoint was checked on 2026-11-15: thinking enabled plus reasoning_effort
# high / max are accepted (max thinks longer); its own list is none … high, xhigh, ultra, max.
EFFORT_LEVELS = ("low", "medium", "high", "max")


def thinking_control(provider, base_url, enabled, protocol="auto"):
    """Return a single wire dialect and an honest compatibility description."""
    host = (urlsplit(str(base_url)).hostname or "").lower()
    if protocol == "auto":
        protocol = ("deepseek" if host == "api.deepseek.com" else
                    "enable_thinking" if host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"} else "unknown")
    if enabled is None:
        return {}, "provider_default", "not_requested"
    level = enabled if isinstance(enabled, str) and enabled in EFFORT_LEVELS else None
    if isinstance(enabled, str):
        enabled = level is not None
    if protocol == "deepseek":
        controls = {"thinking": {"type": "enabled" if enabled else "disabled"}}
        if level:
            controls["reasoning_effort"] = level
        return controls, f"enabled_{level}" if level else "enabled" if enabled else "disabled", "requested_unverified"
    if protocol == "enable_thinking":
        return {"enable_thinking": bool(enabled)}, "enabled" if enabled else "disabled", "requested_unverified"
    if protocol == "reasoning_effort":
        return ({"reasoning_effort": (level or "high") if enabled else "none"},
                f"enabled_{level}" if level else "enabled" if enabled else "disabled", "requested_unverified")
    return {}, "provider_default", "unsupported_or_unknown"


def apply_thinking(body, *, provider, base_url, enabled, protocol="auto", extra_body=None, api="chat"):
    controls, mode, compatibility = thinking_control(provider, base_url, enabled, protocol)
    if api == "responses":
        host = (urlsplit(str(base_url)).hostname or "").lower()
        if enabled is not None and (host == 'api.deepseek.com' or protocol == 'reasoning_effort'):
            level = enabled if isinstance(enabled, str) and enabled in EFFORT_LEVELS else None
            enabled = bool(level) if isinstance(enabled, str) else enabled
            controls = {'reasoning': {'effort': (level or 'high') if enabled else 'none'}}
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


# 2026-11-16 (user: failed AI proofreading/grouping should be collected and retried once with the
# same model thinking harder, instead of going straight to local rules): one level up per run.
ESCALATION_DEFAULT = True
ESCALATION_MAX_SHARE = 0.3
ESCALATION_MIN_CUES = 10


def thinking_dialect(base_url, protocol="auto", endpoint_protocol=""):
    """The one wire dialect a request would use; ``unknown`` when none is verified."""
    if str(endpoint_protocol) == "anthropic_messages":
        return "anthropic_effort"
    if protocol != "auto":
        return protocol
    host = (urlsplit(str(base_url)).hostname or "").lower()
    return ("deepseek" if host == "api.deepseek.com" else
            "enable_thinking" if host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"} else "unknown")


def escalated_thinking(enabled, protocol="auto", *, base_url="", endpoint_protocol=""):
    """The next thinking value for a final retry, or None when there is no higher verified level.

    Graded dialects go off/low/medium -> high -> max; the on/off ``enable_thinking`` dialect only
    goes off -> on. An unknown relay gets nothing: sending a guessed parameter could break it.
    """
    dialect = thinking_dialect(base_url, protocol, endpoint_protocol)
    level = enabled if isinstance(enabled, str) and enabled in EFFORT_LEVELS else None
    on = bool(level) or enabled is True
    if dialect == "enable_thinking":
        return None if on else True
    if dialect not in {"deepseek", "reasoning_effort", "anthropic_effort"}:
        return None
    if not on or level in {"low", "medium"}:
        return "high"
    return None if level == "max" else "max"


ESCALATION_INPUT_RESERVE = 12288
# 2026-11-18 (users: "一直显示返回上限" then local rules): a measured DeepSeek v4-flash run spent
# 6146 reasoning tokens at thinking=high on a 140-character polish half batch (6787 of 10000);
# the ordinary answers in the same run used 20-800. Thinking retries get 32768, a ceiling the
# common thinking models accept; it is a maximum, billing counts only what is generated.
ESCALATION_OUTPUT_TOKENS = 32768
TRUNCATION_CATEGORIES = frozenset({'structured_output_truncated', 'structured_output_truncated_before_answer'})


def escalated_budget(current, operation="polish", known_output=None, known_context=None):
    """The retry's output budget: ESCALATION_OUTPUT_TOKENS within the request window and the
    model's known output limit, never lower than what the user configured."""
    current = max(1, int(current or 0))
    from .provider_input_budget import POLICIES
    policy = POLICIES.get(operation) or POLICIES['polish']
    context = policy.context_tokens
    if isinstance(known_context, int) and not isinstance(known_context, bool) and known_context > 0:
        context = min(context, known_context)
    cap = max(1, min(ESCALATION_OUTPUT_TOKENS, context - ESCALATION_INPUT_RESERVE))
    if isinstance(known_output, (int, float)) and not isinstance(known_output, bool) and known_output > 0:
        cap = min(cap, int(known_output))
    return max(current, cap)


def endpoint_escalated_budget(current, operation, endpoint, model=""):
    from .model_discovery import model_limits

    known = model_limits(endpoint.get('provider', ''), endpoint.get('base_url') or endpoint.get('url', ''),
                         endpoint.get('api_key', ''), model or endpoint.get('model', ''))
    return escalated_budget(current, operation, known.get('output_tokens'), known.get('context_tokens'))


def escalated_output_tokens(snapshot, operation="polish"):
    """Output budget for a thinking-escalation request; reasoning shares the answer's budget.

    2026-11-18 (鳴潮 special): both grouping halves resent at thinking=high with the ordinary
    10000-token cap were cut off before the answer (``HTTP正文因长度限制被截断``) and the batch
    stayed local. See ``escalated_budget`` (the window check in provider_input_budget still
    applies to the request).
    """
    try:
        return endpoint_escalated_budget(getattr(snapshot, 'max_output_tokens', 0), operation,
                                         snapshot.endpoint(), getattr(snapshot, 'model', ''))
    except Exception:
        return escalated_budget(getattr(snapshot, 'max_output_tokens', 0), operation)


def retry_thinking(snapshot, categories, operation="polish", *, base_url="", endpoint_protocol=""):
    """The thinking value for the one final retry, or None when the retry cannot help.

    One level higher when the dialect has one. When it has none (an unverified relay, or already
    at the top level) but every failure was a cut-off answer, the same thinking value is resent
    with the larger output budget: a relay whose model thinks anyway used to go straight to
    local rules here.
    """
    level = escalated_thinking(snapshot.enable_thinking, snapshot.thinking_protocol,
                               base_url=base_url, endpoint_protocol=endpoint_protocol)
    if (level is None and categories and set(categories) <= TRUNCATION_CATEGORIES
            and escalated_output_tokens(snapshot, operation) > int(snapshot.max_output_tokens or 0)):
        return snapshot.enable_thinking
    return level


def escalation_enabled(settings, stage="group"):
    """The saved per-stage switch; a missing key means on (the recommended default)."""
    models = (settings or {}).get("models", {}) or {}
    prefix = "group" if stage != "polish" or (settings or {}).get("switches", {}).get("unified_glm_processing") else "polish"
    return bool(models.get(f"{prefix}_escalate_on_failure", ESCALATION_DEFAULT))


def task_escalation_enabled(stage="group"):
    """The switch as frozen for the running task (falls back to the live settings)."""
    from ..recognition.run_context import get_runtime_context
    settings = getattr(get_runtime_context(), "asr_settings_snapshot", None)
    if not settings:
        import subtitle_core as core
        settings = core.RUNTIME_SETTINGS
    return escalation_enabled(settings, stage)


def escalation_cue_limit(total):
    """Most cues one task may resend; more failures than this point at the service, not the answer."""
    import math
    return max(ESCALATION_MIN_CUES, math.ceil(max(0, int(total)) * ESCALATION_MAX_SHARE))


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
