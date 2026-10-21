"""Graphics-card reminder before local model downloads (user report 2026-10-15, RTX 2060 6 GB)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from twobyteasr.system import vram_check
from twobyteasr.system.hardware import CudaRuntimeStatus
from twobyteasr.system.vram_check import GpuInventory, assess

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ("moss", "firered_aed", "qwen_asr")   # 本机识别 / 质量优先


def nvidia(memory_mb: int, name: str = "NVIDIA GeForce RTX 2060") -> GpuInventory:
    return GpuInventory("nvidia", name=name, total_mb=memory_mb)


def test_rtx_2060_6gb_cannot_hold_qwen3_asr_and_recommends_moss_pro():
    result = assess(QUALITY, nvidia(6144))
    assert result.level == "insufficient"
    assert result.keys == ("qwen_asr",) and result.minimum_gb == 8
    title, body = vram_check.warning_text(result)
    assert title == "显存不足"
    assert "NVIDIA GeForce RTX 2060（6.0 GB 显存）" in body
    assert "Qwen3-ASR 1.7B 运行时约需 8 GB 以上显存" in body
    assert "MOSS Pro 云端" in body


def test_6gb_card_runs_moss_alone_but_it_is_tight_and_firered_fits():
    moss = assess(["moss"], nvidia(6144))
    assert moss.level == "tight" and moss.comfortable_gb == 8
    title, body = vram_check.warning_text(moss)
    assert title == "显存偏紧" and "MOSS 建议至少 8 GB 显存" in body and "MOSS Pro 云端" in body
    assert assess(["firered_aed"], nvidia(6144)).level == "ok"


def test_enough_memory_says_nothing():
    for card in (nvidia(12288, "RTX 3060"), nvidia(16303, "RTX 5070 Ti"), nvidia(24564, "RTX 4090")):
        result = assess(QUALITY, card)
        assert result.level == "ok" and not result.warn


def test_8gb_card_reported_slightly_under_size_meets_the_8gb_minimum():
    # An "8 GB" card reports 8188 MiB; it is not "insufficient" for an 8 GB minimum.
    result = assess(QUALITY, nvidia(8188, "RTX 4060"))
    assert result.level == "tight" and result.keys == ("qwen_asr",)


def test_4gb_card_is_insufficient_for_moss():
    result = assess(["moss"], nvidia(4096, "GTX 1650"))
    assert result.level == "insufficient" and result.minimum_gb == 5


def test_no_nvidia_card_cuda_models_cannot_run():
    result = assess(QUALITY, GpuInventory("no_nvidia", detail="nvidia-smi not found"))
    assert result.level == "no_nvidia" and result.keys == QUALITY
    title, body = vram_check.warning_text(result)
    assert title == "没有检测到 NVIDIA 显卡"
    assert "需要 NVIDIA 显卡（CUDA）" in body and "MOSS Pro 云端" in body and "NVIDIA 驱动" in body


def test_no_nvidia_card_cpu_models_still_get_a_slower_on_cpu_reminder():
    result = assess(["sensevoice", "qwen_aligner"], GpuInventory("no_nvidia"))
    assert result.level == "cpu_only" and result.warn
    _title, body = vram_check.warning_text(result)
    assert "CPU" in body and "MOSS Pro 云端" in body


def test_memory_that_cannot_be_read_is_said_plainly():
    unread = GpuInventory("unknown", name="NVIDIA GeForce RTX 2060",
                          detail="NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.")
    result = assess(QUALITY, unread)
    assert result.level == "unknown" and result.comfortable_gb == 10
    title, body = vram_check.warning_text(result)
    assert title == "读不到显卡信息"
    assert "检测到 NVIDIA GeForce RTX 2060，但读不到显存" in body and "couldn't communicate" in body
    assert "建议至少 10 GB 显存" in body and "MOSS Pro 云端" in body
    _title, body = vram_check.warning_text(assess(["moss"], GpuInventory("unknown", detail="timeout")))
    assert "读不到显卡型号和显存（timeout）" in body


def test_helper_models_and_apple_computers_are_not_checked():
    assert assess(["firered_vad", "speaker_embedding"], GpuInventory("no_nvidia")).level == "ok"
    assert assess(QUALITY, GpuInventory("not_applicable")).warn is False


def test_large_optional_models_use_their_documented_minimums():
    assert assess(["firered_llm"], nvidia(16303, "RTX 5070 Ti")).level == "ok"
    assert assess(["firered_llm"], nvidia(12288, "RTX 3060")).level == "insufficient"
    assert assess(["omni_asr_llm_7b"], nvidia(16384)).level == "insufficient"
    assert assess(["omni_asr_llm_7b"], nvidia(24576)).level == "ok"


def test_parse_nvidia_smi_takes_every_card_and_skips_unreadable_rows():
    text = "NVIDIA GeForce RTX 2060, 6144\nNVIDIA GeForce RTX 3090, 24576\nTesla X, [N/A]\n"
    assert vram_check.parse_nvidia_smi(text) == [("NVIDIA GeForce RTX 2060", 6144), ("NVIDIA GeForce RTX 3090", 24576)]


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS has no NVIDIA check")
def test_read_inventory_picks_the_largest_card_and_reports_failures(monkeypatch):
    import subprocess
    from twobyteasr.system import processes

    monkeypatch.setattr(vram_check, "_CACHED", None)   # restored after the test
    monkeypatch.setattr(vram_check, "_nvidia_smi", lambda: "nvidia-smi.exe")
    outputs = iter([
        subprocess.CompletedProcess([], 0, "RTX 2060, 6144\nRTX 3090, 24576\n", ""),
        subprocess.CompletedProcess([], 9, "", "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\n"),
    ])
    monkeypatch.setattr(processes, "run_hidden_subprocess", lambda *args, **kwargs: next(outputs))
    card = vram_check.read_gpu_inventory(refresh=True)
    assert card == GpuInventory("nvidia", "RTX 3090", 24576)
    failed = vram_check.read_gpu_inventory(refresh=True)
    assert failed.status == "unknown" and "couldn't communicate" in failed.detail
    monkeypatch.setattr(vram_check, "_nvidia_smi", lambda: "")
    assert vram_check.read_gpu_inventory(refresh=True).status == "no_nvidia"


def test_first_run_cuda_probe_result_is_reused():
    fresh = CudaRuntimeStatus(False, "torch_missing", "", "", "NVIDIA GeForce RTX 2060", 6144)
    assert vram_check.inventory_from_cuda_status(fresh) == nvidia(6144)
    no_card = CudaRuntimeStatus(False, "gpu_or_driver_missing", "", "")
    assert vram_check.inventory_from_cuda_status(no_card).status == "no_nvidia"
    unread = CudaRuntimeStatus(False, "cuda_unavailable", "x", "", "RTX 2060", 0)
    assert vram_check.inventory_from_cuda_status(unread).status == "unknown"
    assert vram_check.inventory_from_cuda_status(None).status == "unknown"


def test_acknowledged_combination_is_not_asked_again(monkeypatch):
    monkeypatch.setattr(vram_check, "_ACKNOWLEDGED", set())
    assert not vram_check.acknowledged(["qwen_asr"])
    vram_check.acknowledge(QUALITY)
    assert vram_check.acknowledged(["qwen_asr"]) and vram_check.acknowledged(QUALITY)
    assert not vram_check.acknowledged(["omni_asr_llm_7b"])


@pytest.fixture()
def workshop(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("twobyteasr.local_models.model_workshop.installed_model_keys", lambda _root: set())
    monkeypatch.setattr(vram_check, "_ACKNOWLEDGED", set())
    page = ModelWorkshopPage(ROOT, {"models": {}})
    yield page
    page.deleteLater()
    app.processEvents()


def test_workshop_download_reminds_and_moss_pro_button_uses_the_moss_pro_card_path(workshop, monkeypatch):
    monkeypatch.setattr(vram_check, "read_gpu_inventory", lambda **_kwargs: nvidia(6144))
    downloads, presets, asked = [], [], []
    monkeypatch.setattr(workshop, "download_combination", lambda keys, name: downloads.append(tuple(keys)))
    workshop.api_preset_requested.connect(presets.append)
    model = workshop._cards["qwen_local"].model

    monkeypatch.setattr(workshop, "_ask_vram", lambda assessment: asked.append(assessment.level) or "online")
    workshop._download(model)
    assert downloads == [] and presets == ["mosi_moss_pro"] and workshop.api_target_role == "primary"

    monkeypatch.setattr(workshop, "_ask_vram", lambda assessment: asked.append(assessment.level) or "cancel")
    workshop._download(model)
    assert downloads == []

    monkeypatch.setattr(workshop, "_ask_vram", lambda assessment: asked.append(assessment.level) or "keep")
    workshop._download(model)
    assert downloads == [("qwen_asr",)]
    # Chosen once: the next click downloads without asking again.
    workshop._download(model)
    assert downloads == [("qwen_asr",)] * 2 and asked == ["insufficient"] * 3


def test_workshop_download_on_a_big_card_or_with_a_broken_check_goes_straight_on(workshop, monkeypatch):
    downloads = []
    monkeypatch.setattr(workshop, "download_combination", lambda keys, name: downloads.append(tuple(keys)))
    monkeypatch.setattr(workshop, "_ask_vram", lambda assessment: pytest.fail("no reminder expected"))
    monkeypatch.setattr(vram_check, "read_gpu_inventory", lambda **_kwargs: nvidia(16303, "RTX 5070 Ti"))
    workshop._download(workshop._cards["qwen_local"].model)

    def broken(**_kwargs):
        raise RuntimeError("probe crashed")
    monkeypatch.setattr(vram_check, "read_gpu_inventory", broken)
    workshop._download(workshop._cards["moss"].model)
    assert downloads == [("qwen_asr",), ("moss",)]


@pytest.mark.parametrize("preset", ["mosi_moss_pro", ""])
@pytest.mark.parametrize("tour", [False, True])
def test_first_run_cloud_choice_sets_up_moss_pro(monkeypatch, preset, tour):
    """云端识别 is MOSS Pro + a local timeline model (2026-10-21).

    With the tutorial its 主力转写 step opens the MOSS Pro guide and the timeline
    model downloads when the tutorial is over; without it the guide opens at
    once and the download follows it. Either way the service is MOSS Pro.
    """
    import time
    from types import SimpleNamespace
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog
    from twobyteasr.app import quick_setup, ui

    app = QApplication.instance() or QApplication([])

    class FakeQuickSetup:
        def __init__(self, parent, size_of=None):
            self.choice, self.backends, self.api_preset, self.tour = "cloud", ("api", "local", "off"), preset, tour
            self.tour_check = SimpleNamespace(isChecked=lambda: tour, setChecked=lambda value: None)
            self.source_combo = SimpleNamespace(currentData=lambda: "MODELSCOPE")

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(quick_setup, "QuickSetupDialog", FakeQuickSetup)
    saved = []
    monkeypatch.setattr(ui, "_apply_setup_choice", lambda parent, *args, **kwargs: saved.append(args))
    events = []
    combo = SimpleNamespace(findData=lambda key: 7 if key == "mosi_moss_pro" else -1,
                            setCurrentIndex=lambda index: events.append(("provider", index)))
    parent = SimpleNamespace(qwen_asr_api_provider=combo,
                             _apply_asr_preset_fields=lambda key: events.append(("fields", key)),
                             _open_api_setup_guide=lambda preset_key="": events.append(("guide", preset_key)),
                             _start_first_run_downloads=lambda: events.append(("download",)))
    assert ui._open_quick_setup(parent) is True
    assert saved == [("api", "local", "off", ("firered_aed",))]
    # The source picked in the chooser goes with the timeline download (merged with the Codex round, 2026-10-21).
    assert parent._first_run_downloads == ("api", ("firered_aed",), "MODELSCOPE")
    assert parent._quick_setup_tour is tour
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        app.processEvents()
    assert events[:2] == [("provider", 7), ("fields", "mosi_moss_pro")]
    assert events[2:] == ([] if tour else [("guide", "mosi_moss_pro"), ("download",)])
