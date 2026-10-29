"""Stable application roots shared by source and packaged launches.

INSTALL_ROOT is the program location and may be read-only. Mutable data lives
under USER_DATA_ROOT (%LOCALAPPDATA%\\2ByteASR). MODEL_ROOT is discovered once
and persisted so ``python -m twobyteasr`` and ``2ByteASR.exe`` see the same
installed models. Existing multi-gigabyte model trees are registered in place;
they are never copied by default. RUNTIME_ROOT (uv, private Pythons, the
per-role environments and their registry) is chosen and persisted the same
way (2026-10-17, see :func:`managed_runtime_root`).
"""

from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


APP_NAME = "2ByteASR"
RUNTIME_PATHS_FILENAME = "runtime_paths.json"
SCHEMA_VERSION = 1
MODEL_ROOT_ENV = "2BYTEASR_MODEL_ROOT"
INSTALL_ROOT_ENV = "2BYTEASR_INSTALL_ROOT"
USER_DATA_ENV = "2BYTEASR_USER_DATA_ROOT"
RUNTIME_ROOT_ENV = "2BYTEASR_RUNTIME_ROOT"
RUNTIMES_FOLDER = "runtimes"
# Anything here means runtimes were already prepared in that folder.
_RUNTIME_MARKERS = ("registry.json", "tools", "python", "main", "moss", "firered-llm",
                    "glm_asr", "canary", "mlx", "nemotron")

_CACHE: "RuntimePaths | None" = None
_RUNTIME_ROOT_CACHE: dict[tuple[str, ...], tuple[Path, str]] = {}


def _local_app_data() -> Path:
    configured = os.environ.get(USER_DATA_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local)
    return Path.home() / "AppData" / "Local"


