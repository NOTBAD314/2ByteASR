"""Native Messaging host entry point for the frozen Windows application."""
from __future__ import annotations

import json
from pathlib import Path
import os
import sys
import time
import uuid

from .browser_link_protocol import serve

FIREFOX_MANIFEST = "browser-helper-host-firefox.json"


def allowed_launch(directory, argv):
    if len(argv) == 2 and Path(argv[0]).name.casefold() == FIREFOX_MANIFEST:
        manifest = directory / "assets" / FIREFOX_MANIFEST
        if not Path(argv[0]).is_absolute() or Path(argv[0]).resolve() != manifest.resolve():
            return ""
        return "firefox" if argv[1] in json.loads(manifest.read_bytes())["allowed_extensions"] else ""
    origins = json.loads((directory / "assets/browser-helper-host.json").read_bytes())["allowed_origins"]
    if len(argv) not in {1, 2} or argv[0] not in origins:
        return ""
    if len(argv) == 2 and not (argv[1].startswith("--parent-window=")
                              and argv[1].removeprefix("--parent-window=").isdigit()):
        return ""
    return "chromium"


def _std_binary(index, mode, fallback):
    if fallback is not None:
        return fallback.buffer
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    handle = kernel.GetStdHandle(index & 0xffffffff)
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise OSError("Native Messaging pipe unavailable")
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_BINARY), mode, buffering=0)


def run(root, argv):
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return 2
    directory = Path(root)
    try:
        launcher = allowed_launch(directory, argv)
        if not launcher:
            return 2
        source = _std_binary(-10, "rb", sys.stdin)
        sink = _std_binary(-11, "wb", sys.stdout)
    except (OSError, ValueError, KeyError):
        return 2

    def deliver(message):
        if message["action"] == "ping":
            return {"ok": True, "code": "connected"}
        from PySide6.QtCore import QCoreApplication
        from .single_instance import SingleInstanceGuard
        from ..system.processes import sanitized_child_environment
        import subprocess

        app = QCoreApplication.instance() or QCoreApplication([sys.argv[0]])
        guard = SingleInstanceGuard(SingleInstanceGuard.application_name(directory), parent=app)
        request_id = uuid.uuid4().hex
        if guard.forward_browser(message, timeout_ms=900, request_id=request_id):
            return {"ok": True, "code": "queued"}
        if guard._live_owner_responds(250):
            return {"ok": False, "code": "desktop_busy"}
        environment = sanitized_child_environment()
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        # Browser-origin flags and authentication fields stay out of the new process argv.
        flags = subprocess.CREATE_BREAKAWAY_FROM_JOB if launcher == "firefox" else 0
        subprocess.Popen([sys.executable], cwd=directory, env=environment, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if guard.forward_browser(message, timeout_ms=700, request_id=request_id):
                return {"ok": True, "code": "queued"}
            time.sleep(.2)
        return {"ok": False, "code": "desktop_unavailable"}

    try:
        serve(source, sink, deliver)
    except (OSError, ValueError):
        return 2
    return 0
