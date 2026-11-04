# SPDX-License-Identifier: GPL-3.0-only
"""Private authenticated audio IPC endpoint for the existing single owner."""
from __future__ import annotations
import os
import secrets
import tempfile
from pathlib import Path


def audio_endpoint() -> tuple[str,str]:
    if os.name=="nt":
        return r'\\.\pipe\2byte-audio-'+secrets.token_hex(16),"AF_PIPE"
    directory=Path(tempfile.mkdtemp(prefix="2basr-audio-",dir="/tmp"))
    directory.chmod(0o700)
    return str(directory/"ipc.sock"),"AF_UNIX"


def valid_audio_endpoint(address: str) -> bool:
    if os.name=="nt": return address.startswith(r'\\.\pipe\2byte-audio-')
    path=Path(address)
    return path.is_absolute() and path.name=="ipc.sock" and path.parent.name.startswith("2basr-audio-") and "tmp" in path.resolve().parts


def cleanup_audio_endpoint(address: str) -> None:
    if os.name=="nt" or not valid_audio_endpoint(address): return
    path=Path(address)
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError: pass


def audio_backend() -> str:
    import sys
    return "isolated-wasapi" if os.name=="nt" else "isolated-coreaudio" if sys.platform=="darwin" else "isolated-qt-audio"
