"""Web visual theme pipeline (2byte.web-visual-theme v1) contract tests.

Covers: theme validation/sanitization, StyleRecipe storage + engine routing,
composition prop binding, AI generation contract (fake provider) and project
round-trip persistence.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from twobyteasr.rendering.advanced_renderer import (
    _normalized_recipe,
    normalized_visual_snapshot,
    split_renderer_cues,
)
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.caption_style.style_recipe import StyleRecipe, route_recipe
from twobyteasr.caption_design.web_theme import (
    WebThemeDocument,
    WebThemeValidationError,
    builtin_web_themes,
    fallback_web_theme,
    substitute_placeholders,
)


def _web_recipe() -> StyleRecipe:
    theme = builtin_web_themes()["balatro-joker"].to_dict()
    return StyleRecipe(
        name="Balatro Web",
        engine="remotion",
        typography={"fontFamily": "Microsoft YaHei UI", "fontSize": 64, "bold": True},
        colors={"fill": "#FFE9B8", "outline": "#5C1408"},
        web_theme=theme,
    )


def test_builtin_themes_validate_and_carry_contract_markers():
    themes = builtin_web_themes()
    assert set(themes) == {"balatro-joker", "clean-glass", "doom95", "strand-timefall"}
    balatro = themes["balatro-joker"]
    assert "小丑牌" in balatro.concept or "小丑" in balatro.concept
    assert "{{words}}" in balatro.cue_html
    for required in ("var(--wt-font", "var(--wt-color", "wt-dealer-slam", "wt-dealer-retrieve"):
        assert required in balatro.cue_css or required in balatro.stage_css
    # 当前用户要求的牌体局部六物件（DOM+CSS），全屏纹理已移除。
    everything = balatro.stage_html + balatro.cue_html + balatro.stage_css + balatro.cue_css
    for draft_class in (
        "chips-stack", "mult-flame", "joker-bell", "foil-shimmer",
        "card-slider", "balatro-plate",
    ):
        assert draft_class in everything, draft_class
    # 时间轴铁律范本：出场锚定 --wt-dur；文字层无 infinite。
    assert "var(--wt-dur)" in balatro.cue_css
    for block in balatro.cue_css.split("}"):
        head = block.split("{", 1)[0]
        if ".wt-text" in head or ".wt-w" in head:
            assert "infinite" not in block, head


def test_builtin_doom95_pins_own_appearance():
    """十八轮：主题自带 appearance（theme-first），DOOM95 钉死像素字体栈。"""
    from twobyteasr.caption_design.web_theme import effective_appearance

    doom = builtin_web_themes()["doom95"]
    own = doom.appearance
    assert "Cubic 11" in str(own.get("fontFamily"))
    assert "俐方体11号" in str(own.get("fontFamily"))
    assert own.get("color") == "#C9D1D9"  # 枪灰
    # theme-first：主题 appearance 压过工程快照（黑字根因回归锁）
    merged = effective_appearance(
        doom.to_dict(),
        {"fontFamily": "SimHei", "color": "#000000", "fontSize": 40},
    )
    assert merged["fontFamily"] == own["fontFamily"]
    assert merged["color"] == "#C9D1D9"
    assert merged["fontSize"] == 54
    # 镜像也贴主题：颜色+栈内第一个字体
    mirror = doom.native_mirror_style()
    assert mirror["primary_color"] == "#C9D1D9"
    assert mirror["font_family"] == "Cubic 11"
    # 绿色 HUD 框 + 红点泼溅 + 渐变字设计要素
    assert "#2E8B4F" in doom.cue_css  # 绿框
    assert ".splat" in doom.cue_css  # 红泼溅常驻
    assert ".blood" in doom.cue_css  # 入场血溅粒子


def test_sanitizer_rejects_dangerous_constructs():
    base = builtin_web_themes()["clean-glass"]

    def variant(**changes):
        clone = copy.deepcopy(base)
        field_names = {"cueHtml": "cue_html", "stageCss": "stage_css", "cueCss": "cue_css"}
        for key, value in changes.items():
            setattr(clone, field_names.get(key, key), value)
        return clone

    for broken in (
        variant(cueHtml='<div><script>{{text}}</script></div>'),
        variant(stageCss="@import url(https://evil.example/x.css);"),
        variant(cueCss=".a{background:url(https://evil.example/x.png)}"),
            variant(cueHtml="<div>{{text}}</div>", cueCss=".a{color:red}"),
            # 二十轮：--wt-color 不再强制（theme-first 允许主题自带配色），
            # 但字体 token 仍然必须消费。
            variant(cueHtml="{{words}}", cueCss=".a{color:var(--wt-color)}"),
        variant(palette={"primary": "red", "text": "#FFFFFF"}),
    ):
        with pytest.raises(WebThemeValidationError):
            broken.validate()
    # Unknown attributes (event handlers included) are silently stripped
    # rather than rejected — the sanitized output must be clean.
    scrubbed = variant(cueHtml='<div onclick="steal()">{{text}}</div>')
    scrubbed.validate()
    assert "onclick" not in scrubbed.cue_html and "steal" not in scrubbed.cue_html


def test_substitute_placeholders_builds_word_spans():
    html = '<div class="t">{{words}}</div><i>{{speaker}}</i>'
    out = substitute_placeholders(html, text="你好 x", speaker="<主播>")
    assert '<span class="wt-w">你</span><span class="wt-w">好</span>' in out
    assert " " in out  # spaces stay unspanned
    assert "&lt;主播&gt;" in out


def test_recipe_web_theme_roundtrip_and_routing():
    recipe = _web_recipe()
    recipe.validate()
    assert recipe.engine == "remotion"
    payload = recipe.to_dict()
    assert payload["webTheme"]["name"] == "Balatro Dealer Press"
    restored = StyleRecipe.from_dict(payload)
    assert restored.web_theme["schema"] == "2byte.web-visual-theme"
    route = route_recipe(restored)
    assert route.engine == "remotion"


def test_split_renderer_cues_routes_web_theme_to_advanced(tmp_path):
    recipe = _web_recipe()
    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    project.style_recipes[project.styles[0].id] = recipe.to_dict()
    project.cues.append(StudioCue(id="c1", start_ms=0, end_ms=2000, text="你好"))
    project.cues[0].style_id = project.styles[0].id
    native, advanced = split_renderer_cues(project)
    assert [cue.id for cue in advanced] == ["c1"]
    assert native == []


def test_normalized_snapshot_binds_project_appearance():
    recipe = _web_recipe()
    # Test the project fallback independently of the built-in theme's newly
    # explicit typeface/size (theme-first appearance is a separate contract).
    recipe.web_theme['appearance'] = {}
    normalized = _normalized_recipe(recipe.to_dict())
    assert normalized["webTheme"]["name"] == "Balatro Dealer Press"

    class _Fake:
        pass

    snapshot = _Fake()
    snapshot.style_recipe = recipe.to_dict()
    snapshot.font_family = "KaiTi"
    snapshot.font_size = 72
    snapshot.font_weight = 700
    snapshot.italic = False
    snapshot.fill = {"type": "solid", "color": "#FFFFFF"}
    snapshot.strokes = [{"color": "#112233", "width": 4.0}]
    snapshot.shadow = {}
    snapshot.glow = {}
    snapshot.letter_spacing = 1.5
    snapshot.alignment = 2
    snapshot.position_x = 0
    snapshot.position_y = 0
    snapshot.anchor_x = 0
    snapshot.anchor_y = 0
    snapshot.scale_x = 1
    snapshot.scale_y = 1
    snapshot.rotation = 0
    snapshot.playres_x = 1920
    snapshot.playres_y = 1080
    snapshot.motion_recipe = {}
    snapshot.start_ms = 0
    snapshot.end_ms = 2000
    bound = normalized_visual_snapshot(snapshot)
    appearance = bound["webTheme"]["appearance"]
    assert appearance["fontFamily"] == "KaiTi"
    assert appearance["fontSize"] == 72
    assert appearance["strokeColor"] == "#112233"
    assert appearance["strokeWidth"] == 4.0


def test_project_roundtrip_preserves_web_theme(tmp_path):
    recipe = _web_recipe()
    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    project.style_recipes[project.styles[0].id] = recipe.to_dict()
    target = tmp_path / "web.2byteproj"
    save_project(project, target)
    loaded = load_project(target)
    restored = StyleRecipe.from_dict(loaded.style_recipes[loaded.styles[0].id])
    assert restored.web_theme["cueHtml"]
    assert restored.engine == "remotion"


def test_fallback_web_theme_routes_by_instruction():
    assert fallback_web_theme("balatro 小丑牌赌桌").name == "Balatro Dealer Press"
    assert fallback_web_theme("清晰简洁").name == "Clean Glass"


def test_parse_web_theme_sections_tolerant_forms():
    from twobyteasr.caption_design.web_theme import parse_web_theme_sections

    payload = parse_web_theme_sections(
        "好的，这是主题：\n"
        "===NAME===\n赛博主题\n"
        "===PALETTE===\nprimary=#00FFCC; secondary=#FF007F, text=#FFFFFF\n"
        "===CUE_HTML===\n```html\n<div class=\"t\">{{words}}</div>\n```\n"
        "===CUE_CSS===\n.t{font-family:var(--wt-font);color:var(--wt-color)}\n"
    )
    assert payload["name"] == "赛博主题"
    assert payload["palette"]["primary"] == "#00FFCC"
    assert payload["palette"]["text"] == "#FFFFFF"
    assert payload["cueHtml"] == '<div class="t">{{words}}</div>'
    assert "var(--wt-font)" in payload["cueCss"]


def test_page_exposes_apply_web_theme_wrapper():
    """AI 面板回调与特效字幕库都通过 page._apply_web_theme 访问 controller
    （2026-09-02 第三轮：漏掉这个单行委托就是'生成成功但应用不到字幕'的根因）。"""
    from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin
    from twobyteasr.caption_style.studio_style_controller import StudioStyleController

    assert callable(getattr(StudioAIFlowMixin, "_apply_web_theme", None))
    assert callable(getattr(StudioStyleController, "_apply_web_theme", None))


def test_ai_progress_bar_stage_mapping():
    """阶段/流式字符消息必须推进进度条（用户需要'知道大概到哪了'）。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["bar"])
    from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin

    class _Fake:
        pass

    holder = _Fake()
    holder._update_ai_progress_bar = StudioAIFlowMixin._update_ai_progress_bar.__get__(holder)
    from PySide6.QtWidgets import QProgressBar

    holder.ai_progress_bar = QProgressBar()
    for stage, expected in (
        ("CONNECTING_PROVIDER", 8),
        ("REQUESTING", 15),
        ("正在输出主题（5 百字）… xxx", 16),
        ("正在输出主题（90 百字）… xxx", 45),
        ("VALIDATING", 82),
        ("COMPLETE", 100),
    ):
        holder._update_ai_progress_bar(stage)
        assert holder.ai_progress_bar.value() == expected, (stage, holder.ai_progress_bar.value())


