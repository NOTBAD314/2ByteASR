"""A server-required CLI update fails a task rather than silently degrading it."""
import threading

import pytest

from twobyteasr.providers.ai_providers import AIProviderError
from twobyteasr.recognition.transcript_data import SpeechSegment


@pytest.mark.parametrize("stage", ["polish", "group"])
def test_cli_upgrade_is_terminal_without_outer_retry_or_local_fallback(monkeypatch, stage):
    from tests.test_p5_llm_pipeline import _current_snapshot_fixture
    from twobyteasr.subtitle_rules import polishing, grouping
    from twobyteasr.providers import provider_input_budget
    _current_snapshot_fixture(monkeypatch)
    monkeypatch.setattr(polishing, "polish_llm_settings", lambda: {
        "provider": "custom", "model": "fixture", "base_url": "https://example.test",
        "url": "https://example.test/chat/completions", "api_key": "fixture-only"})
    calls = []
    class Provider:
        def complete(self, *args, **kwargs):
            calls.append(kwargs)
            raise AIProviderError("Grok CLI 版本过旧。服务端收到 1.0.5，要求至少 1.0.13。",
                                  category="upgrade_required")
    monkeypatch.setattr("twobyteasr.providers.ai_providers.provider_for_stage", lambda *a, **k: Provider())
    monkeypatch.setattr(grouping, "provider_for_stage", lambda *a, **k: Provider())
    def no_retry(*args):
        raise AssertionError("server-required update must never be retried")
    monkeypatch.setattr(provider_input_budget, "wait_retry", no_retry)
    segment = SpeechSegment(1, 0., 3., "这个选手也没有接住最后一枪", .9, [])
    abort = threading.Event()
    with pytest.raises(AIProviderError) as raised:
        if stage == "polish":
            polishing.call_correction_api([segment], [], "", "", "fixture", "fixture", [], [], [], abort_event=abort)
        else:
            grouping.call_grouping_api([segment], abort_event=abort)
    assert raised.value.category == "upgrade_required"
    assert len(calls) == 1
    assert abort.is_set()
