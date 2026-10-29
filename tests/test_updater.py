import json
from pathlib import Path

import pytest

from twobyteasr.app import updater
from twobyteasr.app.updater import (
    UpdateError,
    confirm_started,
    current_version,
    format_bytes,
    installed_channel,
    normalize_version,
)


def test_version_metadata_and_semver_normalization(tmp_path):
    metadata = tmp_path / "version.json"
    metadata.write_text(json.dumps({"version": "v0.1.15"}), encoding="utf-8")
    assert current_version(metadata) == "0.1.15"
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("0.6.6-test.1") == "0.6.6-test.1"
    with pytest.raises(UpdateError):
        normalize_version("next")
    metadata.write_text("not json", encoding="utf-8")
    assert current_version(metadata) == "0.0.0"


def test_channel_comes_from_the_installed_version_file(tmp_path, monkeypatch):
    monkeypatch.delenv(updater.CHANNEL_ENV, raising=False)
    metadata = tmp_path / "version.json"
    metadata.write_text(json.dumps({"version": "0.6.5", "channel": "stable"}), encoding="utf-8")
    assert installed_channel(metadata) == "stable"
    metadata.write_text(json.dumps({"version": "0.6.5", "channel": "testing"}), encoding="utf-8")
    assert installed_channel(metadata) == "prerelease"
    monkeypatch.setenv(updater.CHANNEL_ENV, "qa-local")
    assert installed_channel(metadata) == "qa-local"


def test_automatic_checks_stay_off_in_tests_and_audits(monkeypatch):
    assert updater.automatic_checks_allowed() is False  # PYTEST_CURRENT_TEST is set
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TWOBYTEASR_TEST_ROOT", raising=False)
    monkeypatch.setenv("TWOBYTEASR_ACCEPTANCE_DIR", "x")
    assert updater.automatic_checks_allowed() is False
    monkeypatch.delenv("TWOBYTEASR_ACCEPTANCE_DIR")
    monkeypatch.setenv(updater.DISABLE_ENV, "1")
    assert updater.automatic_checks_allowed() is False


def test_start_confirmation_is_written_once(tmp_path, monkeypatch):
    target = tmp_path / "confirm.json"
    monkeypatch.setenv(updater.CONFIRM_ENV, str(target))
    assert confirm_started("0.6.6") is True
    assert json.loads(target.read_text("utf-8"))["version"] == "0.6.6"
    assert confirm_started("0.6.6") is False  # the variable is consumed


def test_cleanup_keeps_a_prepared_update_until_it_is_installed(tmp_path, monkeypatch):
    monkeypatch.setenv(updater.STATE_ENV, str(tmp_path))
    (tmp_path / "s" / "abc").mkdir(parents=True)
    (tmp_path / "prepared.json").write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
    assert updater.cleanup_after_update() == []
    (tmp_path / "prepared.json").write_text(json.dumps({"version": current_version()}), encoding="utf-8")
    assert "s" in updater.cleanup_after_update()
    assert not (tmp_path / "s").exists()


def test_format_bytes():
    assert format_bytes(512) == "512 B"
    assert format_bytes(25 * 1024 * 1024) == "25.0 MB"
    assert format_bytes(3 * 1024 ** 3) == "3.00 GB"


def test_retired_zip_hot_replacement_stays_disabled():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "apply_update.ps1").read_text(encoding="utf-8-sig")
    first_statement = source.split('$ErrorActionPreference = "Stop"', 1)[1].lstrip().splitlines()[2]
    assert first_statement.startswith("throw ")