def test_cli_stream_line_normalization_covers_both_clis():
    from twobyteasr.providers.ai_providers import AntigravityCLIProvider

    state: dict = {"text": "", "thinking": "", "final": None}
    events: list[tuple[str, str]] = []
    emit = lambda kind, detail: events.append((kind, detail))  # noqa: E731

    # Antigravity shape: step_update text_delta + result.response
    AntigravityCLIProvider._consume_cli_stream_line(
        '{"event":"step_update","step_update":{"step_type":"agent_response","text_delta":"你好"}}',
        state, emit,
    )
    AntigravityCLIProvider._consume_cli_stream_line(
        '{"event":"result","result":{"status":"SUCCESS","response":"你好"}}',
        state, emit,
    )
    assert state["text"] == "你好" and state["final"] == "你好"
    assert ("delta", "你好") in events

    # grok shape: stream_event deltas + result string
    state2: dict = {"text": "", "thinking": "", "final": None}
    events2: list[tuple[str, str]] = []
    emit2 = lambda kind, detail: events2.append((kind, detail))  # noqa: E731
    AntigravityCLIProvider._consume_cli_stream_line(
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"OK"}}}',
        state2, emit2,
    )
    AntigravityCLIProvider._consume_cli_stream_line(
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"想想"}}}',
        state2, emit2,
    )
    AntigravityCLIProvider._consume_cli_stream_line(
        '{"type":"result","subtype":"success","result":"OK"}',
        state2, emit2,
    )
    assert state2["text"] == "OK" and state2["thinking"] == "想想"
    assert state2["final"] == "OK"
    # garbage lines are ignored
    AntigravityCLIProvider._consume_cli_stream_line("not json", state2, emit2)
    assert state2["final"] == "OK"


