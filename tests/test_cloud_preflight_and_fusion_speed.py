# -*- coding: utf-8 -*-
"""2026-09-03 轮：云端阶段 t=0 预检、Grok 登陆校对、仲裁提速、探测防挂死。

对应 plan：docs/exec-plans/active/2026-09-03-asr-cloud-preflight-and-fusion-speed.md
背景 run：auto_asr_20260903_035623_37496_eca757.jsonl（阶段 8 缺密钥 30 分钟作废）
与 eaa7a3（torch 探测排空挂死）。
"""

import subprocess
import sys
import time

import pytest

import subtitle_core
import moss_firered_pipeline as pipeline_module
from twobyteasr.providers import ai_providers
from twobyteasr.subtitle_rules import polishing as polishing_module
from twobyteasr.subtitle_rules.correction_safety import reference_consensus_edits
from twobyteasr.app.main_ui_helpers import _is_ai_config_failure
from twobyteasr.system.processes import run_subprocess_with_tree_kill
from twobyteasr.subtitle_rules.text_similarity import _phonetic_text_cached, phonetic_text


@pytest.fixture(autouse=True)
def isolated_asr_task(monkeypatch, tmp_path):
    """Each test is a new task; credentials/network must not come from the host."""
    from twobyteasr.providers import llm_config
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    import requests
    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a, **k: ("", "fixture"))
    monkeypatch.setattr(llm_config, "resolve_api_key", lambda *a, **k: ("", "fixture"))
    monkeypatch.setattr(requests.sessions.Session, "request",
                        lambda *a, **k: pytest.fail("Unexpected network in offline preflight test"))
    with activate_runtime_context(RuntimeContext(event_log_path=str(tmp_path / "events.jsonl")), legacy=subtitle_core):
        yield


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


def test_analysis_has_no_unused_cloud_text_credential_gate(monkeypatch):
    from twobyteasr.recognition.run_context import get_runtime_context
    from twobyteasr.providers import asr_provider_snapshot
    get_runtime_context().recognition_purpose='analysis'
    monkeypatch.setattr(asr_provider_snapshot,'resolve_provider_snapshot',
                        lambda *a:pytest.fail('Analysis must not resolve unused text provider'))
    pipeline_module._preflight_cloud_stages(subtitle_core)


# ---------------------------------------------------------------- 配置失败分类


def test_ai_config_failure_markers_match_cloud_config_errors_only():
    assert _is_ai_config_failure("字幕校对模型缺少 API 密钥。请展开 AI 模型与密钥后填写。")
    assert _is_ai_config_failure("全文断句模型缺少模型名称。请在 AI 模型与密钥中完成配置。")
    assert _is_ai_config_failure("字幕校对模型使用账号登陆传输（grok_cli），当前不可用：尚未登录。")
    assert not _is_ai_config_failure("FireRedASR2-LLM 模型未完整安装，请先在模型工坊下载。")
    assert not _is_ai_config_failure("")


# ---------------------------------------------------------------- 音串缓存


def test_phonetic_text_cache_returns_identical_results():
    _phonetic_text_cached.cache_clear()
    first = phonetic_text("你好世界")
    second = phonetic_text("你好世界")
    assert first == second
    info = _phonetic_text_cached.cache_info()
    assert info.currsize >= 1
    assert info.hits >= 1


# ---------------------------------------------------------------- 共识热点


def test_consensus_identical_independent_references_keep_both_votes():
    """FireRed 与 Qwen3 文本完全一致时两票都必须计入（不能按值去重）。

    回归 2026-09-03：提速重构曾把双参考压成一票导致全部拒绝。
    """
    primary = "我们今天要说的这个话题其实很有意思"
    reference = primary[:4] + "近" + primary[5:]
    edits = reference_consensus_edits(primary, (reference, reference))
    assert edits == [
        {"start": 4, "end": 5, "from": "要", "to": "近", "support": 2}
    ]


def test_consensus_requires_two_reference_slots():
    primary = "我们今天要说的这个话题"
    reference = primary[:4] + "近" + primary[5:]
    assert reference_consensus_edits(primary, (reference, "")) == []


def test_consensus_long_batch_completes_fast():
    """242 段 × 200 字参考在秒级完成（旧实现外推 ~30s+，真实音频曾 8 分钟）。"""
    import random

    random.seed(3)
    chars = "的一是了我不人在他有这上们来到时大地为子中你说生国年着就那和要她出"
    pairs = []
    for _ in range(242):
        base = "".join(random.choice(chars) for _ in range(200))
        ref = list(base)
        for pos in range(8, 200, 24):
            for k in range(3):
                ref[pos + k] = random.choice(chars)
        ref = "".join(ref)
        pairs.append((base, (ref, ref)))
    started = time.perf_counter()
    for primary, refs in pairs:
        reference_consensus_edits(primary, refs)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"242 段共识耗时 {elapsed:.2f}s，热点优化失效"


# ---------------------------------------------------------------- 子进程防挂死


