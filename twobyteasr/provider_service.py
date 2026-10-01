"""Persistent in-process broker for HTTP and one-shot CLI AI adapters."""

from __future__ import annotations

import hashlib
import copy
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from .ai_providers import (
    AIProvider,
    AIProviderError,
    AITransport,
    ProviderStatus,
    adapter_for_stage,
    transport_for_stage,
)
from .resource_governor import GLOBAL_RESOURCE_GOVERNOR, ResourceGovernor, ResourceKind
from .provider_diagnostics import redact_diagnostics


class ProviderHealthState(str, Enum):
    UNKNOWN = "UNKNOWN"
    READY = "READY"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass(frozen=True)
class ProviderCapabilityManifest:
    text: bool = True
    vision: bool = False
    structured_output: bool = True
    structured_output_mode: str = "JSON_MODE"
    streaming: bool = False
    reasoning: bool = False
    tool_calling: bool = False
    max_context: int | None = None
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderHealth:
    state: ProviderHealthState
    message: str
    checked_monotonic: float
    models: tuple[str, ...] = ()


@dataclass
class _ProviderRuntime:
    key: str
    stage: str
    transport: AITransport
    adapter: AIProvider | None
    manifest: ProviderCapabilityManifest
    configuration_error: str = ""
    health: ProviderHealth = field(default_factory=lambda: ProviderHealth(
        ProviderHealthState.UNKNOWN, "尚未检测", 0.0,
    ))
    failure_count: int = 0
    circuit_open_until: float = 0.0
    probe_lock: Any = field(default_factory=threading.Lock)
    login_lock: Any = field(default_factory=threading.Lock)


@dataclass
class ProviderRequestHandle:
    request_id: str
    provider_id: str
    deadline_monotonic: float
    submitted_monotonic: float = field(default_factory=time.monotonic)
    _event: threading.Event = field(default_factory=threading.Event)
    _cancelled: threading.Event = field(default_factory=threading.Event)
    _value: Any = None
    _error: BaseException | None = None
    request_timeout_seconds: float | None = None
    timeout_category: str = "timeout"
    trace: dict[str, Any] = field(default_factory=dict)

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def result(self, timeout: float | None = None) -> Any:
        if not self._event.wait(timeout):
            self.cancel()
            raise AIProviderError("AI 请求超时。", category=self.timeout_category)
        if self._error is not None:
            raise self._error
        return self._value


@dataclass(order=True)
class _QueuedProviderRequest:
    sort_priority: int
    sequence: int
    handle: ProviderRequestHandle = field(compare=False)
    runtime: _ProviderRuntime = field(compare=False)
    messages: Sequence[Mapping[str, Any]] = field(compare=False)
    schema: Mapping[str, Any] | None = field(compare=False)
    kwargs: dict[str, Any] = field(compare=False)
    external_cancel: Callable[[], bool] | None = field(compare=False, default=None)
    callbacks: dict[str, Callable[..., Any]] = field(compare=False, default_factory=dict)


