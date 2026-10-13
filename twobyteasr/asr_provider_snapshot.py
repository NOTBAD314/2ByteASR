"""Immutable ASR provider identity; no UI settings or persisted schema changes."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .grouping_request import GROUPING_PROMPT_VERSION

GROUP_PROMPT_VERSION = "numeric-boundaries-v5-shared-scene-compact-short-material:" + GROUPING_PROMPT_VERSION
GROUP_CACHE_VERSION = "snapshot-validated-grouped-v5-shared-scene-full-context"
POLISH_PROMPT_VERSION = "correction-edits-v13-optional-suspect-local-quarantine"


def _numeric_rule_version():
    # Pure policy modules are imported only when constructing a snapshot;
    # importing polishing here would reopen the subtitle_core facade cycle.
    from .number_fidelity import RULE_VERSION
    return RULE_VERSION


def _terminology_rule_version():
    from .terminology_retrieval import RULE_VERSION
    return RULE_VERSION


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def endpoint_identity(url: str) -> str:
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    safe = urlunsplit((parts.scheme.lower(), host.lower(), parts.path.rstrip("/"), "", ""))
    # Query can select a tenant/deployment, but must never appear in diagnostics.
    return safe + ("?query_sha256=" + digest(parts.query) if parts.query else "")


@dataclass(frozen=True)
class TimeoutPolicy:
    connect: float = 10.0
    read_idle: float = 120.0
    total: float = 120.0
    queue: float = 120.0

    def __post_init__(self):
        if not all(0 < value <= 300 for value in (self.connect, self.read_idle, self.total, self.queue)):
            raise ValueError("ASR timeout budgets must be in (0, 300] seconds")


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: str
    profile_id: str
    profile_revision: str
    model: str
    kind: str
    transport: str
    endpoint_identity: str
    protocol: str
    capabilities: tuple[str, ...]
    role: str = "group"
    configuration_source: str = "legacy-provider-profile"
    speaker_source: str = "single"
    prefer_arabic_numbers: bool = True
    json_mode: bool = True
    structured_output: bool = True
    timeout_policy: TimeoutPolicy = field(default_factory=TimeoutPolicy)
    prompt_versions: tuple[tuple[str, str], ...] = field(default_factory=lambda: (
        ("polished", POLISH_PROMPT_VERSION), ("grouped", GROUP_PROMPT_VERSION)))
    numeric_rules: str = field(default_factory=_numeric_rule_version)
    terminology_retrieval_rules: str = field(default_factory=_terminology_rule_version)
    _endpoint: tuple[tuple[str, str], ...] = field(default=(), repr=False, compare=False)

    @property
    def fingerprint(self) -> str:
        return digest(self.cache_identity())

    def cache_identity(self) -> dict:
        return {"provider": self.provider, "profile_id": self.profile_id,
                "profile_revision": self.profile_revision, "model": self.model,
                "kind": self.kind, "transport": self.transport,
                "endpoint_identity": self.endpoint_identity, "protocol": self.protocol,
                "capabilities": self.capabilities, "timeout_policy": asdict(self.timeout_policy),
                "prompt_versions": dict(self.prompt_versions), "role": self.role,
                "configuration_source": self.configuration_source, "speaker_source": self.speaker_source,
                "numeric_rules": self.numeric_rules, "terminology_retrieval_rules": self.terminology_retrieval_rules,
                "prefer_arabic_numbers": self.prefer_arabic_numbers,
                "json_mode": self.json_mode, "structured_output": self.structured_output}

    def public_identity(self) -> dict:
        return {**self.cache_identity(), "fingerprint": self.fingerprint}

    def endpoint(self) -> dict:
        return dict(self._endpoint)

    def execution_settings(self) -> dict:
        # Only the typed private marker is honored by the production resolver.
        # It is never written to settings.json or a user's project.
        return {"_asr_provider_snapshot": self, "models": {
            f"{stage}_{key}": value for stage in ("polish", "group")
            for key, value in (("provider", self.provider), ("model", self.model),
                               ("transport", self.transport), ("protocol", self.protocol),
                               ("capabilities", list(self.capabilities)),
                               ("json_mode", self.json_mode), ("structured_output", self.structured_output))}}


def snapshot_in_settings(settings) -> ProviderSnapshot | None:
    value = settings.get("_asr_provider_snapshot")
    return value if isinstance(value, ProviderSnapshot) else None


def resolve_provider_snapshot(settings, *, timeout_policy=None, stage="group") -> ProviderSnapshot:
    from .llm_config import endpoint_from_settings, get_active_service, resolved_service_values, AI_SERVICE_SPECS
    frozen = copy.deepcopy(dict(settings))
    if stage not in ('polish', 'group'):
        raise ValueError('Unknown recognition role: ' + stage)
    models = frozen.get('models', {})
    prefix = 'group' if stage == 'polish' and frozen.get('switches', {}).get('unified_glm_processing', False) else stage
    complete_role = all(f'{prefix}_{key}' in models for key in ('provider', 'model', 'transport', 'base_url'))
    if complete_role:
        values = {key: models.get(f'{prefix}_{key}', '') for key in ('provider', 'model', 'transport', 'base_url', 'protocol')}
        values['capabilities'] = models.get(f'{prefix}_capabilities', ('text', 'structured_output'))
        profile_id = next((key for key, spec in AI_SERVICE_SPECS.items()
            if spec.get('provider') == values['provider'] and spec.get('transport') == values['transport']), 'custom')
        endpoint = endpoint_from_settings(frozen, stage, prefer_role=True)
    else:
        # Only genuinely missing role fields may migrate from a legacy profile.
        profile_id = get_active_service(frozen)
        values = resolved_service_values(frozen, profile_id)
        for role in ('polish', 'group'):
            for key in ('provider', 'model', 'base_url', 'protocol'):
                frozen.setdefault('models', {})[f'{role}_{key}'] = values.get(key, '')
        frozen.setdefault('switches', {})['unified_glm_processing'] = True
        endpoint = endpoint_from_settings(frozen, 'group')
    transport = str(values.get("transport") or "openai_compatible")
    if not complete_role and transport.endswith("_cli") and not frozen.get("models", {}).get("ai_service"):
        raise ValueError("ASR requires an explicitly selected CLI provider profile")
    allowed = {"openai_compatible", "grok_cli", "antigravity_cli", "codex_cli"}
    if transport not in allowed:
        raise ValueError("Unsupported explicitly configured ASR transport")
    capabilities = tuple(str(x) for x in values.get("capabilities", ("text", "structured_output")))
    json_mode = bool(models.get(f'{prefix}_json_mode', values.get('json_mode', True)))
    structured_output = bool(models.get(f'{prefix}_structured_output', values.get('structured_output', True)))
    public = {"profile": profile_id, "provider": endpoint["provider"], "model": endpoint["model"],
              "endpoint": endpoint_identity(endpoint.get("base_url", "")),
              "protocol": endpoint["protocol"], "transport": transport, "capabilities": capabilities,
              "json_mode": json_mode, "structured_output": structured_output}
    return ProviderSnapshot(provider=endpoint["provider"], profile_id=profile_id,
        profile_revision=digest(public), model=endpoint["model"],
        kind="cli" if transport.endswith("_cli") else "http", transport=transport,
        endpoint_identity=public["endpoint"], protocol=endpoint["protocol"], capabilities=capabilities,
        role=stage, configuration_source=f'models.{prefix}_*' if complete_role else 'legacy-provider-profile',
        speaker_source=str(models.get('speaker_source', 'single')),
        prefer_arabic_numbers=bool(frozen.get('switches',{}).get('prefer_arabic_numbers',True)),
        json_mode=json_mode, structured_output=structured_output,
        timeout_policy=timeout_policy or TimeoutPolicy(),
        _endpoint=tuple((str(k), str(v)) for k, v in endpoint.items()))


def task_provider_snapshot(stage="group") -> ProviderSnapshot:
    from .runtime import get_runtime_context
    context = get_runtime_context()
    if stage in context.provider_snapshots:
        return context.provider_snapshots[stage]
    if context.asr_settings_snapshot:
        from .recognition_plan import text_ai_plan
        if stage not in text_ai_plan(context.asr_settings_snapshot, purpose=context.recognition_purpose).roles:
            raise RuntimeError(f"Text AI stage is disabled for this task: {stage}")
        snapshot = resolve_provider_snapshot(context.asr_settings_snapshot, stage=stage)
        context.provider_snapshots[stage] = snapshot
        return snapshot
    if context.provider_snapshot is not None:
        return context.provider_snapshot
    # Compatibility entry points outside a queue still resolve current state;
    # group_subtitles freezes this once before it dispatches worker jobs.
    import subtitle_core as core
    return resolve_provider_snapshot(core.RUNTIME_SETTINGS, stage=stage)


def classify_request_error(error: BaseException) -> str:
    import requests
    if isinstance(error, requests.exceptions.SSLError):
        return "tls_error"
    if isinstance(error, requests.ConnectTimeout):
        return "connect_timeout"
    if isinstance(error, requests.ReadTimeout):
        return "read_idle_timeout"
    category = str(getattr(error, "category", "") or "")
    aliases = {"timeout": "total_timeout", "provider_total_timeout": "total_timeout",
        "provider_inactivity_timeout": "read_idle_timeout", "rate_limit": "rate_limited",
        "structured_empty_response": "empty_response", "response_json_error": "parse_failure",
        "structured_json_parse_error": "parse_failure", "response_schema_error": "format_mismatch",
        "structured_schema_error": "format_mismatch", "structured_output": "format_mismatch",
        "structured_output_truncated": "format_mismatch", "structured_output_truncated_before_answer": "empty_response",
        "cli_error": "cli_exit", "process_error": "cli_exit", "nonzero_exit": "cli_exit",
        "empty_content": "empty_response"}
    if category:
        return aliases.get(category, category)
    if isinstance(error, json.JSONDecodeError):
        return "parse_failure"
    if isinstance(error, ValueError):
        return "format_mismatch"
    if isinstance(error, requests.Timeout):
        return "total_timeout"
    if isinstance(error, requests.ConnectionError):
        return "connection_error"
    return "request_error"


# Same set as text_rules.FORMAT_INVISIBLE_CHARACTERS; duplicated so this
# validator never imports the subtitle_core facade.
_BOUNDARY_INVISIBLE = frozenset("\u200b\u200c\u200d\u2060\ufeff")


def _boundary_space(char) -> bool:
    return char.isspace() or char in _BOUNDARY_INVISIBLE


def strip_boundary_space(text) -> str:
    text = str(text)
    start, end = 0, len(text)
    while start < end and _boundary_space(text[start]):
        start += 1
    while end > start and _boundary_space(text[end - 1]):
        end -= 1
    return text[start:end]


def validate_grouped_text(segments, cues) -> bool:
    """Source conservation modulo whitespace that sits on a cue boundary.

    Every non-whitespace source character and every inner space must appear
    exactly once, in order.  Only whitespace at a cue edge may be dropped
    (2026-10-12: the inter-cue space of "这里怎么办 我们还能挠三下" used to be
    kept as "这里怎么办 " — format junk, not content).
    """
    source = "".join(x.text for x in segments)
    cursor = 0
    for cue in cues:
        core = strip_boundary_space(cue.text)
        while cursor < len(source) and _boundary_space(source[cursor]):
            cursor += 1
        if not source.startswith(core, cursor):
            return False
        cursor += len(core)
    while cursor < len(source) and _boundary_space(source[cursor]):
        cursor += 1
    return cursor == len(source)


def restore_source_text(segments, cues) -> bool:
    """Keep existing semantic/timing choices, but slice every output from input.

    Legacy display helpers normalize punctuation/spacing. They may choose the
    boundaries, never the immutable source characters emitted by Stage 9.
    Whitespace on a boundary is the boundary itself: it goes to neither cue.
    """
    from .text_rules import content_only
    source = "".join(item.text for item in segments)
    if content_only(source) != content_only("".join(cue.text for cue in cues)):
        return False
    positions = [index for index, char in enumerate(source) if content_only(char)]
    counts = [len(content_only(cue.text)) for cue in cues]
    if not cues or any(count <= 0 for count in counts):
        return False
    consumed = start = 0
    for cue, count in zip(cues, counts):
        consumed += count
        end = positions[consumed] if consumed < len(positions) else len(source)
        cue.text = strip_boundary_space(source[start:end])
        start = end
    return validate_grouped_text(segments, cues)


class GroupedBatchResult(list):
    def __init__(self, values=(), *, origin="ai", validated=False, cache_hit=False):
        super().__init__(values)
        self.origin = origin
        self.validated = bool(validated)
        self.cache_hit = bool(cache_hit)


def request_record(snapshot, *, stage, batch_id=None, speaker="", attempt=0, cache_key="", input_characters=0):
    from .runtime import get_runtime_context
    return {"job_id": get_runtime_context().job_id, "stage": stage, "batch_id": batch_id,
        "speaker": speaker, "attempt": attempt, "configured_provider": snapshot.profile_id,
        "configuration_source": snapshot.configuration_source, "speaker_source": snapshot.speaker_source,
        "resolved_provider": snapshot.provider, "model": snapshot.model, "transport": snapshot.transport,
        "protocol": snapshot.protocol, "endpoint_identity": snapshot.endpoint_identity,
        "provider_snapshot_fingerprint": snapshot.fingerprint, "cache_key": cache_key,
        "cache_version": GROUP_CACHE_VERSION, "input_characters": input_characters, "boundary_count": None,
        "queue_wait_ms": None, "connect_ms": None, "ttft_ms": None, "first_activity_ms": None,
        "last_activity_ms": None, "total_duration_ms": None, "http_status": None,
        "http_request_id": None, "cli_pid": None, "cli_exit_code": None,
        "raw_response_length": None, "validator_result": "not_run", "fallback_reason": None}
