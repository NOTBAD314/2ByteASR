"""Private request ownership, including an explicitly absent credential.

Never serialize this object into settings, projects, reports or logs. A saved
configuration is live; a client or a connection test owns what it resolved at
creation, including credentials that may subsequently be replaced or deleted.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestEndpoint:
    stage: str
    values: tuple[tuple[str, str], ...] = field(repr=False)


def endpoint_snapshot(settings, stage):
    snapshot = settings.get('_request_endpoint')
    if isinstance(snapshot, RequestEndpoint) and snapshot.stage == stage:
        return dict(snapshot.values)
    return None


def freeze_request_settings(settings, stage):
    from .llm_config import endpoint_from_settings
    frozen = copy.deepcopy(dict(settings))
    endpoint = endpoint_from_settings(frozen, stage)
    for role in ('polish', 'group'):
        frozen.get('models', {}).pop(role + '_api_key', None)
    frozen['_request_endpoint'] = RequestEndpoint(stage, tuple(endpoint.items()))
    return frozen
