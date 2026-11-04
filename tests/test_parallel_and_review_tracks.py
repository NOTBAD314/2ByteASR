from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
import threading
import time

import moss_firered_pipeline
import subtitle_core
from twobyteasr.subtitle_rules import output as output_module
from twobyteasr.subtitle_rules import correction as correction_module
from twobyteasr.subtitle_rules import segmentation as segmentation_module


class _MossPerformanceSettings:
    MOSS_PARALLEL_WORKERS = 2
    MOSS_PARALLEL_MIN_VRAM_GB = 14


def test_old_parallel_settings_are_ignored():
    legacy = _MossPerformanceSettings()
    for count in (1, 2, 3):
        for vram in (12, 16, 100):
            assert moss_firered_pipeline._moss_parallel_worker_count(
                [{"chunk_id": i} for i in range(count)], legacy,
                total_vram_gb=vram, free_vram_gb=vram) == 1


@pytest.mark.parametrize("force", [None, 1, 2])
def test_retired_multi_request_manifest_is_rejected_before_worker_start(tmp_path, monkeypatch, force):
    monkeypatch.setattr(moss_firered_pipeline, "_run_streaming_worker",
                        lambda *a, **k: pytest.fail("independent requests were launched"))
    with pytest.raises(ValueError, match="full_context"):
        moss_firered_pipeline._run_moss_manifest_jobs(
            [{"chunk_id": 1, "offset": 0}, {"chunk_id": 2, "offset": 160}],
            str(tmp_path), {}, _MossPerformanceSettings(), "test", force_workers=force)


def test_review_capture_is_thread_local():
    subtitle_core.reset_review_items()

    def worker(label):
        with subtitle_core.capture_review_items() as items:
            subtitle_core.add_review_item(1.0, label, "detail", label)
            time.sleep(0.01)
        return list(items)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(worker, ("A", "B"))
    assert [item["category"] for item in first] == ["A"]
    assert [item["category"] for item in second] == ["B"]
    assert subtitle_core.RUN_REVIEW_ITEMS == []


