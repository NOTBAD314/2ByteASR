from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.providers.ai_providers import (
    AITransport,
    AntigravityCLIProvider,
    GrokCLIProvider,
    OpenAICompatibleProvider,
    adapter_for_stage,
    provider_for_stage,
)
from twobyteasr.providers.provider_service import AIClient
from twobyteasr.local_models.model_workshop import build_workshop_qss
from twobyteasr.studio.studio_danmaku import aggregate_danmaku, parse_danmaku_xml
from twobyteasr.timeline.studio_edit_sequence import HighlightCandidate
from twobyteasr.studio.studio_highlight_analyzer import candidates_from_local, discover_local_candidates, merge_overlapping_candidates
from twobyteasr.studio.studio_highlight_ui import HighlightAssistantPanel
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.app.ui import build_term_library_page_qss
from twobyteasr.design.ui_theme import THEMES, theme_definition


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _xml(path: Path, rows: list[tuple[float, str]]) -> Path:
    body = "".join(f'<d p="{time},1,25,1,0,0,0,0">{text}</d>' for time, text in rows)
    path.write_text(f"<i>{body}</i>", encoding="utf-8")
    return path


def test_theme_contract_and_dynamic_secondary_qss():
    required = (
        "surface_muted", "surface_input", "text_on_accent", "primary_role",
        "secondary_role", "tertiary_role", "timeline_background", "timeline_grid",
        "timeline_playhead", "control_background", "control_hover", "control_checked",
    )
    workshop_sheets = []
    for theme in THEMES.values():
        assert all(getattr(theme, token) for token in required)
        workshop = build_workshop_qss(theme)
        workshop_sheets.append(workshop)
        assert theme.app_background in workshop
        assert theme.text in workshop
        assert theme.accent in workshop
        assert theme.surface_muted in build_term_library_page_qss(theme)
    assert len(set(workshop_sheets)) == len(THEMES)


def test_danmaku_uses_nearby_baseline_and_reaction_evidence(tmp_path):
    rows = [(1 + i * 0.2, "普通") for i in range(4)]
    rows += [(11 + i * 0.1, "哈哈 绷不住 ？？ 逆天") for i in range(20)]
    rows += [(12, "点点关注，参与天选福袋啦！")]
    rows += [(21 + i * 0.2, "普通") for i in range(4)]
    document = parse_danmaku_xml(_xml(tmp_path / "peak.xml", rows))
    windows = aggregate_danmaku(document, window_ms=10_000, context=1)
    peak = windows[1]
    assert peak.baseline == 4
    assert peak.spike == 5
    assert peak.funny_hits >= 20
    assert peak.chaos_hits >= 20
    assert peak.effective_count == 20
    assert peak.representative_comments
    assert all("点点关注" not in item for item in peak.representative_comments)
    assert peak.promotional_hits == 1
    assert peak.raw_score > windows[0].raw_score


def test_xml_recall_ignores_subtitle_density(tmp_path):
    project = SubtitleProject(
        media=StudioMedia(path="recording.flv", duration_ms=60_000),
        cues=[StudioCue(f"c{i}", 30_000, 31_000, "非常非常密集的普通字幕" * 20) for i in range(20)],
    )
    rows = [(1 + i * 0.1, ("哈哈 笑死", "太好笑", "？？？")[i % 3]) for i in range(18)]
    rows += [(31 + i * 0.4, "普通") for i in range(3)]
    document = parse_danmaku_xml(_xml(tmp_path / "recording.xml", rows))
    candidates = discover_local_candidates(project, document, window_ms=10_000)
    assert candidates
    assert candidates[0].start_ms == 0
    assert all("字幕密度" not in reason for item in candidates for reason in item.reasons)
    fallback = candidates_from_local(project, candidates, limit=3, max_seconds=60)
    # 2026-09-19 P1：本地回退标题诚实化（时间范围+待核实，不用台词截断）。
    assert fallback[0].title.startswith("00:00")
    assert "弹幕集中" in fallback[0].title and fallback[0].clip_range is None
    assert "哈哈哈哈哈哈" not in fallback[0].title
    assert fallback[0].origin == "local"
    assert fallback[0].reason.count("；") <= 2


def test_candidate_nms_and_backward_compatible_schema():
    first = HighlightCandidate("a", "A", 40_000, 60_000, 0.92, danmaku_evidence=["5.4x"])
    second = HighlightCandidate("b", "B", 45_000, 65_000, 0.81, danmaku_evidence=["笑死 12 条"])
    third = HighlightCandidate("c", "C", 90_000, 110_000, 0.72)
    merged = merge_overlapping_candidates([first, second, third])
    assert len(merged) == 2
    assert merged[0].source_in_ms == 40_000
    assert merged[0].source_out_ms == 60_000  # dedup does not enlarge the editorial cut
    payload = HighlightCandidate.from_dict({"id": "old", "title": "旧候选", "source_in_ms": 0, "source_out_ms": 5000}).to_dict()
    assert payload["category"] == "other"
    assert payload["grade"] == "待确认"
    assert payload["recommended_range"] is None


