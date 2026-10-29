"""P1: DeepSeek provider model registry + server-error passthrough."""
from __future__ import annotations

from twobyteasr.providers.llm_config import (
    AI_SERVICE_SPECS,
    model_is_retired,
    service_model_catalog,
)
from twobyteasr.caption_design.studio_ai import _provider_failure_message


class _FakeLLMError(Exception):
    category = "configuration_error"

    def __init__(self, message: str, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


def test_deepseek_registry_is_v4_only_retired_vision_exp_excluded():
    catalog = service_model_catalog({}, "deepseek")
    assert catalog[0] == "deepseek-v4-flash"
    assert "deepseek-v4-pro" in catalog
    # 2026-09-20：服务端已下线 -exp 试验模型，且它作为方案快照残留复活过
    # 死模型调用——目录与墓碑都不再把它当可选项。
    assert "deepseek-v4-flash-vision-exp" not in catalog
    assert model_is_retired("deepseek-v4-flash-vision-exp")
    assert "deepseek-v4-flash-vision" not in catalog, (
        "vision id without the server-side -exp suffix fails with model-not-exist"
    )
    assert "deepseek-chat" not in catalog
    assert "deepseek-reasoner" not in catalog
    assert "vision" in AI_SERVICE_SPECS["deepseek"]["capabilities"]


def test_model_failure_surfaces_server_detail():
    exc = _FakeLLMError(
        'HTTP 400：{"error":{"code":"Model Not Exist","message":"Model does not exist"}}',
        diagnostics={"http_status": 400, "model": "deepseek-v4-flash"},
    )
    _category, _stage, message, _gen = _provider_failure_message(exc)
    assert "HTTP 400" in message
    assert "model=deepseek-v4-flash" in message
    assert "Model Not Exist" in message, "server error body must not be flattened away"
