"""Ranges MOSI's content review stopped, filled by a local model (2026-10-24)."""
from __future__ import annotations

import numpy as np
import pytest

from twobyteasr.recognition import cloud_gap_fill
from twobyteasr.recognition.recognition_choices import HostProfile

NVIDIA = HostProfile("win32", "amd64", nvidia_tool=True, main_runtime=True, mlx_runtime=False, moss_runtime=True)
CPU_ONLY = HostProfile("win32", "amd64", nvidia_tool=False, main_runtime=True, mlx_runtime=False, moss_runtime=False)
MOSS = {"moss", "firered_vad", "speaker_embedding"}


@pytest.mark.parametrize("language, installed, host, expected", [
    ("en", MOSS | {"qwen_asr", "sensevoice"}, NVIDIA, "moss"),
    ("en", MOSS | {"qwen_asr"}, HostProfile("win32", "amd64", True, True, False, moss_runtime=False), "qwen_local"),
    # No NVIDIA: MOSS, Qwen3-ASR and FireRed are out; SenseVoice handles English.
    ("en", MOSS | {"qwen_asr", "firered_aed", "sensevoice"}, CPU_ONLY, "sensevoice"),
    ("ja", {"paraformer"}, CPU_ONLY, None),                      # Paraformer: no Japanese
    ("es", {"sensevoice"}, CPU_ONLY, None),                      # only broad multilingual models
    ("es", {"sensevoice", "whisper_turbo"}, CPU_ONLY, "whisper_turbo"),
    ("", {"paraformer"}, CPU_ONLY, "paraformer"),                # unknown: Chinese and English will do
    ("zh", set(), NVIDIA, None),
    ("zh", {"sensevoice"}, HostProfile("win32", "amd64", False, False, False), None),   # no model runtime
])
def test_the_fill_model_is_installed_runnable_here_and_speaks_the_language(language, installed, host, expected):
    chosen = cloud_gap_fill.choose_backend(language, installed=installed, host=host)
    assert (chosen[0] if chosen else None) == expected


def test_touching_gaps_are_one_range():
    gaps = [dict(start=10.0, end=12.5), dict(start=2.0, end=4.0), dict(start=12.5, end=13.0)]
    assert cloud_gap_fill.merged_ranges(gaps) == [(2.0, 4.0), (10.0, 13.0)]


class Legacy:
    AUDIO_SAMPLE_RATE = 16000

    def __init__(self, rows=(), error=None):
        self.events, self.review, self.stages, self.calls = [], [], [], []
        self.rows, self.error = list(rows), error

    def run_timed_stage(self, index, total, label, resource, runner):
        self.stages.append((label, resource))
        return runner()

    def run_cached_stage(self, name, context, runner, should_cache=bool, extra_signature=None):
        self.stages.append((name, extra_signature))
        return runner()

    def record_run_event(self, kind, **payload):
        self.events.append(dict(payload, event=kind))

    def add_review_item(self, start, category, detail, priority=1, severity=None):
        self.review.append((start, category, severity))

    def transcribe_primary_reference(self, backend, media, regions, audio, seconds):
        self.calls.append((backend, [(r["start"], r["end"]) for r in regions]))
        if self.error:
            raise self.error
        return [dict(row) for row in self.rows]


def payload(*texts):
    rows = [dict(start=float(i * 4), end=float(i * 4 + 2), text=text, speaker="R001_S01") for i, text in enumerate(texts)]
    gap = dict(start=2.0, end=4.0, segment=[2, 3], task_id="t-2", resplittable=True,
               detail="第 2 / 3 段（0:02–0:04）的 MOSI 任务（任务编号 t-2）被 MOSI 的内容安全审查拦下，没有返回这一段的字幕（MOSI 返回的原因：x）。")
    return dict(segments=[dict(r) for r in rows], references=[dict(r) for r in rows], cloud_gaps=[gap])


