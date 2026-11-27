"""Output-only budgets and subtitle retry policy.

Missing historical settings used constants, so only missing fields migrate.
An explicitly saved value (including 4096) remains a user choice.
"""
from urllib.parse import urlsplit

DEFAULT_OUTPUT_TOKENS = 10000
POLICY_VERSION = "subtitle-output-thinking-v1"
from .reasoning_adapter import EFFORT_LEVELS, THINKING_PROTOCOLS, apply_thinking, observe_reasoning


def settings_policy(settings, stage="group", endpoint=None):
    models = settings.get("models", {})
    prefix = "group" if stage != "polish" or settings.get("switches", {}).get("unified_glm_processing") else "polish"
    value = models.get(f"{prefix}_max_output_tokens", DEFAULT_OUTPUT_TOKENS)
    budget = int(value)
    if isinstance(value, bool) or budget <= 0:
        raise ValueError("最大输出 Token 必须为正整数。")
    legacy_values = None
    if endpoint is not None:
        from .llm_config import default_protocol, normalize_base_url
        base = normalize_base_url(models.get(f"{prefix}_base_url", ""))
        provider = models.get(f"{prefix}_provider")
        protocol = models.get(f"{prefix}_protocol") or "auto"
        if (provider, base, models.get(f"{prefix}_model"),
                default_protocol(provider, base) if protocol == "auto" else protocol) == tuple(
                endpoint.get(key) for key in ("provider", "base_url", "model", "protocol")):
            legacy_values = models
    elif not models.get("reasoning_profiles"):
        legacy_values = models
    legacy = legacy_values or {}
    protocol = str(legacy.get(f"{prefix}_thinking_protocol", "auto"))
    if protocol not in THINKING_PROTOCOLS:
        raise ValueError("未知的思考控制协议。")
    return dict(max_output_tokens=budget,
                enable_thinking=bool(legacy.get(f"{prefix}_enable_thinking", False)),
                thinking_protocol=protocol)


def provider_policy(provider):
    settings = getattr(provider, "_settings", None)
    endpoint = dict(getattr(provider, "endpoint", {}) or {})
    endpoint.setdefault("model", getattr(provider, "model", ""))
    if settings is not None:
        from .llm_config import endpoint_from_settings
        endpoint = endpoint_from_settings(settings, getattr(provider, "_stage", "group"))
    from .reasoning_adapter import wire_identity
    from .asr_provider_snapshot import endpoint_identity
    return dict(max_output_tokens=int(endpoint.get("max_output_tokens", DEFAULT_OUTPUT_TOKENS)),
                enable_thinking=endpoint.get("enable_thinking", False),
                thinking_protocol=endpoint.get("thinking_protocol", "auto"),
                reasoning_profile=endpoint.get("reasoning_profile", ""),
                reasoning=wire_identity(endpoint),
                endpoint_identity=endpoint_identity(endpoint.get("base_url", "")))


def thinking_control(provider, base_url, enabled, protocol="auto"):
    from .reasoning_adapter import resolve
    controls, mode, _, compatibility = resolve(
        provider=provider, base_url=base_url, model="", enabled=enabled, protocol=protocol)
    return controls, {"off": "disabled", "default": "provider_default"}.get(mode, mode), compatibility


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
    """Keep the selected mode for a bounded retry on a known route."""
    if not categories:
        return None
    from .reasoning_adapter import wire_identity
    endpoint = {**snapshot.endpoint(), "enable_thinking": snapshot.enable_thinking,
                "thinking_protocol": snapshot.thinking_protocol}
    if base_url:
        endpoint["base_url"] = base_url
    if endpoint_protocol:
        endpoint["protocol"] = endpoint_protocol
    if wire_identity(endpoint)["parameters"]:
        return snapshot.enable_thinking
    if set(categories) <= TRUNCATION_CATEGORIES and (
            escalated_output_tokens(snapshot, operation) > int(snapshot.max_output_tokens or 0)):
        return snapshot.enable_thinking
    return None


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
    observe_reasoning(diagnostics)
    if (diagnostics.get("finish_reason") in {"length", "max_tokens"}
            and isinstance(diagnostics.get("completion_tokens"), (int, float))
            and diagnostics["completion_tokens"] < diagnostics.get("max_tokens", 0)):
        diagnostics["output_budget_observation"] = "length_before_requested_maximum; server_limit_unconfirmed"
