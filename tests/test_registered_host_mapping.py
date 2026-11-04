from types import SimpleNamespace

import numpy as np

import moss_firered_pipeline as pipeline


def test_registered_host_can_absorb_multiple_moss_labels(monkeypatch):
    rows = []
    for speaker, starts in (("S01", (0, 2)), ("S02", (4, 6)), ("S03", (8, 10))):
        for start in starts:
            rows.append({"speaker": speaker, "start": float(start), "end": float(start + 1), "text": speaker})
    rows.append({"speaker": "S04", "start": 12.0, "end": 13.0, "text": "one-off"})

    events = []
    legacy = SimpleNamespace(
        AUDIO_SAMPLE_RATE=10,
        RUNTIME_EXPECTED_SPEAKERS=0,
        load_host_voiceprint_registry=lambda: {
            "hosts": [
                {"id": "host_a", "name": "主播A", "label": "S01", "embedding": [1.0, 0.0]},
                {"id": "host_b", "name": "主播B", "label": "S02", "embedding": [0.0, 1.0]},
            ]
        },
        record_run_event=lambda event, **payload: events.append((event, payload)),
    )
    monkeypatch.setattr(pipeline, "_load_host_encoder", lambda legacy: object())
    monkeypatch.setattr(
        pipeline,
        "_encode_speaker_signals",
        lambda encoder, signals: np.asarray(
            [[1.0, 0.0], [0.0, 1.0], [0.1, 0.995]], dtype=np.float32
        ),
    )

    hosts, mapped = pipeline.apply_registered_host_voiceprints(
        rows,
        ["S01", "S02"],
        np.zeros(140, dtype=np.float32),
        legacy,
        candidate_speakers=["S01", "S02", "S03", "S04"],
    )

    assert hosts == ["S01", "S02"]
    assert {row["speaker"] for row in mapped if row.get("speaker_raw") == "S03"} == {"S02"}
    assert {row["speaker"] for row in mapped if row.get("speaker_raw") == "S02"} == {"S02"}
    assert next(row for row in mapped if row["speaker"] == "S04")["speaker"] == "S04"
    assert events[0][0] == "host_voiceprint_mapping"
    assert events[0][1]["assignments"]["S03"]["name"] == "主播B"


def test_confident_rename_does_not_merge_rejected_second_host(monkeypatch):
    rows = []
    for speaker, starts in (("S01", (0, 4, 8)), ("S02", (2, 6, 10))):
        for start in starts:
            rows.append(
                {
                    "speaker": speaker,
                    "start": float(start),
                    "end": float(start + 1),
                    "text": speaker,
                }
            )

    events = []
    legacy = SimpleNamespace(
        AUDIO_SAMPLE_RATE=10,
        RUNTIME_EXPECTED_SPEAKERS=0,
        load_host_voiceprint_registry=lambda: {
            "hosts": [
                {"id": "host_a", "name": "主播A", "label": "S01", "embedding": [1.0, 0.0]},
                {"id": "host_b", "name": "主播B", "label": "S02", "embedding": [0.0, 1.0]},
            ]
        },
        record_run_event=lambda event, **payload: events.append((event, payload)),
    )
    monkeypatch.setattr(pipeline, "_load_host_encoder", lambda legacy: object())
    monkeypatch.setattr(
        pipeline,
        "_encode_speaker_signals",
        lambda encoder, signals: np.asarray(
            [
                [0.505, 0.375],  # raw S01: stable second host, but not safe to name
                [0.648, 0.331],  # raw S02: confident 主播A -> canonical S01
            ],
            dtype=np.float32,
        ),
    )

    hosts, mapped = pipeline.apply_registered_host_voiceprints(
        rows,
        ["S01", "S02"],
        np.zeros(120, dtype=np.float32),
        legacy,
        candidate_speakers=["S01", "S02"],
    )

    assert hosts == ["S01", "S02"]
    assert {row["speaker"] for row in mapped if row["speaker_raw"] == "S02"} == {"S01"}
    assert {row["speaker"] for row in mapped if row["speaker_raw"] == "S01"} == {"S02"}
    assert all(
        row.get("speaker_voiceprint_fallback") is True
        for row in mapped
        if row["speaker_raw"] == "S01"
    )
    assert events[0][1]["fallback_assignments"]["S01"]["label"] == "S02"


def test_two_enrolled_hosts_do_not_remove_unregistered_third_host(monkeypatch):
    rows = []
    for speaker, starts in (
        ("S01", (0, 6, 12)),
        ("S02", (2, 8, 14)),
        ("S03", (4, 10, 16)),
    ):
        for start in starts:
            rows.append(
                {
                    "speaker": speaker,
                    "start": float(start),
                    "end": float(start + 1),
                    "text": speaker,
                }
            )

    legacy = SimpleNamespace(
        AUDIO_SAMPLE_RATE=10,
        RUNTIME_EXPECTED_SPEAKERS=3,
        load_host_voiceprint_registry=lambda: {
            "hosts": [
                {"id": "host_a", "name": "主播A", "label": "S01", "embedding": [1.0, 0.0]},
                {"id": "host_b", "name": "主播B", "label": "S02", "embedding": [0.0, 1.0]},
            ]
        },
        record_run_event=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(pipeline, "_load_host_encoder", lambda legacy: object())
    monkeypatch.setattr(
        pipeline,
        "_encode_speaker_signals",
        lambda encoder, signals: np.asarray(
            [
                [1.0, 0.0],
                [0.0, 1.0],
                [0.52, 0.48],  # unknown third host: no safe enrolled match
            ],
            dtype=np.float32,
        ),
    )

    hosts, mapped = pipeline.apply_registered_host_voiceprints(
        rows,
        ["S01", "S02", "S03"],
        np.zeros(180, dtype=np.float32),
        legacy,
        candidate_speakers=["S01", "S02", "S03"],
    )

    assert hosts == ["S01", "S02", "S03"]
    assert {row["speaker"] for row in mapped} == {"S01", "S02", "S03"}
