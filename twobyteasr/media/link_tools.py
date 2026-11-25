"""Pinned, application-owned downloader; reuses runtime paths, CA and native tools."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import threading

from .link_manifest import sha256
from ..runtime_paths import get_runtime_paths
from ..system.processes import run_hidden_subprocess, sanitized_child_environment
from ..system.platform_media import executable_name

_INSTALL_LOCK = threading.Lock()


class DownloadCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel and cancel():
        raise DownloadCancelled("已取消；完整文件与可续传部分已保留。")


def tool_spec(root: Path) -> dict:
    lock = json.loads((root/"dependencies.lock.json").read_text(encoding="utf-8-sig"))
    return lock["tools"]["yt_dlp"]


def ensure_tools(*, cancel=None, progress=None, install=True, root=None, proxy="", use_managed=True) -> dict:
    """Call in a worker, never in Qt's event loop. No system Python/Node lookup."""
    paths = get_runtime_paths()
    root = Path(root or paths.install_root)
    if use_managed:
        from .link_tool_updates import active_tools
        selected = active_tools()
        if selected:
            return selected
    spec = tool_spec(root)
    platform = "windows" if os.name == "nt" else "macos"
    item = spec["files"][platform]
    filename = item["name"]
    packaged = root/"tools/yt-dlp"/filename
    managed = paths.managed_runtime_root/"tools/yt-dlp"/spec["version"]/filename
    with _INSTALL_LOCK:
        target = next((p for p in (packaged, managed) if p.is_file() and sha256(p) == item["sha256"]), managed)
        if not target.is_file() or sha256(target) != item["sha256"]:
            if not install:
                raise RuntimeError("下载工具缺失；请在链接下载窗口检查并安装工具。")
            from ..providers.network_policy import request
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(filename+".partial")
            last_error = None
            for attempt in range(2):
                check_cancel(cancel)
                try:
                    with request("get", item["url"], stream=True, timeout=(15, 20),
                                 **({"proxies": {"http": proxy, "https": proxy}} if proxy else {})) as response:
                        response.raise_for_status()
                        count = 0
                        with partial.open("wb") as stream:
                            for chunk in response.iter_content(256*1024):
                                check_cancel(cancel)
                                count += len(chunk)
                                if count > item["bytes"]:
                                    raise ValueError("下载工具大小与锁定版本不符。")
                                stream.write(chunk)
                                if progress:
                                    progress(dict(stage="tools", downloaded=count, total=item["bytes"]))
                    if partial.stat().st_size != item["bytes"] or sha256(partial) != item["sha256"]:
                        raise ValueError("下载工具 SHA-256 校验失败，未安装。")
                    if os.name != "nt":
                        partial.chmod(0o755)
                    completed = run_hidden_subprocess([str(partial), "--ignore-config", "--version"],
                        purpose="link tool verification", capture_output=True, text=True, timeout=30)
                    if completed.returncode or completed.stdout.strip() != spec["version"]:
                        raise ValueError("下载工具运行版本校验失败，未安装。")
                    os.replace(partial, target)
                    last_error = None
                    break
                except DownloadCancelled:
                    raise
                except Exception as exc:
                    last_error = exc
            if last_error:
                raise RuntimeError("下载工具安装失败，请检查网络后重试。") from last_error
    result = probe_tool_versions(target, root, min_node=spec["node_min_major"])
    if result["versions"]["yt_dlp"] != spec["version"] or result["versions"]["ejs"] != spec["ejs_version"]:
        raise RuntimeError("下载工具的运行版本与锁表不一致，请修复应用安装。")
    result["sha256"] = item["sha256"]
    return result


def probe_tool_versions(ytdlp: Path, root: Path, *, min_node=22) -> dict:
    node = root/"tools/node"/executable_name("node")
    ffmpeg = root/"tools/ffmpeg/bin"/executable_name("ffmpeg")
    ffprobe = ffmpeg.with_name(executable_name("ffprobe"))
    for name, path in (("yt-dlp", ytdlp), ("Node", node), ("FFmpeg", ffmpeg), ("FFprobe", ffprobe)):
        if not path.is_file():
            raise RuntimeError(f"程序自带 {name} 缺失，请修复应用安装。")
    env = sanitized_child_environment()
    for key in ("NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)

    def run(exe, *arguments):
        return run_hidden_subprocess([str(exe), *arguments], purpose="link tool probe",
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=24)

    def line(exe, arguments, prefix):
        completed = run(exe, *arguments)
        value = (completed.stdout.strip().splitlines() or [""])[0]
        if completed.returncode or not value.startswith(prefix):
            raise RuntimeError(f"{exe.stem} 无法正常运行。")
        return value

    node_version = line(node, ("--version",), "v")
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+(?:[-+].*)?", node_version)
    if not match or int(match[1]) < min_node:
        raise RuntimeError(f"下载需要 Node {min_node} 或更高版本。")
    ffmpeg_version = line(ffmpeg, ("-version",), "ffmpeg version ")
    ffprobe_version = line(ffprobe, ("-version",), "ffprobe version ")
    if ffmpeg_version.split()[2] != ffprobe_version.split()[2]:
        raise RuntimeError("FFmpeg 和 FFprobe 版本不匹配。")
    yt_dlp_version = line(ytdlp, ("--ignore-config", "--no-plugin-dirs", "--version"), "")
    if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}(?:[.\w-]*)", yt_dlp_version):
        raise RuntimeError("无法确认下载器版本。")
    diagnostic = run(ytdlp, "--ignore-config", "--no-plugin-dirs", "--no-remote-components",
                     "--verbose", "--simulate", "--default-search", "error", "--", "not-a-video-url")
    solver = re.search(r"\byt_dlp_ejs-([\d.]+)", diagnostic.stdout + diagnostic.stderr)
    if not solver:
        raise RuntimeError("下载器缺少可验证的 EJS 组件。")
    return dict(ytdlp=str(ytdlp), node=str(node), ffmpeg=str(ffmpeg), ffprobe=str(ffprobe),
                versions=dict(yt_dlp=yt_dlp_version, ejs=solver[1], node=node_version,
                              ffmpeg=ffmpeg_version, ffprobe=ffprobe_version))