class AIClient(AIProvider):
    """Thin request facade; the ProviderService owns lifecycle and policy."""

    def __init__(
        self,
        service: "ProviderService",
        settings: Mapping[str, Any],
        stage: str,
        *,
        sender: Callable[..., str] | None = None,
    ) -> None:
        self._service = service
        self._settings = copy.deepcopy(dict(settings))
        self._stage = str(stage)
        self._sender = sender
        self.transport = transport_for_stage(settings, stage)
        models = settings.get("models", {}) if isinstance(settings, Mapping) else {}
        from .llm_config import endpoint_from_settings
        self.model = str(endpoint_from_settings(dict(settings),stage).get('model') or '')
        if self.transport is AITransport.ANTIGRAVITY_CLI:
            self.provider_id = "google_antigravity"
        elif self.transport is AITransport.GROK_CLI:
            self.provider_id = "grok_oauth"
        elif self.transport is AITransport.CODEX_CLI:
            self.provider_id = "openai_codex_cli"
        else:
            self.provider_id = str(models.get(f"{stage}_provider") or "custom")
        self.last_timings: dict[str, float | bool] = {}

    def capabilities(self) -> ProviderCapabilityManifest:
        return self._service.capabilities(
            self._settings, self._stage, sender=self._sender,
        )

    def structured_output_mode(self) -> str:
        return self.capabilities().structured_output_mode

    def health(self, *, refresh: bool = False) -> ProviderHealth:
        return self._service.health(
            self._settings, self._stage, sender=self._sender, refresh=refresh,
        )

    def validate(
        self,
        *,
        timeout: float = 20.0,
        cancel_check: Callable[[], bool] | None = None,
        use_cache: bool = True,
        on_progress=None,
    ) -> ProviderStatus:
        started = time.monotonic()
        previous_health = self.cached_health()
        health = self._service.health(
            self._settings,
            self._stage,
            sender=self._sender,
            refresh=not use_cache,
            timeout=max(0.1, float(timeout)),
            cancel_check=cancel_check,
            on_progress=on_progress,
        )
        elapsed = time.monotonic() - started
        self.last_timings = {
            **self.invocation_trace().get("timings", {}),
            "cache_hit": bool(use_cache and health is previous_health),
            "total_seconds": elapsed,
        }
        return ProviderStatus(
            health.state not in {ProviderHealthState.UNAVAILABLE},
            health.state is ProviderHealthState.READY,
            health.message,
            health.models,
        )

    def cached_health(self):
        return self._service._runtime_for(self._settings,self._stage,self._sender).health

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        max_tokens: int = 3500,
        temperature: float = 0.2,
        timeout: float | tuple[float, float] = 120.0,
        cancel_check: Callable[[], bool] | None = None,
        stage: str = "",
        **kwargs: Any,
    ) -> str:
        seconds = max(timeout) if isinstance(timeout, tuple) else float(timeout)
        started = time.monotonic()
        self._last_request_trace = {}
        handle = self.submit(
            messages,
            timeout=seconds,
            cancel_check=cancel_check,
            max_tokens=max_tokens,
            temperature=temperature,
            stage=stage,
            **kwargs,
        )
        policy = kwargs.get("_timeout_policy")
        wait_seconds = policy.queue + policy.total if policy is not None else seconds
        try:
            if policy is not None:
                while not handle._event.wait(.02):
                    if cancel_check is not None and cancel_check():
                        handle.cancel()
                        raise AIProviderError("AI 请求已取消。", category="cancelled")
                    if time.monotonic() >= handle.deadline_monotonic:
                        handle.cancel()
                        diagnostics = kwargs.get("request_diagnostics")
                        if diagnostics is not None and handle.timeout_category == "queue_timeout":
                            diagnostics["queue_wait_ms"] = round((time.monotonic()-handle.submitted_monotonic)*1000, 3)
                        raise AIProviderError("AI 请求超时。", category=handle.timeout_category)
            value = handle.result(max(0.1, wait_seconds) + 1.0)
        finally:
            self._last_request_trace = copy.deepcopy(handle.trace)
            self._last_request_trace.setdefault('request_id', handle.request_id)
            self._last_request_trace.setdefault('receipt_status', 'complete' if handle._event.is_set() else 'cleanup_pending')
        self.last_timings = {**self.invocation_trace().get("timings", {}), "total_seconds": time.monotonic() - started}
        return str(value)

    def submit(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        timeout: float | tuple[float, float] = 120.0,
        cancel_check: Callable[[], bool] | None = None,
        priority: int = 0,
        max_tokens: int = 3500,
        temperature: float = 0.2,
        stage: str = "",
        **kwargs: Any,
    ) -> ProviderRequestHandle:
        seconds = max(timeout) if isinstance(timeout, tuple) else float(timeout)
        return self._service.submit(
            self._settings,
            self._stage,
            messages,
            sender=self._sender,
            timeout=seconds,
            cancel_check=cancel_check,
            priority=priority,
            max_tokens=max_tokens,
            temperature=temperature,
            _adapter_stage=stage,
            **kwargs,
        )

    def structured_complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        schema: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        timeout = kwargs.pop("timeout", 120.0)
        adapter_stage = kwargs.pop("stage", "")
        seconds = max(timeout) if isinstance(timeout, tuple) else float(timeout)
        started = time.monotonic()
        self._last_request_trace = {}
        handle = self._service.submit(
            self._settings,
            self._stage,
            messages,
            schema=dict(schema),
            sender=self._sender,
            timeout=seconds,
            _adapter_stage=adapter_stage,
            **kwargs,
        )
        try:
            value = handle.result(max(0.1, seconds) + 1.0)
        finally:
            self._last_request_trace = copy.deepcopy(handle.trace)
            self._last_request_trace.setdefault('request_id', handle.request_id)
            self._last_request_trace.setdefault('receipt_status', 'complete' if handle._event.is_set() else 'cleanup_pending')
        self.last_timings = {**self.invocation_trace().get("timings", {}), "total_seconds": time.monotonic() - started}
        if not isinstance(value, dict):
            raise AIProviderError("AI 服务返回的 JSON 不是对象。", category="structured_output")
        return value

    def login(
        self,
        *,
        timeout: float = 300.0,
        on_progress: Callable[[str], None] | None = None,
        cancel_check=None,
        user_initiated: bool = False,
    ) -> ProviderStatus:
        return self._service.login(
            self._settings, self._stage, sender=self._sender, timeout=timeout,
            on_progress=on_progress,
            cancel_check=cancel_check,
            user_initiated=user_initiated,
        )

    def logout(self, *, cancel_check=None):
        runtime = self._service._runtime_for(self._settings,self._stage,self._sender)
        action = getattr(runtime.adapter,"logout",None)
        if not callable(action):raise AIProviderError("当前服务不支持退出登录。",category="unsupported")
        status = action(cancel_check=cancel_check)
        runtime.health = ProviderHealth(ProviderHealthState.AUTH_REQUIRED,status.message,time.monotonic())
        return status

    def cancel_login(self):
        runtime = self._service._runtime_for(self._settings,self._stage,self._sender)
        return getattr(runtime.adapter,"cancel",lambda:False)()

    def discover_models(
        self,
        *,
        timeout: float = 20.0,
        cancel_check: Callable[[], bool] | None = None,
        refresh: bool = False,
    ) -> tuple[str, ...]:
        return self._service.discover_models(
            self._settings,
            self._stage,
            sender=self._sender,
            timeout=timeout,
            cancel_check=cancel_check,
            refresh=refresh,
        )

    def invocation_trace(self) -> dict[str, Any]:
        """Return the redaction-ready trace from the actual owned adapter."""
        if hasattr(self, '_last_request_trace'):
            return copy.deepcopy(self._last_request_trace)
        return self._service.invocation_trace(
            self._settings, self._stage, sender=self._sender,
        )

    def record_validation(self, seconds: float, error: str = "") -> None:
        runtime = self._service._runtime_for(self._settings, self._stage, self._sender)
        if runtime.adapter is not None:
            from .provider_diagnostics import redact_diagnostics
            runtime.adapter.last_timings["schema_parse_seconds"] = seconds
            runtime.adapter.last_invocation_trace["schema_error"] = redact_diagnostics(error)


