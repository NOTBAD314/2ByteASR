# SPDX-License-Identifier: GPL-3.0-only
"""Retained standalone mpv IPC boundary; Windows Studio keeps its HWND.

Mac Studio now selects the video-only Qt adapter. The native mpv arguments
and UNIX socket remain available for independent diagnostics, without
claiming that a cross-process Cocoa window embeds in a Qt NSView.
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path


def preview_surface(platform: str | None = None) -> str:
    selected=platform or sys.platform
    return "embedded-hwnd" if selected=="win32" else "embedded-qt-video-sink" if selected=="darwin" else "external-window"


def native_video_arguments(window_id: int, *, platform: str | None = None) -> list[str]:
    platform = platform or sys.platform
    if platform == "win32":
        if int(window_id) <= 0:
            raise ValueError("window_id must be a positive native HWND")
        return ["--gpu-api=d3d11", f"--wid={int(window_id)}"]
    # A native Qt winId on Cocoa is not a cross-process NSView. Never pass it
    # to --wid. Linux also defaults to a separate window, avoiding the same
    # assumption under Wayland. Studio retains playback/PCM ownership.
    return (["--gpu-api=auto", "--gpu-context=macvk"] if platform == "darwin"
            else ["--gpu-api=auto"])


def unix_ipc_path() -> str:
    # macOS sockaddr_un.sun_path is short; TMPDIR is frequently much longer
    # than /tmp. A random 0700 subdirectory also prevents another local user
    # from controlling the un-authenticated mpv JSON IPC endpoint.
    directory = Path(tempfile.mkdtemp(prefix="2basr-mpv-", dir="/tmp"))
    directory.chmod(0o700)
    return str(directory / "ipc.sock")


def cleanup_unix_ipc(path: str) -> None:
    candidate = Path(path)
    if candidate.name != "ipc.sock" or not candidate.parent.name.startswith("2basr-mpv-"):
        return
    try:
        candidate.unlink(missing_ok=True)
        candidate.parent.rmdir()
    except OSError:
        # Another file is never recursively deleted; a leftover private
        # directory is safer than deleting something we no longer own.
        pass


class UnixIPCStream:
    """Unbuffered socket endpoint matching the actor's duplex stream API."""
    def __init__(self, path: str, timeout: float = 1.0):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.socket.settimeout(max(0.01, timeout))
            self.socket.connect(path)
            self.socket.settimeout(None)
        except BaseException:
            self.socket.close()
            raise

    def write(self, value: bytes) -> int:
        self.socket.sendall(value)
        return len(value)

    def fileno(self) -> int:
        return self.socket.fileno()

    def close(self) -> None:
        self.socket.close()


def open_mpv_ipc(path: str, *, timeout: float = 1.0):
    if os.name == "nt":
        return open(path, "r+b", buffering=0)
    return UnixIPCStream(path, timeout)
