from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from twobyteasr.local_models.model_storage import residual_files, scan_storage, verify_model_files  # noqa: E402
from twobyteasr.local_models.model_workshop import MODELS, ModelWorkshopPage  # noqa: E402
from twobyteasr.download_sources import resolve_from_lock  # noqa: E402


ROOT = Path(__file__).parents[1]
ADVANCED_KEYS = {"firered_llm", "glm_asr_nano", "canary_qwen", "omni_asr_llm_7b"}


def _app():
    return QApplication.instance() or QApplication([])


def test_advanced_models_use_pinned_official_metadata_and_remain_unselectable():
    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    by_key = {model.key: model for model in MODELS}
    expected = {
        "firered_llm": ("FireRedTeam/FireRedASR2-LLM", 18870832417, ".venv-firered-llm"),
        "glm_asr_nano": ("zai-org/GLM-ASR-Nano-2512", 4522615511, ".venv-glm-asr"),
        "canary_qwen": ("nvidia/canary-qwen-2.5b", 5119123006, ".venv-canary-qwen"),
        "omni_asr_llm_7b": ("facebook/omniASR-LLM-7B", 31205174710, ".venv-omni-asr"),
    }
    assert ADVANCED_KEYS <= by_key.keys()
    for key, (repository, size, environment) in expected.items():
        model = by_key[key]
        spec = lock["models"][key]
        assert model.role == "primary"
        assert model.download_key == key
        assert model.runtime_available is (key == "firered_llm")
        assert spec["repository"] == repository
        assert spec["download_bytes"] == size
        assert spec["runtime_environment"] == environment
        assert len(spec["revision"]) == 40


def test_advanced_models_reuse_existing_source_resolver():
    firered = resolve_from_lock("firered_llm", "model.pth.tar", "AUTO", lock_path=ROOT / "dependencies.lock.json")
    assert [item.mode for item in firered] == ["MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL"]
    for key, file_name in {
        "glm_asr_nano": "model.safetensors",
        "canary_qwen": "model.safetensors",
        "omni_asr_llm_7b": "omniASR-LLM-7B.pt",
    }.items():
        resolved = resolve_from_lock(key, file_name, "AUTO", lock_path=ROOT / "dependencies.lock.json")
        assert [item.mode for item in resolved] == [
            "MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL",
        ]
        assert all(item.revision for item in resolved)


