"""Optional strict structured output for proofreading through DeepSeek's strict tool call.

2026-11-18 (review of the 鳴潮 special): JSON mode lets the model answer in any shape; three
batches used a flat ``edits`` list and fell back. DeepSeek's beta endpoint enforces a tool's
JSON schema when the function has ``strict: true``
(https://api-docs.deepseek.com/guides/tool_calls): every object lists all properties in
``required``, ``additionalProperties`` is false, optional values are ``anyOf`` with null,
``minLength``/``maxLength``/``minItems``/``maxItems`` are not supported.

Off by default (``models.polish_strict_output``): third-party reports about the beta are mixed
and it has not been measured on this pipeline. When on, only the official DeepSeek endpoint and
streamed requests use it; any rejection or unusable answer sends the same request in JSON mode
and that endpoint stays on JSON mode for the rest of the process. Local validation is unchanged.
"""
from __future__ import annotations

import copy
import threading
from urllib.parse import urlsplit, urlunsplit

STRICT_TOOL_NAME = "submit_answer"
OFFICIAL_DEEPSEEK_HOST = "api.deepseek.com"
_UNSUPPORTED_KEYWORDS = ("minLength", "maxLength", "minItems", "maxItems")
# Errors after which the JSON-mode request is worth sending. Auth, quota, rate limits and
# timeouts would fail the same way, so they are not.
FALLBACK_CATEGORIES = frozenset({
    'request_rejected', 'configuration_error', 'unsupported_parameters', 'provider_tool_request',
    'provider_no_body', 'provider_terminal_error', 'structured_json_parse_error', 'parse_failure',
    'format_mismatch', 'reasoning_only'})

_REJECTED: set[tuple[str, str]] = set()
_LOCK = threading.Lock()


def strict_schema(schema):
    """The same contract in the strict subset: all keys required, optional ones nullable.

    A property with no schema (``{}``, free-form metadata) cannot be expressed and is left
    out, so a strict answer simply never carries it.
    """
    def convert(node, optional=False):
        if not isinstance(node, dict) or not node:
            return None
        node = {key: copy.deepcopy(value) for key, value in node.items() if key not in _UNSUPPORTED_KEYWORDS}
        kind = node.get('type')
        if kind == 'object':
            required = set(node.get('required') or ())
            properties = {}
            for key, value in (node.get('properties') or {}).items():
                converted = convert(value, optional=key not in required)
                if converted is not None:
                    properties[key] = converted
            node.update(properties=properties, required=list(properties), additionalProperties=False)
        elif kind == 'array' and isinstance(node.get('items'), dict):
            node['items'] = convert(node['items']) or {'type': 'string'}
        if optional:
            return {'anyOf': [node, {'type': 'null'}]}
        return node
    return convert(schema)


def drop_strict_nulls(value, schema):
    """Remove the nulls strict mode uses for keys the original contract leaves optional.

    Local validation keeps rejecting a null position or edit type in JSON mode; only the
    keys ``strict_schema`` itself made nullable are read as absent.
    """
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict) and schema.get('type') == 'object':
        required = set(schema.get('required') or ())
        properties = schema.get('properties') or {}
        return {key: drop_strict_nulls(item, properties.get(key)) for key, item in value.items()
                if not (item is None and key not in required)}
    if isinstance(value, list) and schema.get('type') == 'array':
        return [drop_strict_nulls(item, schema.get('items')) for item in value]
    return value


def beta_url(url):
    """The official endpoint's beta chat URL, or '' for any other host."""
    parts = urlsplit(str(url or ''))
    if parts.scheme != 'https' or (parts.hostname or '').lower() != OFFICIAL_DEEPSEEK_HOST:
        return ''
    return urlunsplit(parts._replace(path='/beta/chat/completions', query='', fragment=''))


def enabled_for_task(stage='polish'):
    from ..recognition.run_context import get_runtime_context
    settings = getattr(get_runtime_context(), 'asr_settings_snapshot', None)
    if not settings:
        import subtitle_core as core
        settings = getattr(core, 'RUNTIME_SETTINGS', None) or {}
    models = (settings or {}).get('models', {}) or {}
    prefix = 'group' if stage != 'polish' or (settings or {}).get('switches', {}).get('unified_glm_processing') else 'polish'
    return bool(models.get(f'{prefix}_strict_output', False))


def _key(endpoint):
    return (str(endpoint.get('provider') or ''), str(endpoint.get('url') or endpoint.get('base_url') or ''))


def request_for(endpoint, schema, *, streamed, stage='polish'):
    """The strict tool request to try first, or None to use JSON mode directly."""
    if not streamed or str(endpoint.get('provider') or '').casefold() != 'deepseek':
        return None
    url = beta_url(endpoint.get('url') or endpoint.get('base_url'))
    if not url or not enabled_for_task(stage):
        return None
    with _LOCK:
        if _key(endpoint) in _REJECTED:
            return None
    converted = strict_schema(schema)
    if converted is None:
        return None
    return {'name': STRICT_TOOL_NAME, 'schema': converted, 'url': url,
            'description': 'Return the complete answer object defined by the system prompt.'}


def remember_rejection(endpoint, error):
    """Keep this endpoint on JSON mode for the rest of the process; say why once."""
    with _LOCK:
        first = _key(endpoint) not in _REJECTED
        _REJECTED.add(_key(endpoint))
    if first:
        try:
            from ..recognition.cache import record_run_event
            record_run_event('strict_structured_output_fallback', provider=endpoint.get('provider'),
                             model=endpoint.get('model'), category=str(getattr(error, 'category', '') or ''),
                             error=str(error)[:300], action='json_mode_for_rest_of_process')
        except Exception:
            pass


def clear_rejections():
    with _LOCK:
        _REJECTED.clear()
