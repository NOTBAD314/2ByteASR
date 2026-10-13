"""Recognition must not bypass the owned, idle cache-maintenance boundary."""
import json
import os
from pathlib import Path
from threading import Event
import time
import wave

import pytest

from twobyteasr import cache
from twobyteasr.runtime_paths import RuntimePaths
from twobyteasr.storage_service import StorageService


@pytest.fixture
def owned_storage(tmp_path, monkeypatch):
    data = tmp_path / "data"
    root = data / "cache"
    root.mkdir(parents=True)
    models = data / "models"
    models.mkdir()
    paths = RuntimePaths(tmp_path, data, models, root, data / "projects", data,
                         data / "logs", tmp_path / "renderer", data / "tmp")
    service = StorageService(paths, roots=[root], state_root=data / "storage")
    monkeypatch.setattr(cache, "CACHE_ROOT", str(root))
    return service


def age_directory(path):
    old = time.time() - (cache.CACHE_MAX_AGE_DAYS + 1) * 86400
    os.utime(path, (old, old))


def test_recognition_cleanup_preserves_just_reused_timeline_input(owned_storage, monkeypatch):
    from twobyteasr import recognition_input, timeline_media

    # Exercise the real warm-hit validation, including WAV format and SHA.
    snapshot = dict(version=2, duration_ms=1000, audio_graph={"segments": []},
                    sequence={}, sources={}, media_time_contract=timeline_media.TIME_CONTRACT,
                    media_timebases={})
    snapshot["fingerprint"] = recognition_input._digest(snapshot)
    container = owned_storage.paths.cache_root / "timeline-inputs"
    folder = container / snapshot["fingerprint"]
    folder.mkdir(parents=True)
    target = folder / "timeline.wav"
    with wave.open(str(target), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 16000)
    digest = recognition_input._file_sha256(target)
    (folder / "input.json").write_text(json.dumps(dict(
        fingerprint=snapshot["fingerprint"], media_time_contract=timeline_media.TIME_CONTRACT,
        audio_sha256=digest)), encoding="utf8")
    age_directory(container)
    monkeypatch.setattr(timeline_media, "resolve_audio_layers", lambda *a, **k: ([], {}))
    prepared = recognition_input.prepare_recognition_input(
        snapshot, owned_storage.paths.cache_root, "unused-ffmpeg")
    assert Path(prepared) == target

    # This is the real service order: prepare/hit the input, then legacy cleanup.
    cache.cleanup_old_cache()

    assert target.is_file(), "queue cleanup deleted its own validated recognition input"
    assert recognition_input._file_sha256(target) == digest


def test_recognition_cleanup_preserves_leased_audio(owned_storage, tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source remains available")
    folder = owned_storage.paths.cache_root / "media-key"
    folder.mkdir()
    audio = folder / "audio_16k.npy"
    audio.write_bytes(b"active mapped audio fixture")
    assert owned_storage.register(audio, "audio", source=str(source), producer="cache_shared_audio")
    age_directory(folder)

    with owned_storage.lease(audio):
        cache.cleanup_old_cache()
        assert audio.is_file(), "legacy cleanup ignored an active storage lease"
        assert audio.read_bytes() == b"active mapped audio fixture"


@pytest.mark.parametrize("name", ["faster.json", "vad.json", "commentary.json", "forced_align.json"])
def test_recognition_cleanup_cannot_adopt_files_by_retired_name(owned_storage, name):
    folder = owned_storage.paths.cache_root / "recent-media"
    folder.mkdir()
    unknown = folder / name
    unknown.write_bytes(b"unowned or historical evidence")

    cache.cleanup_old_cache()

    assert unknown.is_file(), "a known filename does not establish deletion ownership"
    assert unknown.read_bytes() == b"unowned or historical evidence"


def test_recognition_cleanup_preserves_remote_evidence_and_missing_source_audio(owned_storage, tmp_path):
    folder = owned_storage.paths.cache_root / "old-media"
    folder.mkdir()
    evidence = folder / "moss.json"
    evidence.write_bytes(b"original remote recognition evidence")
    audio = folder / "audio_16k.npy"
    audio.write_bytes(b"only remaining local audio")
    assert owned_storage.register(evidence, "evidence", producer="fixture", rebuild="remote")
    assert owned_storage.register(audio, "audio", producer="cache_shared_audio",
                                  source=str(tmp_path / "missing-source.wav"))
    age_directory(folder)

    cache.cleanup_old_cache()

    assert evidence.is_file() and audio.is_file()
    assert evidence.read_bytes() == b"original remote recognition evidence"
    assert audio.read_bytes() == b"only remaining local audio"


def test_existing_idle_maintenance_still_reclaims_only_expired_owned_audio(owned_storage, tmp_path):
    from twobyteasr.storage_ui import maintain_registered_storage

    source = tmp_path / "source.wav"
    source.write_bytes(b"available source")
    root = owned_storage.paths.cache_root
    disposable, held, unknown, evidence = (root / name for name in
                                          ("expired.npy", "held.npy", "unknown.bin", "moss.json"))
    for path in (disposable, held, unknown, evidence):
        path.write_bytes(b"fixture")
    for path in (disposable, held):
        assert owned_storage.register(path, "audio", producer="cache_shared_audio", source=str(source))
    assert owned_storage.register(evidence, "evidence", producer="fixture", rebuild="remote")
    with owned_storage._db() as db:
        db.execute("UPDATE entries SET used=?", (time.time() - 30 * 86400,))

    with owned_storage.lease(held):
        outcome = maintain_registered_storage(owned_storage, Event())

    assert {row["path"] for row in outcome.deleted} == {str(disposable)}
    assert not disposable.exists()
    assert all(path.is_file() for path in (held, unknown, evidence, source))
