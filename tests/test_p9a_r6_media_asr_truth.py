"""Focused P9A-R6 contracts for media time and multi-ASR truth."""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.timeline.media_time import MediaTimeMapping
from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.playback.studio_mpv import mpv_startup_arguments
from twobyteasr.studio.studio_ui import MpvCanvas
from twobyteasr.playback.waveform_cache import WaveformCache


def test_media_time_mapping_keeps_project_source_and_stream_domains_distinct():
    mapping = MediaTimeMapping(
        container_start_ms=21.0,
        source_start_ms=21.0,
        video_start_ms=998.0,
        audio_start_ms=21.0,
        sample_rate=48_000,
        sample_timeline_origin_ms=21.0,
    )
    seek = mapping.describe_seek(180_000.0)
    assert seek["project_time_ms"] == 180_000.0
    assert seek["source_media_time_ms"] == 180_000.0
    assert seek["video_stream_pts_ms"] == 180_998.0
    assert seek["audio_stream_pts_ms"] == 180_021.0
    assert mapping.source_to_sample_index(21.0) == 0
    assert mapping.source_to_sample_index(1_021.0) == 48_000


def test_ffprobe_stream_start_time_is_not_scaled_by_timebase(tmp_path):
    import json
    from types import SimpleNamespace

    from twobyteasr.media.media_service import MediaService

    media = tmp_path / "fixture.flv"
    media.write_bytes(b"fixture")
    payload = {
        "format": {"duration": "12.0", "start_time": "0.021", "size": "7"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 360,
                "time_base": "1/1000",
                "start_time": "0.998",
                "start_pts": 998,
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "time_base": "1/1000",
                "start_time": "0.021",
                "start_pts": 21,
            },
        ],
    }

    service = MediaService(probe_runner=lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps(payload), stderr=""
    ))
    snapshot = service.metadata(media, refresh=True)
    assert snapshot.video_start_ms == pytest.approx(998.0)
    assert snapshot.audio_start_ms == pytest.approx(21.0)


