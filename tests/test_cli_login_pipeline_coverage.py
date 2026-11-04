# -*- coding: utf-8 -*-
"""2026-09-04 轮：CLI 登录态管线全覆盖 + 模型发现预设错位。

对应 plan：docs/exec-plans/active/2026-09-04-cli-login-pipeline-coverage.md
用户实录：Grok/Gemini 登录态在识别收尾的联网术语表决阶段报“字幕校对模型缺少
API 密钥”整轮作废；断句二轮校验静默跳过；全文断句编辑器选 DeepSeek 预设
点“刷新模型”拉到 Grok CLI 的模型列表。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest

import subtitle_core
from twobyteasr.providers import ai_providers
from twobyteasr.glossary import domain_terms as domain_terms_module


def _segment(segment_id, text, *, start=0.0, end=2.0):
    return subtitle_core.SpeechSegment(
        segment_id=segment_id,
        start=start,
        end=end,
        text=text,
        confidence=0.78,
        words=[],
        speaker="S01",
        moss_text=text,
        firered_text=text,
        qwen_asr_text=text,
    )


class _FakeCLIProvider:
    def __init__(self, content='{"mappings": []}'):
        self.content = content
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((list(messages), dict(kwargs)))
        if kwargs.get('enable_search') and kwargs.get('request_diagnostics') is not None:
            kwargs['request_diagnostics']['search_evidence']=[{'tool':'web_search','urls':['https://example.com/term']}]
        return self.content

    def validate(self, **kwargs):
        return ai_providers.ProviderStatus(True, True, "OAuth Session 可用")


def _patch_domain_terms_common(monkeypatch):
    """越过早期返回与落盘副作用，聚焦传输分派本身。"""
    monkeypatch.setattr(
        domain_terms_module,
        "collect_global_term_disputes",
        lambda *a, **k: [{"id":1,"primary_text":"听桥的声音","speaker":"S01"}],
    )
    from twobyteasr.recognition.run_context import RuntimeContext
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    owner=RuntimeContext(game_name='测试游戏')
    snapshot=resolve_provider_snapshot(subtitle_core.RUNTIME_SETTINGS)
    monkeypatch.setattr(domain_terms_module,'get_runtime_context',lambda:owner)
    monkeypatch.setattr('twobyteasr.providers.asr_provider_snapshot.task_provider_snapshot',lambda *a:snapshot)
    monkeypatch.setattr(
        domain_terms_module, "record_run_event", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        domain_terms_module, "persist_learned_mappings", lambda *a, **k: None,
    )


# ------------------------------------------------- 联网术语表决（domain_terms）


def test_domain_terms_grok_cli_uses_broker_without_http_validation(monkeypatch):
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", {
        "models": {"ai_service": "grok_account"},
        "switches": {},
    })
    _patch_domain_terms_common(monkeypatch)
    monkeypatch.setattr(
        domain_terms_module,
        "polish_llm_settings",
        lambda: {
            "provider": "grok_oauth", "model": "grok-4.6",
            "base_url": "", "url": "", "api_key": "",
        },
    )
    validate_calls = []
    monkeypatch.setattr(
        domain_terms_module, "validate_endpoint",
        lambda *a, **k: validate_calls.append(a),
    )
    monkeypatch.setattr(
        domain_terms_module, "post_chat_completion",
        lambda *a, **k: pytest.fail("CLI 传输不得走 HTTP post_chat_completion"),
    )
    provider = _FakeCLIProvider()
    monkeypatch.setattr(ai_providers, "provider_for_stage", lambda *a, **k: provider)

    result = domain_terms_module.discover_global_domain_term_mappings(
        [_segment(1, "听桥的声音")], "测试游戏", [], [], [{"term": "听潮"}]
    )

    assert result == []
    assert validate_calls == [], "CLI 传输不得触发 HTTP 端点校验（缺密钥弹窗根因）"
    assert provider.calls, "CLI 传输必须经 provider.complete 发送"
    _, kwargs = provider.calls[0]
    assert kwargs.get("stage") == "domain_terms"


def test_domain_terms_antigravity_cli_dispatches_too(monkeypatch):
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", {
        "models": {"ai_service": "antigravity"},
        "switches": {},
    })
    _patch_domain_terms_common(monkeypatch)
    monkeypatch.setattr(
        domain_terms_module,
        "polish_llm_settings",
        lambda: {"provider": "google_antigravity", "model": "", "base_url": "",
                 "url": "", "api_key": ""},
    )
    monkeypatch.setattr(
        domain_terms_module, "validate_endpoint",
        lambda *a, **k: pytest.fail("CLI 传输不得触发 HTTP 端点校验"),
    )
    provider = _FakeCLIProvider()
    monkeypatch.setattr(ai_providers, "provider_for_stage", lambda *a, **k: provider)

    domain_terms_module.discover_global_domain_term_mappings(
        [_segment(1, "听桥的声音")], "测试游戏", [], [], [{"term": "听潮"}]
    )
    assert provider.calls


def test_domain_terms_unsupported_search_does_not_send_request(monkeypatch):
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", {
        "models": {"ai_service": "deepseek"},
        "switches": {},
    })
    _patch_domain_terms_common(monkeypatch)
    monkeypatch.setattr(
        domain_terms_module,
        "polish_llm_settings",
        lambda: {
            "provider": "deepseek", "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
            "url": "https://api.deepseek.com/v1/chat/completions",
            "api_key": "",
        },
    )
    provider=_FakeCLIProvider()
    monkeypatch.setattr(ai_providers,'provider_for_stage',lambda *a,**k:provider)
    result=domain_terms_module.discover_global_domain_term_mappings(
        [_segment(1,'听桥的声音')],'测试游戏',[],[],[{'term':'听潮'}])
    assert result.status=='unsupported' and not result.failures and not provider.calls


def test_domain_terms_http_without_search_cannot_claim_official_verification(monkeypatch):
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", {
        "models": {"ai_service": "deepseek"},
        "switches": {},
    })
    _patch_domain_terms_common(monkeypatch)
    monkeypatch.setattr(
        domain_terms_module,
        "polish_llm_settings",
        lambda: {
            "provider": "deepseek", "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
            "url": "https://api.deepseek.com/v1/chat/completions",
            "api_key": "sk-fixture",
        },
    )
    http_calls = []

    def _fake_post(messages, **kwargs):
        http_calls.append((list(messages), dict(kwargs)))
        return '{"mappings": []}'

    monkeypatch.setattr(domain_terms_module, "post_chat_completion", _fake_post)

    result=domain_terms_module.discover_global_domain_term_mappings(
        [_segment(1, "听桥的声音")], "测试游戏", [], [], [{"term": "听潮"}]
    )
    assert http_calls==[] and result.status=='unsupported' and not result.failures


# ------------------------------------------------- 断句二轮校验（只移竖线）


_MOVED_BOUNDARY_REPLY = '{"segmented_text": "那我们就直接|进入一个珊瑚场啊", "boundaries": [6, 14]}'


def test_grouping_validate_grok_cli_moves_boundary_via_broker(monkeypatch):
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", {
        "models": {"ai_service": "grok_account"},
        "switches": {},
    })
    monkeypatch.setattr(
        subtitle_core, "post_chat_completion",
        lambda *a, **k: pytest.fail("CLI 传输不得走 HTTP post_chat_completion"),
    )
    provider = _FakeCLIProvider(_MOVED_BOUNDARY_REPLY)
    monkeypatch.setattr(ai_providers, "provider_for_stage", lambda *a, **k: provider)

    segments = [_segment(1, "那我们就直接进入"), _segment(2, "一个珊瑚场啊", start=2.0, end=4.0)]
    result = subtitle_core.validate_grouping_boundaries_with_llm(segments, [8, 14])

    assert result == [6, 14], "CLI 会话下二轮校验必须生效（此前永远静默跳过）"
    assert provider.calls
    _, kwargs = provider.calls[0]
    assert kwargs.get("stage") == "grouped_validate"


def test_grouping_validate_http_unchanged(monkeypatch):
    monkeypatch.setattr('twobyteasr.providers.llm_config.read_scoped_api_key',lambda *_:('fixture','test fixture'))
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", {
        "models": {
            "ai_service": "deepseek",
            "group_provider": "deepseek",
            "group_base_url": "https://api.deepseek.com/v1",
            "group_model": "deepseek-v4-flash",
        },
        "switches": {},
    })
    http_calls = []

    def _fake_post(messages, **kwargs):
        http_calls.append((list(messages), dict(kwargs)))
        return _MOVED_BOUNDARY_REPLY

    monkeypatch.setattr(subtitle_core, "post_chat_completion", _fake_post)

    segments = [_segment(1, "那我们就直接进入"), _segment(2, "一个珊瑚场啊", start=2.0, end=4.0)]
    result = subtitle_core.validate_grouping_boundaries_with_llm(segments, [8, 14])

    assert result == [6, 14]
    assert http_calls
    _, kwargs = http_calls[0]
    assert kwargs.get("model") == "deepseek-v4-flash"


# ------------------------------------------------- 模型发现预设错位（RC3）


def test_group_editor_model_discovery_resolves_selected_service(monkeypatch):
    """全文断句编辑器选 DeepSeek 后，发现请求必须解析到 deepseek 而非默认 grok。

    回归 2026-09-04：_provider_settings 裸平铺 dict 缺 ai_service 时，
    get_active_service 回落默认 grok_account，刷新模型拉到 Grok 列表。
    """
    from PySide6.QtWidgets import QApplication
    from twobyteasr.providers.ai_providers import AITransport, transport_for_stage
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.app.ui import EndpointEditor

    app = QApplication.instance() or QApplication([])
    settings = {"models": {"ai_service": "grok_account"}, "switches": {}}
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY, "_settings", settings)

    editor = EndpointEditor("全文断句模型", "#3B82F6", "group", settings)
    try:
        deepseek_index = editor.service.findData("deepseek")
        assert deepseek_index >= 0
        editor.service.setCurrentIndex(deepseek_index)

        resolved = editor._provider_settings()
        assert resolved["models"]["ai_service"] == "deepseek"
        assert transport_for_stage(resolved, "group") is AITransport.OPENAI_COMPATIBLE
        assert (
            resolved["models"]["group_base_url"]
            == "https://api.deepseek.com/v1"
        )
        # 编辑器来源 settings 不得被覆盖层原地污染。
        assert settings["models"]["ai_service"] == "grok_account"
    finally:
        editor.close()
        editor.deleteLater()
        app.processEvents()