def test_run_subprocess_with_tree_kill_returns_output():
    completed = run_subprocess_with_tree_kill(
        [sys.executable, "-c", "print('ok-probe')"],
        timeout=15,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0
    assert "ok-probe" in (completed.stdout or "")


def test_run_subprocess_with_tree_kill_timeout_raises_quickly():
    started = time.perf_counter()
    with pytest.raises(subprocess.TimeoutExpired):
        run_subprocess_with_tree_kill(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=1,
            text=True,
        )
    assert time.perf_counter() - started < 10


def test_run_subprocess_with_tree_kill_survives_grandchild_pipe_hold():
    """孙进程继承管道写端时 helper 必须有界返回（2026-09-03 PID 37496 实录）。"""
    child_script = (
        "import subprocess, sys\n"
        "subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(25)'],\n"
        "    stdout=sys.stdout, stderr=sys.stderr)\n"
    )
    started = time.perf_counter()
    completed = run_subprocess_with_tree_kill(
        [sys.executable, "-c", child_script],
        timeout=20,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - started
    assert completed.returncode == 0
    # 有界 join（每泵 5s）：即使 reader 被孙进程卡住也必须返回。
    assert elapsed < 15, f"排空耗时 {elapsed:.1f}s，防挂死失效"


# ---------------------------------------------------------------- 校对 CLI 传输


class _FakeCLIProvider:
    def __init__(self, content='{"cues":[]}'):
        self.content = content
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((list(messages), dict(kwargs)))
        if self.content=='{"cues":[]}' and kwargs.get('operation_kind')=='polish':
            import json
            return json.dumps({'checked_ids':[item['id'] for item in json.loads(messages[1]['content'])['cues']],'cues':[]})
        return self.content

    def validate(self, **kwargs):
        return ai_providers.ProviderStatus(True, True, "OAuth Session 可用")


def _patch_grok_transport(monkeypatch, provider):
    settings = {
        "models": {
            "ai_service": "grok_account",
            "provider_profiles": {
                "grok_account": {"base_url": "", "model": "grok-4.6", "protocol": "auto"}
            },
        },
        "switches": {"use_ai_grouping": True},
    }
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", settings, raising=True)
    monkeypatch.setattr(
        polishing_module,
        "polish_llm_settings",
        lambda: {
            "provider": "grok_oauth",
            "model": "grok-4.6",
            "base_url": "",
            "url": "",
            "api_key": "",
        },
    )
    monkeypatch.setattr(ai_providers, "provider_for_stage", lambda *a, **k: provider)
    monkeypatch.setattr(polishing_module, "record_run_event", lambda *a, **k: None)


def test_polish_grok_cli_transport_uses_account_session_without_api_key(monkeypatch):
    provider = _FakeCLIProvider()
    _patch_grok_transport(monkeypatch, provider)
    segment = _segment(101, "测试字幕")
    result = polishing_module.call_correction_api(
        [segment], [], "", "", "fixture", "fixture", [], [], []
    )
    assert result == {101: subtitle_core.clean_subtitle_text(segment.text)}
    assert provider.calls, "CLI 传输必须经 provider.complete 发送"
    sent_messages, kwargs = provider.calls[0]
    assert kwargs.get("stage") == "polished"
    assert "不可信" in sent_messages[0]["content"]


def test_polish_http_missing_key_still_fails_fast(monkeypatch):
    settings = {
        "models": {"ai_service": "deepseek"},
        "switches": {"use_ai_grouping": True},
    }
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", settings, raising=True)
    monkeypatch.setattr(
        polishing_module,
        "polish_llm_settings",
        lambda: {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
            "url": "https://api.deepseek.com/v1/chat/completions",
            "api_key": "",
        },
    )
    monkeypatch.setattr(polishing_module, "record_run_event", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="缺少 API 密钥"):
        polishing_module.call_correction_api(
            [_segment(101, "测试字幕")], [], "", "", "fixture", "fixture", [], [], []
        )


# ---------------------------------------------------------------- 开跑前预检


def _preflight_settings(monkeypatch, service_id):
    settings = {
        "models": {"ai_service": service_id},
        "switches": {"use_ai_grouping": True},
    }
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", settings, raising=True)
    from twobyteasr.providers import llm_config

    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a, **k: ("", ""))


def test_preflight_http_missing_key_raises_at_start(monkeypatch):
    _preflight_settings(monkeypatch, "deepseek")
    with pytest.raises(RuntimeError, match="缺少 API 密钥"):
        pipeline_module._preflight_cloud_stages(subtitle_core)


def test_preflight_cli_not_logged_in_raises_with_actionable_hint(monkeypatch):
    _preflight_settings(monkeypatch, "grok_account")
    provider = _FakeCLIProvider()
    provider.validate = lambda **k: ai_providers.ProviderStatus(
        True, False, "CLI 已安装，尚未登录"
    )
    monkeypatch.setattr(ai_providers, "provider_for_stage", lambda *a, **k: provider)
    with pytest.raises(RuntimeError, match="完成登录"):
        pipeline_module._preflight_cloud_stages(subtitle_core)


def test_preflight_cli_session_ok_passes(monkeypatch):
    _preflight_settings(monkeypatch, "grok_account")
    provider = _FakeCLIProvider()
    monkeypatch.setattr(ai_providers, "provider_for_stage", lambda *a, **k: provider)
    pipeline_module._preflight_cloud_stages(subtitle_core)