def detect_install_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Program location: frozen exe directory, otherwise the repository root."""

    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get(INSTALL_ROOT_ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def pipeline_script_root(module_file: str | os.PathLike[str]) -> Path:
    """Locate pipeline workers without treating the macOS executable as resources."""
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        # The native launcher establishes this trusted resource root before
        # importing pipeline modules. Windows keeps its existing exe-dir layout.
        return detect_install_root()
    return Path(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else module_file)).parent


def user_data_root() -> Path:
    return _local_app_data() / APP_NAME


def _config_path(data_root: Path | None = None) -> Path:
    return (data_root or user_data_root()) / RUNTIME_PATHS_FILENAME


def _leaf_model_name(spec_path: str) -> str:
    return Path(str(spec_path or "").replace("\\", "/")).name


def model_folder_name(spec_path: str) -> str:
    return _leaf_model_name(spec_path)


@dataclass(frozen=True)
class RuntimePaths:
    install_root: Path
    user_data_root: Path
    model_root: Path
    cache_root: Path
    project_root: Path
    config_root: Path
    log_root: Path
    renderer_asset_root: Path
    temp_root: Path
    model_root_source: str = "default"
    discovered_model_roots: tuple[str, ...] = ()
    runtime_root: Path | None = None
    runtime_root_source: str = ""

    @property
    def managed_runtime_root(self) -> Path:
        """Runtime folder; hand-built paths without one use the user-data default."""
        return self.runtime_root if self.runtime_root is not None else self.user_data_root / RUNTIMES_FOLDER

    def to_dict(self) -> dict[str, str]:
        payload = {key: "" if value is None else str(value) for key, value in asdict(self).items()}
        payload["schema_version"] = str(SCHEMA_VERSION)
        return payload


def _load_lock_models(install_root: Path) -> dict:
    lock = install_root / "dependencies.lock.json"
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    models = payload.get("models")
    return models if isinstance(models, dict) else {}


def complete_model_count(models_parent: Path, install_root: Path | None = None) -> int:
    """How many locked models have every required file under ``models_parent``.

    ``models_parent`` is the directory that *contains* model folders (the
    equivalent of ``<install>/models``).
    """

    root = Path(models_parent)
    if not root.is_dir():
        return 0
    lock_root = install_root or detect_install_root()
    count = 0
    for spec in _load_lock_models(lock_root).values():
        if not isinstance(spec, dict):
            continue
        folder = root / _leaf_model_name(str(spec.get("path") or ""))
        required = tuple(str(item) for item in spec.get("required_files") or ())
        if required and model_files_present(folder, required):
            count += 1
    return count


def model_files_present(folder: Path, required: Iterable[str]) -> bool:
    try:
        names = tuple(required)
        return bool(names) and all((folder / item).is_file() and (folder / item).stat().st_size > 0 for item in names)
    except OSError:
        return False


_SCAN_SCOPE = threading.local()


@contextmanager
def single_scan():
    """Within one model scan, resolve each path and read each record once.

    A registry scan looked up ~15 models x several roots and re-resolved the
    same paths and re-read the same files ~200 times (~107 ms per scan, about
    nine scans while the main window opens). Nothing outlives the scan, so an
    install, removal or detach is seen by the next scan as before.
    """
    outer = getattr(_SCAN_SCOPE, "memo", None)
    if outer is None:
        _SCAN_SCOPE.memo = {}
    try:
        yield
    finally:
        if outer is None:
            _SCAN_SCOPE.memo = None


def scan_memo(key, compute):
    """``compute()`` once per key inside :func:`single_scan`, else every call."""
    memo = getattr(_SCAN_SCOPE, "memo", None)
    if memo is None:
        return compute()
    if key not in memo:
        memo[key] = compute()
    return memo[key]


def discover_legacy_model_roots(install_root: Path, data_root: Path) -> list[Path]:
    return list(scan_memo(
        ("legacy_model_roots", str(install_root), str(data_root), os.environ.get(MODEL_ROOT_ENV, ""),
         os.environ.get("TWOBYTEASR_TEST_ROOT", "")),
        lambda: _discover_legacy_model_roots(install_root, data_root)))


def _discover_legacy_model_roots(install_root: Path, data_root: Path) -> list[Path]:
    """Candidate directories that already hold downloaded models.

    Order is preference, not search exclusivity. Callers pick the best
    populated root and persist it. Nothing is copied.
    """

    candidates: list[Path] = []

    def add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if resolved not in candidates:
            candidates.append(resolved)

    env = os.environ.get(MODEL_ROOT_ENV, "").strip()
    if env:
        add(Path(env))
    # Keep explicitly registered earlier destinations discoverable after the
    # user changes the download root. We never move their weights.
    try:
        saved = json.loads(_config_path(data_root).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        saved = {}
    if isinstance(saved, dict):
        for value in [saved.get('model_root'), *saved.get('discovered_model_roots', ())]:
            if value:
                add(Path(str(value)))
    if os.environ.get('TWOBYTEASR_TEST_ROOT'):
        if not candidates:
            add(data_root / 'Models')
        return candidates
    add(data_root / "Models")
    add(data_root / "models")
    add(install_root / "models")
    # Packaged ``dist\\2ByteASR`` sitting inside a source checkout.
    add(install_root.parent.parent / "models")
    add(install_root.parent / "models")
    home = Path.home()
    add(home / "Desktop" / "2ByteASR" / "models")
    add(home / "Documents" / "2ByteASR" / "models")
    configured = _read_persisted_model_root(data_root)
    if configured is not None:
        add(configured)
    return candidates


def _read_persisted_model_root(data_root: Path) -> Path | None:
    path = _config_path(data_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"无法读取路径登记 {path}：{exc}。原文件未被覆盖。") from exc
    if not isinstance(payload, dict):
        return None
    value = str(payload.get("model_root") or "").strip()
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_dir():
        raise RuntimeError(f"已登记的模型目录不可用：{candidate}。请恢复磁盘连接或在路径登记中更正位置；不会重新下载。")
    return candidate


def _pick_model_root(
    install_root: Path,
    data_root: Path,
    *,
    override: str | os.PathLike[str] | None = None,
) -> tuple[Path, str, tuple[Path, ...]]:
    discovered = tuple(discover_legacy_model_roots(install_root, data_root))
    if override is not None:
        chosen = Path(override).expanduser().resolve()
        return chosen, "override", discovered
    env = os.environ.get(MODEL_ROOT_ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve(), "environment", discovered
    persisted = _read_persisted_model_root(data_root)
    default = (data_root / "Models").resolve()
    if persisted is not None and persisted.is_dir():
        # The old automatic default, still empty, is chosen again below so the
        # first download follows the program folder (2026-10-14). A root that
        # holds any file, or any other registered folder, is kept as it is.
        if not (persisted.resolve() == default and _holds_no_files(persisted)):
            return persisted.resolve(), "persisted", discovered

    scored: list[tuple[int, Path]] = []
    for candidate in discovered:
        if not candidate.is_dir():
            continue
        scored.append((complete_model_count(candidate, install_root), candidate))
    populated = [item for item in scored if item[0] > 0]
    if populated:
        populated.sort(key=lambda item: (-item[0], str(item[1]).lower()))
        best = populated[0][1]
        source = "legacy_install" if best == (install_root / "models").resolve() else "legacy_discovered"
        return best, source, discovered
    program = _program_model_root(install_root)
    if program is not None:
        return program, "default_program", discovered
    return default, "default_user_data", discovered


def _holds_no_files(folder: Path) -> bool:
    try:
        for _directory, _dirs, files in os.walk(folder):
            if files:
                return False
    except OSError:
        return False
    return True


def _program_model_root(install_root: Path) -> Path | None:
    """New Windows installs keep models beside the program (2026-10-14).

    Users pick the program folder in Setup (often another drive) or unpack
    Lite/Portable where they like; models then live on that drive and move
    with the folder instead of filling C:. Setup and the in-app updater never
    delete files added under the program folder later (see
    ``installer/2ByteASR-frozen.iss``). ``%LOCALAPPDATA%`` stays the default
    on macOS (the app bundle is no place for weights), in isolated test
    roots, for a dev build in ``<checkout>/dist`` (replaced on every daily
    swap) and when the program folder is not writable.
    """
    if os.name != "nt" or os.environ.get("TWOBYTEASR_TEST_ROOT"):
        return None
    root = Path(install_root)
    if root.parent.name.lower() == "dist" and (root.parent.parent / ".git").exists():
        return None
    candidate = root / "models"
    try:
        import tempfile
        # Actual write access, rather than guessing from the path or ACLs.
        # The folder itself is created by bootstrap once it is chosen.
        with tempfile.TemporaryFile(dir=candidate if candidate.is_dir() else root):
            pass
        return candidate.resolve()
    except OSError:
        return None


_AUTOMATIC_RUNTIME_SOURCES = ("default_program", "default_user_data", "legacy_user_data")


def _read_persisted_runtime_root(data_root: Path) -> tuple[Path, str] | None:
    """Registered runtime folder and how it was chosen."""
    try:
        payload = json.loads(_config_path(data_root).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not str(payload.get("runtime_root") or "").strip():
        return None
    path = Path(os.path.abspath(Path(str(payload["runtime_root"]).strip()).expanduser()))
    source = str(payload.get("runtime_root_source") or "persisted")
    # An automatic choice that was never filled (or whose program folder was
    # reinstalled elsewhere) is chosen again. A folder the user moved runtimes
    # to is kept even while its disk is away: falling back would download
    # ~5 GB per environment again onto another drive.
    if source in _AUTOMATIC_RUNTIME_SOURCES and not path.is_dir():
        return None
    return path, source


def _holds_runtimes(folder: Path) -> bool:
    try:
        return any((folder / name).exists() for name in _RUNTIME_MARKERS)
    except OSError:
        return False


def _program_runtime_root(install_root: Path) -> Path | None:
    """New Windows installs keep runtimes beside the program (2026-10-17).

    Like :func:`_program_model_root`, but for the packaged app only: a source
    checkout keeps its ``.venv-*`` and the user-data runtimes.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False) or os.environ.get("TWOBYTEASR_TEST_ROOT"):
        return None
    root = Path(install_root)
    if root.parent.name.lower() == "dist" and (root.parent.parent / ".git").exists():
        return None
    candidate = root / RUNTIMES_FOLDER
    try:
        import tempfile
        with tempfile.TemporaryFile(dir=candidate if candidate.is_dir() else root):
            pass
        return candidate
    except OSError:
        return None


