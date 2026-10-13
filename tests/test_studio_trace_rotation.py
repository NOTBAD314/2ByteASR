"""studio-open.log is bounded; the rotated file is offered for cleanup."""
from __future__ import annotations

from pathlib import Path

from twobyteasr import runtime_trace
from twobyteasr.runtime_paths import RuntimePaths
from twobyteasr.runtime_trace import RuntimeTraceWriter
from twobyteasr.storage_service import StorageService


def _logs(tmp_path) -> Path:
    return tmp_path / "local" / "2ByteASR" / "logs"


def test_trace_log_rotates_to_one_previous_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(runtime_trace, "TRACE_LOG_MAX_BYTES", 4096)
    logs = _logs(tmp_path)
    logs.mkdir(parents=True)
    # A log left over from builds without a size limit.
    (logs / "studio-open.log").write_text("[00:00:00.000] event=OLD x=1\n" * 400, "utf8")
    writer = RuntimeTraceWriter(capacity=4096, ring_size=32)
    for index in range(300):
        writer.emit("MEDIA_CLOCK_POSITION", {"index": index, "position_ms": index * 16.7})
    assert writer.flush(5.0)
    current = logs / "studio-open.log"
    previous = logs / "studio-open.previous.log"
    assert current.stat().st_size < 4096 + 512
    assert previous.is_file() and previous.stat().st_size < 4096 + 512
    assert "event=OLD" not in previous.read_text("utf8")  # replaced on the next rotation
    assert "event=MEDIA_CLOCK_POSITION index=299" in current.read_text("utf8")


def test_rotated_trace_is_recognized_and_not_protected(tmp_path, monkeypatch):
    from twobyteasr import storage_legacy
    data = tmp_path / "data"
    logs = data / "logs"
    logs.mkdir(parents=True)
    (data / "cache").mkdir()
    (data / "models").mkdir()
    paths = RuntimePaths(tmp_path, data, data / "models", data / "cache", data / "projects", data,
                         logs, tmp_path / "renderer", data / "tmp")
    rotated = logs / "studio-open.previous.log"
    rotated.write_text("[12:00:00.000] event=MEDIA_CLOCK_POSITION position_ms=1\n", "utf8")
    service = StorageService(paths, roots=[logs], state_root=data / "storage")
    item = next(i for i in service.scan(include_models=False).items if i.path == str(rotated))
    assert item.producer == "studio_runtime_trace_legacy"
    assert "仍在写入" not in item.reason  # never treated as the live log
    assert item.manual_cleanable
    size = rotated.stat().st_size
    monkeypatch.setattr(storage_legacy, "legacy_consumers", lambda: [])
    assert storage_legacy.adopt(service, [item])["registered"] == 1
    assert service.clean(service.scan(include_models=False).items).logical_removed_bytes == size
    assert not rotated.exists()
