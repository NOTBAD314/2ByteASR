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

2026-10-17: Claude Desktop reads this file only when it starts and, while it
runs, writes its in-memory copy back whenever its own preferences change, so
an entry added meanwhile disappears within seconds (seen in its main.log:
the app wrote at 23:21:28, Claude rewrote the file at 23:22:00). Writing is
therefore refused while Claude Desktop runs, every write is read back, and a
small record (``mcp/clients.json`` in this app's data folder) remembers what
was written so a vanished entry is reported as overwritten rather than as
never written. Claude Code (also the Code tab inside Claude Desktop) reads
user-level servers from ``~/.claude.json`` instead; ``claude_code_location``.

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
CLAUDE_CODE_CONFIG_NAME = ".claude.json"
BACKUP_MARK = ".2byteasr-backup-"
KEEP_BACKUPS = 5
CLAUDE_DOWNLOAD_URL = "https://claude.ai/download"
CLAUDE_MCP_HELP_URL = "https://modelcontextprotocol.io/docs/develop/connect-local-servers"
DESKTOP, CODE = "claude_desktop", "claude_code"
# Install folders of Claude Desktop's own claude.exe (Store build, per-user
# installer). Claude Code's claude.exe has the same name and lives under
# "...\Claude\claude-code\<version>\", so the name alone is not enough.
_DESKTOP_FOLDERS = ("\\windowsapps\\claude_", "\\anthropicclaude\\")


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


def claude_code_location() -> ConfigLocation:
    """Claude Code's user-level config (``claude mcp add --scope user`` writes here)."""
    folder = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    path = (Path(folder) if folder else Path.home()) / CLAUDE_CODE_CONFIG_NAME
    installed = path.exists() or (Path.home() / ".claude").is_dir()
    return ConfigLocation(path, path, False, installed)


def is_claude_desktop_process(name: str, exe: str, platform: str | None = None) -> bool:
    platform = platform or sys.platform
    if platform == "win32":
        folded = str(exe or "").replace("/", "\\").casefold()
        return (str(name or "").casefold() == "claude.exe" and "\\claude-code\\" not in folded
                and any(mark in folded for mark in _DESKTOP_FOLDERS))
    if platform == "darwin":
        return str(exe or "").endswith("/Claude.app/Contents/MacOS/Claude")
    return False


def _windows_processes(image: str) -> list[tuple[str, str, float]] | None:
    """(name, full path, start epoch) of processes named ``image``; a Toolhelp
    snapshot takes milliseconds where psutil's first full scan took 2.5 s."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return None
    found = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.casefold() == image:
                handle = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)  # QUERY_LIMITED_INFORMATION
                if handle:
                    try:
                        buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
                        times = [wintypes.FILETIME() for _ in range(4)]
                        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) and \
                                kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                            found.append((entry.szExeFile, buffer.value, ticks / 1e7 - 11644473600))
                    finally:
                        kernel32.CloseHandle(handle)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def claude_desktop_started_at(platform: str | None = None) -> float | None:
    """When the running Claude Desktop started (epoch s); 0.0 when it is not
    running; None when processes cannot be listed (then nothing is refused)."""
    platform = platform or sys.platform
    try:
        if platform == "win32":
            rows = _windows_processes("claude.exe")
        else:
            import psutil
            rows = []
            for proc in psutil.process_iter(["name", "exe", "create_time"]):
                info = proc.info
                if str(info.get("name") or "").casefold().startswith("claude"):
                    rows.append((info.get("name") or "", info.get("exe") or "", info.get("create_time") or 0))
    except Exception:  # noqa: BLE001 - an optional check: when it fails nothing is refused
        return None
    if rows is None:
        return None
    started = [float(when) for name, exe, when in rows if is_claude_desktop_process(name, exe, platform)]
    return min(started) if started else 0.0


def _records_path() -> Path:
    return common.settings_root() / "mcp" / "clients.json"


def _records() -> dict:
    try:
        payload = json.loads(_records_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _remember(client: str, path: Path | None) -> None:
    """Record (or with ``path=None`` forget) that our entry was written there."""
    records = _records()
    if path is None:
        if records.pop(client, None) is None:
            return
    else:
        records[client] = {"path": str(path), "written_at": time.time()}
    target = _records_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        pass  # only improves the status wording


def written_at(client: str, location: ConfigLocation | None) -> float:
    """When this app last wrote its entry into ``location`` (0 when it did not)."""
    record = _records().get(client)
    if location is None or not isinstance(record, dict):
        return 0.0
    if os.path.normcase(str(record.get("path") or "")) != os.path.normcase(str(location.path)):
        return 0.0
    try:
        return float(record.get("written_at") or 0)
    except (TypeError, ValueError):
        return 0.0


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


def entry_state(location: ConfigLocation | None, command: str, args: list[str], client: str = DESKTOP) -> str:
    """missing_client / invalid / not_written / lost / outdated / written.

    ``lost``: this app wrote the entry there and did not remove it, but it is
    gone (Claude Desktop rewrote the file from memory while running)."""
    if location is None:
        return "missing_client"
    try:
        payload = read_config(location.source)
    except ConfigError:
        return "invalid"
    current = (payload.get("mcpServers") or {}).get(common.SERVER_NAME)
    if not isinstance(current, dict):
        if written_at(client, location):
            return "lost"
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


def _entry(client: str, command: str, args: list[str]) -> dict:
    entry = common.server_entry(command, args)
    return {"type": "stdio", **entry} if client == CODE else entry


def write_entry(location: ConfigLocation, command: str, args: list[str], client: str = DESKTOP) -> Path | None:
    """Add or update only our server entry, then read it back; returns the
    backup path (None for a new file). ConfigError when the read-back misses it."""
    payload = read_config(location.source)
    backup = _backup(location.path)
    servers = dict(payload.get("mcpServers") or {})
    servers[common.SERVER_NAME] = _entry(client, command, args)
    payload["mcpServers"] = servers
    _write(location.path, payload)
    again = (read_config(location.path).get("mcpServers") or {}).get(common.SERVER_NAME)
    if again != servers[common.SERVER_NAME]:
        raise ConfigError(f"写入后重新读取 {location.path}，里面没有 2byteasr（可能被正在运行的程序改回了）")
    _remember(client, location.path)
    return backup


def remove_entry(location: ConfigLocation, client: str = DESKTOP) -> Path | None:
    payload = read_config(location.source)
    servers = dict(payload.get("mcpServers") or {})
    _remember(client, None)
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


def config_lines(client: str, state: str, written: float = 0.0, started: float | None = None) -> list[str]:
    """What the client's config holds, and for Claude Desktop whether it can
    still be written (``started``: Claude Desktop's start time, 0 = not running)."""
    from ..i18n import tr
    when = time.strftime("%m-%d %H:%M", time.localtime(written)) if written else ""
    if client == CODE:
        return [{
            "written": tr("Claude Code 配置：已写入（之后新开的 Claude Code 会话可用）"),
            "outdated": tr("Claude Code 配置：已有 2byteasr 条目，但指向另一个位置；可重新写入"),
            "not_written": tr("Claude Code 配置：尚未写入"),
            "lost": tr("Claude Code 配置：兔白 {when} 写入的 2byteasr 已经不在了；可再写入一次", when=when),
            "invalid": tr("Claude Code 配置：文件无法解析，未做修改"),
            "missing_client": tr("Claude Code：这台电脑上没有找到"),
        }.get(state, "")]
    running = bool(started)
    if state == "written" and running and written and started < written:
        lines = [tr("Claude Desktop 配置：已写入，但 Claude 在写入前就已打开——它读不到这一项，"
                    "还会在改自己的设置时把它覆盖。请完全退出 Claude 后再写入一次")]
    elif state == "written" and running and written:
        lines = [tr("Claude Desktop 配置：已写入，Claude 打开时已读到")]
    else:
        lines = [{
            "written": tr("Claude Desktop 配置：已写入（完全退出并重新打开 Claude 后生效）"),
            "outdated": tr("Claude Desktop 配置：已有 2byteasr 条目，但指向另一个位置；可重新写入"),
            "not_written": tr("Claude Desktop 配置：尚未写入"),
            "lost": tr("Claude Desktop 配置：兔白 {when} 写入的 2byteasr 被 Claude 覆盖了——Claude 运行时"
                       "只用它打开时读到的设置，改设置时会整份写回", when=when),
            "invalid": tr("Claude Desktop 配置：文件无法解析，未做修改"),
            "missing_client": tr("Claude Desktop：这台电脑上没有找到"),
        }.get(state, "")]
    if running and state != "written":
        lines.append(tr("Claude 正在运行：要先完全退出 Claude（任务栏托盘图标 → 退出，只关窗口不算），再写入"))
    return lines


def connection_lines(stats: dict, listening: bool, state: str, now: float | None = None, *,
                     client: str = DESKTOP, written: float = 0.0, started: float | None = None) -> list[str]:
    """Plain status lines: generated / written / client started / actually connected."""
    from ..i18n import tr
    now = time.time() if now is None else now
    lines = config_lines(client, state, written, started)
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
    from ..i18n import tr
    seconds = max(0, int(seconds))
    if seconds < 60:
        return tr("{n} 秒前", n=seconds)
    if seconds < 3600:
        return tr("{n} 分钟前", n=seconds // 60)
    return tr("{n} 小时前", n=seconds // 3600)
