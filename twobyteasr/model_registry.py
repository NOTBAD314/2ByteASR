"""Health-aware registry of locally installed ASR models.

Installed does not mean "a folder exists under the current executable". A
model is INSTALLED when its locked required files are present at a registered
path — including a legacy source-checkout tree discovered by RuntimePaths.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable

from .runtime_paths import (
    RuntimePaths,
    get_runtime_paths,
    iter_model_dir_candidates,
    model_folder_name,
    model_files_present,
)


class ModelHealth(str, Enum):
    INSTALLED = "INSTALLED"
    PARTIAL = "PARTIAL"
    CORRUPT = "CORRUPT"
    MISSING = "MISSING"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    version: str
    installation_path: Path
    source: str
    expected_files: tuple[str, ...]
    health: ModelHealth
    size_bytes: int
    expected_bytes: int
    runtime_environment: str
    compatible: bool
    missing_files: tuple[str, ...] = ()
    spec_path: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["installation_path"] = str(self.installation_path)
        payload["health"] = self.health.value
        payload["expected_files"] = list(self.expected_files)
        payload["missing_files"] = list(self.missing_files)
        return payload


@dataclass
class ModelRegistry:
    install_root: Path
    model_root: Path
    records: dict[str, ModelRecord] = field(default_factory=dict)
    lock_path: Path | None = None
    error: str = ''

    def installed_keys(self) -> set[str]:
        return {
            key
            for key, record in self.records.items()
            if record.health == ModelHealth.INSTALLED
        }

    def record(self, model_id: str) -> ModelRecord | None:
        return self.records.get(str(model_id))

    def installed_count(self) -> int:
        return len(self.installed_keys())


def _load_lock(install_root: Path) -> dict:
    path = Path(install_root) / "dependencies.lock.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise OSError(f'模型清单读取失败：{path}（{exc}）') from exc
    if not isinstance(payload, dict) or not isinstance(payload.get('models'), dict):
        raise OSError(f'模型清单格式无效：{path}')
    return payload


def _directory_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _health_for(
    folder: Path,
    required: tuple[str, ...],
    hashes: dict[str, str],
    compatible: bool,
) -> tuple[ModelHealth, tuple[str, ...]]:
    if not required:
        if folder.is_dir():
            return (ModelHealth.INSTALLED if compatible else ModelHealth.INCOMPATIBLE), ()
        return ModelHealth.MISSING, ()
    try:
        if folder.exists():
            # Access must be checked explicitly: a denied directory is not a download request.
            with os.scandir(folder):
                pass
        missing = tuple(name for name in required if not (folder / name).is_file() or (folder / name).stat().st_size == 0)
    except OSError as exc:
        return ModelHealth.UNREADABLE, (str(exc),)
    if len(missing) == len(required) and not folder.is_dir():
        return ModelHealth.MISSING, missing
    if missing:
        return ModelHealth.PARTIAL, missing
    if not compatible:
        return ModelHealth.INCOMPATIBLE, ()
    for relative, expected in hashes.items():
        file_path = folder / relative
        if not file_path.is_file():
            return ModelHealth.CORRUPT, (relative,)
        if expected and not _sha256_matches(file_path, str(expected)):
            return ModelHealth.CORRUPT, (relative,)
    return ModelHealth.INSTALLED, ()


def _sha256_matches(path: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return False
    return digest.hexdigest().lower() == expected.lower()


def _locate_model_folder(
    spec_path: str,
    *,
    install_root: Path,
    model_root: Path,
    required: tuple[str, ...] = (),
) -> tuple[Path, str]:
    name = model_folder_name(spec_path)
    preferred = (model_root / name).resolve()
    if model_files_present(preferred, required):
        return preferred, "model_root"
    if os.environ.get('TWOBYTEASR_TEST_ROOT'):
        return preferred, 'model_root'
    install_relative = (install_root / spec_path).resolve()
    candidates = [preferred, install_relative, *iter_model_dir_candidates(name, install_root=install_root)]
    for candidate in candidates:
        if model_files_present(candidate, required):
            return candidate, 'model_root' if candidate == preferred else 'legacy_discovery'
    return next(((p, 'model_root' if p == preferred else 'legacy_discovery') for p in candidates if p.is_dir()), (preferred, 'model_root'))


def scan_model_registry(
    *,
    install_root: Path | None = None,
    model_root: Path | None = None,
    paths: RuntimePaths | None = None,
    verify_hashes: bool = False,
    measure_size: bool = False,
) -> ModelRegistry:
    runtime = paths or get_runtime_paths()
    install = Path(install_root) if install_root is not None else runtime.install_root
    models_parent = Path(model_root) if model_root is not None else runtime.model_root
    try:
        lock = _load_lock(install)
    except OSError as exc:
        return ModelRegistry(install, models_parent, lock_path=install/'dependencies.lock.json', error=str(exc))
    specs = lock.get("models") if isinstance(lock.get("models"), dict) else {}
    registry = ModelRegistry(
        install_root=install,
        model_root=models_parent,
        lock_path=install / "dependencies.lock.json",
    )
    for model_id, spec in specs.items():
        if not isinstance(spec, dict):
            continue
        spec_path = str(spec.get("path") or f"models/{model_id}")
        folder, source = _locate_model_folder(
            spec_path,
            install_root=install,
            model_root=models_parent,
            required=tuple(str(item) for item in spec.get('required_files') or ()),
        )
        required = tuple(str(item) for item in spec.get("required_files") or ())
        hashes = {
            str(name): str(value)
            for name, value in (spec.get("sha256") or {}).items()
        } if verify_hashes else {}
        environment = str(spec.get("runtime_environment") or "")
        compatible = True
        health, missing = _health_for(folder, required, hashes, compatible)
        size_bytes = (
            _directory_size(folder)
            if measure_size and folder.is_dir() and health is not ModelHealth.MISSING
            else 0
        )
        registry.records[str(model_id)] = ModelRecord(
            model_id=str(model_id),
            version=str(spec.get("revision") or spec.get("version") or ""),
            installation_path=folder,
            source=source,
            expected_files=required,
            health=health,
            size_bytes=size_bytes,
            expected_bytes=int(spec.get("download_bytes") or 0),
            runtime_environment=environment,
            compatible=compatible,
            missing_files=missing,
            spec_path=spec_path,
        )
    return registry


def installed_model_keys(
    root: Path | None = None,
    *,
    model_root: Path | None = None,
) -> set[str]:
    """Compatibility wrapper used by the workshop and ASR selectors."""

    if root is None:
        return scan_model_registry(model_root=model_root).installed_keys()
    return scan_model_registry(install_root=Path(root), model_root=model_root).installed_keys()


__all__ = [
    "ModelHealth",
    "ModelRecord",
    "ModelRegistry",
    "installed_model_keys",
    "scan_model_registry",
]
