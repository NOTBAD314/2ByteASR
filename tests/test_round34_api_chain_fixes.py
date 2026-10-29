"""三十四轮守护：API 使用链收尾三项。

- api 浏览视角点击"使用/取消使用"此前 KeyError 被 Qt 吞掉（点多少次没反应）。
- 最终字幕"短字幕继承长段时间"（2字/5.05s）曾把整轮打成硬性时长上限失败——
  改为截断修复+告警；字数超限与空段保持硬失败。
- 转写日志按服务商·模型显示（不再硬编码 Qwen ASR API）。
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _api_page(monkeypatch):
    from twobyteasr.providers import llm_config
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage

    monkeypatch.setattr(llm_config, "read_api_key", lambda p, b: ("sk", "scoped"))
    return ModelWorkshopPage(
        Path("."),
        {
            "models": {
                "qwen_asr_backend": "off",
                "primary_asr_backend": "api",
                "qwen_asr_api_provider": "openrouter_word",
                "qwen_asr_api_model": "microsoft/mai-transcribe-2",
                "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
            }
        },
    )


def test_api_tab_use_click_emits_backend(monkeypatch):
    _app()
    page = _api_page(monkeypatch)
    page._set_role("api")
    events: list = []
    page.backend_requested.connect(lambda role, val: events.append((role, val)))
    try:
        page._perform_action("qwen_api")
    except KeyError:
        assert False, "api 视角点击'使用'不得 KeyError（被 Qt 吞掉=无反应）"
    assert ("primary", "api") in events
    # 取消使用：把主力关掉
    page._perform_action("mai_transcribe_2_word")
    assert ("primary", "none") in events
    page.deleteLater()


def test_api_cards_have_configure_button(monkeypatch):
    _app()
    page = _api_page(monkeypatch)
    card = page._cards["mai_transcribe_2_word"]
    assert hasattr(card, "configure") and card.configure.isVisibleTo(card)
    fired: list = []
    page.api_configure_requested.connect(fired.append)
    card.configure.click()
    assert fired == ["openrouter_word"]
    # 本地模型详情不显示配置按钮
    page._view_model("qwen_local")
    assert not page.detail_configure.isVisibleTo(page)
    page._view_model("groq_api")
    assert page.detail_configure.isVisibleTo(page)
    page.deleteLater()


def test_validate_final_cues_clamps_overlong_short_subtitles():
    from twobyteasr.subtitle_rules.output import validate_final_cues

    def cue(text, start, end):
        return SimpleNamespace(text=text, start=start, end=end, speaker_id="S00", speaker="S00")

    segments = [SimpleNamespace(text="这下为什么跟一下", speaker="S00")]
    cues = [
        cue("这下", 0.0, 5.05),
        cue("为什么", 5.05, 10.10),
        cue("跟一下", 10.10, 15.15),
    ]
    # 修复前：RuntimeError("最终字幕超过硬性长度/时长上限") 整轮失败
    validate_final_cues(cues, segments, 60.0)
    for item in cues:
        assert item.end - item.start <= 5.0 + 1e-6, "短字幕超限应截断到 5s 而非失败"

    # 字数超限仍是硬失败（断句真坏了）
    long_cues = [cue("这" * 30, 0.0, 3.0)]
    try:
        validate_final_cues(long_cues, [SimpleNamespace(text="这" * 30, speaker="S00")], 60.0)
    except RuntimeError as exc:
        assert "硬性长度上限" in str(exc)
    else:
        assert False, "字数超限必须保持硬失败"


def test_asr_api_display_uses_provider_and_model():
    from twobyteasr.providers.llm_config import asr_api_display

    text = asr_api_display(
        {
            "provider": "openrouter_word",
            "model": "microsoft/mai-transcribe-2",
        }
    )
    assert "OpenRouter" in text and "microsoft/mai-transcribe-2" in text
    assert "Qwen" not in text
