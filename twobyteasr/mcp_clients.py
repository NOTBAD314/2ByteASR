"""Connect desktop AI clients to the local MCP server (2026-10-13).

Claude Desktop reads local stdio servers from ``claude_desktop_config.json``.
This module adds or removes only the ``2byteasr`` entry there:

* other servers, preferences and unknown keys are kept exactly;
* the file is backed up before every change, and a file that does not parse
  is never rewritten (the user is told where it is instead);
* the Microsoft Store (MSIX) build of Claude reads a per-package copy under
  ``%LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude``; when that
  package exists the entry is written there, merged from whichever file the
  app currently reads.

"Written" is not "connected": the app counts a client as connected only after
it actually called a tool through the pipe (see ``connection_lines``).

MCPB (``.mcpb``) bundles are not generated: the format packs the server into
the bundle, while this server is the installed 兔白 program itself, and the
specification does not define launching a program outside the bundle.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import mcp_common as common

CONFIG_NAME = "claude_desktop_config.json"
BACKUP_MARK = ".2byteasr-backup-"
KEEP_BACKUPS = 5
CLAUDE_DOWNLOAD_URL = "https://claude.ai/download"
CLAUDE_MCP_HELP_URL = "https://modelcontextprotocol.io/docs/develop/connect-local-servers"


class ConfigError(Exception):
    """The client's config file cannot be changed safely (left untouched)."""


@dataclass(frozen=True)
class ConfigLocation:
    path: Path          # the file the client reads (and the one we write)
    source: Path        # the file to merge from (differs only for a fresh MSIX copy)
    store_app: bool     # Microsoft Store (MSIX) build of Claude
    installed: bool     # Claude Desktop looks installed on this computer


def _msix_packages() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return []
    try:
        return sorted(p for p in (Path(local) / "Packages").glob("Claude_*") if p.is_dir())
    except OSError:
        return []


def claude_desktop_location(platform: str | None = None) -> ConfigLocation | None:
    """Where Claude Desktop keeps its config here; None where it does not exist (Linux)."""
    platform = platform or sys.platform
    if platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "Claude"
        installed = any(p.exists() for p in (Path("/Applications/Claude.app"),
                                             Path.home() / "Applications" / "Claude.app", folder))
        return ConfigLocation(folder / CONFIG_NAME, folder / CONFIG_NAME, False, installed)
    if platform != "win32":
        return None
    roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Claude" / CONFIG_NAME
    packages = _msix_packages()
    if packages:
        packaged = packages[0] / "LocalCache" / "Roaming" / "Claude" / CONFIG_NAME
        return ConfigLocation(packaged, packaged if packaged.exists() or not roaming.exists() else roaming,
                              True, True)
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "AnthropicClaude" if os.environ.get("LOCALAPPDATA") else None
    installed = roaming.parent.is_dir() or bool(local and local.is_dir())
    return ConfigLocation(roaming, roaming, False, installed)