def _to_sections(theme: dict) -> str:
    palette = " ".join(f"{key}={value}" for key, value in theme.get("palette", {}).items())
    return (
        f"===NAME===\n{theme.get('name', '')}\n"
        f"===CONCEPT===\n{theme.get('concept', '')}\n"
        f"===PALETTE===\n{palette}\n"
        f"===STAGE_HTML===\n{theme.get('stageHtml', '')}\n"
        f"===STAGE_CSS===\n{theme.get('stageCss', '')}\n"
        f"===CUE_HTML===\n{theme.get('cueHtml', '')}\n"
        f"===CUE_CSS===\n{theme.get('cueCss', '')}\n"
        f"===NOTES===\n{theme.get('notes', '')}\n"
    )


def test_request_web_theme_design_contract(monkeypatch, tmp_path):
    from twobyteasr.caption_design import studio_ai

    class FakeProvider:
        provider_id = "fake_web"

        def __init__(self, payloads):
            self.payloads = list(payloads)
            self.calls = 0

        def complete(self, messages, **_kwargs):
            self.calls += 1
            return self.payloads.pop(0)

    import json
    from tests.test_hero_theme_compiler import design,hero
    good_theme = dict(hero(True),name='AI Selected Hero')
    provider = FakeProvider([json.dumps(good_theme)])
    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: provider)

    class FakeSelection:
        credential_ready = True
        provider = "fake"
        service = "fake"
        model = "m"

    class FakeRegistry:
        def settings(self):
            return {"models": {}}

        def bind(self, _settings):
            return {"models": {}}

        def selection(self, *_a, **_k):
            return FakeSelection()

    monkeypatch.setattr(studio_ai, "GLOBAL_PROVIDER_REGISTRY", FakeRegistry())
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist",
        lambda **_k: {"chinese_sans": ["Microsoft YaHei UI"]},
    )
    monkeypatch.setattr(studio_ai, "_persist_ai_design_trace", lambda _t: "")

    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    project.cues.append(
        StudioCue(id="c1", start_ms=0, end_ms=2000, text="测试字幕", speaker_id="S01")
    )

    suggestion = studio_ai.request_web_theme_design(project, "c1", "所选字幕风格",resume_design=design())
    assert suggestion.source == "ai"
    assert suggestion.theme["name"] == "AI Selected Hero"
    assert suggestion.theme['motionSpec'] and provider.calls == 1


