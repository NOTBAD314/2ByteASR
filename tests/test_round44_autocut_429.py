"""四十四轮守护：429 限流根治（节流/退避/补扫轮）+ 自动剪口播气口。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twobyteasr.recognition import asr
from twobyteasr.studio.studio_autocut import (
    auto_cut_silence_command,
    compute_silence_ranges_ms,
    source_ranges_to_timeline,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- T1 节流器


def test_throttle_adapts_on_429_and_recovers():
    throttle = asr._AsrApiThrottle()
    assert throttle.snapshot()["min_interval"] == 0.0
    throttle.report_429()
    assert abs(throttle.snapshot()["min_interval"] - 0.6) < 1e-6
    throttle.report_429()
    assert abs(throttle.snapshot()["min_interval"] - 1.2) < 1e-6
    throttle.report_429(9.0)  # Retry-After 覆盖
    assert abs(throttle.snapshot()["min_interval"] - 9.0) < 1e-6 or throttle.snapshot()["min_interval"] == 6.0
    for _ in range(20):
        throttle.report_success()
    assert throttle.snapshot()["min_interval"] < 9.0


def test_retry_after_header_parsing():
    class _Resp:
        def __init__(self, value):
            self.headers = {"Retry-After": value} if value is not None else {}

    assert abs(asr._retry_after_seconds(_Resp("3")) - 3.0) < 1e-6
    assert asr._retry_after_seconds(_Resp("not-a-date")) == 0.0
    assert asr._retry_after_seconds(_Resp(None)) == 0.0


def test_failed_chunks_recovered_by_sweep(monkeypatch, tmp_path):
    """主扫 429 失败的块必须在补扫轮恢复——不再丢弃（字幕空洞根因）。"""
    calls = {"count": 0}
    fail_first = {1, 3}

    def fake_call(audio, context, *, endpoint=None, requests_module=None):
        calls["count"] += 1
        index = int.from_bytes(bytes(audio[:1]), "big")
        if index in fail_first and calls["count"] <= 8:
            raise RuntimeError("ASR API 请求失败（HTTP 429 / no-code）：Too Many Requests")
        return f"块{index}的文字"

    class _NoThrottle:
        def acquire(self):
            return None

        def report_429(self, *_a):
            return None

        def report_success(self):
            return None

    monkeypatch.setattr(asr, "call_qwen_asr_api", fake_call)
    monkeypatch.setattr(asr, "_ASR_API_THROTTLE", _NoThrottle())
    monkeypatch.setattr(asr, "build_qwen_asr_context", lambda _p: "ctx")
    monkeypatch.setattr(
        "twobyteasr.providers.llm_config.qwen_asr_endpoint_from_settings",
        lambda _s: {"url": "http://x", "api_key": "k", "model": "m",
                    "protocol": "openrouter_verbose_json", "provider": "openrouter_word"},
    )
    monkeypatch.setattr(asr.time, "sleep", lambda _s: None)

    chunks = [
        {"start": float(i * 10), "end": float(i * 10 + 10), "audio": (bytes([i]),)}
        for i in range(4)
    ]
    media = tmp_path / "m.flv"
    media.write_bytes(b"x")
    references = asr._transcribe_qwen_api(str(media), chunks)
    texts = [row["text"] for row in references]
    assert texts == ["块0的文字", "块1的文字", "块2的文字", "块3的文字"], texts
    assert calls["count"] > 4  # 触发了补扫重试


# ---------------------------------------------------------------- T3 剪气口


def _tone(seconds: float, sr: int = 16000) -> list[float]:
    import math

    return [0.6 * math.sin(2 * math.pi * 220 * i / sr) for i in range(int(seconds * sr))]


def test_compute_silence_ranges_finds_long_gaps():
    import numpy as np

    sr = 16000
    audio = np.array(
        _tone(3.0) + [0.0] * int(8.0 * sr) + _tone(3.0) + [0.0] * int(6.0 * sr) + _tone(3.0),
        dtype=np.float32,
    )
    ranges = compute_silence_ranges_ms(audio, sr, min_silence_s=5.0, padding_s=0.35)
    assert len(ranges) == 2, ranges
    (a1, b1), (a2, b2) = ranges
    assert abs(a1 - 3350) <= 350 and abs(b1 - 10650) <= 350, ranges
    assert abs(a2 - 14350) <= 350 and abs(b2 - 19650) <= 350, ranges
    # 阈值调高到 8.5s 后两个气口都不算。
    assert compute_silence_ranges_ms(audio, sr, min_silence_s=8.5, padding_s=0.35) == []


def test_source_ranges_map_through_sequence():
    from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment

    sequence = EditSequence(
        source_path="a.flv",
        source_duration_ms=30_000,
        segments=[
            VideoSegment(id="s1", source_path="a.flv", source_in_ms=0, source_out_ms=10_000,
                         timeline_in_ms=0, timeline_out_ms=10_000),
            VideoSegment(id="s2", source_path="a.flv", source_in_ms=15_000, source_out_ms=25_000,
                         timeline_in_ms=10_000, timeline_out_ms=20_000),
        ],
    )
    mapped = source_ranges_to_timeline(sequence, [(12_000, 17_000), (24_000, 26_000)])
    # 12-17s 里只有 15-17 在保留段（时间轴 10-12）；24-26 → 时间轴 19-20。
    assert mapped == [(10_000, 12_000), (19_000, 20_000)], mapped


def test_auto_cut_command_ripples_sequence_and_cues():
    _app()
    from twobyteasr.timeline.studio_edit_sequence import (
        VideoSegment, ensure_edit_sequence, sequence_of, store_sequence,
    )

    project = SubtitleProject(
        media=StudioMedia(path="a.flv", duration_ms=20_000, width=1280, height=720),
        cues=[
            StudioCue("c1", 0, 2_000, "第一句", style_id="default"),
            StudioCue("c2", 12_000, 14_000, "第二句", style_id="default"),
        ],
    )
    sequence = ensure_edit_sequence(project)
    sequence.video_track_locked = False
    sequence.source_duration_ms = 20_000
    sequence.segments = [
        VideoSegment(id="s1", source_path="a.flv", source_in_ms=0, source_out_ms=20_000,
                     timeline_in_ms=0, timeline_out_ms=20_000)
    ]
    store_sequence(project, sequence)

    command = auto_cut_silence_command(project, [(5_000, 11_000)])
    command.redo()
    after = sequence_of(project)
    assert after.timeline_duration_ms == 14_000, after.timeline_duration_ms
    cue2 = next(cue for cue in project.cues if cue.id == "c2")
    assert (cue2.start_ms, cue2.end_ms) == (12_000, 14_000)
    from twobyteasr.timeline.studio_edit_sequence import projected_cues, source_cue_id_of
    projected = next(cue for cue in projected_cues(project) if source_cue_id_of(cue.id) == "c2")
    assert (projected.start_ms, projected.end_ms) == (6_000, 8_000)
    command.undo()
    restored = sequence_of(project)
    assert restored.timeline_duration_ms == 20_000
    cue2 = next(cue for cue in project.cues if cue.id == "c2")
    assert (cue2.start_ms, cue2.end_ms) == (12_000, 14_000)
