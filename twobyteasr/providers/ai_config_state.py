"""Allowlisted AI configuration evidence; no addresses, credentials or input text."""
from __future__ import annotations

import hashlib
import json
import logging


def configuration_state(settings):
    from . import ai_connection_record as record
    from .asr_provider_snapshot import resolve_provider_snapshot, snapshot_in_settings
    from .llm_config import endpoint_requires_key
    switches = settings.get('switches', {})
    stages, identity_parts = {}, []
    for role, flag in (('polish', 'enable_ai_polish'), ('group', 'use_ai_grouping')):
        snapshot = snapshot_in_settings(settings) or resolve_provider_snapshot(settings, stage=role)
        endpoint = snapshot.endpoint()
        enabled = bool(switches.get(flag, True))
        stages[role] = {
            'source': snapshot.configuration_source,
            'service': snapshot.profile_id, 'model': snapshot.model,
            'enabled': enabled,
            'configured': (snapshot.kind == 'cli' or bool(endpoint.get('api_key'))
                           or not endpoint_requires_key(endpoint)),
            'verification': record.result_for(settings, role),
        }
        # This opaque version changes for a credential change too, without
        # exposing any credential, scope, partial key or key-only digest.
        identity_parts.append((record.fingerprint(settings, role), enabled))
    revision = hashlib.sha256(json.dumps(identity_parts).encode('utf-8')).hexdigest()[:16]
    return {'revision': revision, 'stages': stages}


def trace_configuration(source, settings):
    try:
        state = configuration_state(settings)
        logging.getLogger(__name__).info('AI_CONFIGURATION %s %s', source, json.dumps(state, ensure_ascii=False))
        from ..diagnostics.editor_diagnostics import record
        record('ai_configuration', source=source, **state)
        return state
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        logging.getLogger(__name__).warning('AI_CONFIGURATION %s unavailable', source)
        return None
