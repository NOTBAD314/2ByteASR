"""Preflight verifies the aligner directory against the lock entry of the same profile.

2026-11-17 user report (1.1.1): every task with 「Qwen3 对齐 · Ultra」 stopped at t=0 with
"模型文件校验失败，已拒绝加载：model.safetensors", and re-downloading never helped.
Since the 2026-11-14 upgrade Ultra is stored as firered_asr_backend='qwen_aligner' +
qwen_alignment_profile='ultra-v5'. The directory followed the resolved profile (Ultra
folder) while the lock key followed the raw setting ('qwen_aligner', official 0.6B
hashes), so intact Ultra weights were always rejected.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

import moss_firered_pipeline as pipeline
from twobyteasr import model_integrity
from twobyteasr.recognition import alignment_backend, asr
from twobyteasr.system import hardware


def run_preflight(tmp_path, monkeypatch, models):
    settings = {"models": dict(models)}
    folders = {"qwen_aligner": tmp_path / "Qwen3-ForcedAligner-0.6B",
               "qwen_ultra_aligner": tmp_path / "Qwen3-ForcedAligner-Ultra",
               "qwen_ultra_head": tmp_path / "Qwen3-ForcedAligner-Ultra"}
    head = tmp_path / "Qwen3-ForcedAligner-Ultra-LocalHead"
    for folder in (*folders.values(), head):
        folder.mkdir(exist_ok=True)
    primary = tmp_path / "primary"
    primary.mkdir()
    calls = []

    monkeypatch.setattr(asr, "get_runtime_context", lambda: SimpleNamespace(asr_settings_snapshot=settings))
    monkeypatch.setattr(alignment_backend, "model_directory", lambda backend=None: str(folders[backend]))
    monkeypatch.setattr(alignment_backend, "head_directory", lambda: str(head))
    monkeypatch.setattr(model_integrity, "verify_model_files",
                        lambda key, directory, **_: calls.append((key, Path(directory))) or Path(directory))
    monkeypatch.setattr(asr, "check_selected_worker_dependencies", lambda legacy: None)
    monkeypatch.setattr(hardware, "require_local_torch_runtime", lambda settings: None)
    monkeypatch.setattr(hardware, "selected_cuda_components", lambda settings: ())
    monkeypatch.setattr(pipeline, "_script_paths", lambda legacy: {})
    monkeypatch.setattr(pipeline, "_preflight_cloud_stages", lambda legacy: None)
    legacy = SimpleNamespace(
        check_runtime=lambda: None,
        RUNTIME_SETTINGS=settings,
        PRIMARY_ASR_BACKEND="qwen_local",
        resolve_qwen_asr_local_source=lambda: str(primary),
        FIRERED_ASR_BACKEND=settings["models"]["firered_asr_backend"],
        QWEN_ASR_BACKEND="api",
        resolve_qwen_aligner_local_source=asr.resolve_qwen_aligner_local_source,
        selected_qwen_aligner_backend=asr.selected_qwen_aligner_backend,
    )
    pipeline.check_runtime(legacy)
    return [(key, directory.name) for key, directory in calls if key != "qwen_asr"]


@pytest.mark.parametrize(("models", "expected"), [
    # Canonical Ultra (what 1.1.1 stores after the upgrade): the reported failure.
    ({"firered_asr_backend": "qwen_aligner", "qwen_alignment_profile": "ultra-v5"},
     [("qwen_ultra_aligner", "Qwen3-ForcedAligner-Ultra")]),
    # Canonical Ultra with the optional Local Head requested.
    ({"firered_asr_backend": "qwen_aligner", "qwen_alignment_profile": "ultra-v5", "qwen_ultra_local_head": True},
     [("qwen_ultra_aligner", "Qwen3-ForcedAligner-Ultra"), ("qwen_ultra_head", "Qwen3-ForcedAligner-Ultra-LocalHead")]),
    # Official compatibility profile keeps the 0.6B entry.
    ({"firered_asr_backend": "qwen_aligner", "qwen_alignment_profile": "official-v1"},
     [("qwen_aligner", "Qwen3-ForcedAligner-0.6B")]),
    # Explicit legacy backend names still work.
    ({"firered_asr_backend": "qwen_ultra_aligner"}, [("qwen_ultra_aligner", "Qwen3-ForcedAligner-Ultra")]),
])
def test_preflight_lock_entry_matches_resolved_directory(tmp_path, monkeypatch, models, expected):
    from twobyteasr.recognition import qwen_family
    models = dict(models)
    if models.pop("qwen_ultra_local_head", False):
        models[qwen_family.HEAD_OPTION] = True
    assert run_preflight(tmp_path, monkeypatch, models) == expected


def test_canonical_ultra_resolves_to_ultra_entry():
    settings = {"models": {"firered_asr_backend": "qwen_aligner", "qwen_alignment_profile": "ultra-v5"}}
    assert alignment_backend.selected_backend(settings) == "qwen_ultra_aligner"
    lock = model_integrity.load_dependency_lock()["models"]
    # The two entries really differ, so a mixed-up key can never pass by accident.
    assert lock["qwen_aligner"]["sha256"]["model.safetensors"] != lock["qwen_ultra_aligner"]["sha256"]["model.safetensors"]
