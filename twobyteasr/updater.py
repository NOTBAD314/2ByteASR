"""GitHub Release update discovery and verified package download."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from twobyteasr.processes import popen_hidden_subprocess
from typing import Callable

import requests


APP_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = APP_ROOT / "2byteasr_version.json"
REPOSITORY = "NOTBAD314/2ByteASR"
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
API_URLS = (
    LATEST_RELEASE_API,
    f"https://ghfast.top/{LATEST_RELEASE_API}",
    f"https://ghproxy.net/{LATEST_RELEASE_API}",
)
SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


class UpdateError(RuntimeError):
    """The update could not be checked, downloaded, or safely applied."""


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    newer: bool
    release_url: str
    notes: str = ""
    package_url: str = ""
    package_name: str = ""
    checksum_url: str = ""
    digest: str = ""
    installer_url: str = ""

    @property
    def can_self_update(self) -> bool:
        return bool(self.package_url and (self.checksum_url or self.digest))


def _version_key(value: str) -> tuple[int, int, int, int, str]:
    match = SEMVER_RE.match(str(value or "").strip())
    if not match:
        raise UpdateError(f"无法识别版本号：{value!r}")
    prerelease = match.group("pre") or ""
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        0 if prerelease else 1,
        prerelease,
    )


def normalize_version(value: str) -> str:
    value = str(value or "").strip()
    _version_key(value)
    return value[1:] if value.lower().startswith("v") else value


def current_version(path: Path | None = None) -> str:
    path = path or VERSION_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return normalize_version(payload.get("version", ""))
    except (OSError, ValueError, TypeError, UpdateError):
        return "0.0.0"


def release_from_payload(payload: dict, installed_version: str | None = None) -> UpdateInfo:
    installed = normalize_version(installed_version or current_version())
    latest = normalize_version(payload.get("tag_name", ""))
    assets = [item for item in payload.get("assets", ()) if isinstance(item, dict)]
    package_name = f"2ByteASR-Update-{latest}.zip"
    package = next(
        (item for item in assets if str(item.get("name", "")).lower() == package_name.lower()),
        None,
    )
    checksum = next(
        (
            item
            for item in assets
            if package
            and str(item.get("name", "")).lower()
            == f"{str(package.get('name', ''))}.sha256".lower()
        ),
        None,
    )
    installer = next(
        (
            item
            for item in assets
            if str(item.get("name", "")).lower() == f"2byteasr-setup-{latest}.exe"
        ),
        None,
    )
    digest = str((package or {}).get("digest", "") or "")
    if digest.lower().startswith("sha256:"):
        digest = digest.split(":", 1)[1].strip().lower()
    elif digest:
        digest = ""
    return UpdateInfo(
        current_version=installed,
        latest_version=latest,
        newer=_version_key(latest) > _version_key(installed),
        release_url=str(payload.get("html_url") or RELEASE_PAGE),
        notes=str(payload.get("body") or "").strip(),
        package_url=str((package or {}).get("browser_download_url") or ""),
        package_name=str((package or {}).get("name") or ""),
        checksum_url=str((checksum or {}).get("browser_download_url") or ""),
        digest=digest,
        installer_url=str((installer or {}).get("browser_download_url") or ""),
    )


def check_for_update(
    *,
    request_get: Callable = requests.get,
    timeout: tuple[int, int] = (6, 18),
) -> UpdateInfo:
    errors = []
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "2ByteASR-update-checker",
    }
    for url in API_URLS:
        try:
            response = request_get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return release_from_payload(response.json())
        except Exception as exc:  # noqa: BLE001 - retry mirrors, report compact result
            errors.append(f"{url.split('/')[2]}：{' '.join(str(exc).split())[:120]}")
    raise UpdateError("无法连接更新服务器。\n" + "\n".join(errors))


def _download_candidates(url: str) -> tuple[str, ...]:
    if not url:
        return ()
    if not url.startswith("https://github.com/"):
        return (url,)
    return (url, f"https://ghfast.top/{url}", f"https://ghproxy.net/{url}")


def _expected_checksum(info: UpdateInfo, request_get: Callable, timeout) -> str:
    if info.checksum_url:
        errors = []
        for url in _download_candidates(info.checksum_url):
            try:
                response = request_get(
                    url,
                    headers={"User-Agent": "2ByteASR-update-checker"},
                    timeout=timeout,
                )
                response.raise_for_status()
                match = re.search(r"\b[0-9a-fA-F]{64}\b", response.text)
                if match:
                    return match.group(0).lower()
            except Exception as exc:  # noqa: BLE001 - try next endpoint
                errors.append(str(exc))
        if not info.digest:
            raise UpdateError("更新包校验文件下载失败：" + " | ".join(errors)[:400])
    if re.fullmatch(r"[0-9a-f]{64}", info.digest):
        return info.digest
    raise UpdateError("Release 未提供可验证的 SHA-256，已拒绝自动更新。")


def download_update(
    info: UpdateInfo,
    destination: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    request_get: Callable = requests.get,
    timeout: tuple[int, int] = (8, 45),
) -> tuple[Path, str]:
    if not info.can_self_update:
        raise UpdateError("此版本没有可自动安装的小型更新包。")
    expected = _expected_checksum(info, request_get, timeout)
    destination.mkdir(parents=True, exist_ok=True)
    filename = Path(info.package_name).name
    if not filename or filename != info.package_name:
        raise UpdateError("更新包文件名无效。")
    output = destination / filename
    partial = output.with_suffix(output.suffix + ".part")
    errors = []
    for url in _download_candidates(info.package_url):
        try:
            digest = hashlib.sha256()
            received = 0
            with request_get(
                url,
                headers={"User-Agent": "2ByteASR-update-checker"},
                timeout=timeout,
                stream=True,
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", 0) or 0)
                with partial.open("wb") as stream:
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        if not block:
                            continue
                        stream.write(block)
                        digest.update(block)
                        received += len(block)
                        if progress:
                            progress(received, total)
            actual = digest.hexdigest().lower()
            if actual != expected:
                raise UpdateError(f"SHA-256 不一致：期望 {expected}，实际 {actual}")
            os.replace(partial, output)
            return output, actual
        except Exception as exc:  # noqa: BLE001 - retry China-accessible mirrors
            errors.append(f"{url.split('/')[2]}：{' '.join(str(exc).split())[:160]}")
            try:
                partial.unlink()
            except OSError:
                pass
    raise UpdateError("更新包下载失败。\n" + "\n".join(errors))


def launch_update_helper(package: Path, checksum: str, *, wait_pid: int) -> None:
    script = APP_ROOT / "scripts" / "apply_update.ps1"
    launcher = APP_ROOT / "2ByteASR.exe"
    if not script.is_file() or not launcher.is_file():
        raise UpdateError("自动更新助手不完整，请改用新版安装包覆盖安装。")
    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    command = [
        str(powershell),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Package",
        str(package),
        "-ProjectRoot",
        str(APP_ROOT),
        "-ExpectedSha256",
        checksum,
        "-WaitForPid",
        str(int(wait_pid)),
        "-Restart",
    ]
    flags = 0
    if os.name == "nt":
        flags = 0x08000000 | 0x00000008 | 0x00000200
    popen_hidden_subprocess(
        command,
        purpose="detached application update helper",
        process_factory=subprocess.Popen,
        cwd=str(APP_ROOT),
        creationflags=flags,
        close_fds=True,
    )


__all__ = [
    "RELEASE_PAGE",
    "UpdateError",
    "UpdateInfo",
    "check_for_update",
    "current_version",
    "download_update",
    "launch_update_helper",
    "normalize_version",
    "release_from_payload",
]