def _pick_runtime_root(install_root: Path, data_root: Path) -> tuple[Path, str]:
    """Runtime folder for ``data_root``: override, registered, existing, program, user data."""
    env = os.environ.get(RUNTIME_ROOT_ENV, "").strip()
    if env and _same_path(data_root, user_data_root()) and _inside_test_root(Path(env)):
        return Path(os.path.abspath(Path(env).expanduser())), "environment"
    persisted = _read_persisted_runtime_root(data_root)
    if persisted is not None and _inside_test_root(persisted[0]):
        return persisted
    legacy = data_root / RUNTIMES_FOLDER
    if _holds_runtimes(legacy):
        return legacy, "legacy_user_data"
    program = _program_runtime_root(install_root)
    if program is not None:
        return program, "default_program"
    return legacy, "default_user_data"


def _inside_test_root(path: Path) -> bool:
    """Isolated runs never install into or clean a runtime folder outside their root."""
    boundary = os.environ.get("TWOBYTEASR_TEST_ROOT", "").strip()
    if not boundary:
        return True
    return Path(os.path.abspath(path)).is_relative_to(Path(os.path.abspath(boundary)))


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def managed_runtime_root(data_root: str | os.PathLike[str] | None = None) -> Path:
    """Folder holding uv, private Pythons, per-role environments, registry and download cache.

    The single source for every runtime path (registry, installers, cleanup,
    storage page). Decided once and persisted with the model root; see
    :func:`_pick_runtime_root` for the order.
    """
    data = Path(data_root) if data_root is not None else user_data_root()
    current = _CACHE
    if current is not None and current.runtime_root is not None and _same_path(data, current.user_data_root):
        return current.runtime_root
    install = current.install_root if current is not None else detect_install_root()
    key = (os.path.normcase(os.path.abspath(data)), os.path.normcase(str(install)),
           os.environ.get(RUNTIME_ROOT_ENV, ""), os.environ.get("TWOBYTEASR_TEST_ROOT", ""))
    if key not in _RUNTIME_ROOT_CACHE:
        _RUNTIME_ROOT_CACHE[key] = _pick_runtime_root(install, data)
    return _RUNTIME_ROOT_CACHE[key][0]


