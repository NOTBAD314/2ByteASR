"""Successful environment probes are reused for the session; failures are not.

2026-10-10 performance round 2: every recognition started a fresh Python that
imported torch for the FireRed/Qwen environment check and at every model load
for CUDA readiness (2-6 s each, ~7 per run).
"""
import os
from types import SimpleNamespace

import pytest

from twobyteasr.recognition import asr
from twobyteasr.system import environment, hardware


@pytest.fixture(autouse=True)
def _fresh_cache():
    environment.reset_preflight_cache()
    yield
    environment.reset_preflight_cache()


def test_only_ready_results_are_reused_and_reset_clears_them():
    calls = []

    def probe(ready):
        calls.append(ready)
        return {"ready": ready}
    first, reused = environment.reuse_ready_probe("k", lambda: probe(False), lambda v: v["ready"])
    assert (first, reused) == ({"ready": False}, False)
    environment.reuse_ready_probe("k", lambda: probe(True), lambda v: v["ready"])
    value, reused = environment.reuse_ready_probe("k", lambda: probe(True), lambda v: v["ready"])
    assert reused and value == {"ready": True} and calls == [False, True]
    value["ready"] = "mutated by caller"
    assert environment.reuse_ready_probe("k", lambda: probe(True), lambda v: v["ready"])[0] == {"ready": True}
    environment.reset_preflight_cache()
    environment.reuse_ready_probe("k", lambda: probe(True), lambda v: v["ready"])
    assert calls == [False, True, True]


def test_runtime_identity_follows_package_installs(tmp_path):
    scripts = tmp_path / "venv" / "Scripts"
    packages = tmp_path / "venv" / "Lib" / "site-packages"
    scripts.mkdir(parents=True)
    packages.mkdir(parents=True)
    python = scripts / "python.exe"
    python.write_bytes(b"x")
    before = environment.runtime_identity(python)
    os.utime(packages, ns=(1_600_000_000 * 10**9,) * 2)
    pinned = environment.runtime_identity(python)
    (packages / "torch-2.9.dist-info").mkdir()
    os.utime(packages, ns=(1_700_000_000 * 10**9,) * 2)
    assert before != pinned != environment.runtime_identity(python)
    assert [path for path, _ in environment.runtime_identity(python)[2]] == [os.path.normpath(packages)]


def _model_dirs(tmp_path):
    runtime = tmp_path / "Scripts" / "python.exe"
    runtime.parent.mkdir()
    runtime.write_bytes(b"x")
    model = tmp_path / "model"
    model.mkdir()
    return runtime, model


def test_model_probe_reuses_ready_result_and_rechecks_removed_model(tmp_path, monkeypatch):
    runtime, model = _model_dirs(tmp_path)
    spawned = []

    def spawn(details, *_args):
        spawned.append(1)
        return dict(details, ready=True, error="")
    monkeypatch.setattr(asr, "_spawn_model_runtime_probe", spawn)
    kwargs = dict(model_id="firered", runtime=str(runtime), model_path=str(model), import_name="x")
    first = asr._model_runtime_probe(**kwargs)
    second = asr._model_runtime_probe(**kwargs)
    assert first["ready"] and "probe_reused" not in first
    assert second["ready"] and second["probe_reused"] is True and len(spawned) == 1
    model.rmdir()
    removed = asr._model_runtime_probe(**kwargs)
    assert removed["error"] == "model_path_missing" and len(spawned) == 1


def test_model_probe_failure_is_probed_again(tmp_path, monkeypatch):
    runtime, model = _model_dirs(tmp_path)
    spawned = []
    monkeypatch.setattr(asr, "_spawn_model_runtime_probe",
                        lambda details, *_a: spawned.append(1) or dict(details, ready=False, error="torch"))
    kwargs = dict(model_id="qwen3-asr", runtime=str(runtime), model_path=str(model))
    asr._model_runtime_probe(**kwargs)
    asr._model_runtime_probe(**kwargs)
    assert len(spawned) == 2


@pytest.mark.parametrize("usable, expected_probes", [(True, 1), (False, 4)])
def test_readiness_gates_share_one_passed_torch_probe(monkeypatch, usable, expected_probes):
    probes = []

    def probe():
        probes.append(1)
        return {"imported": True, "usable": usable, "available": usable, "torchaudio_imported": True,
                "torch_version": "2.9.0+cu128", "torchaudio_version": "2.9.0+cu128", "gpu_name": "GPU"}
    monkeypatch.setattr(hardware, "_probe_torch_runtime", probe)
    monkeypatch.setattr(hardware, "_visible_nvidia_gpu", lambda: ("GPU", 8192))
    monkeypatch.setattr(hardware, "_nvidia_driver_version", lambda: "580")
    monkeypatch.setattr(hardware, "main_python_executable", lambda: "")
    hardware.detect_torch_audio_runtime(hardware.ready_torch_probe())
    assert [asr._cuda_runtime_ready() for _ in range(3)] == [usable] * 3
    assert len(probes) == expected_probes


def test_free_vram_telemetry_is_never_reused(monkeypatch):
    probes = []
    monkeypatch.setattr(hardware, "_probe_torch_runtime",
                        lambda: probes.append(1) or {"imported": True, "usable": True, "torchaudio_imported": True,
                                                     "free_memory_mb": 1000 * len(probes)})
    monkeypatch.setattr(hardware, "_visible_nvidia_gpu", lambda: ("GPU", 8192))
    monkeypatch.setattr(hardware, "_nvidia_driver_version", lambda: "580")
    hardware.ready_torch_probe()
    first = hardware.collect_gpu_telemetry()["free_memory_mb"]
    second = hardware.collect_gpu_telemetry()["free_memory_mb"]
    assert (first, second, len(probes)) == (2000, 3000, 3)
