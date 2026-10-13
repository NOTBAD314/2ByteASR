"""Model Workshop opens without repeated refreshes or re-reads (2026-10-12)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr import model_workshop  # noqa: E402
from twobyteasr.model_workshop import ModelWorkshopPage  # noqa: E402

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def isolated_model_registry(tmp_path, monkeypatch):
    from twobyteasr.runtime_paths import MODEL_ROOT_ENV, USER_DATA_ENV, reset_runtime_paths
    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(tmp_path))
    monkeypatch.setenv(MODEL_ROOT_ENV, str(tmp_path / "models"))
    monkeypatch.setenv(USER_DATA_ENV, str(tmp_path / "local"))
    reset_runtime_paths()
    yield
    reset_runtime_paths()


def _app():
    return QApplication.instance() or QApplication([])


def _settings():
    return {"models": {"primary_asr_backend": "moss", "firered_asr_backend": "local", "qwen_asr_backend": "api"}}


def test_entering_does_not_refresh_again_unless_inputs_changed():
    app = _app()
    settings = _settings()
    page = ModelWorkshopPage(ROOT, settings)
    assert page._refresh_count == 1
    page.update_runtime_settings(settings)  # what every entry / return home does
    page.update_runtime_settings(settings)
    assert page._refresh_count == 1
    settings["models"]["qwen_asr_backend"] = "local"  # the shared dict is mutated in place
    page.update_runtime_settings(settings)
    assert page._refresh_count == 2
    page.refresh()  # explicit refreshes (downloads, removal, storage, language) always run
    assert page._refresh_count == 3
    page.deleteLater()
    app.processEvents()


def test_each_model_state_is_computed_once_per_refresh(monkeypatch):
    app = _app()
    page = ModelWorkshopPage(ROOT, _settings())
    calls = []
    original = ModelWorkshopPage._compute_model_state

    def counted(self, model, role):
        calls.append((model.key, role))
        return original(self, model, role)
    monkeypatch.setattr(ModelWorkshopPage, "_compute_model_state", counted)
    page.refresh()
    assert calls and len(calls) == len(set(calls))
    # Outside a refresh (card clicks, picker) the state is computed fresh.
    calls.clear()
    model = page._cards["moss"].model
    page._model_state(model)
    page._model_state(model)
    assert len(calls) == 2
    page.deleteLater()
    app.processEvents()


def test_reentry_rechecks_registry_off_thread_and_refreshes_only_on_change(monkeypatch):
    import threading
    from twobyteasr import model_registry
    app = _app()
    page = ModelWorkshopPage(ROOT, _settings())
    current = page._registry
    threads = []
    original = model_registry.scan_model_registry

    def scan(**kwargs):
        threads.append(threading.get_ident())
        return original(**kwargs)
    monkeypatch.setattr(model_registry, "scan_model_registry", scan)

    def run_check():
        page._check_registry_in_background()
        end = time.monotonic() + 5
        while page.background_busy() and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
    run_check()
    assert threads and threading.get_ident() not in threads
    assert page._refresh_count == 1  # same files: nothing refreshed

    changed = model_registry.ModelRegistry(current.install_root, current.model_root, dict(current.records),
                                           current.lock_path, error="模型清单读取失败：测试")
    monkeypatch.setattr(model_registry, "scan_model_registry", lambda **kwargs: changed)
    run_check()
    assert page._refresh_count == 2 and page._registry is changed
    page.deleteLater()
    app.processEvents()


def test_lock_file_hash_is_cached_by_mtime_and_size(tmp_path, monkeypatch):
    from twobyteasr import environment
    lock = tmp_path / "dependencies.lock.json"
    lock.write_text(json.dumps({environment._ENVIRONMENTS_LOCK_KEY: {"main": {"python": "3.10"}}}), encoding="utf-8")
    monkeypatch.setattr(environment, "lock_path", lambda: str(lock))
    loads = []
    original = environment.json.load
    monkeypatch.setattr(environment.json, "load", lambda stream: (loads.append(1), original(stream))[1])
    first = environment.environments_hash()
    assert environment.environments_hash() == first and len(loads) == 1
    lock.write_text(json.dumps({environment._ENVIRONMENTS_LOCK_KEY: {"main": {"python": "3.12"}}}), encoding="utf-8")
    os.utime(lock, ns=(time.time_ns(), time.time_ns() + 3_000_000_000))
    assert environment.environments_hash() != first and len(loads) == 2


def test_readiness_receipt_is_reread_only_when_it_changes(tmp_path):
    from twobyteasr.runtime_paths import user_data_root
    folder = user_data_root() / "model-readiness"
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / "moss.json"
    receipt.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    assert model_workshop._readiness_status("moss") == "PASS"
    receipt.write_text(json.dumps({"status": "FAIL", "pad": "x"}), encoding="utf-8")
    os.utime(receipt, ns=(time.time_ns(), time.time_ns() + 3_000_000_000))
    assert model_workshop._readiness_status("moss") == "FAIL"
    assert model_workshop._readiness_status("missing-model") == ""
