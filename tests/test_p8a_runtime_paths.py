"""P8A RuntimePaths + ModelRegistry: source/packaged share one model root."""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path

from twobyteasr.local_models.model_registry import ModelHealth, installed_model_keys, scan_model_registry
from twobyteasr.local_models.model_storage import build_storage_qss, scan_storage
from twobyteasr.local_models.model_workshop import MODELS
from twobyteasr.runtime_paths import (
    MODEL_ROOT_ENV,
    bootstrap_runtime_paths,
    build_runtime_paths,
    reset_runtime_paths,
    set_model_root,
)
from twobyteasr.design.ui_theme import THEMES, theme_definition


@pytest.fixture(autouse=True)
def isolated_legacy_paths(tmp_path,monkeypatch):
    from twobyteasr.runtime_paths import USER_DATA_ENV
    # These cases deliberately exercise legacy discovery within a temporary
    # fake home. No path is permitted to resolve to the real user's data.
    monkeypatch.delenv('TWOBYTEASR_TEST_ROOT',raising=False)
    monkeypatch.delenv(USER_DATA_ENV,raising=False)
    monkeypatch.setenv('USERPROFILE',str(tmp_path))
    monkeypatch.setenv('HOME',str(tmp_path))
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    monkeypatch.setenv(MODEL_ROOT_ENV,'')
    reset_runtime_paths()
    yield
    reset_runtime_paths()


def _lock(models: dict) -> dict:
    return {"schema_version": 1, "models": models}


def _install_model(root: Path, folder: str, files: tuple[str, ...] = ("a.bin",)) -> Path:
    dest = root / folder
    dest.mkdir(parents=True, exist_ok=True)
    for name in files:
        (dest / name).write_bytes(b"ok")
    return dest


