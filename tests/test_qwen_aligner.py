from types import SimpleNamespace

import numpy as np
import pytest

from twobyteasr.recognition.asr import (
    _funasr_generate,
    align_qwen_transcript_segments,
    funasr_timestamp_tokens,
    reference_chunks_to_timeline_tokens,
)
from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings


def test_whisper_chunks_can_supply_a_conservative_subtitle_timeline():
    tokens = reference_chunks_to_timeline_tokens(
        [{"start": 1.0, "end": 3.0, "text": "你好 world"}],
        source="whisper-timeline",
    )
    assert "".join(item["text"] for item in tokens) == "你好world"
    assert tokens[0]["start"] == pytest.approx(1.0)
    assert tokens[-1]["end"] == pytest.approx(3.0)
    assert all(item["source"] == "whisper-timeline" for item in tokens)


class FakeAligner:
    def __init__(self):
        self.calls = []

    def align(self, *, audio, text, language):
        self.calls.append((audio, text, language))
        return [
            [
                SimpleNamespace(text=value[0], start_time=0.10, end_time=0.30),
                SimpleNamespace(text=value[-1], start_time=0.32, end_time=0.55),
            ]
            for value in text
        ]


def test_qwen_aligner_tokens_keep_each_moss_segment_offset():
    aligner = FakeAligner()
    audio = np.zeros(5 * 16000, dtype=np.float32)
    tokens = align_qwen_transcript_segments(
        aligner,
        audio,
        [
            {"start": 1.0, "end": 2.0, "text": "你好"},
            {"start": 3.0, "end": 4.0, "text": "世界"},
        ],
        batch_size=2,
    )

    assert [item["text"] for item in tokens] == ["你", "好", "世", "界"]
    assert [item["start"] for item in tokens] == [1.1, 1.32, 3.1, 3.32]
    assert all(item["source"] == "qwen-forced-aligner" for item in tokens)
    assert aligner.calls[0][2] == ["Chinese", "Chinese"]


def test_runtime_settings_accept_qwen_aligner_timeline_backend():
    payload = {
        "models": {
            "firered_asr_backend": "qwen_aligner",
            "qwen_asr_backend": "whisper_turbo",
        }
    }
    settings, warnings = _merge_known_settings(DEFAULT_SETTINGS, payload)
    assert settings["models"]["firered_asr_backend"] == "qwen_aligner"
    assert settings["models"]["qwen_asr_backend"] == "whisper_turbo"
    assert not [item for item in warnings if "firered_asr_backend" in item]


def test_funasr_timestamps_are_normalized_from_milliseconds():
    tokens = funasr_timestamp_tokens(
        {
            "text": "你好世界",
            "timestamp": [[0, 180], [180, 360], [360, 540], [540, 760]],
        },
        base_start=2.5,
        source="paraformer",
    )
    assert [item["text"] for item in tokens] == list("你好世界")
    assert tokens[0]["start"] == 2.5
    assert tokens[-1]["end"] == 3.26
    assert all(item["source"] == "paraformer" for item in tokens)


def test_funasr_serialized_timestamps_are_accepted():
    tokens = funasr_timestamp_tokens(
        {"text": "\u4f60\u597d", "timestamp": "[[0, 120], [120, 300]]"},
        source="paraformer",
    )
    assert [item["text"] for item in tokens] == ["\u4f60", "\u597d"]
    assert tokens[-1]["end"] == pytest.approx(0.3)


def test_paraformer_explicitly_requests_timestamp_prediction():
    class FakeModel:
        def __init__(self):
            self.options = None

        def generate(self, **options):
            self.options = options
            return []

    model = FakeModel()
    _funasr_generate(model, "sample.wav", "paraformer")
    assert model.options["pred_timestamp"] is True


def test_runtime_settings_accept_funasr_role_backends():
    settings, warnings = _merge_known_settings(
        DEFAULT_SETTINGS,
        {
            "models": {
                "firered_asr_backend": "paraformer",
                "qwen_asr_backend": "sensevoice",
            }
        },
    )
    assert settings["models"]["firered_asr_backend"] == "paraformer"
    assert settings["models"]["qwen_asr_backend"] == "sensevoice"
    assert not [item for item in warnings if "asr_backend" in item]
