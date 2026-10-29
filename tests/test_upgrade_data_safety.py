"""Data upgrade failures must retain original bytes and custom references."""
import errno
import json
from pathlib import Path

import pytest

from twobyteasr import runtime_paths
from twobyteasr.storage import settings


@pytest.fixture
def legacy_settings(tmp_path, monkeypatch):
    source = tmp_path / "old" / settings.SETTINGS_FILENAME
    target = tmp_path / "new" / settings.SETTINGS_FILENAME
    source.parent.mkdir()
    original = b'\xef\xbb\xbf' + json.dumps({
        "schema_version": 1,
        "models": {"polish_model": "BerLIN"},
        "glossary": {"enable_domain_terms": True},
    }).encode("utf-8")
    source.write_bytes(original)
    monkeypatch.setattr(settings, "stable_settings_root", lambda: target.parent)
    monkeypatch.setattr(settings, "_legacy_settings_candidates", lambda: [source])
    return source, target, original


def test_legacy_import_atomic_idempotent_and_retains_recovery_source(legacy_settings):
    source, target, original = legacy_settings
    settings._migrate_settings_into_stable_root(target)
    assert target.read_bytes() == original == source.read_bytes()
    imported, _, _ = settings.load_runtime_settings()
    assert imported["models"]["polish_model"] == "BerLIN"
    target.write_bytes(b'{"schema_version":1,"models":{"polish_model":"S0pp"}}')
    settings._migrate_settings_into_stable_root(target)
    assert b"S0pp" in target.read_bytes()
    assert source.read_bytes() == original
    assert list(target.parent.glob("*.tmp")) == []


@pytest.mark.parametrize("failure_point", ["create", "flush", "replace"])
def test_legacy_import_enospc_does_not_create_partial_or_defaults(legacy_settings, monkeypatch, failure_point):
    source, target, original = legacy_settings
    def no_space(*args, **kwargs):
        raise OSError(errno.ENOSPC, "isolated test: disk full")
    if failure_point == "create":
        monkeypatch.setattr(settings.tempfile, "mkstemp", no_space)
    elif failure_point == "flush":
        monkeypatch.setattr(settings.os, "fsync", no_space)
    else:
        monkeypatch.setattr(settings.os, "replace", no_space)
    with pytest.raises(RuntimeError, match="旧设置保留"):
        settings.load_runtime_settings()
    assert source.read_bytes() == original
    assert not target.exists()
    assert list(target.parent.glob("*.tmp")) == []


@pytest.mark.parametrize("broken", [b'{"schema_version":', b'[]', b'\xff\xff'])
def test_bad_legacy_settings_fail_without_overwrite(legacy_settings, broken):
    source, target, _ = legacy_settings
    source.write_bytes(broken)
    with pytest.raises(RuntimeError, match="未写入默认值"):
        settings.load_runtime_settings()
    assert source.read_bytes() == broken and not target.exists()


def test_runtime_registration_atomic_failure_retains_old_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv(runtime_paths.USER_DATA_ENV, str(tmp_path / "data"))
    model_root = tmp_path / "custom-models"
    model_root.mkdir()
    paths = runtime_paths.build_runtime_paths(install_root=tmp_path / "program", model_root=model_root)
    runtime_paths.persist_runtime_paths(paths)
    registry = paths.user_data_root / "runtime_paths.json"
    original = registry.read_bytes()
    def no_space(*args):
        raise OSError(errno.ENOSPC, "isolated replacement failure")
    monkeypatch.setattr(runtime_paths.os, "replace", no_space)
    with pytest.raises(OSError):
        runtime_paths.persist_runtime_paths(paths)
    assert registry.read_bytes() == original
    assert list(registry.parent.glob(".runtime-paths-*.tmp")) == []


def test_path_change_keeps_custom_models_projects_in_place(tmp_path, monkeypatch):
    monkeypatch.delenv(runtime_paths.MODEL_ROOT_ENV, raising=False)
    monkeypatch.setenv(runtime_paths.USER_DATA_ENV, str(tmp_path / "data"))
    model_root = tmp_path / "custom-models"
    project_root = tmp_path / "custom-projects"
    model_root.mkdir(); project_root.mkdir()
    data = runtime_paths.user_data_root()
    studio = data / "SubtitleStudioPreview"
    studio.mkdir(parents=True)
    (studio / "settings.json").write_text(json.dumps({"project_root": str(project_root)}), "utf8")
    paths = runtime_paths.build_runtime_paths(install_root=tmp_path / "old-program", model_root=model_root)
    runtime_paths.persist_runtime_paths(paths)
    monkeypatch.delenv(runtime_paths.MODEL_ROOT_ENV, raising=False)
    after = runtime_paths.build_runtime_paths(install_root=tmp_path / "new-program")
    assert after.model_root == model_root.resolve()
    assert after.project_root == project_root
    assert after.user_data_root == paths.user_data_root
    assert not (data / "Models").exists()


def test_missing_registered_drive_is_error_not_empty_model_install(tmp_path, monkeypatch):
    monkeypatch.delenv(runtime_paths.MODEL_ROOT_ENV, raising=False)
    monkeypatch.setenv(runtime_paths.USER_DATA_ENV, str(tmp_path / "data"))
    data = runtime_paths.user_data_root(); data.mkdir(parents=True)
    path = data / "runtime_paths.json"
    original = json.dumps({"schema_version": 1, "model_root": str(tmp_path / "missing-drive")}).encode()
    path.write_bytes(original)
    with pytest.raises(RuntimeError, match="不会重新下载"):
        runtime_paths.build_runtime_paths(install_root=tmp_path / "program")
    assert path.read_bytes() == original


def test_installer_never_recursively_removes_models_runtimes_or_data():
    root = Path(__file__).resolve().parents[1]
    for name in ("2ByteASR.iss", "2ByteASR-frozen.iss"):
        text = (root / "installer" / name).read_text("utf8")
        assert 'D2CA55A8-6992-4C39-BAF1-2D790E9B5E26' in text
        assert '[InstallDelete]' not in text
        for leaf in ("models", ".venv-main", ".venv-moss", "Projects", "reports"):
            assert f'Name: "{{app}}\\{leaf}"' not in text
        for config in ("2byteasr_settings.json", "game_profiles.json", "glossary.txt"):
            row = next(row for row in text.splitlines() if row.startswith("Source:") and config in row and "Excludes:" not in row)
            assert "onlyifdoesntexist" in row and "uninsneveruninstall" in row


@pytest.mark.parametrize("internal", [True, False])
def test_isolation_preserves_only_owned_custom_model_root(tmp_path, monkeypatch, internal):
    from twobyteasr.test_isolation import install
    boundary = (tmp_path / "tmp" / "boundary").resolve()
    custom = boundary / "custom models" if internal else tmp_path / "operator-models"
    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(boundary))
    monkeypatch.setenv(runtime_paths.MODEL_ROOT_ENV, str(custom))
    install()
    expected = custom if internal else boundary / "models"
    assert Path(__import__('os').environ[runtime_paths.MODEL_ROOT_ENV]) == expected
    if not internal:
        assert not custom.exists()
