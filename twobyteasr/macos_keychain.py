"""macOS Keychain storage for the local credential store (2026-10-13).

The whole provider-key store (the same JSON the Windows build keeps in its
DPAPI file) is one generic-password item of the user's login keychain, written
and read with Apple's ``/usr/bin/security`` tool. The secret never appears on
a command line: writes go through ``security -i`` on stdin with the payload as
hex (``-X``); reads use ``find-generic-password -w``. When the keychain cannot
be used, callers keep keys for the session only — never a plaintext file.

Not yet verified on a real Mac (written and unit-tested on Windows with a fake
``security``); see the 2026-10-13 plan.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SECURITY = '/usr/bin/security'
SERVICE = 'org.2byteasr.desktop.credentials'
ACCOUNT = 'provider-keys-v2'
NOT_FOUND = 44  # security(1): "The specified item could not be found in the keychain."


class KeychainError(RuntimeError):
    pass


def service_name() -> str:
    """The keychain item for the current user-data folder.

    The normal folder (~/Library/Application Support/2ByteASR) keeps the plain
    name. Any other data root (tests, acceptance runs, portable copies) gets
    its own item, so a test can never overwrite the user's saved keys.
    """
    try:
        from .runtime_paths import user_data_root
        root = user_data_root().expanduser().resolve()
    except Exception:
        return SERVICE
    default = (Path.home() / 'Library' / 'Application Support' / '2ByteASR').resolve()
    if root == default:
        return SERVICE
    return SERVICE + '.' + hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:12]


def _run(args, *, input_text=None, runner=None):
    runner = runner or subprocess.run
    return runner([SECURITY, *args], input=input_text, capture_output=True, text=True, timeout=20)


def available(*, runner=None) -> bool:
    if sys.platform != 'darwin' and runner is None:
        return False
    if runner is None and not os.path.exists(SECURITY):
        return False
    try:
        result = _run(['default-keychain'], runner=runner)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(str(result.stdout or '').strip())


def read(*, runner=None) -> dict | None:
    """The stored payload, ``None`` when no item exists yet."""
    try:
        result = _run(['find-generic-password', '-s', service_name(), '-a', ACCOUNT, '-w'], runner=runner)
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeychainError(f'无法读取钥匙串：{type(exc).__name__}') from exc
    if result.returncode == NOT_FOUND:
        return None
    if result.returncode != 0:
        raise KeychainError(f'无法读取钥匙串（security 退出码 {result.returncode}）')
    text = str(result.stdout or '').strip()
    try:
        payload = json.loads(text)
    except ValueError:
        # ``-w`` prints data it considers non-printable as hex.
        try:
            payload = json.loads(bytes.fromhex(text).decode('utf-8'))
        except ValueError as exc:
            raise KeychainError('钥匙串里的密钥数据无法解析') from exc
    if not isinstance(payload, dict):
        raise KeychainError('钥匙串里的密钥数据格式不对')
    return payload


def write(payload: dict, *, runner=None) -> None:
    data = json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    command = f'add-generic-password -U -s {service_name()} -a {ACCOUNT} -l 2ByteASR -X {data.hex()}\n'
    try:
        result = _run(['-i'], input_text=command, runner=runner)
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeychainError(f'无法写入钥匙串：{type(exc).__name__}') from exc
    if result.returncode != 0 or 'error' in str(result.stderr or '').lower():
        raise KeychainError('无法写入钥匙串（可能已锁定或被拒绝）')


def delete(*, runner=None) -> None:
    try:
        result = _run(['delete-generic-password', '-s', service_name(), '-a', ACCOUNT], runner=runner)
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeychainError(f'无法删除钥匙串项目：{type(exc).__name__}') from exc
    if result.returncode not in (0, NOT_FOUND):
        raise KeychainError(f'无法删除钥匙串项目（security 退出码 {result.returncode}）')
