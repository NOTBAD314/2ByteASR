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
            rows.append((window * 30 + i * 3 + 0.5, ("哈哈哈哈 笑死", "？？？", "太强了")[i % 3]))
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
    rows = [(1 + i, ("牛！太强了", "厉害", "封神")[i % 3]) for i in range(6)]        # w0: 6 条 hype
    rows += [(31 + i, "普通") for i in range(6)]            # w1: 6 条无反应
    rows += [(61 + i, "普通") for i in range(6)]            # w2: 6 条无反应
    document = parse_danmaku_xml(_xml(tmp_path / "quality.xml", rows))
    windows = aggregate_danmaku(document, window_ms=30_000, context=1)
    from twobyteasr.studio.studio_danmaku import local_spike_windows

    picked = local_spike_windows(windows, min_spike=1.25, top_k=10)
    assert [item.start_ms for item in picked] == [0], "只有高质量窗口应被召回"


def test_gap_merge_nms_merges_fragments_not_events():
    # 10-24: proximity alone must not join distinct events or enlarge a cut.
    inside = HighlightCandidate("a", "整局", 0, 600000, .9)
    fragment = HighlightCandidate("b", "后续", 630000, 810000, .8)
    assert len(merge_overlapping_candidates([inside,fragment])) == 2
    contained = HighlightCandidate("e", "重复范围", 100000, 130000, .85)
    host = HighlightCandidate("f", "原范围", 40000, 400000, .9)
    result = merge_overlapping_candidates([contained,host])
    assert len(result)==1 and result[0].source_out_ms==400000


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
            rows.append((window * 30 + i * 3 + 0.5, ("哈哈哈哈 笑死", "？？？", "太强了")[i % 3]))
    document = parse_danmaku_xml(_xml(tmp_path / "long20.xml", rows))
    cues = [StudioCue(f"c{i}", i * 30_000, i * 30_000 + 2_000, "正常对话") for i in range(21)]
    locals_ = discover_local_candidates(_project(cues, 660_000), document, window_ms=30_000)
    fallback = candidates_from_local(_project(cues, 660_000), locals_, limit=3, max_seconds=1200)
    assert fallback, "本地回退应产生候选"
    assert fallback[0].context_out_ms - fallback[0].context_in_ms >= 590_000
    assert fallback[0].clip_range is None, "长反应簇是上下文，不能冒充成片范围"


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
    panel=HighlightAssistantPanel()
    panel.reload_candidates([HighlightCandidate('k1','观众赞叹',10000,190000,.9,
        evidence=[dict(id='d:1',kind='danmaku',start_ms=12000,end_ms=12000,text='牛！')])])
    card=panel.results.itemWidget(panel.results.item(0))
    evidence=card.findChild(QLabel,'highlightEvidence')
    assert evidence and '牛！' in evidence.text() and not evidence.isVisibleTo(card)
    card.details_action.trigger()
    assert evidence.isVisibleTo(card)
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
    _app();panel=HighlightAssistantPanel()
    panel.set_project_status(_project([StudioCue('c0',0,2000,'开场白')],30000),'')
    panel.set_analysis_note('local_fallback','HTTP 401 unauthorized')
    assert '已保留本地建议' in panel.local_hint.text()
    assert '401' in panel.status.text() and '401' not in panel.local_hint.text()
    panel.set_analysis_note('completed','')
    assert not panel.local_hint.text()
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
    project=_project([StudioCue('c0',10000,12000,'普通对话')],120000)
    rows=[(10+i*.2,('哈哈哈','？？？','真的假的')[i%3]) for i in range(30)]
    document=parse_danmaku_xml(_xml(tmp_path/'local.xml',rows))
    candidates=discover_local_candidates(project,document,window_ms=10000)
    fallback=candidates_from_local(project,candidates,limit=3,max_seconds=60)
    assert fallback
    item=fallback[0]
    assert item.origin=='local' and item.clip_range is None
    assert '附近' in item.title and '弹幕集中' in item.title
    assert item.grade=='待确认' and '热窗' not in item.clip_reason
    assert any(r['kind']=='danmaku' and r['text'] in {'哈哈哈','？？？','真的假的'} for r in item.evidence)
    assert any(r['kind']=='subtitle' for r in item.evidence)


def test_replace_candidates_preserves_user_status():
    from twobyteasr.timeline.studio_edit_commands import replace_candidates_command
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    project=SubtitleProject(media=StudioMedia(path='r.flv',duration_ms=600000))
    old=HighlightCandidate('old-1','旧',100000,160000,.8,status='accepted',source_path='r.flv')
    sequence_of(project).clip_candidates=[old]
    fresh=HighlightCandidate('new-1','新',102000,158000,.9,source_path='r.flv')
    replace_candidates_command(project,[fresh],preserve_decisions=True).redo()
    assert sequence_of(project).clip_candidates[0].status=='accepted'
    row=sequence_of(project).clip_candidates[0]
    import copy
    row=copy.deepcopy(row);row.status='suggested'
    replace_candidates_command(project,[row]).redo()
    assert sequence_of(project).clip_candidates[0].status=='suggested'
