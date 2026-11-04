"""Incremental ASR chunks share 0.5 s of audio; their rows must not interleave.

2026-10-21 user report: a 24 min Japanese episode (SenseVoice primary, no word
timestamps) failed local grouping in 0.8.0/0.8.1 with "Stage 9后处理违反原文逐字符
守恒". The last line of one chunk started after the first line of the next, the
final time sort swapped them, and the conservation check stopped the task.
"""
import json
from pathlib import Path

import pytest

import subtitle_core  # noqa: F401  (legacy core first: segmentation star-imports it)

from twobyteasr.recognition.incremental_asr import split_chunk_overlaps


DATA = Path(__file__).parent / "data" / "sensevoice_ja_chunk_overlap_20261021.json"


def test_rows_of_adjacent_chunks_meet_in_the_middle_of_the_overlap():
    rows = [
        {"start_ms": 0, "end_ms": 25_000, "text": "一", "chunk_index": 0},
        {"start_ms": 25_000, "end_ms": 45_000, "text": "二", "chunk_index": 0},
        {"start_ms": 44_500, "end_ms": 69_500, "text": "三", "chunk_index": 1},
        {"start_ms": 69_500, "end_ms": 89_500, "text": "四", "chunk_index": 1},
    ]

    split, seams = split_chunk_overlaps(rows)

    assert seams == 1
    assert [(row["start_ms"], row["end_ms"]) for row in split] == [
        (0, 25_000), (25_000, 44_750), (44_750, 69_500), (69_500, 89_500)]
    assert [row["text"] for row in split] == ["一", "二", "三", "四"]
    assert rows[1]["end_ms"] == 45_000  # the cached manifest rows stay as recognized


def test_a_short_last_row_keeps_its_time_and_order():
    rows = [
        {"start_ms": 44_800, "end_ms": 44_900, "text": "え"},
        {"start_ms": 44_500, "end_ms": 60_000, "text": "なに"},
    ]

    split, seams = split_chunk_overlaps(rows)

    assert seams == 1
    assert [(row["start_ms"], row["end_ms"]) for row in split] == [(44_800, 44_820), (44_820, 60_000)]


def test_whole_file_rows_in_seconds_meet_in_the_middle_too():
    """2026-10-23 user log: whole-file SenseVoice rows overlapped 0.13 s at 46.92 s."""
    rows = [
        {"start": 23.87, "end": 47.05, "text": "一", "source": "sensevoice"},
        {"start": 46.92, "end": 62.24, "text": "二", "source": "sensevoice"},
        {"start": 73.12, "end": 97.85, "text": "三", "source": "sensevoice"},
    ]

    split, seams = split_chunk_overlaps(rows, keys=("start", "end"), margin=0.02)

    assert seams == 1
    assert split[0]["end"] == split[1]["start"] == pytest.approx(46.985)
    assert (split[0]["start"], split[1]["end"], split[2]["start"], split[2]["end"]) == (23.87, 62.24, 73.12, 97.85)
    assert [row["text"] for row in split] == ["一", "二", "三"]
    assert rows[0]["end"] == 47.05


class _StopAfterPrimary(BaseException):
    pass


