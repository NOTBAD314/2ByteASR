"""Remembered 「测试连接」 results and the gate for AI-only features (2026-10-22).

User (10-22): without an API key and a tested connection, 术语库校对,
联网补充核验 and subtitle translation must be greyed out and say a key is
needed. The test result used to live only in the open editor
(``EndpointEditor.last_connection_ok``) and was gone after a restart, so it is
remembered here by a fingerprint of what was tested: transport, provider,
endpoint, model and a SHA-256 of the key. The key itself is never written.
Changing the key, the service or the model gives another fingerprint, which
counts as not tested.

The file sits next to ``secrets.dat`` (``%LOCALAPPDATA%\\2ByteASR``); the
settings schema does not change.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .llm_config import secrets_path

FILE_NAME = 'ai_connection_checks.json'
KEEP = 24   # fingerprints remembered (a few services and models per person)

# feature_gate() answers
READY = 'ready'          # key (or account login) and a passed test
OFF = 'off'              # both AI switches are off
NO_KEY = 'no_key'        # an API service without a key
UNTESTED = 'untested'    # never tested with these settings
FAILED = 'failed'        # the last test with these settings failed


def record_path() -> Path:
    return secrets_path().with_name(FILE_NAME)


def fingerprint(settings: dict, stage: str = 'polish') -> str:
    """What a request for ``stage`` would use, hashed; '' when it cannot be resolved."""
    from .ai_providers import transport_for_stage
    from .asr_provider_snapshot import endpoint_identity
    from .llm_config import endpoint_from_settings
    try:
        endpoint = endpoint_from_settings(dict(settings or {}), stage)
        transport = transport_for_stage(dict(settings or {}), stage).value
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        return ''
    key = str(endpoint.get('api_key') or '').strip()
    parts = [transport, str(endpoint.get('provider') or ''), endpoint_identity(str(endpoint.get('base_url') or '')),
             str(endpoint.get('model') or ''), hashlib.sha256(key.encode('utf-8')).hexdigest() if key else '']
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode('utf-8')).hexdigest()


def _load() -> dict:
    try:
        data = json.loads(record_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    checks = data.get('checks') if isinstance(data, dict) else None
    return dict(checks) if isinstance(checks, dict) else {}


def remember(settings: dict, stage: str, ok: bool) -> str:
    """Store the result of a connection test of ``settings`` for ``stage``; returns the fingerprint."""
    mark = fingerprint(settings, stage)
    if not mark:
        return ''
    checks = _load()
    checks.pop(mark, None)
    checks[mark] = {'ok': bool(ok), 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    checks = dict(list(checks.items())[-KEEP:])
    path = record_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(json.dumps({'version': 1, 'checks': checks}, ensure_ascii=False, indent=1),
                             encoding='utf-8')
        os.replace(temporary, path)
    except OSError:
        pass
    return mark


def result_for(settings: dict, stage: str = 'polish') -> bool | None:
    """True / False: the last test with exactly these settings; None: never tested."""
    mark = fingerprint(settings, stage)
    entry = _load().get(mark) if mark else None
    return bool(entry.get('ok')) if isinstance(entry, dict) else None


def checked_at(settings: dict, stage: str = 'polish') -> str:
    """When exactly these settings were last tested ('2026-10-22T21:40:00'); '' when never."""
    mark = fingerprint(settings, stage)
    entry = _load().get(mark) if mark else None
    return str(entry.get('at') or '') if isinstance(entry, dict) else ''


def feature_gate(settings: dict) -> str:
    """May the AI-only features (translation, 术语库校对, 联网补充核验) be used? One of the constants above.

    They all use the 字幕校对 (polish) service, so that is the one checked; an
    account login (CLI) has no key but still needs a passed test.
    """
    from .ai_providers import AITransport
    from .llm_config import effective_ai_identity, endpoint_requires_key
    try:
        identity = effective_ai_identity(settings, 'polish')
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        return NO_KEY
    # No key says so even with AI switched off (switches may be off *because* there is no key).
    if (str(identity.get('transport', '')) == AITransport.OPENAI_COMPATIBLE.value
            and not identity.get('credential_configured')
            and endpoint_requires_key({'provider': identity.get('provider'), 'base_url': identity.get('base_url')})):
        return NO_KEY
    switches = dict((settings or {}).get('switches') or {})
    if not (switches.get('enable_ai_polish', True) or switches.get('use_ai_grouping', True)):
        return OFF
    result = result_for(settings, 'polish')
    if result is None:
        return UNTESTED
    return READY if result else FAILED
