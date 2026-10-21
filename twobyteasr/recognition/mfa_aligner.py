"""Montreal Forced Aligner: experimental 字幕时间轴 backend for Chinese and Japanese (2026-10-19).

The user asked for MFA after an aligner survey. Measured on their own Chinese
game commentary and on a Japanese anime episode (plan
``docs/exec-plans/active/2026-10-19-language-colors-and-word-aligners.md``):
Chinese boundaries agree closely with Qwen3-ForcedAligner; Japanese is mixed
(each gets different lines wrong; MFA struggles with names it does not
know). So it is offered as an experimental choice, never a default.

MFA runs in its own conda environment (``<runtime root>\\mfa``, Kaldi CPU
build, created by ``scripts/install_mfa_runtime.py``) through
``mfa_aligner_worker.py``, with the same jobs and receipt rows as
``asr.run_qwen_aligner_worker``. The GUI process never imports MFA.
English and other languages stay with the Qwen3 aligner.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

BACKEND = "mfa_aligner"
MODEL_KEY = "mfa_aligner"
# language -> lock key of its model folder (MFA 3.4.3 models from huggingface.co/MontrealCorpusTools)
LANGUAGE_MODELS = {"Chinese": "mfa_aligner", "Japanese": "mfa_aligner_ja"}
RUNTIME_DIR_NAME = "mfa"
# Next to the env folder, as scripts/install_mfa_runtime.py writes them: the
# installer's working folder (micromamba.exe) and the "not complete" marker.
INSTALL_DIR_NAME = "mfa-install"
RUNTIME_PENDING = "mfa.install-pending.json"
RUNTIME_MARKER = "2byteasr-mfa-runtime.json"  # in <env>/conda-meta when complete
PREFIX_ENV = "TWOBYTEASR_MFA_PREFIX"
# Imports that need the env's DLL folders (Kaldi, OpenFst) and the tokenizers.
CHECK_IMPORTS = "import _kalpy, pynini, sudachipy, spacy_pkuseg, montreal_forced_aligner"
PROTOCOL = "mfa-aligner-units-v1"
WORKER = "mfa_aligner_worker.py"
LANGUAGES = frozenset(LANGUAGE_MODELS)
PENDING_MARKER = ".2byteasr-install-pending.json"


class MfaUnavailableError(RuntimeError):
    """The MFA runtime or its models are not installed."""


def _lock_spec(key: str) -> dict:
    from ..runtime_paths import _load_lock_models, get_runtime_paths
    return _load_lock_models(get_runtime_paths().install_root).get(key) or {}


def model_dir(language: str = "Chinese") -> str | None:
    """The installed model folder of ``language`` (every locked file, no pending install), or None."""
    from ..runtime_paths import iter_model_dir_candidates
    spec = _lock_spec(LANGUAGE_MODELS[language])
    folder = Path(str(spec.get("path") or "")).name
    required = list(spec.get("required_files") or ())
    if not folder or not required:
        return None
    for candidate in (Path(p) for p in iter_model_dir_candidates(folder)):
        if all((candidate / name).is_file() for name in required) and not (candidate / PENDING_MARKER).exists():
            return str(candidate)
    return None


def model_dirs() -> dict[str, str]:
    """``{language: folder}`` for every language whose models are installed."""
    return {language: path for language in LANGUAGE_MODELS if (path := model_dir(language))}


def runtime_prefix() -> Path:
    env = os.environ.get(PREFIX_ENV, "").strip()
    if env:
        return Path(env).expanduser()
    from ..system.runtime_registry import runtimes_root
    return runtimes_root() / RUNTIME_DIR_NAME


def runtime_python(prefix: Path | None = None) -> str | None:
    """The conda env's interpreter when the runtime (at ``prefix``, default the app's) is complete, else None."""
    prefix = Path(prefix) if prefix is not None else runtime_prefix()
    python = prefix / ("python.exe" if os.name == "nt" else "bin/python")
    marker = prefix / "conda-meta" / RUNTIME_MARKER
    if python.is_file() and marker.is_file() and not (prefix.parent / RUNTIME_PENDING).exists():
        return str(python)
    return None


def worker_path() -> str:
    from .asr import SCRIPT_DIR
    worker = os.path.join(os.path.abspath(SCRIPT_DIR), WORKER)
    if not os.path.isfile(worker):
        worker = os.path.join(os.path.abspath(SCRIPT_DIR), "workers", WORKER)
    return worker


def runtime_environment(prefix: Path, base: dict | None = None) -> dict:
    """The worker's ``conda activate`` environment for ``prefix`` (its DLL folders first on PATH).

    Loaded from the worker file (stdlib imports only) so the storage move
    checks the env exactly as the worker starts MFA.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_2byteasr_mfa_worker_env", worker_path())
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MFA aligner worker missing: {worker_path()}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.activated_environment(Path(prefix), base)


