"""三十六轮守护：API 主力真 VAD 切块 + 10s 短块 + 完成后入口去工作台。

用户实录（异环自行车 76s）：增量层把整块 45s 当"语音区间"传入 → 25s 硬切
块边界落在连续语流中间 → MAI 的大停顿级 segment 让 21 句话共享 0→25.2 一个
时间戳 → 下游匀速重摊 → 字幕出现/切换延迟秒级、数字串烧（"12013014015 0"）、
切缝 0.4s 双 pad 让 "150" 被两块各识别一遍。
"""

import numpy as np
import pytest

from twobyteasr.recognition import asr
from twobyteasr.recognition.asr import build_qwen_asr_chunks

SAMPLING = 16_000


def _audio(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLING), dtype=np.float32)


def test_chunk_seconds_param_splits_shorter():
    # 音频比区域长 2s，尾块的右 pad 才不会被音频长度截断
    audio = _audio(27.0)
    regions = [{"start": 0.0, "end": 25.0}]
    chunks = build_qwen_asr_chunks(audio, regions, SAMPLING, chunk_seconds=10.0)
    spans = [(round(c["start"], 3), round(c["end"], 3)) for c in chunks]
    # 三块：0→10、10→20、20→25.2；首块带左 pad（钳 0），尾块带右 pad
    assert spans[0] == (0.0, 10.0)
    assert spans[1] == (10.0, 20.0)
    assert spans[2] == (20.0, 25.2)


def test_capped_seam_has_no_mutual_padding():
    """同一区间的切分缝不互相 pad：缝两侧边界精确相接，不再各带 0.2s。"""
    audio = _audio(60.0)
    regions = [{"start": 5.0, "end": 35.0}]
    chunks = build_qwen_asr_chunks(audio, regions, SAMPLING, chunk_seconds=10.0)
    spans = [(round(c["start"], 3), round(c["end"], 3)) for c in chunks]
    assert spans == [(4.8, 15.0), (15.0, 25.0), (25.0, 35.2)]
    for earlier, later in zip(spans, spans[1:]):
        assert earlier[1] == later[0], "切缝必须精确相接，不得重叠"


def test_merge_gap_limit_keeps_silence_out():
    """gap>1s 的相邻 VAD 区间不得合并——合并会把中间静音摊进字幕时间
    （实录：0.2-1.6 与 5.0-6.4 被合成 0-6.6 一行，静音 3.4s 全被吞）。"""
    audio = _audio(36.0)
    regions = [
        {"start": 0.2, "end": 1.6},
        {"start": 5.0, "end": 6.4},
        {"start": 19.5, "end": 23.9},
        {"start": 24.8, "end": 29.0},  # gap 0.9 ≤ 1.0 → 允许合并
    ]
    chunks = build_qwen_asr_chunks(
        audio, regions, SAMPLING, chunk_seconds=10.0, max_merge_gap_seconds=1.0
    )
    spans = [(round(c["start"], 3), round(c["end"], 3)) for c in chunks]
    assert spans == [(0.0, 1.8), (4.8, 6.6), (19.3, 29.2)]
    # 静音区内部（去掉两侧 0.2s pad）不被任何行覆盖
    def covered(a, b):
        return sum(max(0.0, min(e, b) - max(s, a)) for s, e in spans)
    assert covered(2.2, 4.8) == 0.0
    assert covered(7.0, 19.0) == 0.0


def test_default_chunking_keeps_legacy_25s_behavior():
    audio = _audio(60.0)
    regions = [{"start": 0.0, "end": 45.0}]
    chunks = build_qwen_asr_chunks(audio, regions, SAMPLING)
    spans = [(round(c["start"], 3), round(c["end"], 3)) for c in chunks]
    # 本地/复核路径不变：25s 上限；切缝同样精确相接（不回退旧行为）
    assert spans[0][0] == 0.0
    assert spans[0][1] == 25.0
    assert spans[1] == (25.0, 45.2)


def test_api_primary_uses_10s_chunks(monkeypatch):
    """backend_override='api'（主力路径）必须用 10s 短块；复核保持 25s。"""
    captured = {}

    def _fake_transcribe(audio_path, chunks, *, publish_primary=False):
        captured['publish_primary'] = publish_primary
        captured["spans"] = [
            (round(c["start"], 3), round(c["end"], 3)) for c in chunks
        ]
        return [{"start": c["start"], "end": c["end"], "text": "文"} for c in chunks]

    monkeypatch.setattr(asr, "_transcribe_api_owned", _fake_transcribe)
    monkeypatch.setattr(asr, "decode_audio_to_array", lambda path: _audio(26.0))
    # 端点检查要求有 Key；用假 Key，不依赖本机保存的真实密钥。
    monkeypatch.setattr("twobyteasr.providers.llm_config.read_asr_api_key", lambda *_args: ("sk-fixture", "fixture"))
    import subtitle_core

    monkeypatch.setattr(subtitle_core, "USE_QWEN_ASR_REFERENCE", True)
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "api")
    regions = [{"start": 0.0, "end": 24.0}]

    # 主力（override）：24s 连续语流切成 ≤10s 的三块
    asr.transcribe_qwen_reference(
        "audio.wav", regions, shared_audio=None, backend_override="api"
    )
    assert captured["spans"] == [(0.0, 10.0), (10.0, 20.0), (20.0, 24.2)]
    assert captured['publish_primary'] is True

    # 复核（无 override，backend=api）：保持 25s 上限，整块一行
    asr.transcribe_qwen_reference("audio.wav", regions, shared_audio=None)
    assert captured["spans"] == [(0.0, 24.2)]
    assert captured['publish_primary'] is False


def test_api_not_in_incremental_primary_backends():
    """API 主力不走增量（增量层没有 VAD，整块当语音区间传入）。"""
    import moss_firered_pipeline as pipeline

    assert "api" not in pipeline.INCREMENTAL_PRIMARY_BACKENDS
    assert {"qwen_local", "sensevoice"} <= pipeline.INCREMENTAL_PRIMARY_BACKENDS


def test_completion_button_lands_in_studio_edit():
    """完成后「压制字幕视频」落工作台编辑区，不再直达导出对话框。"""
    import types

    from twobyteasr.app import ui as ui_module

    captured = {}
    fake_self = types.SimpleNamespace(
        _last_studio_project="P.2byteproj",
        open_studio_project=lambda path=None, **kwargs: captured.update(
            {"path": path, **kwargs}
        ),
    )
    ui_module.MainWindow._open_render_from_result(fake_self)
    assert captured["mode"] == "edit"
    assert captured["source"] == "completion_studio"
    assert captured["path"] == "P.2byteproj"


def test_primary_stage_label_names_provider():
    import inspect
    import moss_firered_pipeline as pipeline

    source = inspect.getsource(pipeline)
    assert "api_primary_label" in source
    assert "在线 ASR API 主力转写（" in source
