# SPDX-License-Identifier: GPL-3.0-only
"""Mirror a published GitHub release to GitCode (used by release_pipeline.py gitcode).

Mainland users reach GitCode (measured 2026-10-14: ~14 MB/s) where github.com
fails.  The in-app updater (twobyteasr/app/updater.py) maps every GitHub release URL
to the GitCode copy under the same tag and file name, so a release is complete
on GitCode only when its own files *and* every older component archive its
update manifest still references are there.

The token comes from GITCODE_TOKEN or a file holding only the token; it is sent
only as a query parameter to api.gitcode.com and to git through GIT_ASKPASS,
never printed or written to a log.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OWNER, NAME = "Notbad314", "2ByteASR"
API = "https://api.gitcode.com/api/v5"
GIT_URL = f"https://gitcode.com/{OWNER}/{NAME}.git"
DOWNLOAD = f"https://gitcode.com/{OWNER}/{NAME}/releases/download/"
GITHUB_DOWNLOAD = "https://github.com/NOTBAD314/2ByteASR/releases/download/"
DEFAULT_TOKEN_FILE = Path.home() / ".config" / "gitcode" / "token.txt"
USER_AGENT = "2ByteASR-release-mirror/1.0"
COMPONENT_NOTES = ("这是 [GitHub {tag}](https://github.com/NOTBAD314/2ByteASR/releases/tag/{tag}) 的国内镜像，"
                   "只放程序内更新仍在使用的组件包，供新版本更新时下载。每个文件都按签名更新清单里的 SHA-256 校验。"
                   "完整安装包请下载最新版本。")


def read_token(path: Path | None = None) -> str:
    value = os.environ.get("GITCODE_TOKEN", "").strip()
    if not value:
        source = Path(path) if path else DEFAULT_TOKEN_FILE
        if not source.is_file():
            raise SystemExit(f"GitCode token missing: set GITCODE_TOKEN or create {source}")
        value = source.read_text("utf-8-sig").strip()
    if not value or any(ch.isspace() for ch in value):
        raise SystemExit("GitCode token must be a single word")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


class GitCode:
    """Minimal GitCode API v5 client; ``urlopen`` is replaceable for tests."""

    def __init__(self, token: str = "", *, urlopen=urllib.request.urlopen, log=print):
        self.token = token
        self.urlopen = urlopen
        self.log = log

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        query = dict(params or {})
        if self.token:
            query["access_token"] = self.token
        url = f"{API}{path}" + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method, headers={
            "User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.urlopen(request, timeout=60) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw)
            except ValueError:
                return error.code, raw[:300].decode("utf8", "replace")

    def release(self, tag: str) -> dict | None:
        status, payload = self.call("GET", f"/repos/{OWNER}/{NAME}/releases/tags/{urllib.parse.quote(tag)}")
        return payload if status == 200 and isinstance(payload, dict) and payload.get("tag_name") == tag else None

    @staticmethod
    def uploaded(release: dict | None) -> set[str]:
        # Source archives GitCode generates itself live under /archive/.
        return {item.get("name") for item in (release or {}).get("assets") or []
                if "/archive/" not in (item.get("browser_download_url") or "")}

    def create_release(self, tag: str, title: str, notes: str, prerelease: bool = False) -> dict:
        status, payload = self.call("POST", f"/repos/{OWNER}/{NAME}/releases", body={
            "tag_name": tag, "name": title, "body": notes, "target_commitish": tag, "prerelease": prerelease})
        if status not in (200, 201):
            raise SystemExit(f"GitCode: creating release {tag} failed: HTTP {status} {payload}")
        self.log(f"gitcode: created release {tag}")
        return self.release(tag) or payload

    def mark_latest(self, tag: str, title: str, notes: str) -> None:
        status, payload = self.call("PATCH", f"/repos/{OWNER}/{NAME}/releases/{urllib.parse.quote(tag)}", body={
            "name": title, "body": notes, "release_status": "latest"})
        if status != 200:
            raise SystemExit(f"GitCode: marking {tag} latest failed: HTTP {status} {payload}")
        self.log(f"gitcode: {tag} marked latest")

    def latest_tag(self) -> str:
        status, payload = self.call("GET", f"/repos/{OWNER}/{NAME}/releases/latest")
        return str(payload.get("tag_name") or "") if status == 200 and isinstance(payload, dict) else ""

    def upload(self, tag: str, path: Path) -> None:
        status, info = self.call("GET", f"/repos/{OWNER}/{NAME}/releases/{urllib.parse.quote(tag)}/upload_url",
                                 {"file_name": path.name})
        if status != 200 or not isinstance(info, dict) or "url" not in info:
            raise SystemExit(f"GitCode: no upload address for {path.name}: HTTP {status} {info}")
        headers = dict(info.get("headers") or {})
        headers["Content-Length"] = str(path.stat().st_size)
        started = time.monotonic()
        # The address is a pre-signed Huawei Cloud OBS PUT; it takes the file as is.
        with path.open("rb") as stream:
            request = urllib.request.Request(info["url"], data=stream, method="PUT", headers=headers)
            with self.urlopen(request, timeout=3600) as response:
                if response.status not in (200, 201):
                    raise SystemExit(f"GitCode: upload of {path.name} answered HTTP {response.status}")
        seconds = max(time.monotonic() - started, 0.001)
        self.log(f"gitcode: uploaded {tag}/{path.name} ({path.stat().st_size / 2**20:.1f} MiB, "
                 f"{path.stat().st_size / seconds / 2**20:.1f} MB/s)")


def push_refs(repo: Path, refspecs: list[str], token: str, *, run=subprocess.run, log=print) -> None:
    """git push to GitCode; the token reaches git only through GIT_ASKPASS."""
    with tempfile.TemporaryDirectory() as folder:
        askpass = Path(folder) / "askpass.cmd"
        askpass.write_text('@echo off\r\necho %1 | findstr /i "Username" >nul && (echo ' + OWNER
                           + ') || (echo %GITCODE_PUSH_TOKEN%)\r\n', "ascii")
        env = dict(os.environ, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT="0", GITCODE_PUSH_TOKEN=token)
        result = run(["git", "-c", "credential.helper=", "push", "--no-verify", GIT_URL, *refspecs],
                     cwd=repo, env=env, capture_output=True, text=True, encoding="utf8", errors="replace")
        output = ((result.stdout or "") + (result.stderr or "")).replace(token, "***").strip()
        log("gitcode: git push " + " ".join(refspecs) + ("\n" + output if output else ""))
        if result.returncode:
            raise SystemExit("GitCode: git push failed (a file over the project's size limit is a common cause)")


def referenced_archives(manifest: dict, tag: str) -> list[dict]:
    """Component archives of ``manifest`` that live in an older release: name, size, sha256, tag, github."""
    found = []
    for component in (manifest.get("components") or {}).values():
        archive = (component or {}).get("archive") or {}
        for url in archive.get("urls") or ():
            if url.startswith(GITHUB_DOWNLOAD):
                older = url[len(GITHUB_DOWNLOAD):].split("/", 1)[0]
                if older != tag:
                    found.append({"name": archive["name"], "size": int(archive["size"]), "sha256": archive["sha256"],
                                  "tag": urllib.parse.unquote(older), "github": url})
                break
    return found


def fetch_verified(url: str, target: Path, size: int, sha256: str, *, urlopen=urllib.request.urlopen) -> Path:
    """Download ``url`` to ``target`` and keep it only when size and SHA-256 match."""
    if target.is_file() and target.stat().st_size == size and sha256_file(target) == sha256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response, partial.open("wb") as stream:
        for block in iter(lambda: response.read(1 << 20), b""):
            stream.write(block)
    if partial.stat().st_size != size or sha256_file(partial) != sha256:
        partial.unlink()
        raise SystemExit(f"{url} does not match the signed manifest")
    os.replace(partial, target)
    return target


def verify_download(url: str, size: int, sha256: str | None, *, opener=None) -> dict:
    """Anonymous GET of a GitCode file.

    With ``sha256`` the whole file is downloaded and hashed; without it one
    byte is requested and the total size is read from Content-Range.
    """
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    row = {"url": url}
    headers = {"User-Agent": USER_AGENT}
    if not sha256:
        headers["Range"] = "bytes=0-0"
    started = time.monotonic()
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=120) as response:
            row["status"] = response.status
            if sha256:
                digest, received = hashlib.sha256(), 0
                for block in iter(lambda: response.read(1 << 20), b""):
                    received += len(block)
                    digest.update(block)
                row["length"] = received
                row["mb_per_s"] = round(received / max(time.monotonic() - started, 0.001) / 2**20, 1)
                row["ok"] = received == size and digest.hexdigest() == sha256
            else:
                total = str(response.headers.get("Content-Range") or "").rpartition("/")[2]
                row["length"] = int(total) if total.isdigit() else -1
                row["ok"] = row["length"] == size
    except Exception as exc:  # noqa: BLE001 - recorded in the report
        row["error"] = str(exc)[:300]
        row["ok"] = False
    return row