def test_source_and_packaged_share_discovered_model_root(tmp_path, monkeypatch):
    local = tmp_path / "localapp"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(MODEL_ROOT_ENV, raising=False)
    reset_runtime_paths()

    repo = tmp_path / "repo"
    packaged = tmp_path / "dist" / "2ByteASR"
    repo.mkdir()
    packaged.mkdir(parents=True)
    lock = _lock({
        "moss": {"path": "models/MOSS-Transcribe-Diarize", "required_files": ["a.bin"]},
        "firered_aed": {"path": "models/FireRedASR2-AED", "required_files": ["a.bin"]},
    })
    (repo / "dependencies.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (packaged / "dependencies.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    _install_model(repo / "models", "MOSS-Transcribe-Diarize")
    _install_model(repo / "models", "FireRedASR2-AED")

    source_paths = build_runtime_paths(install_root=repo, persist=True)
    assert source_paths.model_root == (repo / "models").resolve()
    assert installed_model_keys(repo) == {"moss", "firered_aed"}

    reset_runtime_paths()
    packaged_paths = build_runtime_paths(install_root=packaged, persist=True)
    assert packaged_paths.model_root == (repo / "models").resolve()
    assert installed_model_keys(packaged) == {"moss", "firered_aed"}
    assert packaged_paths.user_data_root == local / "2ByteASR"
    assert packaged_paths.model_root != packaged / "models"


def test_registry_does_not_treat_wrong_app_root_as_missing(tmp_path, monkeypatch):
    local = tmp_path / "AppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(MODEL_ROOT_ENV, raising=False)
    reset_runtime_paths()
    legacy = tmp_path / "Desktop" / "2ByteASR" / "models"
    exe_root = tmp_path / "dist" / "2ByteASR"
    exe_root.mkdir(parents=True)
    lock = _lock({"qwen_asr": {"path": "models/Qwen3-ASR-1.7B", "required_files": ["config.json"]}})
    (exe_root / "dependencies.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    _install_model(legacy, "Qwen3-ASR-1.7B", ("config.json",))
    monkeypatch.setenv(MODEL_ROOT_ENV, str(legacy))
    registry = scan_model_registry(install_root=exe_root)
    record = registry.record("qwen_asr")
    assert record is not None
    assert record.health is ModelHealth.INSTALLED
    assert record.installation_path == (legacy / "Qwen3-ASR-1.7B").resolve()


def test_storage_scan_uses_registry_not_install_relative_path(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(MODEL_ROOT_ENV, raising=False)
    reset_runtime_paths()
    install = tmp_path / "dist"
    install.mkdir()
    models_dir = tmp_path / "shared-models"
    _install_model(models_dir, "aed", ("model.bin",))
    payload = {
        "models": {
            "firered_aed": {
                "path": "models/aed",
                "required_files": ["model.bin"],
                "download_bytes": 10,
                "runtime_environment": ".venv-main",
                "revision": "a",
            }
        }
    }
    (install / "dependencies.lock.json").write_text(json.dumps(payload), encoding="utf-8")
    set_model_root(models_dir, persist=True)
    models = [model for model in MODELS if model.download_key == "firered_aed"]
    entries = scan_storage(install, models, {"firered"})
    by_key = {entry.key: entry for entry in entries}
    assert by_key["firered_aed"].installed is True
    assert by_key["firered_aed"].path == (models_dir / "aed").resolve()


def test_storage_qss_uses_current_theme_tokens_not_cream_hardcodes():
    from twobyteasr.design.theme_manager import theme_key

    qss = build_storage_qss()
    theme = theme_definition(theme_key())
    assert theme.surface in qss
    assert theme.text in qss
    assert theme.surface_elevated in qss
    hard = {"#fbfaf6", "#fffdf8", "#f5f1ea", "#fbfaf6"}
    used = {theme.surface.lower(), theme.surface_elevated.lower(), theme.panel.lower()}
    for color in hard:
        if color not in used:
            assert color not in qss.lower()


def test_bootstrap_does_not_copy_models(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(MODEL_ROOT_ENV, raising=False)
    reset_runtime_paths()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "dependencies.lock.json").write_text(
        json.dumps(_lock({"moss": {"path": "models/MOSS-Transcribe-Diarize", "required_files": ["a.bin"]}})),
        encoding="utf-8",
    )
    original = _install_model(repo / "models", "MOSS-Transcribe-Diarize")
    (original / "a.bin").write_bytes(b"payload-bytes")
    paths = bootstrap_runtime_paths(install_root=repo, persist=True)
    copied = local / "2ByteASR" / "Models" / "MOSS-Transcribe-Diarize" / "a.bin"
    assert not copied.exists()
    assert paths.model_root == (repo / "models").resolve()
    assert (paths.model_root / "MOSS-Transcribe-Diarize" / "a.bin").read_bytes() == b"payload-bytes"


# 2026-10-14: a new Windows install keeps models beside the program folder.
def _fresh_install(tmp_path, monkeypatch, name="D-drive/兔白字幕"):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(MODEL_ROOT_ENV, raising=False)
    reset_runtime_paths()
    program = tmp_path / name
    program.mkdir(parents=True)
    (program / "dependencies.lock.json").write_text(
        json.dumps(_lock({"moss": {"path": "models/MOSS-Transcribe-Diarize", "required_files": ["a.bin"]}})),
        encoding="utf-8",
    )
    return local, program


@pytest.mark.skipif(os.name != "nt", reason="program-folder default is Windows only")
def test_new_install_downloads_models_beside_the_program(tmp_path, monkeypatch):
    local, program = _fresh_install(tmp_path, monkeypatch)
    paths = bootstrap_runtime_paths(install_root=program, persist=True)
    assert paths.model_root == (program / "models").resolve()
    assert paths.model_root_source == "default_program"
    assert not (local / "2ByteASR" / "Models").exists() or not any((local / "2ByteASR" / "Models").iterdir())
    # The choice is registered and kept on the next start.
    reset_runtime_paths()
    assert build_runtime_paths(install_root=program).model_root == (program / "models").resolve()


@pytest.mark.skipif(os.name != "nt", reason="program-folder default is Windows only")
def test_empty_old_default_is_moved_to_program_folder_but_used_one_is_kept(tmp_path, monkeypatch):
    local, program = _fresh_install(tmp_path, monkeypatch)
    old_default = local / "2ByteASR" / "Models"
    old_default.mkdir(parents=True)
    registry = local / "2ByteASR" / "runtime_paths.json"
    registry.write_text(json.dumps({"model_root": str(old_default), "model_root_source": "persisted"}), "utf-8")
    assert build_runtime_paths(install_root=program).model_root == (program / "models").resolve()

    # Anything already downloaded there (even a partial file) keeps it registered.
    reset_runtime_paths()
    (old_default / "MOSS-Transcribe-Diarize").mkdir()
    (old_default / "MOSS-Transcribe-Diarize" / "a.bin.part").write_bytes(b"x")
    assert build_runtime_paths(install_root=program).model_root == old_default.resolve()


@pytest.mark.skipif(os.name != "nt", reason="program-folder default is Windows only")
def test_user_chosen_and_dev_dist_roots_are_not_redirected(tmp_path, monkeypatch):
    local, program = _fresh_install(tmp_path, monkeypatch)
    chosen = tmp_path / "E-drive" / "models"
    chosen.mkdir(parents=True)
    build_runtime_paths(install_root=program, model_root=chosen, persist=True)
    reset_runtime_paths()
    assert build_runtime_paths(install_root=program).model_root == chosen.resolve()

    # A packaged build inside a source checkout's dist/ is replaced on every
    # daily swap; it keeps the user-data default.
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    dev_dist = checkout / "dist" / "2ByteASR"
    dev_dist.mkdir(parents=True)
    (local / "2ByteASR" / "runtime_paths.json").unlink()
    monkeypatch.setenv(MODEL_ROOT_ENV, "")  # persisting exported the chosen root
    reset_runtime_paths()
    paths = build_runtime_paths(install_root=dev_dist)
    assert paths.model_root == (local / "2ByteASR" / "Models").resolve()
    assert paths.model_root_source == "default_user_data"


def test_isolated_test_root_never_defaults_to_the_program_folder(tmp_path, monkeypatch):
    local, program = _fresh_install(tmp_path, monkeypatch)
    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(tmp_path / "test-root"))
    paths = build_runtime_paths(install_root=program)
    assert paths.model_root != (program / "models").resolve()