def installed() -> bool:
    return bool(runtime_python()) and len(model_dirs()) == len(LANGUAGE_MODELS)


def handles(jobs) -> bool:
    """MFA aligns these jobs only when every one is Chinese or Japanese."""
    return bool(jobs) and all(str(job.get("language") or "") in LANGUAGES for job in jobs)


def missing_message() -> str:
    parts = []
    if not runtime_python():
        parts.append("MFA 运行环境")
    missing = [name for language, name in (("Chinese", "中文"), ("Japanese", "日语")) if not model_dir(language)]
    if missing:
        parts.append("MFA " + "、".join(missing) + "模型")
    return "Montreal Forced Aligner（实验）未安装完整：缺少" + "、".join(parts or ["文件"]) + "。请在模型工坊重新下载。"


def run_aligner(audio, jobs, *, passes=("word", "char"), batch_size=8) -> dict:
    """Same jobs and result rows as ``asr.run_qwen_aligner_worker`` (``passes`` and ``batch_size`` unused)."""
    import numpy as np
    from .asr import AUDIO_SAMPLE_RATE, _run_isolated_asr_worker
    from ..system.processes import python_utf8_command
    python, models = runtime_python(), model_dirs()
    if not python or any(str(job.get("language") or "") not in models for job in jobs):
        raise MfaUnavailableError(missing_message())
    worker = worker_path()
    if not os.path.isfile(worker):
        raise RuntimeError(f"MFA aligner worker missing: {worker}")
    pcm = np.ascontiguousarray(audio, dtype=np.float32)
    if pcm.ndim != 1 or not np.isfinite(pcm).all():
        raise RuntimeError("对齐 worker 需要有限值单声道 float32 PCM")
    digest = hashlib.sha256(pcm.tobytes()).hexdigest()
    policy = {"version": PROTOCOL, "audio_format": "float32-mono-npy-v1", "sample_rate": AUDIO_SAMPLE_RATE}
    jobs = [dict(job, id=str(job["id"])) for job in jobs]
    with tempfile.TemporaryDirectory(prefix="mfa_aligner_worker_") as temp_dir:
        audio_path = os.path.join(temp_dir, "audio.npy")
        np.save(audio_path, pcm, allow_pickle=False)
        manifest = os.path.join(temp_dir, "manifest.json")
        output = os.path.join(temp_dir, "results.json")
        Path(manifest).write_text(json.dumps({"policy": policy, "jobs": jobs, "audio": {
            "path": audio_path, "samples": int(pcm.size), "sha256": digest}}, ensure_ascii=False), encoding="utf-8")
        payload = _run_isolated_asr_worker(
            python_utf8_command([python, "-I", worker, "--manifest", manifest, "--output", output,
                                 *[f"--model-dir={language}={path}" for language, path in sorted(models.items())]]),
            output, model_id="MFA-ALIGNER", audio_input="shared_audio",
            model_path=os.pathsep.join(models.values()), entrypoint=WORKER)
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or [str(row.get("id")) for row in results] != [job["id"] for job in jobs]:
        raise RuntimeError("MFA 对齐 worker 返回的任务缺失、重复或乱序")
    if payload.get("policy") != policy or payload.get("audio_sha256") != digest or payload.get("protocol") != PROTOCOL:
        raise RuntimeError("MFA 对齐 worker 回执与输入不一致")
    for job, row in zip(jobs, results):
        if row.get("text") != job["text"]:
            raise RuntimeError("MFA 对齐 worker 改写了输入文字")
    return payload