def test_waveform_read_uses_nonzero_sample_timeline_origin(tmp_path):
    root = tmp_path / "waveform"
    root.mkdir()
    frames = 4
    level = {"level": 0, "frames": frames, "milliseconds_per_frame": 100.0, "file": "lod0.f32"}
    payload = {
        "schema_version": 1,
        "source_path": "fixture.flv",
        "source_size": 1,
        "source_mtime_ns": 1,
        "sample_rate": 48_000,
        "window_samples": 4_800,
        "duration_ms": 400,
        "source_start_ms": 21.0,
        "stream_start_ms": 21.0,
        "sample_timeline_origin_ms": 21.0,
        "levels": [level],
    }
    (root / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    import numpy as np

    np.asarray([[i, i] for i in range(frames)], dtype=np.float32).tofile(root / "lod0.f32")
    _level, window = WaveformCache(root).read_window(121, 321, 100)
    assert window[:, 0].tolist() == [1.0, 2.0]


def test_seek_trace_contains_all_time_domains():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    canvas = MpvCanvas()
    canvas.set_media_time_mapping(
        {
            "container_start_ms": 21.0,
            "source_start_ms": 21.0,
            "video_start_ms": 998.0,
            "audio_start_ms": 21.0,
        },
        has_video=True,
    )
    canvas.begin_seek_trace(60.0, source="test")
    trace = canvas.seek_latency_traces()[-1]
    assert trace["project_time_ms"] == 60_000.0
    assert trace["source_media_time_ms"] == 60_000.0
    assert trace["video_stream_pts_ms"] == 60_998.0
    assert trace["audio_stream_pts_ms"] == 60_021.0
    assert set(("project_time_ms", "source_media_time_ms", "video_stream_pts_ms", "audio_stream_pts_ms")) <= set(trace["time_mapping"])
    canvas.deleteLater()


def test_primary_mpv_startup_never_opens_audio_device():
    args = mpv_startup_arguments("mpv.exe", 123, r"\\.\pipe\fixture")
    assert "--aid=no" in args
    assert "--aid=auto" not in args
    assert "--video-sync=audio" in args


def test_audio_engine_has_no_continuous_clock_timer():
    from twobyteasr.playback import audio_engine

    source = inspect.getsource(audio_engine.StudioAudioEngine)
    assert "QTimer" not in source
    assert '"clock_timer_alive": False' in inspect.getsource(audio_engine._AudioEngineWorker._emit)


def test_audited_model_stage_emits_explicit_six_state_contract(tmp_path):
    import moss_firered_pipeline as pipeline

    events = []
    legacy = SimpleNamespace(record_run_event=lambda event, **payload: events.append((event, payload)))
    worker = tmp_path / "worker.py"
    runtime = tmp_path / "python.exe"
    worker.write_text("", encoding="utf-8")
    runtime.write_text("", encoding="utf-8")
    assert pipeline._run_audited_model_stage(
        legacy,
        model_id="fixture",
        role="text_verification",
        backend="local",
        media_path="fixture.wav",
        worker=str(worker),
        runtime=str(runtime),
        runner=lambda: [{"text": "ok"}],
    )
    pipeline._run_audited_model_stage(
        legacy,
        model_id="skipped",
        role="timeline_alignment",
        backend="off",
        media_path="fixture.wav",
        worker="",
        runtime="",
        runner=lambda: [],
        selected=False,
        skip_reason="disabled",
    )
    assert [event for event, _payload in events] == [
        "MODEL_SELECTED",
        "MODEL_ENVIRONMENT_READY",
        "MODEL_STAGE_ENTERED",
        "MODEL_RESULT_SCHEMA",
        "MODEL_COMPLETED",
        "MODEL_SKIPPED",
    ]
    assert events[1][1]["environment_ready"] is True
    assert events[4][1]["segment_count"] == 1


def test_audited_model_stage_marks_missing_environment_failed(tmp_path):
    import moss_firered_pipeline as pipeline

    events = []
    legacy = SimpleNamespace(record_run_event=lambda event, **payload: events.append((event, payload)))
    result = pipeline._run_audited_model_stage(
        legacy,
        model_id="qwen3-asr",
        role="text_verification",
        backend="local",
        media_path="fixture.wav",
        worker=str(tmp_path / "missing-worker"),
        runtime=str(tmp_path / "missing-runtime"),
        runner=lambda: [{"text": "must not run"}],
        allow_failure=True,
    )
    assert result == []
    assert [event for event, _payload in events] == [
        "MODEL_SELECTED",
        "MODEL_ENVIRONMENT_READY",
        "MODEL_FAILED",
    ]
    assert "environment_missing" in events[-1][1]["failure_reason"]


def test_audited_model_stage_emits_one_failure_for_empty_result(tmp_path):
    import moss_firered_pipeline as pipeline

    events = []
    legacy = SimpleNamespace(record_run_event=lambda event, **payload: events.append((event, payload)))
    worker = tmp_path / "worker.py"
    runtime = tmp_path / "python.exe"
    worker.write_text("", encoding="utf-8")
    runtime.write_text("", encoding="utf-8")
    assert pipeline._run_audited_model_stage(
        legacy,
        model_id="firered",
        role="timeline_alignment",
        backend="local",
        media_path="fixture.wav",
        worker=str(worker),
        runtime=str(runtime),
        runner=lambda: [],
        allow_failure=True,
    ) == []
    assert [event for event, _payload in events] == [
        "MODEL_SELECTED",
        "MODEL_ENVIRONMENT_READY",
        "MODEL_STAGE_ENTERED",
        "MODEL_RESULT_SCHEMA",
        "MODEL_FAILED",
    ]
    assert events[-1][1]["failure_reason"] == "empty_result"


def test_runtime_fingerprint_reports_p9a_r6_symbols():
    from twobyteasr.diagnostics.build_identity import runtime_fingerprint_payload

    features = runtime_fingerprint_payload()["features"]
    assert features["P9A_R6_CANONICAL_MEDIA_TIME_PRESENT"] is True
    assert features["P9A_R6_MPV_PRIMARY_AUDIO_PRESENT"] is False
    assert features["STUDIO_SINGLE_AUDIO_SESSION_PRESENT"] is True
    assert features["P9A_R6_WAVEFORM_ORIGIN_PRESENT"] is True
    assert features["P9A_R6_MODEL_AUDIT_PRESENT"] is True


def test_firered_and_qwen_provenance_are_not_replaced_by_consensus(monkeypatch):
    import moss_firered_pipeline as pipeline

    monkeypatch.setattr(pipeline, "select_host_speakers", lambda *_args, **_kwargs: ["S00"])
    monkeypatch.setattr(pipeline, "apply_registered_host_voiceprints", lambda segments, hosts, *_args, **_kwargs: (hosts, segments))
    monkeypatch.setattr(pipeline, "_rescue_transient_host_segments", lambda *_args, **_kwargs: None)

    class Legacy:
        SpeechSegment = SpeechSegment
        WordUnit = WordUnit
        MIN_SUBTITLE_SECONDS = 0.8
        ASR_CONSENSUS_MIN_SIMILARITY = 0.72
        QWEN_ASR_TEXT_ALIGNMENT_PAD_SECONDS = 0.3
        QWEN_ASR_ALTERNATE_MIN_SIMILARITY = 0.4
        USE_QWEN_ASR_REFERENCE = True

        @staticmethod
        def clean_subtitle_text(value):
            return str(value or "")

        @staticmethod
        def content_only(value):
            return str(value or "").strip()

        @staticmethod
        def best_alternate_window(_primary, candidate):
            return str(candidate or ""), 0.9 if candidate else 0.0

        @staticmethod
        def asr_consensus_similarity(_left, _right):
            return 0.91

        @staticmethod
        def record_run_event(*_args, **_kwargs):
            return None

        @staticmethod
        def add_review_item(*_args, **_kwargs):
            return None

    legacy = Legacy()
    segments = pipeline.build_moss_host_primary_segments(
        {"segments": [{"start": 10.0, "end": 12.0, "text": "测试文本", "speaker": "S00", "confidence": 0.9}]},
        [{"text": "测试", "start": 10.2, "end": 10.8, "confidence": 0.81}, {"text": "文本", "start": 10.8, "end": 11.4, "confidence": 0.93}],
        [{"start": 9.0, "end": 13.0}],
        20.0,
        legacy,
    )
    segment = segments[0]
    assert segment.firered_start == pytest.approx(10.2)
    assert segment.firered_end == pytest.approx(11.4)
    assert segment.firered_alignment_confidence == pytest.approx(0.87)
    segment.qwen_asr_text = "测试文本"
    qwen = [{"start": 10.0, "end": 12.0, "text": "测试文本", "confidence": 0.66}]
    pipeline.attach_qwen_review_evidence(segments, qwen, legacy)
    assert segment.qwen_confidence == pytest.approx(0.66)
    segment.reference_consensus = 0.99
    assert segment.firered_alignment_confidence != segment.reference_consensus
