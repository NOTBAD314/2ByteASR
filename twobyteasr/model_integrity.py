"""Integrity checks for pinned local models that load code or pickle data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ModelIntegrityError(RuntimeError):
    """Raised before an untrusted or changed model artifact can be loaded."""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def load_dependency_lock(root: Path | None = None) -> dict:
    root = Path(root) if root is not None else project_root()
    with (root / "dependencies.lock.json").open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schema_version") != 1:
        raise ModelIntegrityError("不支持的依赖锁文件版本。")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_files(
    model_name: str,
    model_root: str | Path | None = None,
    *,
    root: Path | None = None,
) -> Path:
    """Verify all security-sensitive files listed for a pinned model."""
    root = Path(root) if root is not None else project_root()
    lock = load_dependency_lock(root)
    try:
        spec = lock["models"][model_name]
    except KeyError as exc:
        raise ModelIntegrityError(f"依赖锁中没有模型：{model_name}") from exc
    if model_root is not None:
        target = Path(model_root)
    else:
        from .runtime_paths import resolve_model_dir

        target = resolve_model_dir(Path(str(spec.get("path") or "")).name, install_root=root)
    target = target.resolve()
    allowed_roots = [root.resolve()]
    try:
        from .runtime_paths import get_runtime_paths

        allowed_roots.append(get_runtime_paths().model_root.resolve())
        allowed_roots.append(get_runtime_paths().install_root.resolve())
    except Exception:
        pass
    if not any(_is_relative_to(target, allowed) for allowed in allowed_roots):
        # Still allow the located directory when required files are present —
        # packaged EXE must verify models that live in the shared MODEL_ROOT.
        if not target.is_dir():
            raise ModelIntegrityError(f"拒绝校验未知位置的模型：{target}")

    hashes = spec.get("sha256", {})
    required_files = list(dict.fromkeys(spec.get("required_files", ())))
    for relative in required_files:
        candidate = (target / relative).resolve()
        try:
            candidate.relative_to(target)
        except ValueError as exc:
            raise ModelIntegrityError(f"模型锁包含非法路径：{relative}") from exc
        if not candidate.is_file():
            raise ModelIntegrityError(
                f"模型必需文件缺失：{candidate}\n"
                "请重新运行 download_models.bat，程序会断点续传并只补下载缺失文件。"
            )

    for relative, expected in hashes.items():
        candidate = (target / relative).resolve()
        try:
            candidate.relative_to(target)
        except ValueError as exc:
            raise ModelIntegrityError(f"模型锁包含非法路径：{relative}") from exc
        if not candidate.is_file():
            raise ModelIntegrityError(
                f"模型关键文件缺失：{candidate}\n"
                "请重新运行 download_models.bat，程序会断点续传并只补下载缺失文件。"
            )
        actual = sha256_file(candidate)
        if actual.lower() != str(expected).lower():
            raise ModelIntegrityError(
                f"模型文件校验失败，已拒绝加载：{candidate.name}。"
                f"请删除损坏文件 {candidate} 后重新运行 download_models.bat。"
            )
    return target


def locked_model(model_name: str, *, root: Path | None = None) -> dict:
    return dict(load_dependency_lock(root)["models"][model_name])