def read_config(path: Path) -> dict:
    """The parsed config ({} when absent); ConfigError when it is not a JSON object."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"读不到 {path}：{exc}") from exc
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"{path} 不是有效的 JSON（第 {getattr(exc, 'lineno', '?')} 行），没有修改它") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"{path} 的内容不是 JSON 对象，没有修改它")
    servers = payload.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise ConfigError(f"{path} 里的 mcpServers 不是对象，没有修改它")
    return payload


def entry_state(location: ConfigLocation | None, command: str, args: list[str]) -> str:
    """missing_client / invalid / not_written / outdated / written."""
    if location is None:
        return "missing_client"
    try:
        payload = read_config(location.source)
    except ConfigError:
        return "invalid"
    current = (payload.get("mcpServers") or {}).get(common.SERVER_NAME)
    if not isinstance(current, dict):
        return "not_written" if location.installed else "missing_client"
    wanted = common.server_entry(command, args)
    same = current.get("command") == wanted["command"] and list(current.get("args") or []) == wanted["args"] \
        and (current.get("env") or {}) == wanted.get("env", {})
    return "written" if same else "outdated"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}{BACKUP_MARK}{stamp}")
    counter = 1
    while backup.exists():
        counter += 1
        backup = path.with_name(f"{path.name}{BACKUP_MARK}{stamp}-{counter}")
    backup.write_bytes(path.read_bytes())
    old = sorted(path.parent.glob(f"{path.name}{BACKUP_MARK}*"), key=lambda p: p.stat().st_mtime)
    for stale in old[:-KEEP_BACKUPS]:
        try:
            stale.unlink()
        except OSError:
            pass
    return backup


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.2byteasr.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_entry(location: ConfigLocation, command: str, args: list[str]) -> Path | None:
    """Add or update only our server entry; returns the backup path (None for a new file)."""
    payload = read_config(location.source)
    backup = _backup(location.path)
    servers = dict(payload.get("mcpServers") or {})
    servers[common.SERVER_NAME] = common.server_entry(command, args)
    payload["mcpServers"] = servers
    _write(location.path, payload)
    return backup


def remove_entry(location: ConfigLocation) -> Path | None:
    payload = read_config(location.source)
    servers = dict(payload.get("mcpServers") or {})
    if common.SERVER_NAME not in servers:
        return None
    backup = _backup(location.path)
    servers.pop(common.SERVER_NAME)
    payload["mcpServers"] = servers
    _write(location.path, payload)
    return backup


def claude_code_command(command: str, args: list[str]) -> str:
    """The one-line ``claude mcp add`` for Claude Code (user scope)."""
    def quote(value: str) -> str:
        return f'"{value}"' if any(ch in value for ch in ' \t&()^%!;,') or not value else value
    entry = common.server_entry(command, args)
    env = "".join(f" -e {key}={quote(value)}" for key, value in (entry.get("env") or {}).items())
    return f"claude mcp add --scope user{env} {common.SERVER_NAME} -- " + " ".join(quote(p) for p in [command, *args])


def connection_lines(stats: dict, listening: bool, state: str, now: float | None = None) -> list[str]:
    """Plain status lines: generated / written / client started / actually connected."""
    from .i18n import tr
    now = time.time() if now is None else now
    lines = []
    lines.append({
        "written": tr("Claude Desktop 配置：已写入（完全退出并重新打开 Claude 后生效）"),
        "outdated": tr("Claude Desktop 配置：已有 2byteasr 条目，但指向另一个位置；可重新写入"),
        "not_written": tr("Claude Desktop 配置：尚未写入"),
        "invalid": tr("Claude Desktop 配置：文件无法解析，未做修改"),
        "missing_client": tr("Claude Desktop：这台电脑上没有找到"),
    }.get(state, ""))
    if not listening:
        lines.append(tr("连接：兔白未开启 MCP 访问，客户端调用会被拒绝"))
        return [line for line in lines if line]
    client = stats.get("client") or tr("未报告名称的客户端")
    last_tool = float(stats.get("last_tool_at") or 0)
    started = float(stats.get("client_started_at") or 0)
    if last_tool:
        lines.append(tr("连接：实际已连线 — {client} 在 {ago} 调用了 {method}",
                        client=client, ago=_ago(now - last_tool), method=stats.get("last_method") or "?"))
    elif started:
        lines.append(tr("连接：客户端已启动兔白的 MCP 服务（{ago}），还没有调用工具",
                        ago=_ago(now - started)))
    else:
        lines.append(tr("连接：正在等待客户端（本次启动后还没有客户端连接）"))
    return lines


def _ago(seconds: float) -> str:
    from .i18n import tr
    seconds = max(0, int(seconds))
    if seconds < 60:
        return tr("{n} 秒前", n=seconds)
    if seconds < 3600:
        return tr("{n} 分钟前", n=seconds // 60)
    return tr("{n} 小时前", n=seconds // 3600)
