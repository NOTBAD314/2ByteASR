"""2026-10-28 (Mac user): the Qwen3 aligner was downloaded, yet the home card
still said 需要下载 and 「开始前还需处理：字幕时间轴」.

The home card (and the Studio 识别字幕 sheet, same rule) kept its own copy of
the files each choice needs, without the Apple Silicon (MLX) choices, so
``mlx_qwen_aligner`` and both MLX Qwen3-ASR primaries could never be ready.
For Japanese or English audio the card also checked the CPU/CUDA aligner,
although the run uses the MLX one (run_qwen_aligner_worker).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import twobyteasr.app.ui as ui_mod
from twobyteasr.app.ui import PRIMARY_MODEL_CHOICES, REVIEW_MODEL_CHOICES, TIMELINE_MODEL_CHOICES, MainWindow
from twobyteasr.recognition.recognition_choices import HostProfile

APPLE_SILICON = HostProfile('darwin', 'arm64', nvidia_tool=False, main_runtime=True, mlx_runtime=True)
WINDOWS_NVIDIA = HostProfile('win32', 'amd64', nvidia_tool=True, main_runtime=True, mlx_runtime=False)


@pytest.fixture
def window():
    import subtitle_core as legacy
    QApplication.instance() or QApplication([])
    win = MainWindow([], legacy, object(), None)
    yield win
    win.close()


def _state(win, monkeypatch, installed, host, spoken='zh', **backends):
    monkeypatch.setattr(ui_mod, "installed_model_keys", lambda _root: set(installed))
    monkeypatch.setattr(win, "_subtitle_language_options", lambda: {"recognition_language": spoken})
    win._home_host_profile = host
    return win.recognition_role_state(backends=backends)["roles"]


def test_downloaded_apple_silicon_aligner_is_ready_on_the_home_card(window, monkeypatch):
    # The user's plan: FireRed on the Apple GPU, MLX Qwen3 aligner, SenseVoice.
    roles = _state(window, monkeypatch, {"firered_aed", "mlx_qwen_aligner", "sensevoice"}, APPLE_SILICON,
                   primary="firered", timeline="mlx_qwen_aligner", review="sensevoice")
    assert roles["timeline"]["status_key"] == "已就绪"
    assert roles["timeline"]["recovery"] == ""
    assert roles["timeline"]["short"] == "Aligner"   # not the raw key mlx_qwen_aligner
    assert {role: facts["status_key"] for role, facts in roles.items()} == dict.fromkeys(roles, "已就绪")


def test_apple_silicon_aligner_still_asks_for_its_own_download(window, monkeypatch):
    roles = _state(window, monkeypatch, {"firered_aed", "qwen_aligner"}, APPLE_SILICON,
                   primary="firered", timeline="mlx_qwen_aligner", review="off")
    assert roles["timeline"]["status_key"] == "需要下载"


@pytest.mark.parametrize("spoken", ["ja", "en", "ko"])
def test_apple_silicon_aligner_counts_for_aligned_languages(window, monkeypatch, spoken):
    roles = _state(window, monkeypatch, {"mlx_qwen3_asr_0_6b", "mlx_qwen_aligner"}, APPLE_SILICON, spoken=spoken,
                   primary="mlx_qwen3_asr", timeline="mlx_qwen_aligner", review="off")
    assert roles["timeline"]["backend"] == "mlx_qwen_aligner"
    assert roles["timeline"]["status_key"] == "已就绪"
    assert roles["timeline"]["note"] is None
    assert roles["primary"]["status_key"] == "已就绪"
    assert roles["primary"]["short"] == "Qwen3-ASR 0.6B"


def test_chinese_timing_models_still_hand_other_languages_to_the_cpu_aligner(window, monkeypatch):
    roles = _state(window, monkeypatch, {"firered_aed", "mlx_qwen_aligner"}, WINDOWS_NVIDIA, spoken="ja",
                   primary="firered", timeline="local", review="off")
    assert roles["timeline"]["backend"] == "qwen_aligner"
    assert roles["timeline"]["status_key"] == "需要下载"
    assert roles["timeline"]["note"]


@pytest.mark.parametrize("role,choices", [("primary", PRIMARY_MODEL_CHOICES), ("review", REVIEW_MODEL_CHOICES),
                                          ("timeline", TIMELINE_MODEL_CHOICES)])
def test_every_selector_choice_is_ready_once_its_files_exist(window, monkeypatch, role, choices):
    others = {"primary": "none", "timeline": "off", "review": "off"}
    for _label, backend, needs in choices:
        host = APPLE_SILICON if backend.startswith("mlx_") else WINDOWS_NVIDIA
        roles = _state(window, monkeypatch, needs, host, **dict(others, **{role: backend}))
        assert roles[role]["status_key"] == "已就绪", backend