def fill(legacy, data, *, chosen, requested="auto", regions=((0.5, 1.5), (2.5, 3.5), (4.5, 5.5)), moss=None,
         monkeypatch=None, seen=None):
    def choose(language):
        if seen is not None:
            seen.append(language)
        return chosen
    monkeypatch.setattr(cloud_gap_fill, "choose_backend", choose)
    cloud_gap_fill.fill_cloud_gaps(legacy, data, media_path="a.mp4", shared_audio=np.zeros(8 * 16000, np.float32),
                                   speech_regions=[dict(start=a, end=b) for a, b in regions], audio_seconds=8.0,
                                   cache_context={}, requested_language=requested, stage_total=11,
                                   moss_runner=moss)


def test_a_gap_is_recognized_in_its_speech_regions_and_merged_in_order(monkeypatch):
    legacy, data, seen = Legacy(rows=[dict(start=2.6, end=3.4, text="filled in", speaker="0")]), payload("so we went into the vent and the animatronic jumped at me", "the cops were called because I screamed so loud"), []
    fill(legacy, data, chosen=("sensevoice", "SenseVoice Small"), monkeypatch=monkeypatch, seen=seen)
    assert seen == ["en"]                                       # judged from the other segments' text
    assert legacy.calls == [("sensevoice", [(2.5, 3.5)])]
    assert [row["text"] for row in data["segments"]] == ["so we went into the vent and the animatronic jumped at me", "filled in", "the cops were called because I screamed so loud"]
    filled = data["references"][1]
    assert filled["source"] == "sensevoice-gapfill" and filled["speaker"] == "LOCAL_0"
    event = legacy.events[-1]
    assert event["event"] == "cloud_asr_gap_fill" and event["filled"] and event["rows"] == 1
    assert event["model"] == "SenseVoice Small" and event["ranges"] == [[2.0, 4.0]] and event["resplittable"]
    assert legacy.review == [(2.0, "这一段由本地模型补识别", "review")]
    assert legacy.stages[0] == (cloud_gap_fill.STAGE_LABEL, "SenseVoice Small")


def test_local_moss_recognizes_the_gap_audio_itself(monkeypatch):
    got = []

    def moss(audio):
        got.append(len(audio))
        return {"segments": [dict(start=0.1, end=0.9, text="moss text", speaker="S01")]}
    legacy, data = Legacy(), payload("so we went into the vent and the animatronic jumped at me", "the cops were called because I screamed so loud")
    fill(legacy, data, chosen=("moss", "MOSS-Transcribe-Diarize"), moss=moss, monkeypatch=monkeypatch)
    assert got == [2 * 16000] and not legacy.calls
    row = data["segments"][1]
    assert (row["start"], row["end"], row["speaker"]) == (2.1, 2.9, "LOCAL_S01")


def test_without_a_local_model_the_task_finishes_with_the_gap(monkeypatch):
    legacy, data = Legacy(), payload("so we went into the vent and the animatronic jumped at me", "the cops were called because I screamed so loud")
    fill(legacy, data, chosen=None, monkeypatch=monkeypatch)
    assert len(data["segments"]) == 2
    assert legacy.events[-1]["reason"] == "no_local_model" and not legacy.events[-1]["filled"]
    assert legacy.review == [(2.0, "这一段没有字幕", "warning")]


def test_a_failing_local_model_leaves_the_gap_and_keeps_the_task(monkeypatch):
    legacy, data = Legacy(error=RuntimeError("CUDA out of memory")), payload("so we went into the vent and the animatronic jumped at me", "the cops were called because I screamed so loud")
    fill(legacy, data, chosen=("qwen_local", "Qwen3-ASR 1.7B"), monkeypatch=monkeypatch)
    event = legacy.events[-1]
    assert event["reason"] == "fill_failed" and "CUDA out of memory" in event["error"] and len(data["segments"]) == 2


def test_a_task_with_no_text_at_all_stops_and_says_why(monkeypatch):
    legacy, data = Legacy(), payload()
    with pytest.raises(RuntimeError) as failure:
        fill(legacy, data, chosen=None, monkeypatch=monkeypatch)
    text = str(failure.value)
    assert "内容安全审查" in text and "第 2 / 3 段" in text and "没有能补识别这段语言" in text
    assert legacy.events[-1]["event"] == "cloud_asr_gap_fill"     # recorded before stopping