def test_group_batches_run_in_parallel(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_group(batch, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        segment = batch[0]
        return [
            subtitle_core.SubtitleCue(
                1, segment.start, segment.end, segment.text, speaker=segment.speaker
            )
        ]

    monkeypatch.setattr(segmentation_module, "call_grouping_api", fake_group)
    monkeypatch.setattr(segmentation_module, "PARALLEL_CLOUD_BATCHES", True)
    monkeypatch.setattr(segmentation_module, "CLOUD_BATCH_WORKERS", 2)
    segments = [
        subtitle_core.SpeechSegment(1, 0.0, 1.0, "第一句", 0.9, [], speaker="S01"),
        subtitle_core.SpeechSegment(2, 1.1, 2.0, "第二句", 0.9, [], speaker="S02"),
    ]
    cues = segmentation_module.group_subtitles(segments)
    assert peak == 2
    assert {cue.speaker for cue in cues} == {"S01", "S02"}


def test_local_grouping_mode_never_calls_cloud_api(monkeypatch):
    calls = []

    def forbidden_cloud_call(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("local grouping must not call the cloud API")

    monkeypatch.setattr(segmentation_module, "call_grouping_api", forbidden_cloud_call)
    segments = [
        subtitle_core.SpeechSegment(
            1, 0.0, 1.2, "这是本地断句", 0.9, [], speaker="S01"
        ),
        subtitle_core.SpeechSegment(
            2, 1.3, 2.4, "不需要云端模型", 0.9, [], speaker="S01"
        ),
    ]

    cues = segmentation_module.group_subtitles(segments, use_ai=False)

    assert calls == []
    assert subtitle_core.content_exact("".join(cue.text for cue in cues)) == subtitle_core.content_exact(
        "".join(segment.text for segment in segments)
    )


def test_polish_batch_size_reduces_requests_for_typical_short_media():
    segments = [
        subtitle_core.SpeechSegment(
            index,
            float(index),
            float(index) + 0.5,
            f"第{index}句内容",
            0.9,
            [],
            speaker="S01",
        )
        for index in range(1, 33)
    ]
    polish_batches = correction_module.split_items_for_api(
        segments,
        max_cues=subtitle_core.POLISH_BATCH_MAX_CUES,
    )
    grouping_batches = correction_module.split_items_for_api(segments)

    assert [len(batch) for batch in polish_batches] == [16, 16]
    assert [len(batch) for batch in grouping_batches] == [20, 12]


def test_review_track_is_written_inside_project(tmp_path, monkeypatch):
    project_root = tmp_path / "2ByteASR"
    project_root.mkdir()
    monkeypatch.setattr(output_module, "SCRIPT_DIR", str(project_root))
    subtitle_core.reset_review_items()
    subtitle_core.add_review_item(
        2.0,
        "Qwen骨架缺口",
        "Qwen supports excluded program speech",
        "节目对白",
        priority=2,
    )
    cues = [subtitle_core.SubtitleCue(1, 0.0, 1.0, "主播正文", speaker="S01")]
    result = output_module.write_all_outputs_transactional(
        cues,
        str(tmp_path / "sample_剪映文稿.txt"),
        str(tmp_path / "sample_剪映文稿.srt"),
        include_review_track=True,
    )
    review_path = Path(result["review_path"])
    assert review_path.parent == project_root / "review_tracks"
    assert review_path.is_file()
    assert "Qwen骨架缺口" in review_path.read_text(encoding="utf-8-sig")


def test_combined_srt_is_single_lane_but_speaker_tracks_keep_overlap(tmp_path):
    cues = [
        subtitle_core.SubtitleCue(1, 0.0, 2.0, "主播一", speaker="S01"),
        subtitle_core.SubtitleCue(2, 1.8, 3.0, "主播二", speaker="S02"),
    ]
    single_lane = output_module.build_single_lane_cues(cues)
    assert single_lane[0].end == single_lane[1].start == 1.8
    assert cues[0].end == 2.0

    out_srt = tmp_path / "sample_剪映文稿.srt"
    output_module.write_all_outputs_transactional(
        cues,
        str(tmp_path / "sample_剪映文稿.txt"),
        str(out_srt),
    )
    total = out_srt.read_text(encoding="utf-8-sig")
    first_track = (tmp_path / "sample_剪映文稿_主播1_S01.srt").read_text(
        encoding="utf-8-sig"
    )
    assert "00:00:00,000 --> 00:00:01,800" in total
    assert "00:00:00,000 --> 00:00:02,000" in first_track


def test_timeline_disabled_writes_txt_only(tmp_path):
    cues = [subtitle_core.SubtitleCue(1, 0.0, 1.0, "只要文字", speaker="S01")]
    txt_path = tmp_path / "txt-only.txt"
    srt_path = tmp_path / "txt-only.srt"
    result = output_module.write_all_outputs_transactional(
        cues,
        str(txt_path),
        str(srt_path),
        include_review_track=True,
        include_srt=False,
    )
    assert txt_path.is_file()
    assert "只要文字" in txt_path.read_text(encoding="utf-8")
    assert not srt_path.exists()
    assert result["speaker_outputs"] == []
    assert result["review_path"] == ""


def test_output_writes_every_detected_speaker_track(tmp_path):
    cues = [
        subtitle_core.SubtitleCue(1, 0.0, 1.0, "主播一", speaker="S01"),
        subtitle_core.SubtitleCue(2, 1.0, 2.0, "主播二", speaker="S02"),
        subtitle_core.SubtitleCue(3, 2.0, 3.0, "主播三", speaker="S03"),
    ]
    result = output_module.write_all_outputs_transactional(
        cues,
        str(tmp_path / "three_剪映文稿.txt"),
        str(tmp_path / "three_剪映文稿.srt"),
    )

    assert [speaker for speaker, _, _ in result["speaker_outputs"]] == [
        "S01",
        "S02",
        "S03",
    ]
    assert (tmp_path / "three_剪映文稿_主播3_S03.srt").is_file()


def test_output_sanitizes_speaker_label_in_filename(tmp_path):
    cues = [
        subtitle_core.SubtitleCue(
            1, 0.0, 1.0, "safe text", speaker="../../host:*?"
        )
    ]
    result = output_module.write_all_outputs_transactional(
        cues,
        str(tmp_path / "safe.txt"),
        str(tmp_path / "safe.srt"),
    )
    _, output_path, _ = result["speaker_outputs"][0]
    assert Path(output_path).parent == tmp_path
    assert Path(output_path).is_file()
    assert ".." not in Path(output_path).name



def test_qwen_supported_non_host_segment_becomes_review_item():
    subtitle_core.reset_review_items()
    hosts = [
        subtitle_core.SpeechSegment(
            1, 0.0, 1.0, "主播说话", 0.9, [], speaker="S01"
        )
    ]
    moss_payload = {
        "host_speakers": ["S01"],
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "主播说话", "speaker": "S01"},
            {"start": 2.0, "end": 3.2, "text": "女皇的后裔", "speaker": "S05"},
        ],
    }
    qwen_chunks = [{"start": 1.8, "end": 3.4, "text": "所有人都是女皇的后裔"}]
    count = moss_firered_pipeline.add_qwen_skeleton_gap_review_items(
        hosts, qwen_chunks, moss_payload, subtitle_core
    )
    assert count == 1
    assert subtitle_core.RUN_REVIEW_ITEMS[-1]["category"] == "Qwen骨架缺口"
    assert "S05" in subtitle_core.RUN_REVIEW_ITEMS[-1]["detail"]
