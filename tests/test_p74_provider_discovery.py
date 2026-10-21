import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.providers.ai_providers import (
    AIProvider,
    AIProviderError,
    OpenAICompatibleProvider,
)
from twobyteasr.app.ui import EndpointEditor, ProviderModelDiscoveryWorker


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _endpoint() -> dict:
    return {
        "provider": "custom",
        "base_url": "https://models.example/v1",
        "api_key": "temporary-key",
        "model": "manual-model",
        "url": "https://models.example/v1/chat/completions",
        "protocol": "openai_compatible_chat",
    }


def test_openai_model_discovery_uses_cache_and_refreshes(monkeypatch):
    fetches = []
    cache = {("custom", "https://models.example/v1"): ["cached-model"]}

    monkeypatch.setattr(
        "twobyteasr.providers.ai_providers.get_cached_models",
        lambda provider, base_url, **kwargs: cache.get((provider, base_url)),
    )
    monkeypatch.setattr(
        "twobyteasr.providers.ai_providers.fetch_openai_compatible_models",
        lambda base_url, api_key, timeout, **kwargs: fetches.append((base_url, api_key, timeout))
        or ["fresh-b", "fresh-a"],
    )
    monkeypatch.setattr(
        "twobyteasr.providers.ai_providers.set_cached_models",
        lambda provider, base_url, models, **kwargs: cache.__setitem__((provider, base_url), list(models)),
    )
    provider = OpenAICompatibleProvider(_endpoint())

    assert provider.discover_models() == ("cached-model",)
    assert fetches == []
    assert provider.discover_models(refresh=True) == ("fresh-b", "fresh-a")
    assert fetches == [("https://models.example/v1", "temporary-key", 20.0)]
    assert cache[("custom", "https://models.example/v1")] == ["fresh-b", "fresh-a"]


def test_model_discovery_cancellation_and_unsupported_manual_fallback(monkeypatch):
    provider = OpenAICompatibleProvider(_endpoint())
    monkeypatch.setattr(
        "twobyteasr.providers.ai_providers.fetch_openai_compatible_models",
        lambda *_args, **_kwargs: pytest.fail("cancelled discovery must not touch the network"),
    )
    with pytest.raises(AIProviderError) as cancelled:
        provider.discover_models(cancel_check=lambda: True, refresh=True)
    assert cancelled.value.category == "cancelled"

    with pytest.raises(AIProviderError) as unsupported:
        AIProvider().discover_models()
    assert unsupported.value.category == "model_discovery_unsupported"
    assert "手动输入" in str(unsupported.value)


def test_model_discovery_worker_reports_cancel_with_manual_fallback(monkeypatch):
    app = _app()
    entered = threading.Event()

    class CancelAwareProvider:
        def discover_models(self, *, cancel_check, **_kwargs):
            entered.set()
            deadline = time.monotonic() + 1.0
            while not cancel_check() and time.monotonic() < deadline:
                time.sleep(0.005)
            assert cancel_check()
            raise AIProviderError("模型发现已取消。", category="cancelled")

    monkeypatch.setattr(
        "twobyteasr.providers.endpoint_editor_ui.provider_for_stage",
        lambda _settings, _stage: CancelAwareProvider(),
    )
    worker = ProviderModelDiscoveryWorker({"models": {}}, "polish")
    failures = []
    worker.failed.connect(failures.append)
    worker.start()
    assert entered.wait(1.0)
    worker.requestInterruption()
    assert worker.wait(2_000)
    app.processEvents()

    assert failures == ["模型发现已取消；可继续手动输入模型 ID"]


def test_editable_model_selector_opens_from_text_area_click():
    app = _app()
    editor = EndpointEditor("AI 服务", "#5B8E63", "polish", {"models": {"ai_service": "openai"}})
    editor.resize(720, 620)
    editor.show()
    app.processEvents()

    line_edit = editor.model.lineEdit()
    assert line_edit is not None
    QTest.mouseClick(line_edit, Qt.MouseButton.LeftButton, pos=line_edit.rect().center())
    app.processEvents()

    assert editor.model._popup.isVisible()
    editor.model.hidePopup()
    editor.close()
    editor.deleteLater()
