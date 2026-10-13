# -*- coding: utf-8 -*-
"""Recognition results carry no format whitespace (2026-10-12 user report).

The user's project 未命名工程 24 had "这里怎么办 " (#129) ending in a half-width
space, immediately followed by "我们还能挠三下".  Stage 9 sliced every cue
from the source by content counts and attached the inter-cue space to the left
cue.  Format junk is removed at the source and once more, deterministically,
right before the project and its delivery digest are built.  Single inner
spaces (pause spacing, English words, names) must survive.
"""
from __future__ import annotations

import os
import time
import wave
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade before text_rules
from twobyteasr.asr_provider_snapshot import (
    _BOUNDARY_INVISIBLE, restore_source_text, validate_grouped_text,
)
from twobyteasr.text_rules import FORMAT_INVISIBLE_CHARACTERS, normalize_format_whitespace


def rows(*texts, speaker="S01"):
    return [SimpleNamespace(text=text, speaker=speaker) for text in texts]


# Real grouping_trace batch 13 of the user's project (read-only copy).
BATCH13_SOURCE = "他会不会直接切到化蝶呢无所谓这里怎么办 我们还能挠三下"
BATCH13_CUES = ["他会不会直接切到化蝶呢", "无所谓", "这里怎么办 ", "我们还能挠三下"]


def test_restore_source_text_gives_the_boundary_space_to_neither_cue():
    cues = rows(*BATCH13_CUES)
    assert restore_source_text(rows(BATCH13_SOURCE), cues)
    assert [cue.text for cue in cues] == ["他会不会直接切到化蝶呢", "无所谓", "这里怎么办", "我们还能挠三下"]
    # The boundary may also be offered on the right-hand side or with
    # full-width / NBSP / zero-width junk around it.
    for junk in (" ", "\u3000", "\u00a0", "\u200b", "  \u200b "):
        cues = rows("这里怎么办", junk + "我们还能挠三下")
        assert restore_source_text(rows("这里怎么办" + junk + "我们还能挠三下"), cues)
        assert [cue.text for cue in cues] == ["这里怎么办", "我们还能挠三下"]


def test_restore_keeps_an_inner_pause_space_and_punctuation():
    cues = rows("没事", "开一把就知道了", "无所谓这里怎么办 我们还能挠三下")
    source = rows("没事 开一把就知道了，", "无所谓这里怎么办 我们还能挠三下")
    assert restore_source_text(source, cues)
    assert [cue.text for cue in cues] == ["没事", "开一把就知道了，", "无所谓这里怎么办 我们还能挠三下"]
    merged = rows("没事 开一把就知道了，")
    assert restore_source_text(rows("没事 开一把就知道了，"), merged)
    assert merged[0].text == "没事 开一把就知道了，"


def test_restore_is_idempotent():
    cues = rows(*BATCH13_CUES)
    restore_source_text(rows(BATCH13_SOURCE), cues)
    once = [cue.text for cue in cues]
    assert restore_source_text(rows(BATCH13_SOURCE), cues)
    assert [cue.text for cue in cues] == once


def test_validation_is_exact_except_for_cue_boundary_whitespace():
    source = rows(BATCH13_SOURCE)
    assert validate_grouped_text(source, rows("他会不会直接切到化蝶呢无所谓", "这里怎么办", "我们还能挠三下"))
    assert validate_grouped_text(source, rows("他会不会直接切到化蝶呢无所谓", "这里怎么办 ", "我们还能挠三下"))  # old cache
    # Inner spaces and every other character still have to match exactly.
    assert not validate_grouped_text(source, rows("他会不会直接切到化蝶呢无所谓这里怎么办我们还能挠三下"))
    assert not validate_grouped_text(source, rows("他会不会直接切到化蝶呢 无所谓这里怎么办 我们还能挠三下"))
    assert not validate_grouped_text(source, rows("他会不会直接切到化蝶呢无所谓", "这里怎么办", "我们还能挠三"))
    assert not validate_grouped_text(source, rows("他会不会直接切到化蝶呢无所谓", "我们还能挠三下", "这里怎么办"))
    assert validate_grouped_text(rows("你好，世界"), rows("你好，", "世界"))
    assert not validate_grouped_text(rows("你好，世界"), rows("你好", "世界"))


# (input, expected) — the second column is what must survive.
CASES = [
    ("这里怎么办 ", "这里怎么办"),                       # trailing half-width
    (" 我们还能挠三下", "我们还能挠三下"),                 # leading half-width
    ("\u3000对 布丁\u3000", "对 布丁"),                    # full-width edges, inner pause kept
    ("\u00a0嗯 魔偶首发的嗎\u00a0", "嗯 魔偶首发的嗎"),      # NBSP edges
    ("对的  对的", "对的 对的"),                          # doubled space collapses, pause kept
    ("对 \u3000对 很不错啊 嗯", "对 对 很不错啊 嗯"),       # mixed run collapses
    ("没事\u200b 开一把就知道了", "没事 开一把就知道了"),   # zero-width residue
    ("\ufeff有点担心 有点担心", "有点担心 有点担心"),        # BOM
    ("好 ？我们走", "好？我们走"),                        # space before full-width punctuation
    ("真的吗？ 好", "真的吗？好"),                        # space after full-width punctuation
    ("没事 开一把就知道了", "没事 开一把就知道了"),         # must keep
    ("OK let's go 走", "OK let's go 走"),                 # English word spaces
    ("Team Liquid 赢了 2:1", "Team Liquid 赢了 2:1"),       # names / number formats
    ("第一行\n 第二行 ", "第一行\n第二行"),                 # user line break kept
    ("🧑\u200d🤝\u200d🧑 好", "🧑\u200d🤝\u200d🧑 好"),       # emoji ZWJ sequence is content
]


