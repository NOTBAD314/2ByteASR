from __future__ import annotations

import os
import hashlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from twobyteasr.model_workshop import (  # noqa: E402
    MODELS,
    ModelWorkshopPage,
    ModelDownloadDialog,
    _model_roles,
    _runtime_role_available,
)
from twobyteasr import repository_download as repo_download  # noqa: E402


ROOT = Path(__file__).parents[1]


def _app():
    return QApplication.instance() or QApplication([])


def test_asr_text_capability_populates_primary_and_review_without_id_whitelist():
    by_key = {model.key: model for model in MODELS}
    for key in {
        "moss", "firered", "qwen_local", "firered_llm", "glm_asr_nano",
        "canary_qwen", "omni_asr_llm_7b", "sensevoice", "paraformer",
        "whisper", "funasr_nano",
    }:
        assert "ASR_TEXT" in by_key[key].asr_capabilities
        assert "primary" in _model_roles(by_key[key])
        assert "review" in _model_roles(by_key[key])


def test_timeline_role_requires_timestamp_or_alignment_capability():
    by_key = {model.key: model for model in MODELS}
    assert "timeline" not in _model_roles(by_key["moss"])
    assert "timeline" not in _model_roles(by_key["firered_llm"])
    assert "timeline" in _model_roles(by_key["firered"])
    assert "timeline" in _model_roles(by_key["paraformer"])
    assert "timeline" in _model_roles(by_key["whisper"])
    assert "timeline" in _model_roles(by_key["qwen_aligner"])


def test_unverified_advanced_adapters_are_visible_for_both_text_roles_but_disabled():
    by_key = {model.key: model for model in MODELS}
    for key in {"glm_asr_nano", "canary_qwen", "omni_asr_llm_7b"}:
        model = by_key[key]
        assert set(_model_roles(model)) == {"primary", "review"}
        assert not _runtime_role_available(model, "primary")
        assert not _runtime_role_available(model, "review")
    firered_llm = by_key["firered_llm"]
    assert _runtime_role_available(firered_llm, "primary")
    assert _runtime_role_available(firered_llm, "review")


def test_duplicate_primary_review_checkpoint_warns_and_defaults_to_cancel(monkeypatch):
    app = _app()
    settings = {"models": {
        "primary_asr_backend": "qwen_local",
        "firered_asr_backend": "off",
        "qwen_asr_backend": "off",
    }}
    monkeypatch.setattr(
        "twobyteasr.model_workshop.installed_model_keys",
        lambda _root: {"qwen_asr"},
    )
    page = ModelWorkshopPage(ROOT, settings)
    emitted = []
    page.backend_requested.connect(lambda role, backend: emitted.append((role, backend)))
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    page._request_model_selection(page._cards["qwen_local"].model, "installed", role="review")

    assert emitted == []
    page.deleteLater()
    app.processEvents()


def _download_spec(payload: bytes) -> dict:
    digest = hashlib.sha256(payload).hexdigest()
    files = ["nested/config.json"]
    return {
        "repository": "official/repo",
        "revision": "abc123",
        "modelscope_repository": "mirror/repo",
        "modelscope_revision": "master",
        "required_files": files,
        "source_manifests": {
            "hf": {
                "repository": "official/repo",
                "revision": "abc123",
                "files": files,
                "sha256": {"nested/config.json": digest},
            },
            "modelscope": {
                "repository": "mirror/repo",
                "revision": "master",
                "files": files,
                "sha256": {},
            },
        },
    }


def test_repository_adapter_auto_fails_over_to_official_and_preserves_nested_path(tmp_path, monkeypatch):
    payload = b'{"model":"demo"}'
    attempts = []

    def download_direct(manifest, staging, relative):
        attempts.append(manifest.mode)
        if manifest.mode == "MODELSCOPE":
            raise RuntimeError("not found")
        path = staging / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    monkeypatch.setattr(repo_download, "_download_direct", download_direct)
    destination = tmp_path / "model"
    selected = repo_download.download_model(
        model_key="demo",
        spec=_download_spec(payload),
        destination=destination,
        mode="AUTO",
        staging_root=tmp_path / "staging",
    )

    assert selected == "HF_OFFICIAL"
    assert attempts == ["MODELSCOPE", "HF_OFFICIAL"]
    assert (destination / "nested" / "config.json").read_bytes() == payload


def test_repository_adapter_auto_reaches_official_after_two_source_failures(tmp_path, monkeypatch):
    payload = b"official"
    attempts = []

    def download_direct(manifest, staging, relative):
        attempts.append(manifest.mode)
        if manifest.mode in {"MODELSCOPE", "HF_MIRROR"}:
            raise RuntimeError("mirror unavailable")
        path = staging / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    monkeypatch.setattr(repo_download, "_download_direct", download_direct)
    selected = repo_download.download_model(
        model_key="demo",
        spec=_download_spec(payload),
        destination=tmp_path / "model",
        mode="AUTO",
        staging_root=tmp_path / "staging",
    )

    assert selected == "HF_OFFICIAL"
    assert attempts == ["MODELSCOPE", "HF_OFFICIAL"]


