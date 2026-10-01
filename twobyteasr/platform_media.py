# SPDX-License-Identifier: GPL-3.0-only
"""Names and installed paths of native media executables, never libmpv."""
from __future__ import annotations
import os
from pathlib import Path


def executable_name(name: str, *, windows: bool | None = None) -> str:
    return name + (".exe" if (os.name == "nt" if windows is None else windows) else "")


def ffmpeg_tool(name: str = "ffmpeg", *, root: Path | None = None) -> Path:
    if name not in {"ffmpeg", "ffprobe"}:
        raise ValueError("Unsupported media tool: " + name)
    if root is None:
        from .runtime_paths import get_runtime_paths
        root = get_runtime_paths().install_root
    return Path(root) / "tools" / "ffmpeg" / "bin" / executable_name(name)
