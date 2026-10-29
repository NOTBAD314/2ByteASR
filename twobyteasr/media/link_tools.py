"""Pinned, application-owned downloader; reuses runtime paths, CA and native tools."""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading

from .link_manifest import sha256
from ..runtime_paths import get_runtime_paths
from ..system.processes import run_hidden_subprocess
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


def ensure_tools(*, cancel=None, progress=None, install=True, root=None, proxy="") -> dict:
    """Call in a worker, never in Qt's event loop. No system Python/Node lookup."""
    paths = get_runtime_paths()
    root = Path(root or paths.install_root)
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
    node = root/"tools/node"/executable_name("node")
    ffmpeg = root/"tools/ffmpeg/bin"/executable_name("ffmpeg")
    for name, path in (("Node", node), ("FFmpeg", ffmpeg)):
        if not path.is_file():
            raise RuntimeError(f"程序自带 {name} 缺失，请修复应用安装。")
    node_version = run_hidden_subprocess([str(node), "--version"], purpose="link Node check",
        capture_output=True, text=True, timeout=10).stdout.strip()
    if int(node_version.lstrip("v").split(".")[0]) < spec["node_min_major"]:
        raise RuntimeError("下载需要 Node 22 或更高版本，请更新兔白自带运行库。")
    ffmpeg_version = run_hidden_subprocess([str(ffmpeg), "-version"], purpose="link FFmpeg check",
        capture_output=True, text=True, timeout=10).stdout.splitlines()[0]
    return dict(ytdlp=str(target), node=str(node), ffmpeg=str(ffmpeg),
        versions=dict(yt_dlp=spec["version"], ejs=spec["ejs_version"], node=node_version, ffmpeg=ffmpeg_version),
        sha256=item["sha256"])