def test_auto_data_source_cases(tmp_path):
    _app()
    panel = HighlightAssistantPanel()
    empty = SubtitleProject(media=StudioMedia(path="a.flv", duration_ms=10_000), cues=[])
    panel.set_project_status(empty, "")
    assert panel._auto_mode == "none" and not panel.analyze_button.isEnabled()
    panel.set_project_status(empty, str(tmp_path / "a.xml"))
    assert panel._auto_mode == "xml"
    subtitles = SubtitleProject(
        media=StudioMedia(path="a.flv", duration_ms=10_000),
        cues=[StudioCue("c", 0, 1000, "字幕")],
    )
    panel.set_project_status(subtitles, "")
    assert panel._auto_mode == "subtitles"
    panel.set_project_status(subtitles, str(tmp_path / "a.xml"))
    assert panel._auto_mode == "subtitles_xml"
    assert panel.subtitle_status.text().startswith("字幕：1 条")
    panel.deleteLater()


def test_candidate_actions_fit_narrow_clip_assistant():
    app = _app()
    panel = HighlightAssistantPanel()
    panel.resize(300, 720)
    panel.reload_candidates([
        HighlightCandidate(
            "candidate",
            "角色突然破防，全场弹幕爆炸",
            40_000,
            68_000,
            0.92,
            reason="弹幕密度 5.4x，存在明确 setup 到 payoff",
            danmaku_evidence=["有效弹幕 27 条", "搞笑反应 18 条"],
        )
    ])
    panel.show()
    app.processEvents()
    assert panel.results.horizontalScrollBar().maximum() == 0
    card = panel.results.itemWidget(panel.results.item(0))
    assert card is not None
    assert card.sizeHint().width() <= panel.results.viewport().width()
    panel.close()
    panel.deleteLater()


def test_studio_global_clip_assistant_belongs_to_editor_or_overflow(monkeypatch, tmp_path):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    _app()
    page = SubtitleStudioPage()
    assert page.highlight_panel.styleSheet() == ""
    page.show_project_hub()
    assert not page.studio_clip_assistant_button.isVisibleTo(page)
    page._create_blank_studio()
    assert page.studio_clip_assistant_button.isVisibleTo(page) or page.studio_clip_assistant_button in getattr(page, "_studio_toolbar_overflow_widgets", ())
    page.close_page()
    page.deleteLater()


def test_provider_factory_keeps_transports_distinct(monkeypatch):
    api_settings = {"models": {
        "ai_service": "custom", "polish_transport": AITransport.OPENAI_COMPATIBLE.value,
        "polish_provider": "custom",
        "polish_model": "fixture",
        "polish_base_url": "https://example.test/v1",
    }}
    monkeypatch.setattr("twobyteasr.providers.ai_providers.endpoint_from_settings", lambda *_a: {
        "provider": "custom", "model": "fixture", "base_url": "https://example.test/v1",
        "url": "https://example.test/v1/chat/completions", "api_key": "fixture",
    })
    api_client = provider_for_stage(api_settings, "polish")
    antigravity_client = provider_for_stage({"models": {"ai_service": "antigravity", "polish_transport": "antigravity_cli"}}, "polish")
    grok_client = provider_for_stage({"models": {"ai_service": "grok_account", "polish_transport": "grok_cli"}}, "polish")
    assert all(isinstance(client, AIClient) for client in (api_client, antigravity_client, grok_client))
    assert api_client.transport is AITransport.OPENAI_COMPATIBLE
    assert antigravity_client.transport is AITransport.ANTIGRAVITY_CLI
    assert grok_client.transport is AITransport.GROK_CLI
    assert isinstance(adapter_for_stage(api_settings, "polish"), OpenAICompatibleProvider)
    assert isinstance(adapter_for_stage({"models": {"ai_service": "antigravity", "polish_transport": "antigravity_cli"}}, "polish"), AntigravityCLIProvider)
    assert isinstance(adapter_for_stage({"models": {"ai_service": "grok_account", "polish_transport": "grok_cli"}}, "polish"), GrokCLIProvider)


def test_grok_cli_request_uses_direct_completion_contract():
    provider = GrokCLIProvider(
        executable=r"C:\tools\grok.exe",
        model="grok-4.6",
    )

    command = provider._request_command("Return JSON", None)

    assert command[command.index("--max-turns") + 1] == "2"
    assert command[command.index("--reasoning-effort") + 1] == "high"
    assert "--no-subagents" in command
    assert "--disable-web-search" in command
    assert "--no-plan" in command
    assert "--verbatim" in command
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert command[command.index("--tools") + 1] == ""
    assert Path(command[command.index("--cwd") + 1]).name == "2ByteASR-ProviderCLI"
    denied = command[command.index("--disallowed-tools") + 1].split(",")
    assert {
        "run_terminal_cmd", "bash", "grep", "grep_search", "read_file",
        "write", "search_replace", "list_dir", "task", "search_tool",
        "use_tool", "Agent", "ask_user_question", "workflow",
        "enter_plan_mode", "exit_plan_mode",
    } <= set(denied)
    system_prompt = command[command.index("--system-prompt-override") + 1]
    assert "Do not inspect files" in system_prompt
    assert command[command.index("--model") + 1] == "grok-4.6"