def test_storage_scan_counts_model_and_shared_runtime_separately(tmp_path):
    models = [model for model in MODELS if model.key in {"firered", "firered_llm"}]
    payload = {
        "models": {
            "firered_aed": {
                "path": "models/aed", "required_files": ["model.bin"],
                "download_bytes": 10, "runtime_environment": ".venv-main", "revision": "a",
            },
            "firered_llm": {
                "path": "models/llm", "required_files": ["model.bin"],
                "download_bytes": 20, "runtime_environment": ".venv-firered-llm", "revision": "b",
            },
        }
    }
    (tmp_path / "dependencies.lock.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "models" / "aed").mkdir(parents=True)
    (tmp_path / "models" / "aed" / "model.bin").write_bytes(b"1234")
    (tmp_path / ".venv-main").mkdir()
    (tmp_path / ".venv-main" / "runtime.bin").write_bytes(b"123456")

    entries = scan_storage(tmp_path, models, {"firered"})
    by_key = {entry.key: entry for entry in entries}
    assert by_key["firered_aed"].model_key == "firered"
    assert by_key["firered_aed"].installed is True
    assert by_key["firered_aed"].actual_bytes == 4
    assert by_key["firered_aed"].environment_bytes == 6
    assert by_key["firered_aed"].current is True
    assert by_key["firered_llm"].installed is False
    assert by_key["firered_llm"].expected_bytes == 20
    assert by_key["firered_llm"].environment_bytes == 0


def test_residual_scan_requires_receipted_staging_and_preserves_development_tmp(tmp_path, monkeypatch):
    inside_model = tmp_path / "models" / "candidate" / "weight.part"
    inside_tmp = tmp_path / "tmp" / "download.tmp"
    ordinary = tmp_path / "models" / "candidate" / "config.json"
    for path in (inside_model, inside_tmp, ordinary):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    outside = tmp_path.parent / "global-hf-cache-test.part"
    outside.write_bytes(b"do-not-touch")
    from types import SimpleNamespace
    monkeypatch.setattr('twobyteasr.local_models.model_storage.get_runtime_paths',lambda:SimpleNamespace(model_root=tmp_path/'models'))
    from twobyteasr.local_models.model_download_cache import write_transaction
    stage=tmp_path/'models/.downloads/candidate/hf/identity';stage.mkdir(parents=True)
    staged=stage/'weight.part';staged.write_bytes(b'owned')
    write_transaction(stage,model_key='candidate',destination=tmp_path/'models/candidate',files=['weight.part'],state='paused')
    try:
        found = set(residual_files(tmp_path))
        assert found == {staged}
        assert inside_model.read_bytes()==b'x' and inside_tmp.read_bytes()==b'x'
        assert outside.read_bytes() == b"do-not-touch"
    finally:
        outside.unlink(missing_ok=True)


def test_storage_verification_requires_locked_files(tmp_path):
    payload = {"models": {"demo": {"path": "models/demo", "required_files": ["a.bin"]}}}
    (tmp_path / "dependencies.lock.json").write_text(json.dumps(payload), encoding="utf-8")
    ok, message = verify_model_files(tmp_path, "demo")
    assert ok is False and "缺少关键文件" in message
    (tmp_path / "models" / "demo").mkdir(parents=True)
    (tmp_path / "models" / "demo" / "a.bin").write_bytes(b"ok")
    ok, message = verify_model_files(tmp_path, "demo")
    assert ok is True and "通过" in message


def test_current_model_protection_covers_all_roles(monkeypatch):
    app = _app()
    monkeypatch.setattr("twobyteasr.local_models.model_workshop.installed_model_keys", lambda _root: set())
    page = ModelWorkshopPage(ROOT, {"models": {
        "primary_asr_backend": "moss",
        "firered_asr_backend": "local",
        "qwen_asr_backend": "local",
    }})
    assert page._current_model_keys() == {"moss", "firered", "qwen_local"}
    for key in ADVANCED_KEYS - {"firered_llm"}:
        model = page._cards[key].model
        assert page._model_state(model, "primary") == "missing"
        page._installed.add(model.download_key)
        assert page._model_state(model, "primary") == "downloaded"
        assert page._action_text(model, "downloaded") == ("已下载 · 接入中", False)
    firered_llm = page._cards["firered_llm"].model
    page._installed.add(firered_llm.download_key)
    assert page._model_state(firered_llm, "primary") == "installed"
    assert page._action_text(firered_llm, "installed") == ("使用", True)
    page.deleteLater()
    app.processEvents()


def test_omni_download_warns_on_sub_17_gib_gpu_but_allows_override(monkeypatch):
    # Since 2026-10-15 the general graphics-card reminder (system/vram_check.py) covers this.
    from twobyteasr.system import vram_check
    app = _app()
    monkeypatch.setattr("twobyteasr.local_models.model_workshop.installed_model_keys", lambda _root: set())
    monkeypatch.setattr(vram_check, "read_gpu_inventory",
                        lambda **_kwargs: vram_check.GpuInventory("nvidia", "RTX Test", 16 * 1024))
    monkeypatch.setattr(vram_check, "_ACKNOWLEDGED", set())
    page = ModelWorkshopPage(ROOT, {"models": {}})
    model = page._cards["omni_asr_llm_7b"].model
    downloads = []
    monkeypatch.setattr(page, "download_combination", lambda keys, name: downloads.append((keys, name)))

    asked = []
    monkeypatch.setattr(page, "_ask_vram", lambda assessment: asked.append(assessment.level) or "cancel")
    page._download(model)
    assert downloads == [] and asked == ["insufficient"]
    monkeypatch.setattr(page, "_ask_vram", lambda assessment: "keep")
    page._download(model)
    assert downloads == [(["omni_asr_llm_7b"], "Omnilingual ASR LLM 7B")]
    page.deleteLater()
    app.processEvents()
