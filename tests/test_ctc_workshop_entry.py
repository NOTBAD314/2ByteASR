"""Model Workshop download entry for the Japanese CTC aligner (2026-10-13)."""
import json
from pathlib import Path
from types import SimpleNamespace

from twobyteasr import ctc_alignment, repository_download
from twobyteasr.model_workshop import CANONICAL_MODEL_ORDER, MODELS, ModelWorkshopPage, _browser_groups

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
SPEC = LOCK["models"]["ja_ctc_aligner"]


def _card():
    return next(model for model in MODELS if model.key == "ja_ctc_aligner")


def test_card_is_listed_under_the_timeline_tab_and_downloads_the_locked_model():
    card = _card()
    assert "ja_ctc_aligner" in CANONICAL_MODEL_ORDER
    assert card.download_key == "ja_ctc_aligner" and card.install_keys == ("ja_ctc_aligner",)
    assert _browser_groups(card) == ("timeline",)
    # Used automatically by Japanese recognition: not a selectable timeline backend.
    assert card.adapter_bindings == () and card.auto_stage
    assert not card.recommended


def test_auto_used_model_shows_its_own_installed_text_instead_of_integrating():
    page = SimpleNamespace(_removing=set())
    text, enabled = ModelWorkshopPage._action_text(page, _card(), "downloaded")
    assert text == "自动使用" and enabled is False
    assert _card().auto_stage == "已安装 · 日语识别时自动使用"  # detail badge
    qwen = next(model for model in MODELS if model.key == "qwen_aligner")
    assert ModelWorkshopPage._action_text(page, qwen, "downloaded") == ("已下载 · 接入中", False)


def test_auto_source_tries_the_pinned_modelscope_copy_then_hugging_face():
    plans = repository_download.planned_sources(SPEC, "AUTO")
    assert [plan.mode for plan in plans] == ["MODELSCOPE", "HF_OFFICIAL"]
    modelscope, official = plans
    # The ModelScope commit whose five files were checked against the locked SHA-256.
    assert modelscope.revision == "18a6b5970be543c1171a30e5f2889c63878acd2e"
    assert official.revision == SPEC["revision"]
    for plan in plans:
        assert set(plan.files) == set(SPEC["required_files"])
        assert plan.sha256 == {name: digest.lower() for name, digest in SPEC["sha256"].items()}
    url = repository_download._artifact_url(modelscope, "pytorch_model.bin")
    assert url.startswith("https://modelscope.cn/api/v1/models/jonatasgrosman/wav2vec2-large-xlsr-53-japanese/repo")
    assert "Revision=18a6b5970be543c1171a30e5f2889c63878acd2e" in url
    mirror = repository_download.planned_sources(SPEC, "HF_MIRROR")[0]
    assert repository_download._artifact_url(mirror, "vocab.json").startswith("https://hf-mirror.com/jonatasgrosman/")


def test_download_scripts_accept_the_key_and_readiness_runs_the_worker():
    for script in ("scripts/download_models.ps1", "scripts/setup_model_backend.ps1"):
        assert '"ja_ctc_aligner"' in (ROOT / script).read_text(encoding="utf-8-sig")
    readiness = (ROOT / "scripts/validate_prepared_model.py").read_text(encoding="utf-8")
    assert "model=='ja_ctc_aligner'" in readiness and "ctc_alignment.run_worker" in readiness
    assert not SPEC.get("resource_only")


def test_model_folder_waiting_for_install_completion_is_not_used(tmp_path, monkeypatch):
    folder = tmp_path / ctc_alignment.MODEL_DIR_NAME
    folder.mkdir()
    (folder / "config.json").write_text("{}", encoding="utf-8")
    (folder / "pytorch_model.bin").write_bytes(b"x")
    monkeypatch.setattr("twobyteasr.runtime_paths.iter_model_dir_candidates", lambda name: [])
    monkeypatch.setenv("2BYTEASR_JA_CTC_ALIGNER_DIR", str(folder))
    # Keep the repository's own models folder out of the candidates.
    monkeypatch.setattr(ctc_alignment, "__file__", str(tmp_path / "app" / "twobyteasr" / "ctc_alignment.py"))
    assert ctc_alignment.model_dir() == str(folder)
    (folder / ".2byteasr-install-pending.json").write_text("{}", encoding="utf-8")
    assert ctc_alignment.model_dir() is None
