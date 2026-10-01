"""Application-wide provider registry and request-state contract.

Home, Studio and background requests bind to this one live settings object.
The catalog remains in :mod:`llm_config`; this module is the only facade that
combines catalog selection, credentials and the persistent ProviderService.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .llm_config import (
    AI_SERVICE_SPECS,
    activate_ai_service,
    active_service_values,
    endpoint_from_settings,
    get_active_service,
    read_scoped_api_key,
    service_model_catalog,
    update_active_profile,
)
from .provider_service import GLOBAL_PROVIDER_SERVICE, AIClient


class ProviderRequestState(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    AUTH_READY = "AUTH_READY"
    SESSION_READY = "SESSION_READY"
    REQUESTING = "REQUESTING"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    PARSE_OK = "PARSE_OK"
    SCHEMA_OK = "SCHEMA_OK"
    QUALITY_OK = "QUALITY_OK"
    SUCCESS = "SUCCESS"
    AUTH_ERROR = "AUTH_ERROR"
    SPAWN_ERROR = "SPAWN_ERROR"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    TIMEOUT = "TIMEOUT"
    MODEL_ERROR = "MODEL_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    QUALITY_ERROR = "QUALITY_ERROR"
    CANCELLED = "CANCELLED"


@dataclass
class ProviderStateMachine:
    state: ProviderRequestState = ProviderRequestState.UNCONFIGURED
    history: list[dict[str, Any]] = field(default_factory=list)

    def advance(self, state: ProviderRequestState, detail: str = "") -> None:
        self.state = state
        self.history.append({
            "state": state.value,
            "time_monotonic": round(time.monotonic(), 6),
            "detail": str(detail or "")[:300],
        })


@dataclass(frozen=True)
class ProviderSelection:
    service: str
    provider: str
    model: str
    base_url: str
    protocol: str
    transport: str
    credential_ready: bool
    credential_source: str


class ProviderRegistry:
    """Thread-safe owner of the currently bound runtime settings object."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._settings: dict[str, Any] | None = None

    def bind(self, settings: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(settings, dict):
            raise TypeError("provider settings must be a dict")
        with self._lock:
            self._settings = settings
            return settings

    def settings(self) -> dict[str, Any]:
        with self._lock:
            if self._settings is None:
                from .settings import load_runtime_settings

                loaded = load_runtime_settings()
                self._settings = loaded[0] if isinstance(loaded, tuple) else loaded
            return self._settings

    def selection(
        self, settings: dict[str, Any] | None = None, *, stage: str = "polish"
    ) -> ProviderSelection:
        # Inspecting a frozen background request must not rebind the UI's
        # live settings. Only explicit bind/activate operations change them.
        live = settings if settings is not None else self.settings()
        values = active_service_values(live, stage=stage)
        endpoint = endpoint_from_settings(live, stage)
        return ProviderSelection(
            service=str(values.get("service") or get_active_service(live)),
            provider=str(endpoint.get("provider") or values.get("provider") or "custom"),
            model=str(endpoint.get("model") or values.get("model") or ""),
            base_url=str(endpoint.get("base_url") or values.get("base_url") or ""),
            protocol=str(endpoint.get("protocol") or values.get("protocol") or "auto"),
            transport=str(values.get("transport") or "openai_compatible"),
            credential_ready=bool(endpoint.get("api_key") or str(values.get("transport")) != "openai_compatible"),
            credential_source=str(endpoint.get("key_source") or "未配置"),
        )

    def activate(
        self,
        service: str,
        *,
        model: str = "",
        settings: dict[str, Any] | None = None,
        stage: str = "polish",
    ) -> ProviderSelection:
        live = self.bind(settings) if settings is not None else self.settings()
        service_id = str(service or "custom")
        if service_id not in AI_SERVICE_SPECS:
            service_id = "custom"
        activate_ai_service(live, service_id, stage=stage)
        if model:
            update_active_profile(live, stage=stage, model=str(model))
        return self.selection(live, stage=stage)

    def models(
        self, service: str, settings: dict[str, Any] | None = None
    ) -> tuple[str, ...]:
        live = self.bind(settings) if settings is not None else self.settings()
        return tuple(service_model_catalog(live, str(service)))

    def credential(self, selection: ProviderSelection) -> tuple[bool, str]:
        if selection.transport != "openai_compatible":
            return True, "CLI Session"
        return bool(selection.credential_ready), str(selection.credential_source)

    def client(
        self,
        *,
        stage: str = "polish",
        settings: dict[str, Any] | None = None,
        sender=None,
    ) -> AIClient:
        live = settings if settings is not None else self.settings()
        return GLOBAL_PROVIDER_SERVICE.client_for_stage(live, stage, sender=sender)


GLOBAL_PROVIDER_REGISTRY = ProviderRegistry()


__all__ = [
    "GLOBAL_PROVIDER_REGISTRY",
    "ProviderRegistry",
    "ProviderRequestState",
    "ProviderSelection",
    "ProviderStateMachine",
]
