"""Runtime environment registry: the single source of truth for interpreters.

MAIN / MOSS / FIRERED_LLM python interpreters must never be derived from the
install directory of a packaged build — ``dist`` is rewritten by every build
and update. Resolution order (first existing interpreter wins):

1. explicit environment override (``TWOBYTEASR_<ROLE>_PYTHON`` and the
   historical ``TWOBYTEASR_MAIN_PYTHON``),
2. the persisted registry (``<runtime root>\\registry.json``),
3. the stable per-role root (``<runtime root>\\<role>``).

Legacy in-place venv discovery is source-only and explicitly opt-in. Ordinary
resolution is read-only. Validated generation publication is explicit and
serializes the complete registry read/modify/write across processes.

The runtime root is ``runtime_paths.managed_runtime_root()``: the program
folder's ``runtimes`` for new Windows installs, ``%LOCALAPPDATA%\\2ByteASR\\
runtimes`` where runtimes already are, or wherever the user moved them.

Existing healthy environments are registered in place; nothing is copied or
re-downloaded. Source mode and packaged mode resolve the same runtimes.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from twobyteasr.runtime_paths import managed_runtime_root

# "mlx": Apple Silicon MLX speech runtime without PyTorch (2026-10-13).
RUNTIME_ROLES = ("main", "moss", "firered_llm", "glm_asr", "canary", "mlx")

_ROLE_VENV_NAMES = {
    "canary": ".venv-canary",
    "glm_asr": ".venv-glm-asr",
    "main": ".venv-main",
    "moss": ".venv-moss",
    "firered_llm": ".venv-firered-llm",
    "mlx": ".venv-mlx",
}

_ROLE_DIRS = {
    "main": "main",
    "moss": "moss",
    "firered_llm": "firered-llm",
}

_ROLE_ENV_OVERRIDES = {
    "canary": ("TWOBYTEASR_CANARY_PYTHON",),
    "glm_asr": ("TWOBYTEASR_GLM_ASR_PYTHON",),
    "main": ("TWOBYTEASR_MAIN_PYTHON", "TWOBYTEASR_MAIN_RUNTIME_PYTHON"),
    "moss": ("TWOBYTEASR_MOSS_PYTHON", "TWOBYTEASR_MOSS_RUNTIME_PYTHON"),
    "firered_llm": ("TWOBYTEASR_FIRERED_LLM_PYTHON",),
    "mlx": ("TWOBYTEASR_MLX_PYTHON",),
}

REGISTRY_SCHEMA_VERSION = 1

_LOCK = threading.RLock()
_CACHE: dict[str, str] = {}


@contextmanager
def _publication_lock(timeout: float = 15.0):
    """Serialize registry read/modify/write across installers and GUI processes.

    The persistent filename is harmless: ownership is an OS handle/byte lock
    that is released even when the publishing process crashes.
    """
    path = registry_path().with_suffix('.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'\0')
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError('另一进程正在更新运行环境登记；本次没有覆盖登记，请重试。') from exc
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class RuntimeRegistration:
    runtime_id: str
    role: str
    python_executable: str
    root: str
    source: str
    registered_at: str


def runtimes_root() -> Path:
    return Path(managed_runtime_root())


def stable_runtime_root(role: str) -> Path:
    return runtimes_root() / _ROLE_DIRS.get(role, role)


def registry_path() -> Path:
    return runtimes_root() / "registry.json"


def _relative_python(role: str, base: Path) -> Path:
    return runtime_python_path(base / _ROLE_VENV_NAMES.get(role, f".venv-{role}"))


def runtime_python_path(root: Path) -> Path:
    return root / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def _candidate_pythons(role: str) -> list[tuple[Path, str]]:
    """Ordered (python_path, source) candidates for one role."""
    candidates: list[tuple[Path, str]] = []

    def add(path: Path, source: str) -> None:
        if path not in [item[0] for item in candidates]:
            candidates.append((path, source))

    for name in _ROLE_ENV_OVERRIDES.get(role, ()):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            add(Path(value), f"environment:{name}")

    registered = load_registry().get(role)
    if isinstance(registered, dict):
        # Recover only the explicitly recorded venv root/config; identical
        # base binaries are not evidence of identical environments.
        saved_root = str(registered.get("root") or "").strip()
        if saved_root and (Path(saved_root) / "pyvenv.cfg").is_file():
            entry = runtime_python_path(Path(saved_root))
            if entry.is_file():
                add(entry, "registry:venv-root")
        python_value = str(registered.get("python_executable") or "").strip()
        if python_value:
            add(Path(python_value), "registry")

    # Formal runtime selection is confined to the app-owned runtime root.
    # Developer runtimes are an explicit source-only opt-in, never discovery
    # based on another application's PATH or a historical Desktop checkout.
    developer = (not getattr(sys, 'frozen', False)
                 and os.environ.get('TWOBYTEASR_DEVELOPER_RUNTIMES') == '1'
                 and os.environ.get('TWOBYTEASR_MANAGED_RUNTIME_ONLY') != '1')
    if not developer:
        boundary = runtimes_root().resolve()
        candidates = [(path, source) for path, source in candidates if path.resolve().is_relative_to(boundary)]
        add(runtime_python_path(stable_runtime_root(role)), 'stable_root')
        return candidates

    try:
        from twobyteasr.runtime_paths import detect_install_root

        install_root = detect_install_root()
    except Exception:
        install_root = Path.cwd()

    for base, label in (
        (install_root.parent.parent, "legacy_source_checkout"),
        (install_root.parent, "legacy_install_parent"),
        (install_root, "legacy_install_root"),
        (Path.home() / "Desktop" / "2ByteASR", "legacy_desktop_checkout"),
    ):
        try:
            add(_relative_python(role, Path(base)), label)
        except OSError:
            continue

    add(runtime_python_path(stable_runtime_root(role)), "stable_root")
    return candidates


def load_registry() -> dict:
    try:
        payload = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    entries = payload.get("runtimes") if isinstance(payload, dict) else None
    return dict(entries) if isinstance(entries, dict) else {}


def _save_registry(entries: dict) -> None:
    path = registry_path()
    payload = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "runtimes": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def register_runtime(role: str, python_executable: str, *, source: str = "manual") -> RuntimeRegistration:
    """Persist one interpreter in place (never copied)."""
    if role not in RUNTIME_ROLES:
        raise ValueError('Unknown runtime role: '+str(role))
    from ..python_runtime_identity import python_entry_path
    python_path = Path(python_entry_path(python_executable))
    root = python_path.parent.parent
    registration = RuntimeRegistration(
        runtime_id=f"{role}-runtime",
        role=role,
        python_executable=str(python_path),
        root=str(root),
        source=source,
        registered_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    with _LOCK, _publication_lock():
        entries = load_registry()
        existing = entries.get(role, {})
        if (os.path.normcase(str(existing.get("python_executable", ""))) == os.path.normcase(str(python_path))
                and existing.get("root") == str(root)):
            return RuntimeRegistration(runtime_id=existing.get('runtime_id', registration.runtime_id),
                role=role, python_executable=str(python_path), root=str(root),
                source=existing.get('source', source), registered_at=existing.get('registered_at', registration.registered_at))
        entries[role] = {
            "runtime_id": registration.runtime_id,
            "python_executable": registration.python_executable,
            "root": registration.root,
            "entry_python": registration.python_executable,
            "resolved_binary": str(python_path.resolve()),
            "source": registration.source,
            "registered_at": registration.registered_at,
        }
        _save_registry(entries)
        _CACHE.pop(role, None)
    return registration


def resolve_runtime_python(role: str, *, register: bool = False) -> str:
    """Absolute path to the role interpreter, or '' when none exists.

    Production interpreters must remain inside the application's runtime
    directory. Legacy development environments require an explicit source-only
    opt-in; frozen applications never discover them. Ordinary resolution does
    not publish. The compatibility opt-in may register a discovered override,
    but never writes a previously read registry entry back over a new generation.
    """
    if role not in RUNTIME_ROLES:
        raise ValueError('Unknown runtime role: '+str(role))
    register = register and os.environ.get("TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY") != "1"
    with _LOCK:
        # Re-evaluate overrides and persisted identity; an old cache cannot
        # override a newly selected venv or a repaired registration.
        for candidate, source in _candidate_pythons(role):
            try:
                if candidate.is_file():
                    from ..python_runtime_identity import python_entry_path
                    resolved = python_entry_path(candidate)
                    if register and not source.startswith('registry'):
                        register_runtime(role, resolved, source=source)
                    _CACHE[role] = resolved
                    return resolved
            except OSError:
                continue
        return ""


def runtime_root(role: str) -> str:
    """Venv root for the resolved interpreter ('' when unresolved)."""
    python_executable = resolve_runtime_python(role)
    return str(Path(python_executable).parent.parent) if python_executable else ""


def intended_runtime_root(role: str) -> str:
    """Where this role's runtime should live (registry entry or stable root).

    Repair and user-facing diagnostics use this so a missing environment is
    reported — and rebuilt — at the stable root, never inside ``dist``.
    """
    registered = load_registry().get(role)
    if isinstance(registered, dict):
        root = str(registered.get("root") or "").strip()
        if root and Path(root).resolve().is_relative_to(runtimes_root().resolve()):
            return root
    return str(stable_runtime_root(role))


def runtime_probe_path() -> str:
    """Single source of truth for the standalone environment_probe.py location.

    Source mode: ``<repo>\\twobyteasr\\environment_probe.py``.
    Frozen mode: ``<install_root>\\environment_probe.py`` (shipped next to the
    worker scripts by the PyInstaller spec). MAIN, MOSS and repair share this
    locator — no call site may assemble its own probe path. Returns '' when
    the probe file cannot be found; callers must refuse to spawn and report.
    """
    candidates: list[Path] = []
    try:
        from twobyteasr.runtime_paths import detect_install_root

        candidates.append(Path(detect_install_root()) / "environment_probe.py")
    except Exception:
        pass
    candidates.append(Path(__file__).resolve().parents[2] / "twobyteasr" / "environment_probe.py")
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    return ""


def reset_runtime_registry_cache() -> None:
    with _LOCK:
        _CACHE.clear()


__all__ = [
    "RUNTIME_ROLES",
    "RuntimeRegistration",
    "intended_runtime_root",
    "load_registry",
    "register_runtime",
    "registry_path",
    "reset_runtime_registry_cache",
    "resolve_runtime_python",
    "runtime_probe_path",
    "runtime_root",
    "runtimes_root",
    "stable_runtime_root",
]
