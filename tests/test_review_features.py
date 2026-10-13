"""Tests for the review-pass features: instance lock, first-run wizard,
media append/retry merging, i18n parity and model-integrity hints."""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


def test_instance_lock_is_exclusive(tmp_path, monkeypatch):
    from twobyteasr.ui import _acquire_instance_lock

    # 隔离：避免与用户正在运行的真实实例锁冲突
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    first = _acquire_instance_lock()
    assert first is not None, "first instance should acquire the lock"
    try:
        second = _acquire_instance_lock()
        assert second is None, "second instance must not acquire the lock"
    finally:
        first.release()
    third = _acquire_instance_lock()
    assert third is not None, "lock is released after unlock"
    third.release()


def test_first_run_guide_dialog_constructs_and_detects_hardware():
    from twobyteasr.ui import GuidedSetupDialog

    app = QApplication.instance() or QApplication([])
    dialog = GuidedSetupDialog()
    assert [dialog.lang_combo.itemData(i) for i in range(dialog.lang_combo.count())] == ['zh', 'zh-Hant', 'en', 'ja']
    # _detect_gpu must not raise even without nvidia-smi (CI)
    assert dialog.gpu_info.text()
    assert dialog.preset_group.button(0).minimumHeight() >= 90
    dialog._apply_preset("light")
    assert dialog.selected_backends() == ("sensevoice", "off", "off")
    assert dialog.selected_download_keys() == ("sensevoice",)
    assert dialog.preset_group.button(1).isChecked()
    # The real CUDA probe is still running: let it report before the dialog becomes garbage, or a
    # later collection on its output-pump thread tears the dialog down off the GUI thread.
    deadline = time.monotonic() + 30
    while dialog._cuda_status is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_first_run_guide_switches_presets_without_waiting_for_cuda_probe(monkeypatch):
    from twobyteasr import ui

    app = QApplication.instance() or QApplication([])
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_probe():
        calls.append(1)
        started.set()
        release.wait(timeout=2)
        return SimpleNamespace(ready=False, gpu_name="")

    monkeypatch.setattr(ui, "detect_cuda_runtime", slow_probe)
    before = time.perf_counter()
    dialog = ui.GuidedSetupDialog()
    assert time.perf_counter() - before < 0.5
    assert started.wait(timeout=1)

    before = time.perf_counter()
    for _ in range(25):
        dialog._apply_preset("light")
        dialog._apply_preset("online")
        dialog._apply_preset("quality")
    assert time.perf_counter() - before < 0.5
    assert calls == [1]
    assert dialog.selected_backends() == dialog.PRESETS["quality"]

    release.set()
    deadline = time.monotonic() + 1
    while dialog._cuda_status is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert dialog._cuda_status is not None
    dialog.close()


@pytest.mark.parametrize(
    ("code", "gpu_name", "style", "phrase"),
    [
        # Fresh install: no PyTorch yet, but the card is there; one-click install brings CUDA PyTorch.
        ("torch_missing", "NVIDIA GeForce RTX 4060 Laptop GPU", "statusGood", "一键安装会同时装好 CUDA 版 PyTorch"),
        ("torch_missing", "", "statusBad", "未检测到 NVIDIA 显卡或驱动"),
        ("cpu_torch", "NVIDIA GeForce RTX 4060 Laptop GPU", "statusBad", "当前设备还不能运行"),
    ],
)
def test_first_run_guide_cuda_text_on_fresh_install(monkeypatch, code, gpu_name, style, phrase):
    import gc

    from twobyteasr import ui
    from twobyteasr.hardware import CudaRuntimeStatus

    app = QApplication.instance() or QApplication([])
    # Earlier dialogs may still be cyclic garbage; collect them here on the GUI thread, not in
    # whichever worker thread (e.g. a real CUDA probe's output pump) happens to trigger GC later.
    gc.collect()
    status = CudaRuntimeStatus(False, code, "", "", gpu_name)
    monkeypatch.setattr(ui, "detect_cuda_runtime", lambda: status)
    dialog = ui.GuidedSetupDialog()
    deadline = time.monotonic() + 2
    while dialog._cuda_status is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert dialog._cuda_status is status
    assert dialog.selected_backends() == dialog.PRESETS["quality"]
    assert dialog.gpu_info.objectName() == style
    assert phrase in dialog.gpu_info.text()
    if gpu_name and code == "torch_missing":
        assert gpu_name in dialog.gpu_info.text()
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_merge_media_paths_appends_and_dedupes(tmp_path):
    from twobyteasr.ui import _merge_media_paths

    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    first.touch()
    second.touch()
    merged = _merge_media_paths([str(first)], [str(second), str(first)])
    assert len(merged) == 2
    assert str(first) in merged and str(second) in merged
    # order preserved: existing first, then new items
    assert merged[0] == str(first)


def test_i18n_tables_have_identical_keys():
    import twobyteasr.i18n as i18n_mod

    en_keys = set(i18n_mod._TRANSLATIONS["en"])
    ja_keys = set(i18n_mod._TRANSLATIONS["ja"])
    assert en_keys == ja_keys
    # Review-pass entries must exist in both languages
    for key in ("重试失败项", "首次使用引导", "2ByteASR 已在运行"):
        assert key in en_keys


def test_model_integrity_missing_file_hint(tmp_path, monkeypatch):
    from twobyteasr import model_integrity as mi

    fake_lock = {
        "models": {
            "fake-model": {
                "path": "models/fake-model",
                "sha256": {"model.ckpt": "0" * 64},
            }
        }
    }
    monkeypatch.setattr(mi, "load_dependency_lock", lambda root=None: fake_lock)
    (tmp_path / "models" / "fake-model").mkdir(parents=True)
    with pytest.raises(mi.ModelIntegrityError) as excinfo:
        mi.verify_model_files("fake-model", root=tmp_path)
    message = str(excinfo.value)
    assert "模型关键文件缺失" in message
    assert "download_models.bat" in message
