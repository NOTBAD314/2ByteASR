import pytest

from twobyteasr.system import hardware


def _fake_probe(
    *,
    version="2.13.0+cpu",
    cuda_version=None,
    available=False,
    usable=None,
    error="",
    audio_version="2.13.0+cpu",
    audio_error="",
):
    return {
        "imported": True,
        "torch_version": version,
        "cuda_version": cuda_version or "",
        "available": available,
        "usable": available if usable is None else usable,
        "gpu_name": "RTX Test" if available else "",
        "memory_mb": 12288 if available else 0,
        "error": error,
        "torchaudio_imported": not bool(audio_error),
        "torchaudio_version": "" if audio_error else audio_version,
        "torchaudio_error": audio_error,
    }


def test_cuda_diagnosis_explains_vmware_when_gpu_is_not_visible(monkeypatch):
    monkeypatch.setattr(hardware, "_probe_torch_runtime", lambda: _fake_probe())
    monkeypatch.setattr(hardware, "_visible_nvidia_gpu", lambda: ("", 0))

    status = hardware.detect_cuda_runtime()

    assert status.ready is False
    assert status.code == "gpu_or_driver_missing"
    assert "MOSS 无法运行" in status.summary
    assert "VMware" in status.guidance
    assert "CUDA Toolkit" in status.guidance


def test_cuda_diagnosis_distinguishes_cpu_torch_from_missing_gpu(monkeypatch):
    monkeypatch.setattr(hardware, "_probe_torch_runtime", lambda: _fake_probe())
    monkeypatch.setattr(hardware, "_visible_nvidia_gpu", lambda: ("RTX Test", 12288))

    status = hardware.detect_cuda_runtime()

    assert status.code == "cpu_torch"
    assert "CPU 版 PyTorch" in status.summary
    assert "重新配置" in status.guidance


def test_cuda_diagnosis_reports_ready_device(monkeypatch):
    monkeypatch.setattr(
        hardware,
        "_probe_torch_runtime",
        lambda: _fake_probe(version="2.11.0+cu126", cuda_version="12.6", available=True),
    )
    monkeypatch.setattr(hardware, "_visible_nvidia_gpu", lambda: ("RTX Test", 12288))

    status = hardware.detect_cuda_runtime()

    assert status.ready is True
    assert status.code == "ready"
    assert status.gpu_name == "RTX Test"
    assert status.memory_mb == 12288


def test_cuda_diagnosis_identifies_cu130_driver_mismatch(monkeypatch):
    monkeypatch.setattr(
        hardware,
        "_probe_torch_runtime",
        lambda: _fake_probe(version="2.13.0+cu130", cuda_version="13.0", available=False),
    )
    monkeypatch.setattr(hardware, "_visible_nvidia_gpu", lambda: ("RTX 3060 Laptop GPU", 6144))
    monkeypatch.setattr(hardware, "_nvidia_driver_version", lambda: "576.80")

    status = hardware.detect_cuda_runtime()

    assert status.ready is False
    assert status.code == "driver_torch_mismatch"
    assert "显卡本身并不太老" in status.guidance
    assert "cu126" in status.guidance
    assert status.cuda_version == "13.0"
    assert status.driver_version == "576.80"


def test_cuda_diagnosis_rejects_visible_gpu_when_first_kernel_fails(monkeypatch):
    monkeypatch.setattr(
        hardware,
        "_probe_torch_runtime",
        lambda: _fake_probe(
            version="2.11.0+cu126",
            cuda_version="12.6",
            available=True,
            usable=False,
            error="no kernel image is available for execution on the device",
        ),
    )
    monkeypatch.setattr(hardware, "_visible_nvidia_gpu", lambda: ("RTX 5070 Ti", 16384))

    status = hardware.detect_cuda_runtime()

    assert status.ready is False
    assert status.code == "gpu_arch_unsupported"
    assert "cu128" in status.guidance


def test_require_cuda_runtime_raises_actionable_error(monkeypatch):
    monkeypatch.setattr(hardware, "_probe_torch_runtime", lambda: _fake_probe())
    monkeypatch.setattr(hardware, "_visible_nvidia_gpu", lambda: ("", 0))

    with pytest.raises(RuntimeError, match="NVIDIA CUDA GPU") as error:
        hardware.require_cuda_runtime()

    assert "VMware" in str(error.value)


def test_torch_audio_runtime_rejects_mixed_cuda_builds(monkeypatch):
    monkeypatch.setattr(
        hardware,
        "_probe_torch_runtime",
        lambda: _fake_probe(
            version="2.11.0+cu126",
            cuda_version="12.6",
            audio_version="2.11.0+cu128",
        ),
    )

    status = hardware.detect_torch_audio_runtime()

    assert status.ready is False
    assert status.code == "torch_audio_build_mismatch"
    assert "cu126" in status.summary
    assert "cu128" in status.summary


def test_torch_audio_runtime_surfaces_import_mismatch(monkeypatch):
    monkeypatch.setattr(
        hardware,
        "_probe_torch_runtime",
        lambda: _fake_probe(
            version="2.11.0+cu126",
            audio_error="Detected that PyTorch and TorchAudio were compiled with different CUDA versions",
        ),
    )

    status = hardware.detect_torch_audio_runtime()

    assert status.code == "torchaudio_mismatch"
    assert "成对重装" in status.guidance