def test_request_web_theme_invalid_concepts_fail_without_fallback(monkeypatch, tmp_path):
    from twobyteasr.caption_design import studio_ai

    class FakeProvider:
        provider_id = "fake_web"

        def __init__(self):
            self.calls = 0

        def complete(self, messages, **_kwargs):
            self.calls += 1
            return "抱歉，我无法完成这个任务。"  # no sections, no JSON

    provider = FakeProvider()
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE, "client_for_stage", lambda *_a, **_k: provider)

    class FakeSelection:
        credential_ready = True
        provider = 'fake'
        model = 'm'

    class FakeRegistry:
        def settings(self):
            return {"models": {}}

        def bind(self, _s):
            return {}

        def selection(self, *_a, **_k):
            return FakeSelection()

    monkeypatch.setattr(studio_ai, "GLOBAL_PROVIDER_REGISTRY", FakeRegistry())
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY, "selection", lambda *_a, **_k: FakeSelection())
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist", lambda **_k: {},
    )
    monkeypatch.setattr(studio_ai, "_persist_ai_design_trace", lambda _t: "")

    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    project.cues.append(StudioCue(id="c1", start_ms=0, end_ms=2000, text="测试"))
    with pytest.raises(ValueError):
        studio_ai.request_web_theme_design(project,'c1','balatro 小丑',runtime_settings={'models':{}},ledger_root=tmp_path)
    assert provider.calls == 1