def test_sensevoice_fallback_to_whole_file_splits_the_cached_rows(monkeypatch, tmp_path):
    """2026-10-23 user log: incremental recognition returned no text, the task fell back to
    whole-file SenseVoice (a cache hit) and two padded chunks overlapped 0.13 s."""
    from contextlib import nullcontext
    from types import SimpleNamespace

    import numpy as np

    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition import incremental_asr, speaker_strategy
    from twobyteasr.recognition.run_context import RuntimeContext

    (tmp_path / "source.mp4").write_bytes(b"test transport fixture")
    cached = [
        {"start": 23.87, "end": 47.05, "text": "然后我们看一下", "source": "sensevoice"},
        {"start": 46.92, "end": 62.24, "text": "这个怪有点难打", "source": "sensevoice"},
    ]
    events = []

    class NoParsedText:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("sensevoice worker returned no parsed text")

    def stop(*args, **kwargs):
        raise _StopAfterPrimary()

    legacy = SimpleNamespace(
        RUNTIME_SETTINGS={}, PRIMARY_ASR_BACKEND="sensevoice", FIRERED_ASR_BACKEND="off",
        PARALLEL_GPU_ASR=True, PARALLEL_CPU_VAD=False, USE_FIRERED_BOUNDARY_REFINEMENT=False,
        AUDIO_SAMPLE_RATE=16000, reset_review_items=lambda: None,
        output_paths_for_media=lambda p: ("unused.txt", "unused.srt"), detect_timeline_fps=lambda p: 24,
        media_cache_context=lambda p: {"cache_dir": str(tmp_path)}, begin_media_report=lambda *a: None,
        run_timed_stage=lambda n, total, label, resource, run: run(),
        run_cached_stage=lambda name, cache, run, **kw: cached,
        load_shared_audio=lambda *a: np.zeros(16000, dtype=np.float32),
        record_run_event=lambda name, **data: events.append((name, data)),
        capture_review_items=lambda: nullcontext([]), extend_review_items=lambda rows: None,
        transcribe_primary_reference=lambda *a: cached,
        transcribe_firered_reference=lambda *a: [],
    )
    monkeypatch.setattr(incremental_asr, "IncrementalASRPipeline", NoParsedText)
    monkeypatch.setattr(pipeline, "_script_paths", lambda _: {
        "firered_vad": str(tmp_path / "missing"), "firered_worker": "", "main_python": "", "firered_source": ""})
    monkeypatch.setattr(pipeline, "_moss_stage_signature", lambda _: {})
    monkeypatch.setattr(pipeline, "_cloud_hint_signature", lambda *a: {})
    monkeypatch.setattr(pipeline, "_gpu_runtime_snapshot", lambda: {})
    monkeypatch.setattr(pipeline, "detect_lightweight_vad", lambda *a: [dict(start=23.9, end=62.0)])
    monkeypatch.setattr(pipeline, "_run_audited_model_stage", lambda *a, runner, **kw: runner())
    monkeypatch.setattr(speaker_strategy, "resolve", stop)

    with pytest.raises(_StopAfterPrimary):
        pipeline.process_media(str(tmp_path / "source.mp4"), 1, 1, legacy, RuntimeContext(requested_language="zh"))

    names = [name for name, _ in events]
    assert "incremental_asr_fallback" in names
    assert ("primary_chunk_overlap_split", {"backend": "sensevoice", "seams": 1}) in events
    assert cached[0]["end"] == 47.05  # the cache keeps the rows as recognized


def _group_user_report_rows(monkeypatch, rows, tagged):
    from twobyteasr.recognition import cache, optional_timing
    from twobyteasr.recognition.run_context import get_runtime_context
    from twobyteasr.recognition.transcript_data import SpeechSegment
    from twobyteasr.subtitle_rules import japanese_morphology as jm

    events = []
    monkeypatch.setattr(cache, "record_run_event", lambda event, **payload: events.append(event))
    context = get_runtime_context()
    monkeypatch.setattr(context, "task_language", "ja")
    monkeypatch.setattr(context, "japanese_phrases", None)
    # The same steps the pipeline runs for row-bounds-only primaries.
    segments = subtitle_core.apply_editorial_segment_rules([
        SpeechSegment(index, row["start_ms"] / 1000, row["end_ms"] / 1000, row["text"], 1.0, [],
                      speaker=row["speaker_id"])
        for index, row in enumerate(rows, 1)
    ])
    for segment in segments:
        segment.words = subtitle_core.segment_content_timeline(segment, ())
    document = jm.build_document([segment.text for segment in segments], tagged)
    assert document.measured_segments == len(segments)
    jm.install(document)
    cues = optional_timing.grouping(segments, [], subtitle_core, speech_regions=[],
                                    protect_all_source_boundaries=False, cache_context=None, use_ai=False)
    return segments, cues, events


def test_user_report_episode_groups_in_source_order_after_the_overlap_split(monkeypatch):
    if not DATA.is_file():
        pytest.skip("private user-report data (tests/data is not part of the public source)")
    from twobyteasr.subtitle_rules.text_rules import content_only

    report = json.loads(DATA.read_text(encoding="utf-8"))
    rows, seams = split_chunk_overlaps(report["rows"])
    assert seams == 30  # 33 chunks; two returned rows that end before the next chunk

    segments, cues, events = _group_user_report_rows(monkeypatch, rows, report["nagisa"])

    assert "grouping_postprocess_rejected" not in events
    assert "grouping_local_source_boundary_fallback" not in events
    assert content_only("".join(cue.text for cue in cues)) == content_only("".join(s.text for s in segments))
    # Before the split the fallback kept all 63 recognizer rows of 20-25 s each.
    assert len(cues) > 4 * len(segments)
    assert max(cue.end - cue.start for cue in cues) < 20.0
