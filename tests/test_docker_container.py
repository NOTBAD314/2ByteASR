"""Regression coverage for the container's data and platform boundaries."""
import json
from pathlib import Path
import pytest

def test_existing_settings_are_preserved_byte_for_byte(tmp_path):
    from twobyteasr.container.launch import seed_settings
    target = tmp_path / "2byteasr_settings.json"
    original = b'{"models":{"primary_asr_backend":"api"}}\n'
    target.write_bytes(original)
    seed_settings(target)
    assert target.read_bytes() == original

def test_first_launch_uses_an_available_cpu_engine(tmp_path):
    from twobyteasr.container.launch import seed_settings
    target = tmp_path / "2byteasr_settings.json"
    seed_settings(target)
    settings = json.loads(target.read_text("utf8"))
    assert settings["models"]["primary_asr_backend"] == "sensevoice"
    assert settings["models"]["speaker_source"] == "native"
    assert not settings["switches"]["enable_firered_boundary_refinement"]
    assert not settings["switches"]["enable_qwen_asr_reference"]

def test_launch_respects_explicit_roots(tmp_path, monkeypatch):
    from twobyteasr.container.launch import configure
    for name in ("2BYTEASR_USER_DATA_ROOT", "2BYTEASR_MODEL_ROOT", "2BYTEASR_RUNTIME_ROOT"):
        monkeypatch.setenv(name, str(tmp_path / name))
    configure()
    for name in ("2BYTEASR_USER_DATA_ROOT", "2BYTEASR_MODEL_ROOT", "2BYTEASR_RUNTIME_ROOT"):
        assert (tmp_path / name).is_dir()

@pytest.mark.parametrize("keys", [[], ["moss"], ["sensevoice", "mlx_qwen_aligner"], ["../escape"]])
def test_unsupported_download_has_no_side_effects(keys, tmp_path):
    from twobyteasr.container.models import prepare
    with pytest.raises(ValueError):
        prepare(keys, "AUTO", tmp_path)
    assert list(tmp_path.iterdir()) == []

def test_x11_embedding_is_container_only(monkeypatch):
    from twobyteasr.platform_mpv import native_video_arguments
    monkeypatch.delenv("TWOBYTEASR_CONTAINER", raising=False)
    assert native_video_arguments(7, platform="linux") == ["--gpu-api=auto"]
    monkeypatch.setenv("TWOBYTEASR_CONTAINER", "1")
    assert "--wid=7" in native_video_arguments(7, platform="linux")
    assert native_video_arguments(7, platform="win32") == ["--gpu-api=d3d11", "--wid=7"]
    assert "--wid=7" not in native_video_arguments(7, platform="darwin")
    with pytest.raises(ValueError):
        native_video_arguments(0, platform="linux")

def test_container_credentials_roundtrip_and_tamper(tmp_path):
    from twobyteasr.container.secrets import transform
    store = tmp_path / "secrets.dat"
    payload = b'{"schema":2,"key":"test-only-not-a-real-key"}'
    encrypted = transform("protect", payload, store)
    assert payload not in encrypted
    assert transform("unprotect", encrypted, store) == payload
    with pytest.raises(RuntimeError):
        transform("unprotect", encrypted[:-4] + b"xxxx", store)
    key = tmp_path / "container-secrets.key"
    key.unlink()
    with pytest.raises(RuntimeError):
        transform("unprotect", encrypted, store)
    assert not key.exists()