class ProviderService:
    """Persistent broker with typed health, deadlines, cancellation and circuit state."""

    def __init__(
        self,
        *,
        workers: int = 2,
        governor: ResourceGovernor | None = None,
        circuit_failures: int = 3,
        circuit_seconds: float = 30.0,
    ) -> None:
        self._workers_requested = max(1, int(workers))
        self._governor = governor or GLOBAL_RESOURCE_GOVERNOR
        self._circuit_failures = max(1, int(circuit_failures))
        self._circuit_seconds = max(1.0, float(circuit_seconds))
        self._lock = threading.RLock()
        self._runtimes: dict[str, _ProviderRuntime] = {}
        self._queue: queue.PriorityQueue[_QueuedProviderRequest] = queue.PriorityQueue()
        self._threads: list[threading.Thread] = []
        self._handles: dict[str, ProviderRequestHandle] = {}
        self._sequence = 0
        self._telemetry: list[dict[str, Any]] = []

    @staticmethod
    def _config_key(
        settings: Mapping[str, Any],
        stage: str,
        sender: Callable[..., str] | None,
    ) -> str:
        from .llm_config import endpoint_from_settings, active_service_values
        # Home and Studio differ in unrelated UI options, not provider identity.
        transport = transport_for_stage(settings, stage)
        endpoint = endpoint_from_settings(dict(settings), stage)
        model_settings = settings.get("models", {})
        if transport is not AITransport.OPENAI_COMPATIBLE:
            # API-only checkbox state and catalogue contents cannot split the
            # same official CLI session. Use the actual invocation identity.
            material = [transport.value, endpoint.get("model") or '']
        else:
            material = [transport.value, endpoint,
                {name:model_settings.get(f"{stage}_{name}") for name in ("capabilities","max_context")}]
        encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"{digest}:{id(sender) if sender is not None else 0}"

    @staticmethod
    def _manifest(settings: Mapping[str, Any], stage: str, transport: AITransport) -> ProviderCapabilityManifest:
        models = settings.get("models", {}) if isinstance(settings, Mapping) else {}
        explicit = models.get(f"{stage}_capabilities")
        values: set[str] = set()
        if isinstance(explicit, Mapping):
            values = {str(key) for key, enabled in explicit.items() if enabled}
        elif isinstance(explicit, (list, tuple, set)):
            values = {str(item) for item in explicit}
        defaults = {"text", "structured_output"}
        values = values or defaults
        max_context = models.get(f"{stage}_max_context")
        from .llm_config import endpoint_from_settings
        model = str(endpoint_from_settings(dict(settings),stage).get('model') or '')
        protocol = str(models.get(f"{stage}_protocol") or "").casefold()
        if transport is not AITransport.OPENAI_COMPATIBLE:
            structured_mode = "TEXT_JSON"
        elif protocol == "responses":
            structured_mode = "STRICT_JSON_SCHEMA"
        else:
            structured_mode = "JSON_MODE"
        return ProviderCapabilityManifest(
            text="text" in values,
            vision="vision" in values,
            structured_output="structured_output" in values,
            structured_output_mode=structured_mode,
            # Current HTTP and CLI adapters return completed payloads only.
            streaming=False,
            reasoning="reasoning" in values,
            tool_calling="tool_calling" in values,
            max_context=int(max_context) if max_context not in {None, ""} else None,
            models=(model,) if model else (),
        )

    def _runtime_for(
        self,
        settings: Mapping[str, Any],
        stage: str,
        sender: Callable[..., str] | None,
    ) -> _ProviderRuntime:
        key = self._config_key(settings, stage, sender)
        with self._lock:
            existing = self._runtimes.get(key)
            if existing is not None:
                return existing
        transport = transport_for_stage(settings, stage)
        error = ""
        adapter: AIProvider | None = None
        try:
            adapter = adapter_for_stage(settings, stage, sender=sender)
        except Exception as exc:
            error = str(exc)
        runtime = _ProviderRuntime(
            key=key,
            stage=str(stage),
            transport=transport,
            adapter=adapter,
            manifest=self._manifest(settings, stage, transport),
            configuration_error=error,
        )
        if error and any(token in error.casefold() for token in ("api key", "密钥", "credential")):
            runtime.health = ProviderHealth(
                ProviderHealthState.AUTH_REQUIRED,
                error,
                time.monotonic(),
            )
        with self._lock:
            return self._runtimes.setdefault(key, runtime)

    @staticmethod
    def _health_from_status(status: ProviderStatus) -> ProviderHealthState:
        message = str(status.message or "").casefold()
        if "timed out" in message or "超时" in message:
            return ProviderHealthState.UNKNOWN
        if status.available and status.authenticated:
            return ProviderHealthState.READY
        if status.available:
            return ProviderHealthState.AUTH_REQUIRED
        return ProviderHealthState.UNAVAILABLE

    def client_for_stage(
        self,
        settings: Mapping[str, Any],
        stage: str,
        *,
        sender: Callable[..., str] | None = None,
    ) -> AIClient:
        return AIClient(self, settings, stage, sender=sender)

    def capabilities(
        self,
        settings: Mapping[str, Any],
        stage: str,
        *,
        sender: Callable[..., str] | None = None,
    ) -> ProviderCapabilityManifest:
        runtime = self._runtime_for(settings, stage, sender)
        getter = getattr(runtime.adapter,"runtime_capabilities",None)
        if callable(getter):
            runtime.manifest = ProviderCapabilityManifest(**{**runtime.manifest.__dict__,**getter()})
        return runtime.manifest

    def invocation_trace(
        self,
        settings: Mapping[str, Any],
        stage: str,
        *,
        sender: Callable[..., str] | None = None,
    ) -> dict[str, Any]:
        runtime = self._runtime_for(settings, stage, sender)
        payload = getattr(runtime.adapter, "last_invocation_trace", {})
        result = dict(payload) if isinstance(payload, Mapping) else {}
        result['timings'] = dict(getattr(runtime.adapter,'last_timings',{}) or {})
        history = getattr(runtime.adapter, "process_trace_history", ())
        if isinstance(history, (list, tuple)):
            result["process_history"] = [dict(item) for item in history if isinstance(item, Mapping)]
        from .provider_diagnostics import diagnostic_phases, redact_diagnostics
        result["phases"] = diagnostic_phases(result)
        return redact_diagnostics(result)

    def health(
        self,
        settings: Mapping[str, Any],
        stage: str,
        *,
        sender: Callable[..., str] | None = None,
        refresh: bool = False,
        timeout: float = 1.5,
        cancel_check: Callable[[], bool] | None = None,
        on_progress=None,
    ) -> ProviderHealth:
        runtime = self._runtime_for(settings, stage, sender)
        now_mono = time.monotonic()
        if runtime.configuration_error:
            runtime.health = ProviderHealth(
                ProviderHealthState.UNAVAILABLE, runtime.configuration_error, now_mono,
            )
            return runtime.health
        if runtime.circuit_open_until > now_mono:
            return ProviderHealth(
                ProviderHealthState.DEGRADED,
                "Provider 连续失败，暂时停止请求；请稍后重试。",
                runtime.health.checked_monotonic,
                runtime.health.models,
            )
        if not refresh and runtime.health.state is not ProviderHealthState.UNKNOWN and now_mono-runtime.health.checked_monotonic<480:
            return runtime.health
        if cancel_check is not None and cancel_check():
            raise AIProviderError("AI 检测已取消。", category="cancelled")
        assert runtime.adapter is not None
        started = time.monotonic()
        try:
            while not runtime.probe_lock.acquire(timeout=.05):
                if cancel_check and cancel_check():
                    raise AIProviderError("AI 检测已取消。",category="cancelled")
            try:
                # Another UI may have completed the same probe while we waited.
                reuse = runtime.health.checked_monotonic > started
                if reuse:
                    return runtime.health
                runtime.adapter._probe_progress = on_progress
                status = runtime.adapter.validate(timeout=max(.1,float(timeout)),
                    cancel_check=cancel_check,use_cache=not refresh)
            finally:
                runtime.adapter._probe_progress = None
                runtime.probe_lock.release()
        except Exception as exc:
            if getattr(exc,'category','')=='cancelled':
                raise
            runtime.health = ProviderHealth(
                ProviderHealthState.UNAVAILABLE, str(exc), time.monotonic(),
            )
            return runtime.health
        state = self._health_from_status(status)
        if state is ProviderHealthState.UNKNOWN:
            invalidate = getattr(runtime.adapter, "invalidate_status_cache", None)
            if callable(invalidate):
                invalidate()
        runtime.health = ProviderHealth(state, status.message, time.monotonic(), tuple(status.models))
        if status.models:
            from .llm_config import active_service_values, cache_service_models
            cache_service_models(active_service_values(dict(settings),stage=stage).get('service'),status.models,settings=dict(settings))
        self._record(runtime, "health", {
            "status": state.value,
            "total_ms": round((time.monotonic() - started) * 1000.0, 3),
        })
        return runtime.health

    def login(
        self,
        settings: Mapping[str, Any],
        stage: str,
        *,
        sender: Callable[..., str] | None = None,
        timeout: float = 300.0,
        on_progress: Callable[[str], None] | None = None,
        cancel_check=None,
        user_initiated: bool = False,
    ) -> ProviderStatus:
        if not user_initiated:
            raise AIProviderError('请明确点击“登录”后启动官方认证；播放、预览与后台探测不会启动登录。',category='explicit_login_required')
        runtime = self._runtime_for(settings, stage, sender)
        login = getattr(runtime.adapter, "login", None)
        if not callable(login):
            return ProviderStatus(False, False, "当前服务不支持 OAuth CLI 登录")
        if not runtime.login_lock.acquire(blocking=False):
            raise AIProviderError("官方登录窗口正在等待认证，请回到已打开的登录流程。", category="login_in_progress")
        previous = runtime.health
        try:
            kwargs = {"timeout": timeout, "on_progress": on_progress}
            if runtime.transport in (AITransport.CODEX_CLI, AITransport.ANTIGRAVITY_CLI):
                kwargs["cancel_check"] = cancel_check
            try:
                from .processes import process_action_scope
                with process_action_scope('user-click-provider-login'):
                    status = login(**kwargs)
            except Exception as exc:
                # Cancelling a new OAuth attempt cannot revoke an existing
                # session. Recheck Codex via its cheap official status command.
                detail = redact_diagnostics(str(exc))
                if runtime.transport is AITransport.CODEX_CLI:
                    try:
                        current = runtime.adapter.validate(timeout=5, use_cache=False)
                    except Exception:
                        current = None
                    if current is not None and current.authenticated:
                        status = ProviderStatus(True, True, detail + "；当前账号仍已登录。", current.models)
                    else:
                        raise
                elif previous and previous.state is ProviderHealthState.READY:
                    status = ProviderStatus(True, True, detail + "；保留已验证会话。", previous.models)
                else:
                    raise
        finally:
            runtime.login_lock.release()
        runtime.health = ProviderHealth(
            ProviderHealthState.READY if status.authenticated else ProviderHealthState.AUTH_REQUIRED,
            status.message,
            time.monotonic(),
            tuple(status.models),
        )
        return status

    def discover_models(
        self,
        settings: Mapping[str, Any],
        stage: str,
        *,
        sender: Callable[..., str] | None = None,
        timeout: float = 20.0,
        cancel_check: Callable[[], bool] | None = None,
        refresh: bool = False,
    ) -> tuple[str, ...]:
        runtime = self._runtime_for(settings, stage, sender)
        if runtime.adapter is None:
            raise AIProviderError(
                runtime.configuration_error or "Provider 配置无效。",
                category="model_discovery",
            )
        started = time.monotonic()
        models = runtime.adapter.discover_models(
            timeout=timeout,
            cancel_check=cancel_check,
            refresh=refresh,
        )
        runtime.manifest = ProviderCapabilityManifest(
            **{
                **runtime.manifest.__dict__,
                "models": tuple(models),
            }
        )
        runtime.health = ProviderHealth(
            runtime.health.state,
            runtime.health.message,
            time.monotonic(),
            tuple(models),
        )
        from .llm_config import active_service_values, cache_service_models
        cache_service_models(active_service_values(dict(settings),stage=stage).get('service'),models,settings=dict(settings))
        self._record(runtime, "model_discovery", {
            "status": "OK",
            "model_count": len(models),
            "total_ms": round((time.monotonic() - started) * 1000.0, 3),
            "refresh": bool(refresh),
        })
        return tuple(models)

    def _ensure_workers(self) -> None:
        with self._lock:
            while len(self._threads) < self._workers_requested:
                thread = threading.Thread(
                    target=self._worker,
                    daemon=True,
                    name=f"provider-service-{len(self._threads) + 1}",
                )
                self._threads.append(thread)
                thread.start()

    def submit(
        self,
        settings: Mapping[str, Any],
        stage: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        schema: Mapping[str, Any] | None = None,
        sender: Callable[..., str] | None = None,
        timeout: float = 120.0,
        cancel_check: Callable[[], bool] | None = None,
        priority: int = 0,
        **kwargs: Any,
    ) -> ProviderRequestHandle:
        # Validate operation budgets before queueing, including any implicit
        # HTTP readiness probe performed by _execute. Adapters repeat the
        # deterministic check at their own direct-call boundary.
        if kwargs.get('operation_kind') is not None:
            from .llm_config import endpoint_from_settings
            from .model_discovery import model_limits
            endpoint=endpoint_from_settings(dict(settings),stage)
            kwargs['_model_limits']=model_limits(endpoint.get('provider',''),endpoint.get('base_url',''),
                endpoint.get('api_key',''),endpoint.get('model',''))
            from .provider_input_budget import prepare_input,InputBudgetError,project_transport_messages
            messages = project_transport_messages(messages, schema or kwargs.get('json_schema'), transport_for_stage(settings,stage))
            try:
                prepare_input(messages,schema=schema or kwargs.get('json_schema'),max_tokens=kwargs.get('max_tokens',3500),
                    operation=kwargs['operation_kind'],scope=kwargs.get('input_scope'),
                    crops=kwargs.get('image_crops'),comparison=bool(kwargs.get('image_comparison')),
                    model_limits=kwargs.get('_model_limits'),user_limits=kwargs.get('_user_limits'))
            except InputBudgetError as exc:
                error=AIProviderError(str(exc),category='request_too_large');error.report=exc.report
                raise error from exc
        runtime = self._runtime_for(settings, stage, sender)
        request_id = uuid.uuid4().hex
        policy = kwargs.get("_timeout_policy")
        handle = ProviderRequestHandle(
            request_id=request_id,
            provider_id=str(getattr(runtime.adapter, "provider_id", "unavailable")),
            deadline_monotonic=time.monotonic() + (policy.queue if policy is not None else max(0.1, float(timeout))),
            request_timeout_seconds=policy.total if policy is not None else None,
            timeout_category="queue_timeout" if policy is not None else "timeout",
        )
        absolute_deadline=getattr(policy,'deadline_monotonic',None)
        if absolute_deadline is not None:
            handle.deadline_monotonic=min(handle.deadline_monotonic,absolute_deadline)
        callbacks = {
            name: callback
            for name in ("on_start", "on_delta", "on_usage", "on_complete", "on_error")
            if callable(callback := kwargs.pop(name, None))
        }
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
            self._handles[request_id] = handle
        self._queue.put(_QueuedProviderRequest(
            -int(priority), sequence, handle, runtime, tuple(copy.deepcopy(messages)),
            copy.deepcopy(dict(schema)) if isinstance(schema, Mapping) else None,
            dict(kwargs), cancel_check, callbacks,
        ))
        self._ensure_workers()
        return handle

    def _worker(self) -> None:
        while True:
            request = self._queue.get()
            handle = request.handle
            try:
                if handle.cancelled or (request.external_cancel and request.external_cancel()):
                    raise AIProviderError("AI 请求已取消。", category="cancelled")
                with self._governor.lease(
                    ResourceKind.AI,
                    foreground=False,
                    cancelled=lambda: (
                        handle.cancelled
                        or (request.external_cancel is not None and request.external_cancel())
                        or time.monotonic() >= handle.deadline_monotonic
                    ),
                ) as allowed:
                    if not allowed:
                        category = "cancelled" if handle.cancelled or (request.external_cancel and request.external_cancel()) else handle.timeout_category
                        raise AIProviderError("AI 请求已取消。" if handle.cancelled else "AI 请求超时。", category=category)
                    handle._value = self._execute(request)
            except BaseException as exc:
                handle._error = exc
            finally:
                handle._event.set()
                with self._lock:
                    self._handles.pop(handle.request_id, None)
                self._queue.task_done()

    def cancel_all(self) -> int:
        """Broadcast cancellation without waiting for adapters or child processes."""
        with self._lock:
            handles = tuple(self._handles.values())
        for handle in handles:
            handle.cancel()
        return len(handles)

    def wait_for_idle(self, timeout: float = 2.0) -> bool:
        """Wait a bounded interval for all submitted requests to leave the broker."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            with self._lock:
                handles = tuple(self._handles.values())
            if not handles:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return False
            handles[0]._event.wait(min(0.05, remaining))

    def shutdown(self, *, timeout: float = 2.0) -> bool:
        """Cancel active work and wait a bounded interval for adapter teardown."""

        self.cancel_all()
        return self.wait_for_idle(timeout=timeout)

    def _execute(self, request: _QueuedProviderRequest) -> Any:
        runtime, handle = request.runtime, request.handle
        started = time.monotonic()
        health = runtime.health
        policy = request.kwargs.get("_timeout_policy")
        design_operation = request.kwargs.get('operation_kind') is not None
        if policy is not None:
            # ASR snapshots were resolved before the task. Do not issue an
            # uncounted readiness request or inherit another batch's circuit.
            if runtime.configuration_error or runtime.adapter is None:
                raise AIProviderError("ASR Provider配置无效。", category="configuration_error")
            if runtime.transport is AITransport.OPENAI_COMPATIBLE:
                from .llm_config import validate_endpoint
                validate_endpoint(runtime.adapter.endpoint, "ASR Provider")
            health = ProviderHealth(ProviderHealthState.READY, "ASR配置已验证", time.monotonic())
        elif design_operation and health.state is ProviderHealthState.UNKNOWN and runtime.transport is AITransport.OPENAI_COMPATIBLE:
            # A design button owns one budgeted request. A hidden 1.5s text
            # probe can reject an otherwise working slow endpoint and is not
            # the requested generation. Validate configuration here; report
            # actual authentication/availability from that one real request.
            if runtime.configuration_error or runtime.adapter is None:
                raise AIProviderError('AI Provider配置无效。', category='configuration_error')
            from .llm_config import validate_endpoint
            validate_endpoint(runtime.adapter.endpoint, 'AI 设计')
        elif health.state is ProviderHealthState.UNKNOWN and runtime.transport is AITransport.OPENAI_COMPATIBLE:
            # The runtime already owns the configured adapter; keep the initial
            # auth probe bounded so a missing login never becomes a 150s call.
            assert runtime.adapter is not None or runtime.configuration_error
            if runtime.configuration_error:
                health = ProviderHealth(ProviderHealthState.UNAVAILABLE, runtime.configuration_error, time.monotonic())
                runtime.health = health
            else:
                try:
                    status = runtime.adapter.validate(
                        timeout=1.5,
                        cancel_check=lambda: handle.cancelled or (
                            request.external_cancel is not None and request.external_cancel()
                        ),
                        use_cache=True,
                    )
                except TypeError:
                    status = runtime.adapter.validate(timeout=1.5)
                state = self._health_from_status(status)
                if state is ProviderHealthState.UNKNOWN:
                    invalidate = getattr(runtime.adapter, "invalidate_status_cache", None)
                    if callable(invalidate):
                        invalidate()
                health = ProviderHealth(state, status.message, time.monotonic(), tuple(status.models))
                runtime.health = health
        if health.state is ProviderHealthState.AUTH_REQUIRED:
            raise AIProviderError("需要登录当前 AI Provider。", category="authentication_required")
        if health.state in {
            ProviderHealthState.UNAVAILABLE,
            ProviderHealthState.DEGRADED,
            ProviderHealthState.RATE_LIMITED,
        }:
            raise AIProviderError(health.message or "AI Provider 不可用。", category=health.state.value.casefold())
        if time.monotonic() >= handle.deadline_monotonic:
            raise AIProviderError("AI 请求等待超时。", category=handle.timeout_category)
        policy = request.kwargs.get("_timeout_policy")
        if policy is not None:
            handle.deadline_monotonic = time.monotonic() + policy.total
            absolute_deadline=getattr(policy,'deadline_monotonic',None)
            if absolute_deadline is not None:
                handle.deadline_monotonic=min(handle.deadline_monotonic,absolute_deadline)
            handle.timeout_category = "total_timeout"
            diagnostics = request.kwargs.get("request_diagnostics")
            if diagnostics is not None:
                diagnostics["queue_wait_ms"] = round(
                    float(diagnostics.get("queue_wait_ms") or 0) + (time.monotonic()-handle.submitted_monotonic)*1000, 3)
                diagnostics["transport_started_monotonic"] = time.monotonic()
        callback = request.callbacks.get("on_start")
        if callback:
            callback(handle.request_id)
        assert runtime.adapter is not None
        fork = getattr(runtime.adapter, 'fork_request', None)
        adapter = fork() if callable(fork) else runtime.adapter
        retry_count = 0
        last_error: BaseException | None = None
        while retry_count <= 1:
            remaining = handle.deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise AIProviderError("AI 请求超时。", category="timeout")
            cancel_check = lambda: handle.cancelled or (
                request.external_cancel is not None and request.external_cancel()
            )
            kwargs = dict(request.kwargs)
            kwargs.pop("_timeout_policy", None)
            kwargs["timeout"] = (min(policy.connect, remaining), min(policy.read_idle, remaining)) if policy is not None and runtime.transport is AITransport.OPENAI_COMPATIBLE else remaining
            if policy is not None:
                kwargs["_total_deadline"] = handle.deadline_monotonic
            kwargs["cancel_check"] = cancel_check
            kwargs["stage"] = kwargs.pop("_adapter_stage", "")
            diagnostics = kwargs.get('request_diagnostics')
            if diagnostics is not None:
                diagnostics['request_id'] = handle.request_id
            stream_callback=kwargs.get('on_stream_event')
            if stream_callback:
                stream_callback('request_identity', json.dumps({'provider_request_id':handle.request_id,
                    'attempt':retry_count+1,'transport':runtime.transport.value}))
            try:
                if request.schema is not None:
                    value = adapter.structured_complete(
                        request.messages, request.schema, **kwargs,
                    )
                else:
                    value = adapter.complete(request.messages, **kwargs)
                if cancel_check():
                    raise AIProviderError('AI 请求已取消，丢弃迟到结果。', category='cancelled')
                runtime.failure_count = 0
                runtime.circuit_open_until = 0.0
                runtime.health = ProviderHealth(
                    ProviderHealthState.READY,
                    "Provider 请求成功",
                    time.monotonic(),
                    runtime.health.models,
                )
                total_ms = (time.monotonic() - started) * 1000.0
                queue_ms = max(0.0, (started - handle.submitted_monotonic) * 1000.0)
                self._record(runtime, "request", {
                    "request_id": handle.request_id,
                    "model": str(getattr(runtime.adapter, "model", "")),
                    "queue_ms": round(queue_ms, 3),
                    "first_response_ms": (float(adapter.last_timings["first_stdout_seconds"])*1000 if getattr(adapter,"last_timings",{}).get("first_stdout_seconds") is not None else None),
                    "total_ms": round(total_ms, 3),
                    "retry_count": retry_count,
                    "status": "OK",
                    "fallback": False,
                })
                if callback := request.callbacks.get("on_complete"):
                    callback(value)
                return value
            except BaseException as exc:
                last_error = exc
                category = str(getattr(exc, "category", "provider_error"))
                if category == "authentication_required":
                    runtime.health = ProviderHealth(
                        ProviderHealthState.AUTH_REQUIRED, str(exc), time.monotonic(),
                    )
                if category in {"rate_limit", "rate_limited"}:
                    runtime.health = ProviderHealth(
                        ProviderHealthState.RATE_LIMITED, str(exc), time.monotonic(),
                    )
                retryable = category in {
                    "connection", "server_error", "transient", "rate_limit", "rate_limited",
                }
                if policy is not None or design_operation or not retryable or retry_count >= 1 or handle.cancelled:
                    break
                retry_count += 1
            finally:
                handle.trace = copy.deepcopy(getattr(adapter, 'last_invocation_trace', {}))
                handle.trace['timings'] = copy.deepcopy(getattr(adapter, 'last_timings', {}))
                handle.trace['provider_request_id'] = handle.trace.get('request_id')
                handle.trace['request_id'] = handle.request_id
                if adapter is not runtime.adapter:
                    # Last-completed UI diagnostics only. Never transfer process
                    # ownership or mutable dictionaries from a live request.
                    runtime.adapter.last_invocation_trace = copy.deepcopy(handle.trace)
                    runtime.adapter.last_timings = copy.deepcopy(handle.trace['timings'])
        assert last_error is not None
        category = str(getattr(last_error, "category", "provider_error"))
        if category not in {
            "cancelled", "authentication_required", "structured_output", "structured_output_schema",
            "structured_json_parse_error", "schema", "quality_validator",
            # timeout 是延迟信号（CLI 账号会话常见长尾），不是供应商死亡。
            # 计入熔断会让并行批次的正常慢批连锁击穿（2026-09-03 断句 9/13
            # 回退取证）；调用方已有自己的重试与本地回退。
            "timeout",
            "provider_total_timeout", "provider_inactivity_timeout",
            "queue_timeout", "connect_timeout", "read_idle_timeout", "total_timeout",
            "first_response_timeout", "idle_timeout",
            "empty_response", "format_mismatch", "parse_failure", "text_mutation_rejected",
            "request_too_large", "payload_too_large", "transport_length", "permission_denied",
            "unsupported_search",
        }:
            runtime.failure_count += 1
            if runtime.failure_count >= self._circuit_failures:
                runtime.circuit_open_until = time.monotonic() + self._circuit_seconds
                runtime.health = ProviderHealth(
                    ProviderHealthState.DEGRADED,
                    "Provider 连续失败，circuit 已打开。",
                    time.monotonic(),
                )
        total_ms = (time.monotonic() - started) * 1000.0
        queue_ms = max(0.0, (started - handle.submitted_monotonic) * 1000.0)
        self._record(runtime, "request", {
            "request_id": handle.request_id,
            "model": str(getattr(runtime.adapter, "model", "")),
            "queue_ms": round(queue_ms, 3),
            "first_response_ms": None,
            "total_ms": round(total_ms, 3),
            "cancel_ms": round(total_ms, 3) if category == "cancelled" else None,
            "retry_count": retry_count,
            "status": category,
            "fallback": False,
        })
        if callback := request.callbacks.get("on_error"):
            callback(last_error)
        raise last_error

    def _record(self, runtime: _ProviderRuntime, event: str, values: Mapping[str, Any]) -> None:
        payload = {
            "event": event,
            "timestamp": time.time(),
            "provider": str(getattr(runtime.adapter, "provider_id", "unavailable")),
            "adapter": runtime.transport.value,
            **dict(values),
        }
        # Prompts, credentials and response bodies are deliberately absent.
        with self._lock:
            self._telemetry.append(payload)
            if len(self._telemetry) > 1000:
                del self._telemetry[:-1000]

    def telemetry(self) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            return tuple(self._telemetry)


GLOBAL_PROVIDER_SERVICE = ProviderService()


__all__ = [
    "AIClient",
    "GLOBAL_PROVIDER_SERVICE",
    "ProviderCapabilityManifest",
    "ProviderHealth",
    "ProviderHealthState",
    "ProviderRequestHandle",
    "ProviderService",
]
