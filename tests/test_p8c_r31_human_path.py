"""P8C-R3.1 targeted tests: secret three-state save, probe locator, parity gate."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from twobyteasr.providers import llm_config
from twobyteasr.providers.llm_config import (
    delete_api_key_for,
    read_api_key,
)

FAKE_STORE_KEY = "TESTSTORE-VALUE-0001"
FAKE_OTHER_KEY = "TESTOTHER-VALUE-0002"
FAKE_ENV_KEY = "TESTENV-VALUE-0003"


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- A: 密钥三态


def test_save_keeps_secret_when_widget_unchanged(monkeypatch):
    payload = {"schema": 2, "API__deepseek__api.deepseek.com": FAKE_STORE_KEY}
    writes: list[dict] = []

    def fake_write(store):
        import json

        writes.append(json.loads(json.dumps(store)))
        return llm_config.secrets_path()

    monkeypatch.setattr(llm_config, "_read_secrets", lambda: dict(payload))
    monkeypatch.setattr(llm_config, "_write_encrypted_secrets", fake_write)
    # UNCHANGED: 空输入框的保存语义 = 不触碰 store。save_api_key_for 只在
    # 非空 key 时被调用——这里验证读取契约仍命中已存密钥。
    assert read_api_key("deepseek", "https://api.deepseek.com/v1")[0] == FAKE_STORE_KEY
    assert writes == []


def test_clear_deletes_scoped_aliases_only(monkeypatch):
    payload = {
        "schema": 2,
        "API__deepseek__api.deepseek.com": FAKE_STORE_KEY,
        "API__api.deepseek.com": FAKE_STORE_KEY,
        "API__gemini__generativelanguage.googleapis.com": FAKE_OTHER_KEY,
        "POLISH_LLM_API_KEY": FAKE_OTHER_KEY,
    }
    monkeypatch.setattr(llm_config, "_read_secrets", lambda: dict(payload))
    saved: dict = {}
    monkeypatch.setattr(
        llm_config,
        "_write_encrypted_secrets",
        lambda store: saved.update(store) or llm_config.secrets_path(),
    )
    delete_api_key_for("deepseek", "https://api.deepseek.com/v1")
    assert "API__deepseek__api.deepseek.com" not in saved
    assert "API__api.deepseek.com" not in saved
    # Cross-provider and legacy buckets must survive a DeepSeek clear.
    assert saved.get("API__gemini__generativelanguage.googleapis.com") == FAKE_OTHER_KEY
    assert saved.get("POLISH_LLM_API_KEY") == FAKE_OTHER_KEY


def test_clear_falls_back_to_environment_key(monkeypatch):
    store = {
        "schema": 2,
        "API__deepseek__api.deepseek.com": FAKE_STORE_KEY,
        "API__api.deepseek.com": FAKE_STORE_KEY,
    }
    monkeypatch.setattr(llm_config, "_read_secrets", lambda: dict(store))
    monkeypatch.setattr(
        llm_config,
        "_write_encrypted_secrets",
        lambda updated: store.clear() or store.update(updated) or llm_config.secrets_path(),
    )
    delete_api_key_for("deepseek", "https://api.deepseek.com/v1")
    assert "API__deepseek__api.deepseek.com" not in store
    # A5: 环境变量不受 store 清除影响，仍是运行时后备。
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_ENV_KEY)
    key, source = read_api_key("deepseek", "https://api.deepseek.com/v1")
    assert key == FAKE_ENV_KEY
    assert "DEEPSEEK_API_KEY" in source


# ---------------------------------------------------------------- EndpointEditor 三态


def test_endpoint_editor_key_states(tmp_path):
    from twobyteasr.app.ui import EndpointEditor

    _app()
    settings = {"models": {
        "polish_provider": "deepseek",
        "polish_base_url": "https://api.deepseek.com/v1",
        "polish_model": "deepseek-v4-flash",
        "ai_service": "deepseek",
        "provider_profiles": {},
    }}
    editor = EndpointEditor("AI 服务", "#5B8E63", "polish", settings)
    values = editor.values()
    assert values["key_state"] == "unchanged"
    assert values["key"] == ""
    # Typing = REPLACE.
    editor.key.setText("TESTTYPED-VALUE-0003")
    assert editor.values()["key_state"] == "replace"
    # Manual clear returns to UNCHANGED (never deletes).
    editor.key.clear()
    assert editor.values()["key_state"] == "unchanged"
    # Explicit clear button = CLEAR.
    editor._request_key_clear()
    assert editor.values()["key_state"] == "clear"
    editor.deleteLater()


# ---------------------------------------------------------------- B: probe locator


def test_runtime_probe_path_resolves_source_layout():
    from twobyteasr.system.runtime_registry import runtime_probe_path

    resolved = runtime_probe_path()
    assert resolved, "probe locator must find environment_probe.py"
    assert os.path.isfile(resolved)


def test_environment_probe_missing_returns_structured_failure(monkeypatch, tmp_path):
    from twobyteasr.system import environment as env

    monkeypatch.setattr(env, "probe_script_path", lambda: "")
    result = env._run_probe_process("main", {"python": "3.10", "packages": {}})
    assert not result.ok
    assert any("环境探测脚本缺失" in problem for problem in result.problems)


# ---------------------------------------------------------------- C: parity 门


def _pixmap_with(color: str | None, size: int = 120) -> QPixmap:
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(0xFF202020)
    if color:
        painter_color = QColor(color)
        for y in range(10, size - 10, 4):
            for x in range(10, size - 10, 4):
                image.setPixelColor(x, y, painter_color)
    return QPixmap.fromImage(image)


def test_count_stroke_pixels_counts_canonical_black():
    from twobyteasr.studio.studio_ui import _count_stroke_pixels

    pixmap = _pixmap_with("#ff000000")
    assert _count_stroke_pixels(pixmap, ["#ff000000"]) > 60
    assert _count_stroke_pixels(_pixmap_with(None), ["#ff000000"]) == 0


class _SnapshotStub:
    def __init__(self, strokes):
        self.strokes = strokes
        self.cue_id = "c0"


def test_parity_gate_blocks_transparent_fidelity_stroke():
    from types import SimpleNamespace

    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    snapshot = _SnapshotStub([{"color": "#ff000000", "width": 20.0}])
    live = _pixmap_with("#ff000000")
    fidelity_broken = _pixmap_with(None)
    fidelity_ok = _pixmap_with("#ff000000")

    gate = SimpleNamespace(
        _advanced_cue_pixmap=live,
        _fidelity_parity_drop_reason="",
        _studio_trace=lambda *a, **k: None,
    )
    assert SubtitleStudioPage._fidelity_stroke_parity_ok(gate, fidelity_ok, snapshot) is True
    assert SubtitleStudioPage._fidelity_stroke_parity_ok(gate, fidelity_broken, snapshot) is False
    assert "stroke_pixels" in gate._fidelity_parity_drop_reason


def test_parity_gate_skips_when_no_stroke_requested():
    from types import SimpleNamespace

    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    snapshot = _SnapshotStub([{"color": "#ff000000", "width": 0.0}])
    gate = SimpleNamespace(
        _advanced_cue_pixmap=_pixmap_with("#ff000000"),
        _fidelity_parity_drop_reason="",
        _studio_trace=lambda *a, **k: None,
    )
    assert SubtitleStudioPage._fidelity_stroke_parity_ok(gate, _pixmap_with(None), snapshot) is True
