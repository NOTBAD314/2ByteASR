"""三十一轮守护：用户七项反馈的回归锁定。

①SenseVoice frozen 子进程路由+主力异常透传；②词库下拉默认不选；
③分析稿保留最终 cue+Qwen3 45s 片限长；④面板候选区常驻；⑤证据字符串
拆字矫正；⑦页面隐藏期渲染器恢复重试。
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from twobyteasr.recognition.asr import build_qwen_asr_chunks
from twobyteasr.timeline.studio_edit_sequence import HighlightCandidate, _string_list
from twobyteasr.studio.studio_highlight_ui import HighlightAssistantPanel
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    create_studio_outputs,
    load_project,
    save_project,
)

QWEN_ASR_CHUNK_SECONDS = 25.0


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_string_list_coerces_plain_string_to_single_row():
    assert _string_list("弹幕高峰，观众狂笑") == ["弹幕高峰，观众狂笑"]
    assert _string_list(["a", "", "b"]) == ["a", "b"]
    assert _string_list(None) == []
    assert _string_list({"bad": 1}) == []


def test_candidate_string_evidence_stays_one_row():
    candidate = HighlightCandidate(
        "k1", "标题", 0, 1_000, 0.9,
        reason="r",
        danmaku_evidence="弹幕高峰，观众狂笑",  # LLM 常见形态：字符串而非数组
        subtitle_evidence="台词证据",
        quotes="整句引用",
        risk_notes="风险",
        subtitle_emphasis="重点",
    )
    candidate.validate()
    assert candidate.danmaku_evidence == ["弹幕高峰，观众狂笑"]
    assert candidate.subtitle_evidence == ["台词证据"]
    assert candidate.quotes == ["整句引用"]
    assert candidate.risk_notes == ["风险"]
    assert candidate.subtitle_emphasis == ["重点"]

    restored = HighlightCandidate.from_dict(
        {"id": "k2", "title": "t", "source_in_ms": 0, "source_out_ms": 1_000,
         "danmaku_evidence": "字符串载荷"}
    )
    assert restored.danmaku_evidence == ["字符串载荷"]


def test_qwen_chunks_split_overlong_single_region():
    import numpy as np

    sampling = 16_000
    audio = np.zeros(int(45.0 * sampling), dtype=np.float32)
    regions = [{"start": 0.0, "end": 45.0}]
    chunks = build_qwen_asr_chunks(audio, regions, sampling)
    assert len(chunks) >= 2, "45s 单区间必须被切开，不再整体透传成一条巨型 cue"
    for chunk in chunks:
        # 切分上限作用于人声区间；chunk 本体还带左右 QWEN_ASR_AUDIO_PAD 缓冲。
        assert chunk["end"] - chunk["start"] <= QWEN_ASR_CHUNK_SECONDS + 0.5


def test_highlight_panel_candidates_zone_permanent():
    _app()
    panel = HighlightAssistantPanel()
    project = SubtitleProject(
        media=StudioMedia(path="x.mp4", duration_ms=30_000),
        cues=[StudioCue("c0", 0, 2_000, "开场白")],
    )
    panel.set_project_status(project, "")
    # 空态：候选区常驻（占位+分隔），设置区默认展开
    assert panel.candidates_body.isVisibleTo(panel)
    assert panel.candidates_empty.isVisibleTo(panel)
    assert panel.config_body.isVisibleTo(panel)

    panel.reload_candidates(
        [HighlightCandidate("k1", "翻盘", 10_000, 190_000, 0.9, reason="完整事件")]
    )
    assert panel.results.count() == 1
    assert not panel.candidates_empty.isVisibleTo(panel)
    assert not panel.config_body.isVisibleTo(panel), "分析后自动收起设置"
    assert panel.active_stage() == "candidates"

    # 后续刷新不得把设置叠回来（二十九轮回归保持）
    panel.set_project_status(project, "")
    assert not panel.config_body.isVisibleTo(panel)

    # 折叠钮点击必须立即可见生效（三十一轮："设置点击没有任何效果"）
    panel.config_toggle.click()
    assert panel.config_body.isVisibleTo(panel)
    assert panel.active_stage() == "settings"
    panel.config_toggle.click()
    assert not panel.config_body.isVisibleTo(panel)
    assert panel.active_stage() == "candidates"
    panel.deleteLater()


def test_analysis_transcript_keeps_final_cues(tmp_path):
    media = tmp_path / "rec.flv"
    media.write_bytes(b"flv")
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=60_000),
        cues=[],
    )
    project.validate()
    project_path = tmp_path / "proj.2byteproj"
    save_project(project, project_path)

    class _Cue:
        def __init__(self, start, end, text):
            self.start_ms, self.end_ms, self.text = start, end, text
            self.id = f"c-{start}"
            self.speaker_id = "S00"
            self.style_id = "default"
            self.evidence_refs = []
            self.start = start / 1000.0
            self.end = end / 1000.0
            self.speaker = "S00"
            self.segment_id = 1

    txt = tmp_path / "analysis.txt"
    txt.write_text("分析稿", encoding="utf-8")
    create_studio_outputs(
        str(media),
        [_Cue(1_000, 3_000, "第一句"), _Cue(4_000, 6_000, "第二句")],
        txt_path=str(txt),
        srt_path="",
        target_project_path=str(project_path),
        generation_metadata={
            "analysis_transcript": True,
            "asr_provisional_cues": [
                {"id": "asr-1", "start_ms": 500, "end_ms": 3_500},
            ],
        },
    )
    saved = load_project(project_path)
    assert len(saved.cues) == 2, "快速分析完成后最终 cue 必须留在工程里（不再消失）"
    states = saved.generation_metadata.get("asr_cue_states", {})
    assert all(states.get(cue.id) == "final" for cue in saved.cues)
    assert states.get("asr-1") == "invalidated"
    assert saved.studio_state.get("analysis_transcript"), "剪辑助手分析稿载荷仍在"

    # 已有正式字幕（非 ASR 产出）时不被分析稿覆盖
    manual = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=60_000),
        cues=[StudioCue("manual-1", 10_000, 12_000, "人工字幕")],
    )
    manual.validate()
    save_project(manual, project_path)
    create_studio_outputs(
        str(media),
        [_Cue(20_000, 22_000, "分析句")],
        txt_path=str(txt),
        srt_path="",
        target_project_path=str(project_path),
        generation_metadata={"analysis_transcript": True},
    )
    saved2 = load_project(project_path)
    assert [cue.id for cue in saved2.cues] == ["manual-1"], "正式字幕不被分析稿替换"


def test_renderer_restore_waits_for_visibility(tmp_path):
    _app()
    from PySide6.QtTest import QTest
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    page.resize(1200, 800)
    calls: list[str] = []
    page.ensure_active_subtitle_renderer = lambda *, reason="sync": calls.append(reason)
    page._ensure_renderer_when_visible(reason="unit_test")
    assert calls == [], "隐藏态不得提交 NONE 结论"
    page.show()
    QTest.qWait(300)
    assert "unit_test" in calls, "页面可见后必须补一次渲染器重算（恢复 NATIVE）"
    page.close_page()
    page.deleteLater()