@pytest.mark.parametrize("raw, expected", CASES)
def test_format_whitespace_examples_delete_junk_and_keep_meaning(raw, expected):
    assert normalize_format_whitespace(raw) == expected
    assert normalize_format_whitespace(expected) == expected  # idempotent


@pytest.mark.parametrize("raw, expected", CASES)
def test_studio_qc_uses_the_same_whitespace_rules(raw, expected):
    from twobyteasr.studio_qc import normalize_format_spaces
    assert normalize_format_spaces(raw) == normalize_format_whitespace(raw)


def test_invisible_character_sets_agree():
    from twobyteasr import studio_qc
    assert set(FORMAT_INVISIBLE_CHARACTERS) == set(_BOUNDARY_INVISIBLE) == set(studio_qc._FORMAT_INVISIBLE)


def test_delivery_normalization_runs_once_and_is_idempotent():
    from twobyteasr.pipeline_runtime import normalize_delivered_cue_text
    events = []
    legacy = SimpleNamespace(record_run_event=lambda name, **payload: events.append((name, payload)))
    cues = [SimpleNamespace(cue_id=1, text="这里怎么办 "), SimpleNamespace(cue_id=2, text="我们还能挠三下"),
            SimpleNamespace(cue_id=3, text="对的  对的"), SimpleNamespace(cue_id=4, text="没事 开一把就知道了")]
    changed = normalize_delivered_cue_text(cues, legacy)
    assert [cue.text for cue in cues] == ["这里怎么办", "我们还能挠三下", "对的 对的", "没事 开一把就知道了"]
    assert [row["cue_id"] for row in changed] == [1, 3]
    assert events and events[0][0] == "cue_format_whitespace_normalized" and events[0][1]["count"] == 2
    assert normalize_delivered_cue_text(cues, legacy) == []


class _RunLegacy:
    """The handful of legacy hooks complete_media_run calls."""

    def __init__(self, root):
        self.root = root
        self.events = []
        self.task_reporting = SimpleNamespace(
            report_paths_for_media=lambda path: (str(root / "report.json"), str(root / "report.txt")))

    def record_run_event(self, name, **payload):
        self.events.append((name, payload))

    @staticmethod
    def print_review_summary():
        return []

    @staticmethod
    def run_timed_stage(_index, _total, _name, _device, callback):
        return callback()

    @staticmethod
    def review_item_severity(_item):
        return "info"

    def finish_media_report(self, *_args, **kwargs):
        self.report = kwargs
        return str(self.root / "report.json"), str(self.root / "report.txt")

    @staticmethod
    def format_elapsed(seconds):
        return f"{seconds:.0f}s"


def test_saved_project_reference_reopen_and_export_agree(tmp_path, monkeypatch):
    """The delivery digest is taken after normalization: no
    "工程字幕数量或文本时间摘要与已保存结果不一致" on open/reopen."""
    import twobyteasr.studio_project as storage
    from twobyteasr.models import SubtitleCue
    from twobyteasr.pipeline_runtime import complete_media_run
    from twobyteasr.recognition_result import media_identity_for_task, verify_result_reference
    from twobyteasr.runtime import RuntimeContext
    from twobyteasr.studio_subtitle_export import compile_srt

    monkeypatch.setattr(storage, "project_library_root", lambda *a, **k: tmp_path / "Projects")
    real_create = storage.create_studio_outputs
    seen = []

    def create(media_path, cues, **kwargs):
        cues = list(cues)
        seen.extend(cue.text for cue in cues)
        kwargs["decoded_audio_seconds"] = None  # no media probe in this isolated test
        return real_create(media_path, cues, **kwargs)

    monkeypatch.setattr(storage, "create_studio_outputs", create)
    media = tmp_path / "clip.wav"
    with wave.open(str(media), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 16000 * 3)
    context = RuntimeContext(media_path=str(media), job_id="whitespace-job")
    context.media_identity = media_identity_for_task(media, context)
    cues = [SubtitleCue(1, 0.1, 0.9, "这里怎么办 ", speaker="S01"),
            SubtitleCue(2, 0.9, 1.6, "我们还能挠三下", speaker="S01"),
            SubtitleCue(3, 1.7, 2.6, "\u3000没事  开一把就知道了\u200b", speaker="S01")]
    legacy = _RunLegacy(tmp_path)
    complete_media_run(cues=cues, segments=[], file_index=1, file_total=1, started=time.perf_counter(),
                       audio_seconds=3.0, txt_path="", srt_path="", stage_index=1, stage_total=1,
                       legacy=legacy, runtime_context=context)
    expected = ["这里怎么办", "我们还能挠三下", "没事 开一把就知道了"]
    assert seen == expected
    reference = context.committed_result_ref
    project = verify_result_reference(reference)  # exact delivery digest
    assert [cue.text for cue in project.cues] == expected
    assert [cue.original_text for cue in project.cues] == expected
    reopened = storage.load_project(reference["path"])
    assert [cue.text for cue in reopened.cues] == expected
    verify_result_reference(reference, project=reopened)
    srt = compile_srt(reopened.cues)
    assert "这里怎么办\n" in srt and "这里怎么办 " not in srt and "没事 开一把就知道了" in srt
    assert any(name == "cue_format_whitespace_normalized" for name, _ in legacy.events)