def _project_root(data_root: Path) -> Path:
    settings = data_root / "SubtitleStudioPreview" / "settings.json"
    try:
        payload = json.loads(settings.read_text(encoding="utf-8-sig"))
        custom = str(payload.get("project_root") or "").strip() if isinstance(payload, dict) else ""
        if custom:
            return Path(custom).expanduser()
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"无法读取工程库设置 {settings}：{exc}。原文件未被覆盖。") from exc
    return data_root / "Projects"


def build_runtime_paths(
    *,
    install_root: str | os.PathLike[str] | None = None,
    model_root: str | os.PathLike[str] | None = None,
    runtime_root: str | os.PathLike[str] | None = None,
    persist: bool = False,
) -> RuntimePaths:
    install = detect_install_root(install_root)
    data = user_data_root()
    chosen, source, discovered = _pick_model_root(install, data, override=model_root)
    if runtime_root is not None:
        runtimes, runtime_source = Path(os.path.abspath(Path(runtime_root).expanduser())), "override"
    else:
        runtimes, runtime_source = _pick_runtime_root(install, data)
    paths = RuntimePaths(
        install_root=install,
        user_data_root=data,
        model_root=chosen,
        cache_root=data / "cache",
        project_root=_project_root(data),
        config_root=data,
        log_root=data / "logs",
        renderer_asset_root=install / "renderer",
        temp_root=data / "tmp",
        model_root_source=source,
        discovered_model_roots=tuple(str(item) for item in discovered),
        runtime_root=runtimes,
        runtime_root_source=runtime_source,
    )
    if persist:
        persist_runtime_paths(paths)
    return paths


def persist_runtime_paths(paths: RuntimePaths) -> Path:
    destination = _config_path(paths.user_data_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # An environment override is for this process only; keep what was registered.
    runtime = ((_read_persisted_runtime_root(paths.user_data_root) or (None, ""))
               if paths.runtime_root_source == "environment"
               else (paths.runtime_root, paths.runtime_root_source))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "install_root": str(paths.install_root),
        "user_data_root": str(paths.user_data_root),
        "model_root": str(paths.model_root),
        "model_root_source": paths.model_root_source,
        "cache_root": str(paths.cache_root),
        "project_root": str(paths.project_root),
        "config_root": str(paths.config_root),
        "log_root": str(paths.log_root),
        "renderer_asset_root": str(paths.renderer_asset_root),
        "temp_root": str(paths.temp_root),
        "discovered_model_roots": list(paths.discovered_model_roots),
    }
    if runtime[0] is not None:
        payload["runtime_root"] = str(runtime[0])
        payload["runtime_root_source"] = runtime[1]
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix='.runtime-paths-', suffix='.tmp', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    os.environ[MODEL_ROOT_ENV] = str(paths.model_root)
    return destination


def reset_runtime_paths() -> None:
    global _CACHE
    _CACHE = None
    _RUNTIME_ROOT_CACHE.clear()


def get_runtime_paths(*, refresh: bool = False) -> RuntimePaths:
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = build_runtime_paths()
    return _CACHE


