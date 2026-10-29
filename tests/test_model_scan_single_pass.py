"""One model-registry scan resolves paths and reads records once; nothing outlives it.

2026-10-10 performance round 2: a scan re-resolved the same folders and re-read
the association record ~200 times (~107 ms, about nine scans while the main
window opens). The per-scan memo must not hide an install, removal or detach
from the next scan.
"""
import json
from pathlib import Path

from twobyteasr.local_models import model_associations
from twobyteasr import runtime_paths
from twobyteasr.local_models.model_associations import detach_model, is_model_detached


def test_memo_exists_only_inside_one_scan(monkeypatch):
    calls = []
    with runtime_paths.single_scan():
        for _ in range(3):
            runtime_paths.scan_memo("k", lambda: calls.append(1) or len(calls))
        with runtime_paths.single_scan():  # nested scans share the outer memo
            runtime_paths.scan_memo("k", lambda: calls.append(1) or len(calls))
    runtime_paths.scan_memo("k", lambda: calls.append(1) or len(calls))
    runtime_paths.scan_memo("k", lambda: calls.append(1) or len(calls))
    assert len(calls) == 3
    assert getattr(runtime_paths._SCAN_SCOPE, "memo", None) is None


def test_association_record_read_once_per_scan_and_detach_seen_next_scan(tmp_path, monkeypatch):
    record = tmp_path / "model-associations.json"
    folder = tmp_path / "models" / "Qwen3-ASR-1.7B"
    folder.mkdir(parents=True)
    reads = []
    original = model_associations._load
    monkeypatch.setattr(model_associations, "_load", lambda path: reads.append(path) or original(path))
    with runtime_paths.single_scan():
        assert [is_model_detached(folder, record_path=record) for _ in range(5)] == [False] * 5
    assert len(reads) == 1
    detach_model(folder, "qwen3_asr", record_path=record)
    assert json.loads(record.read_text("utf-8"))["detached"]
    with runtime_paths.single_scan():
        assert is_model_detached(folder, record_path=record)


def test_legacy_roots_copy_cannot_alter_the_scan_memo(tmp_path):
    with runtime_paths.single_scan():
        first = runtime_paths.discover_legacy_model_roots(tmp_path / "install", tmp_path / "data")
        first.append(Path("injected"))
        second = runtime_paths.discover_legacy_model_roots(tmp_path / "install", tmp_path / "data")
    assert Path("injected") not in second