def test_explicit_repository_source_never_falls_back(tmp_path, monkeypatch):
    attempts = []

    def fail_modelscope(manifest, _staging, _relative):
        attempts.append(manifest.mode)
        raise RuntimeError("missing")

    monkeypatch.setattr(repo_download, "_download_direct", fail_modelscope)
    try:
        repo_download.download_model(
            model_key="demo",
            spec=_download_spec(b"demo"),
            destination=tmp_path / "model",
            mode="MODELSCOPE",
            staging_root=tmp_path / "staging",
        )
    except RuntimeError as exc:
        assert "所有候选来源均失败" in str(exc)
    else:
        raise AssertionError("explicit source failure unexpectedly succeeded")
    assert attempts == ["MODELSCOPE"]


def test_firered_source_hashes_are_not_shared_with_modelscope():
    import json

    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    manifests = lock["models"]["firered_llm"]["source_manifests"]
    assert manifests["hf"]["revision"] == lock["models"]["firered_llm"]["revision"]
    assert manifests["modelscope"]["revision"] == "master"
    assert manifests["hf"]["sha256"]
    assert manifests["modelscope"]["sha256"] == {
        "Qwen2-7B-Instruct/config.json":
            "8b9a4f6c0acf4854a2d301616d4203039c3d7972cb0a557dae98686b6c3ae4b2",
        "asr_encoder.pth.tar":
            "6cfa83b4d692c0ac8b61a767fc4253a6350c11e1edcdf6418d040b41240b900e",
    }
    assert set(manifests["modelscope"]["sha256"]) < set(manifests["hf"]["sha256"])


def test_shared_model_hashes_apply_to_modelscope_and_hf_downloads():
    spec = {
        "repository": "official/repo",
        "revision": "abc",
        "modelscope_repository": "mirror/repo",
        "modelscope_revision": "master",
        "required_files": ["model.bin"],
        "sha256": {"model.bin": "a" * 64},
    }
    for mode in ("MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL"):
        manifest = repo_download.source_manifest(spec, mode)
        assert manifest is not None
        assert manifest.sha256 == {"model.bin": "a" * 64}


def test_every_workshop_download_has_a_modelscope_route():
    import json

    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    download_keys = {model.download_key for model in MODELS if model.download_key}
    assert download_keys
    assert all(lock["models"][key].get("modelscope_repository") for key in download_keys)


def test_firered_empty_placeholder_configs_are_not_required():
    import json

    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    assert "config.yaml" not in lock["models"]["firered_vad"]["required_files"]
    assert "config.yaml" not in lock["models"]["firered_aed"]["required_files"]


def test_firered_llm_manifest_tracks_files_used_by_official_runtime():
    import json

    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    spec = lock["models"]["firered_llm"]
    assert "asr_encoder.pth.tar" in spec["required_files"]
    assert "config.yaml" not in spec["required_files"]
    for manifest in spec["source_manifests"].values():
        assert "asr_encoder.pth.tar" in manifest["files"]
        assert "config.yaml" not in manifest["files"]


def test_powershell_download_path_uses_python_module_not_hf_console_script():
    script = (ROOT / "scripts" / "download_models.ps1").read_text(encoding="utf-8-sig")
    assert "-m twobyteasr.repository_download" in script
    assert "hf.exe" not in script
    assert "& $HfExe download" not in script


def test_download_dialog_is_frameless_utf8_and_keeps_result_inline(monkeypatch):
    app = _app()
    model = next(item for item in MODELS if item.key == "firered_llm")
    dialog = ModelDownloadDialog(ROOT, model)
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.findChild(type(dialog.title_bar), "modelDownloadTitleBar") is not None

    starts = []
    monkeypatch.setattr(dialog.process, "start", lambda program, args: starts.append((program, args)))
    monkeypatch.setattr(dialog.process, "waitForStarted", lambda _timeout: True)
    dialog.start()
    environment = dialog.process.processEnvironment()
    assert environment.value("PYTHONUTF8") == "1"
    assert environment.value("PYTHONIOENCODING") == "utf-8"
    assert starts

    dialog._finished_v2(0, QProcess.ExitStatus.NormalExit)
    assert dialog.progress_status.text() == "✓ 已安装 · 可使用"
    assert dialog.start_button.text() == "完成"
    assert dialog.start_button.isVisible() or not dialog.isVisible()
    dialog.deleteLater()
    app.processEvents()


def test_workshop_download_completion_does_not_open_native_message_box(monkeypatch):
    app = _app()
    page = ModelWorkshopPage(ROOT, {"models": {}})
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: calls.append(args))
    dialog = ModelDownloadDialog(ROOT, next(item for item in MODELS if item.key == "firered_llm"))
    page._download_completed(dialog, True, "done")
    page._download_completed(dialog, False, "failed")
    assert calls == []
    dialog.deleteLater()
    page.deleteLater()
    app.processEvents()
