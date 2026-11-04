# SPDX-License-Identifier: GPL-3.0-only
"""Native renderer browser locations matching locked Remotion BrowserFetcher."""
from __future__ import annotations
import os
import platform as host_platform
import sys
from pathlib import Path


def bundled_browser(root: Path, *, platform: str | None = None, machine: str | None = None) -> Path:
    system = platform or sys.platform
    architecture = (machine or host_platform.machine()).casefold()
    if system == "win32":
        tag, executable = "win64", "chrome-headless-shell.exe"
    elif system == "darwin":
        tag, executable = ("mac-arm64" if architecture in {"arm64", "aarch64"} else "mac-x64"), "chrome-headless-shell"
    else:
        tag = "linux-arm64" if architecture in {"arm64", "aarch64"} else "linux64"
        executable = "headless_shell" if tag == "linux-arm64" else "chrome-headless-shell"
    return Path(root) / "node_modules" / ".remotion" / "chrome-headless-shell" / tag / ("chrome-headless-shell-" + tag) / executable


def system_browser(*, platform: str | None = None) -> Path:
    configured = os.environ.get("TWOBYTEASR_RENDERER_CHROME", "")
    if configured:
        return Path(configured)
    system = platform or sys.platform
    if system == "win32":
        return Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if system == "darwin":
        return Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    # Discovery is deliberately local and never downloads a browser.
    import shutil
    return Path(shutil.which("chromium") or shutil.which("google-chrome") or "/usr/bin/chromium")