def bootstrap_runtime_paths(
    *,
    install_root: str | os.PathLike[str] | None = None,
    persist: bool = True,
) -> RuntimePaths:
    """Resolve and optionally persist roots for this process."""

    global _CACHE
    paths = build_runtime_paths(install_root=install_root, persist=persist)
    _CACHE = paths
    os.environ.setdefault(MODEL_ROOT_ENV, str(paths.model_root))
    for directory in (
        paths.user_data_root,
        paths.model_root,
        paths.cache_root,
        paths.project_root,
        paths.log_root,
        paths.temp_root,
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
    return paths


def set_model_root(path: str | os.PathLike[str], *, persist: bool = True) -> RuntimePaths:
    global _CACHE
    current = get_runtime_paths()
    paths = build_runtime_paths(
        install_root=current.install_root,
        model_root=path,
        persist=persist,
    )
    _CACHE = paths
    return paths


def set_runtime_root(path: str | os.PathLike[str], *, source: str = "moved") -> RuntimePaths:
    """Register a new runtime folder (after its contents were moved there)."""
    global _CACHE
    from dataclasses import replace
    current = get_runtime_paths()
    paths = replace(current, runtime_root=Path(os.path.abspath(Path(path).expanduser())), runtime_root_source=source)
    persist_runtime_paths(paths)
    _RUNTIME_ROOT_CACHE.clear()
    _CACHE = paths
    return paths


def iter_model_dir_candidates(
    folder_name: str,
    *,
    install_root: Path | None = None,
) -> Iterable[Path]:
    """Yield existing locations for one model folder, preferred first."""

    name = _leaf_model_name(folder_name)
    seen: set[str] = set()
    paths = get_runtime_paths()
    if os.environ.get("TWOBYTEASR_TEST_ROOT"):
        from .local_models.model_associations import is_model_detached
        candidate = (paths.model_root / name).resolve()
        for parent in (paths.model_root, *(Path(p) for p in paths.discovered_model_roots)):
            path = parent / name
            candidate = scan_memo(("resolve", str(path)), path.resolve)
            key = os.path.normcase(str(candidate))
            if key not in seen and not is_model_detached(candidate):
                seen.add(key)
                yield candidate
        return
    install = Path(install_root) if install_root is not None else paths.install_root
    ordered = [
        paths.model_root / name,
        install / "models" / name,
        install / name,
    ]
    for extra in discover_legacy_model_roots(install, paths.user_data_root):
        ordered.append(extra / name)
    for candidate in ordered:
        try:
            resolved = scan_memo(("resolve", str(candidate)), candidate.resolve)
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        from .local_models.model_associations import is_model_detached
        if is_model_detached(resolved):
            continue
        if key in seen:
            continue
        seen.add(key)
        yield resolved


def resolve_model_dir(folder_name: str, *, install_root: Path | None = None) -> Path:
    """Return the first existing directory for ``folder_name``, else MODEL_ROOT."""

    candidates = list(iter_model_dir_candidates(folder_name, install_root=install_root))
    specs = _load_lock_models(install_root or get_runtime_paths().install_root)
    required = next((spec.get('required_files', ()) for spec in specs.values()
                     if _leaf_model_name(spec.get('path', '')) == _leaf_model_name(folder_name)), ())
    for candidate in candidates:
        if model_files_present(candidate, required):
            return candidate
    return next((p for p in candidates if p.is_dir()), candidates[0] if candidates else user_data_root() / 'Models' / _leaf_model_name(folder_name))


def source_and_packaged_roots() -> dict[str, str]:
    paths = get_runtime_paths()
    return {
        "frozen": str(bool(getattr(sys, "frozen", False))),
        "install_root": str(paths.install_root),
        "user_data_root": str(paths.user_data_root),
        "model_root": str(paths.model_root),
        "model_root_source": paths.model_root_source,
        "runtime_root": str(paths.managed_runtime_root),
        "runtime_root_source": paths.runtime_root_source,
        "project_root": str(paths.project_root),
        "config_root": str(paths.config_root),
        "cache_root": str(paths.cache_root),
    }


__all__ = [
    "APP_NAME",
    "MODEL_ROOT_ENV",
    "RuntimePaths",
    "bootstrap_runtime_paths",
    "build_runtime_paths",
    "complete_model_count",
    "detect_install_root",
    "discover_legacy_model_roots",
    "get_runtime_paths",
    "iter_model_dir_candidates",
    "managed_runtime_root",
    "model_folder_name",
    "persist_runtime_paths",
    "reset_runtime_paths",
    "resolve_model_dir",
    "RUNTIME_ROOT_ENV",
    "set_model_root",
    "set_runtime_root",
    "source_and_packaged_roots",
    "user_data_root",
]
