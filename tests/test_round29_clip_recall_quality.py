"""Round 29 guard tests: clip-assistant recall quality and usability.

用户六项反馈的可执行验收：
- 弹幕模式下字幕语义召回仍然运行（安静精彩段不再漏召回）；
- 连续弹幕高峰聚成一个跨全段的候选（长事件不再碎裂/重复）；
- 低量高质弹幕（默默夸赞）凭内容准入；
- 相邻重复候选 gap-merge、独立事件不误合并；
- 建议长度上限 3600s 且 min/max 联动；
- 分析完成后设置区自动收起（后续 set_project_status 不再叠回来）；
- 分析模型可选且覆写只作用于当次调用，不污染全局 settings；
- 候选卡证据默认可见。
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from twobyteasr.studio.studio_danmaku import aggregate_danmaku, parse_danmaku_xml
from twobyteasr.timeline.studio_edit_sequence import HighlightCandidate
from twobyteasr.studio.studio_highlight_analyzer import (
    _apply_ai_override,
    candidates_from_local,
    cluster_windows,
    discover_local_candidates,
    merge_overlapping_candidates,
    transcript_window,
)
from twobyteasr.studio.studio_highlight_ui import HighlightAssistantPanel
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _xml(path: Path, rows: list[tuple[float, str]]) -> Path:
    body = "".join(f'<d p="{time},1,25,1,0,0,0,0">{text}</d>' for time, text in rows)
    path.write_text(f"<i>{body}</i>", encoding="utf-8")
    return path


def _project(cues: list[StudioCue], duration_ms: int) -> SubtitleProject:
    return SubtitleProject(media=StudioMedia(path="recording.flv", duration_ms=duration_ms), cues=cues)


def test_cluster_recall_merges_contiguous_spikes(tmp_path):
    """10 个连续 30s 弹幕高峰 = 1 个候选，span 覆盖全段而不是 10 个碎候选。"""
    rows: list[tuple[float, str]] = []
    for window in range(10):
        for i in range(8):
            rows.append((window * 30 + i * 3 + 0.5, "哈哈哈哈 笑死"))
    rows += [(305 + i, "普通聊天") for i in range(3)]
    document = parse_danmaku_xml(_xml(tmp_path / "long.xml", rows))
    cues = [StudioCue(f"c{i}", i * 30_000, i * 30_000 + 2_000, "正常对话内容平平淡淡") for i in range(11)]
    candidates = discover_local_candidates(_project(cues, 360_000), document, window_ms=30_000)
    danmaku_candidates = [item for item in candidates if item.danmaku is not None]
    assert danmaku_candidates, "弹幕高峰应产生候选"
    top = danmaku_candidates[0]
    assert top.start_ms == 0
    assert top.end_ms >= 300_000, "连续高峰应聚成跨全段的候选"
    assert "弹幕高峰" in top.reasons[0] and "10 段" in top.reasons[0]


def test_quiet_highlight_recalled_with_danmaku_bound(tmp_path):
    """弹幕全程平淡但字幕有强转折时，靠字幕语义召回（旧逻辑此模式忽略字幕）。"""
    rows = [(i * 5.0, "普通") for i in range(132)]  # 全程均匀（0–655s），无峰、无边界伪峰
    document = parse_danmaku_xml(_xml(tmp_path / "quiet.xml", rows))
    cues = [
        StudioCue("c0", 0, 4_000, "今天我们继续打这个图"),
        StudioCue("c1", 600_000, 604_000, "卧槽居然翻盘了？！"),
        StudioCue("c2", 604_500, 608_000, "没想到真的成功了"),
    ]
    candidates = discover_local_candidates(_project(cues, 660_000), document, window_ms=30_000)
    assert not any(item.danmaku is not None for item in candidates), "均匀弹幕不应有峰值候选"
    semantic = [item for item in candidates if any("强情绪" in reason for reason in item.reasons)]
    assert semantic, "安静精彩段必须能靠字幕语义召回"
    assert any(item.start_ms <= 604_000 for item in semantic)


def test_quiet_quality_window_admitted(tmp_path):
    """低量高质弹幕（每条都带反应词）凭内容准入，不需要密度峰。"""
    rows = [(1 + i, "牛！太强了") for i in range(6)]        # w0: 6 条 hype
    rows += [(31 + i, "普通") for i in range(6)]            # w1: 6 条无反应
    rows += [(61 + i, "普通") for i in range(6)]            # w2: 6 条无反应
    document = parse_danmaku_xml(_xml(tmp_path / "quality.xml", rows))
    windows = aggregate_danmaku(document, window_ms=30_000, context=1)
    from twobyteasr.studio.studio_danmaku import local_spike_windows

    picked = local_spike_windows(windows, min_spike=1.25, top_k=10)
    assert [item.start_ms for item in picked] == [0], "只有高质量窗口应被召回"


def test_gap_merge_nms_merges_fragments_not_events():
    inside = HighlightCandidate("a", "整局翻盘", 0, 600_000, 0.9)
    fragment = HighlightCandidate("b", "同一局的收尾", 630_000, 810_000, 0.8)  # 180s，gap 30s → 合并
    merged = merge_overlapping_candidates([inside, fragment])
    assert len(merged) == 1
    assert merged[0].source_in_ms == 0 and merged[0].source_out_ms == 810_000

    separate_a = HighlightCandidate("c", "事件一", 0, 30_000, 0.9)
    separate_b = HighlightCandidate("d", "事件二", 90_000, 120_000, 0.8)  # gap 60s > 阈值 → 不合并
    kept = merge_overlapping_candidates([separate_a, separate_b])
    assert len(kept) == 2

    contained = HighlightCandidate("e", "爆点", 100_000, 130_000, 0.85)
    host = HighlightCandidate("f", "完整事件", 40_000, 400_000, 0.9)
    assert len(merge_overlapping_candidates([contained, host])) == 1


def test_cluster_windows_groups_by_time_gap():
    from twobyteasr.studio.studio_danmaku import DanmakuWindow

    def window(start: int, end: int) -> DanmakuWindow:
        return DanmakuWindow(start, end, 1, 1, 1.0, 1.0, [], {}, 0.0)

    clusters = cluster_windows([window(0, 30_000), window(30_000, 60_000), window(180_000, 210_000)])
    assert [len(group) for group in clusters] == [2, 1]


def test_transcript_sampling_spans_long_window():
    cues = [StudioCue(f"c{i}", i * 10_000, i * 10_000 + 5_000, f"第{i}句") for i in range(100)]
    text = transcript_window(_project(cues, 1_000_000), 0, 1_000_000, limit=10, sample=True)
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 10
    assert "第0句" in lines[0]
    assert "第99句" in lines[-1], "长窗口应跨段采样到结尾，而不是只取前 N 条"


def test_candidates_from_local_keeps_long_cluster_span(tmp_path):
    rows: list[tuple[float, str]] = []
    for window in range(20):
        for i in range(8):
            rows.append((window * 30 + i * 3 + 0.5, "哈哈哈哈 笑死"))
    document = parse_danmaku_xml(_xml(tmp_path / "long20.xml", rows))
    cues = [StudioCue(f"c{i}", i * 30_000, i * 30_000 + 2_000, "正常对话") for i in range(21)]
    locals_ = discover_local_candidates(_project(cues, 660_000), document, window_ms=30_000)
    fallback = candidates_from_local(_project(cues, 660_000), locals_, limit=3, max_seconds=1200)
    assert fallback, "本地回退应产生候选"
    assert fallback[0].source_out_ms - fallback[0].source_in_ms >= 590_000, "max>600s 时 10 分钟片段不应被截断"


def test_length_spinbox_range_and_coupling(tmp_path):
    _app()
    panel = HighlightAssistantPanel()
    assert panel.max_box.maximum() >= 3600
    panel.min_box.setValue(300)
    assert panel.min_box.value() == 300
    panel.max_box.setValue(100)
    assert panel.min_box.value() == 100, "max 调小时 min 必须联动，避免 min>max"
    panel.min_box.setValue(200)
    assert panel.max_box.value() == 200, "min 调大时 max 必须跟随"
    panel.deleteLater()


def test_analysis_auto_collapses_settings(tmp_path):
    _app()
    panel = HighlightAssistantPanel()
    project = _project([StudioCue("c0", 0, 2_000, "开场白")], 30_000)
    panel.set_project_status(project, "")
    assert panel.config_body.isVisibleTo(panel), "无候选时设置区应可见"
    panel.reload_candidates([
        HighlightCandidate("k1", "翻盘名场面", 10_000, 190_000, 0.9, reason="完整事件", quotes=["牛！"]),
    ])
    assert panel.results.count() == 1
    assert not panel.config_body.isVisibleTo(panel), "有候选后设置区应自动收起"
    assert panel.candidates_body.isVisibleTo(panel)
    assert panel.active_stage() == "candidates"
    # 回归锁定：后续 set_project_status（autosave/dirty flush）不得把设置区叠回来
    panel.set_project_status(project, "")
    assert not panel.config_body.isVisibleTo(panel)
    assert panel.candidates_body.isVisibleTo(panel)
    panel.deleteLater()


def test_card_evidence_visible_by_default(tmp_path):
    _app()
    panel = HighlightAssistantPanel()
    panel.resize(300, 720)
    panel.reload_candidates([
        HighlightCandidate(
            "k1",
            "翻盘名场面",
            10_000,
            190_000,
            0.9,
            reason="观众反应集中",
            quotes=["牛！这就是翻盘", "泪目了"],
            danmaku_evidence=["弹幕高峰 2 段共 41 条"],
        ),
    ])
    card = panel.results.itemWidget(panel.results.item(0))
    assert card is not None
    evidence = card.findChild(QLabel, "highlightEvidence")
    # 2026-09-18 五字段规约：原始弹幕默认收起、随详情展开（2026-09-19
    # 修复了 evidence 曾永远不可见的存量 bug——现在详情按钮真正联动）。
    assert evidence is not None and bool(evidence.text())
    assert evidence.isHidden()
    detail_button = next(
        button for button in card.findChildren(QPushButton) if button.text() == "详情"
    )
    detail_button.click()
    assert not evidence.isHidden()
    panel.deleteLater()


def test_ai_override_is_call_site_only():
    settings = {"models": {
        "polish_transport": "grok_cli",
        "polish_provider": "grok_oauth",
        "polish_model": "grok-4.6",
    }, "switches": {}}
    override = _apply_ai_override(settings, "deepseek", "deepseek-v4-pro")
    assert override is not settings
    assert override["models"]["polish_provider"] == "deepseek"
    assert override["models"]["polish_model"] == "deepseek-v4-pro"
    assert settings["models"]["polish_provider"] == "grok_oauth", "全局 settings 不得被污染"
    unchanged = _apply_ai_override(settings, "", "")
    assert unchanged is settings, "无选择时直接复用原 settings"


def test_panel_ai_selection_persisted_and_emitted(tmp_path, monkeypatch):
    _app()
    panel = HighlightAssistantPanel()
    store = QSettings(str(tmp_path / "clip.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(panel, "_clip_settings", lambda: store)
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY

    monkeypatch.setattr(
        GLOBAL_PROVIDER_REGISTRY, "models",
        lambda service, settings=None: ("deepseek-v4-flash", "deepseek-v4-pro"),
        raising=True,
    )
    panel._restore_ai_selection()
    assert panel.selected_ai() == ("", ""), "默认跟随全局"

    index = panel.ai_service_combo.findData("deepseek")
    assert index >= 0
    panel.ai_service_combo.setCurrentIndex(index)
    assert panel.ai_model_combo.count() == 3, "默认 + 两个模型"
    panel.ai_model_combo.setCurrentIndex(2)
    assert panel.selected_ai() == ("deepseek", "deepseek-v4-pro")
    assert str(store.value("highlight_ai_service", "")) == "deepseek"
    assert str(store.value("highlight_ai_model", "")) == "deepseek-v4-pro"

    emitted: list[dict] = []
    panel.analyze_requested.connect(emitted.append)
    panel.set_project_status(_project([StudioCue("c0", 0, 2_000, "开场白")], 30_000), "")
    panel._analyze()
    assert emitted, "点击分析应发射选项"
    assert emitted[-1].get("ai_service") == "deepseek"
    assert emitted[-1].get("model") == "deepseek-v4-pro"
    panel.deleteLater()


def test_analysis_note_surfaced_on_llm_fallback(tmp_path):
    _app()
    panel = HighlightAssistantPanel()
    project = _project([StudioCue("c0", 0, 2_000, "开场白")], 30_000)
    panel.set_project_status(project, "")
    panel.set_analysis_note("local_fallback", "HTTP 401 unauthorized")
    assert "AI 排序不可用" in panel.status.text()
    assert "401" in panel.status.text()
    panel.set_analysis_note("completed", "")
    assert "AI 排序不可用" not in panel.status.text(), "成功后提示应清除"
    panel.deleteLater()


# —— 2026-09-19 P1：簇级统计统一 + 本地回退诚实化 + 解释上下文存档 ——

def test_cluster_stats_is_single_source_for_card_and_reason(tmp_path):
    from twobyteasr.studio.studio_danmaku import aggregate_danmaku
    from twobyteasr.studio.studio_highlight_analyzer import cluster_stats, discover_local_candidates, candidates_from_local

    rows = [(5 + i * 0.5, "哈哈哈哈" if i % 3 == 0 else "这是什么？") for i in range(40)]
    document = parse_danmaku_xml(_xml(tmp_path / "stats.xml", rows))
    windows = aggregate_danmaku(document, window_ms=10_000, context=1)
    from twobyteasr.studio.studio_danmaku import local_spike_windows
    from twobyteasr.studio.studio_highlight_analyzer import cluster_windows
    spikes = local_spike_windows(windows, min_spike=1.25, top_k=10)
    stats = cluster_stats(cluster_windows(spikes)[0]) if spikes else {}
    assert stats
    # 条数语义：funny/chaos_count ≤ 弹幕总条数（一条至多计 1）。
    assert stats["funny_count"] + stats["chaos_count"] <= stats["raw_total"]
    assert stats["windows"] >= 1 and stats["peak_spike"] >= 0
    # raw_total ≥ usable_total（去噪只会减不会增）。
    assert stats["raw_total"] >= stats["usable_total"]


def test_local_fallback_is_honest_not_fabricated(tmp_path):
    from twobyteasr.projects.studio_project import StudioSpeaker

    project = SubtitleProject(media=StudioMedia(path="rec.flv", duration_ms=120_000))
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    for i in range(20):
        project.cues.append(StudioCue(f"c{i}", 5_000 + i * 5_000, 8_000 + i * 5_000, f"第{i}局开始了", speaker_id="S01"))
    rows = [(10 + i * 0.4, "哈哈" if i % 2 else "？") for i in range(30)]
    document = parse_danmaku_xml(_xml(tmp_path / "local.xml", rows))
    candidates = discover_local_candidates(project, document, window_ms=10_000)
    fallback = candidates_from_local(project, candidates, limit=3, max_seconds=60)
    assert fallback
    item = fallback[0]
    # 标题不再用截断台词冒充事件；标注待核实。
    assert "待核实" in item.title
    assert item.title != item.subtitle_evidence[0] if item.subtitle_evidence else True
    assert item.origin == "local"
    assert item.context_required == "high"
    # 发生了什么=台词摘录（明确来源），不编造事件。
    assert "主播台词摘录" in (item.event_summary or "")
    # 为什么值得剪=热度证据+待核实声明，不含"观众反应集中："数字翻译前缀。
    assert "尚未核实" in item.clip_reason
    assert not item.clip_reason.startswith("观众反应集中：")
    # 统计为簇级口径（卡片底部同 dict）。
    signal = item.danmaku_signal
    assert "usable_total" in signal and "windows" in signal and "peak_spike" in signal
    assert "funny_count" in signal and "chaos_count" in signal
    # 信号范围字幕上下文随候选存档（重生成解释/人工核对共享）。
    assert item.subtitle_context


def test_replace_candidates_preserves_user_status():
    from twobyteasr.timeline.studio_edit_commands import replace_candidates_command
    from twobyteasr.timeline.studio_edit_sequence import sequence_of

    project = SubtitleProject(media=StudioMedia(path="r.flv", duration_ms=600_000))
    old = HighlightCandidate("old-1", "旧", 100_000, 160_000, 0.8, status="accepted")
    sequence_of(project).clip_candidates = [old]
    fresh = HighlightCandidate("new-1", "新", 102_000, 158_000, 0.9)
    replace_candidates_command(project, [fresh]).redo()
    stored = sequence_of(project).clip_candidates
    assert stored[0].status == "accepted"  # 重生成不丢用户取舍
    other = HighlightCandidate("new-2", "无关", 400_000, 460_000, 0.7)
    replace_candidates_command(project, [other]).redo()
    assert sequence_of(project).clip_candidates[0].status == "suggested"
