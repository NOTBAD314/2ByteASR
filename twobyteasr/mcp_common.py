"""Local MCP access: settings, the GUI pipe, the access key and path checks (2026-10-12).

Shared by the running GUI (``mcp_bridge``) and the stdio server process
(``mcp_stdio``). Stdlib only: the stdio process must start fast and must
never print anything except protocol messages on stdout.

* The feature is off by default. Settings live under the additive ``mcp`` key
  of the Studio settings file (``enabled``, ``scope``, ``allow_edits``,
  ``allow_export``).
* While enabled, the GUI listens on a per-user named pipe and writes a random
  key next to the settings; the stdio server reads the key for every request.
  Turning the feature off (or "撤销授权") stops the pipe and deletes the key,
  so new requests fail at once.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path

PROTOCOL = "2byteasr-mcp-bridge/1"
SCOPES = ("current", "library")
DEFAULTS = {"enabled": False, "scope": "current", "allow_edits": False, "allow_export": False}
EXPORT_FOLDER = "MCP 导出"
MAX_LINE_BYTES = 4 * 1024 * 1024


def settings_root() -> Path:
    """Same root as ``settings.stable_settings_root`` (isolation aware)."""
    if os.environ.get("TWOBYTEASR_TEST_ROOT"):
        from .test_isolation import isolation_root
        return isolation_root() / "config"
    from .runtime_paths import user_data_root
    return Path(user_data_root())


def key_path() -> Path:
    return settings_root() / "mcp" / "access.key"


def pipe_name() -> str:
    """Per-user, per-data-root pipe name (Qt server name and \\\\.\\pipe\\ path)."""
    digest = hashlib.sha256(str(settings_root()).lower().encode("utf-8")).hexdigest()[:16]
    return f"2ByteASR-MCP-{digest}"


def pipe_path() -> str:
    return "\\\\.\\pipe\\" + pipe_name()


def read_settings() -> dict:
    from .studio_project import studio_settings_path
    try:
        payload = json.loads(studio_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {}
    value = payload.get("mcp") if isinstance(payload, dict) else None
    result = dict(DEFAULTS)
    if isinstance(value, dict):
        result.update({k: value[k] for k in DEFAULTS if k in value})
    result["enabled"] = bool(result["enabled"])
    result["allow_edits"] = bool(result["allow_edits"])
    result["allow_export"] = bool(result["allow_export"])
    if result["scope"] not in SCOPES:
        result["scope"] = "current"
    return result


def save_settings(values: dict) -> dict:
    from .application_settings import _write_settings_json
    clean = dict(DEFAULTS)
    clean.update({k: values[k] for k in DEFAULTS if k in values})
    clean = {"enabled": bool(clean["enabled"]), "scope": clean["scope"] if clean["scope"] in SCOPES else "current",
             "allow_edits": bool(clean["allow_edits"]), "allow_export": bool(clean["allow_export"])}
    _write_settings_json(lambda payload: payload.__setitem__("mcp", clean))
    return clean


def create_key() -> str:
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(key, encoding="ascii")
    os.replace(temporary, path)
    return key


def read_key() -> str:
    try:
        return key_path().read_text(encoding="ascii").strip()
    except OSError:
        return ""


def delete_key() -> None:
    try:
        key_path().unlink()
    except FileNotFoundError:
        pass


def is_reparse_point(path: Path) -> bool:
    """Symbolic link or junction (any reparse point) on this path component."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def inside(root: Path, target: Path) -> bool:
    """``target`` lies under ``root`` by real path, and no component between them
    is a link or junction (both checked before any read or write)."""
    try:
        root_real = Path(os.path.realpath(root))
        target_abs = Path(os.path.abspath(target))
        target_real = Path(os.path.realpath(target))
    except (OSError, ValueError):
        return False
    if not (target_real == root_real or root_real in target_real.parents):
        return False
    probe = target_abs
    root_abs = Path(os.path.abspath(root))
    while True:
        if probe != root_abs and is_reparse_point(probe):
            return False
        if probe == root_abs or probe.parent == probe:
            break
        probe = probe.parent
    return probe == root_abs


SAFE_NAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]{1,80}$")


def safe_file_stem(name: str) -> str | None:
    """A plain file name stem (no separators, no dots-only, no device names)."""
    name = str(name or "").strip()
    if not SAFE_NAME.match(name) or name.strip(". ") != name or set(name) <= {"."}:
        return None
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                                      *(f"LPT{i}" for i in range(10))}:
        return None
    return name


def client_config(command: str, args: list[str]) -> str:
    """The JSON a desktop MCP client needs (stdio)."""
    return json.dumps({"mcpServers": {"2byteasr": {"command": command, "args": args}}}, ensure_ascii=False, indent=2)


def server_command() -> tuple[str, list[str]]:
    import sys
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp-stdio"]
    root = Path(__file__).resolve().parents[1]
    python = root / ".venv-main" / "Scripts" / "python.exe"
    return str(python if python.is_file() else sys.executable), ["-B", str(root / "quick_start.py"), "--mcp-stdio"]
