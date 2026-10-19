"""Container-local encrypted secrets; key and ciphertext live in /config."""
from __future__ import annotations
import os
from pathlib import Path

MAGIC = b"2BYTEASR-LINUX-1\x00"

def transform(operation: str, data: bytes, secrets_file: Path) -> bytes:
    from cryptography.fernet import Fernet, InvalidToken
    if operation not in {"protect", "unprotect"}:
        raise ValueError("Unknown secret-store operation")
    key_file = secrets_file.with_name("container-secrets.key")
    if operation == "protect" and not key_file.exists():
        key_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
    try:
        cipher = Fernet(key_file.read_bytes())
    except (OSError, ValueError) as error:
        raise RuntimeError("Docker 密钥文件缺失或损坏，请恢复完整 /config 备份。") from error
    if operation == "protect":
        return MAGIC + cipher.encrypt(data)
    if not data.startswith(MAGIC):
        raise RuntimeError("这不是 Docker 密钥文件；Windows 密钥不能直接复制到容器。")
    try:
        return cipher.decrypt(data[len(MAGIC):])
    except InvalidToken as error:
        raise RuntimeError("Docker 密钥无法解密，请恢复匹配的 /config 备份。") from error
