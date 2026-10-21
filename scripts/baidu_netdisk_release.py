# SPDX-License-Identifier: GPL-3.0-only
"""Copy a release's installers to the owner's Baidu Netdisk (RELEASING.md step 10; added 2026-10-18).

Baidu's open platform lets an app write only inside its own folder, ``/apps/<app name>`` (shown in the
Netdisk as ``/我的应用数据/<app name>``); the owner shares that folder once as a permanent link, and every
release copied here appears in the same share.  Official API only (pan.baidu.com/union/doc):
device-code authorization, then precreate -> locateupload -> superfile2 (4 MB chunks, the size every
account tier accepts) -> create.

Secrets: ``%USERPROFILE%\\.config\\baidu-netdisk\\app.json`` holds ``{"app_key", "secret_key"[, "app_name"]}``
(written by the owner); the tokens live next to it in ``token.dpapi`` (Windows DPAPI, current user).
Neither is printed or logged.  Baidu's refresh token works once: every refresh saves the new pair first.

    python -B scripts/baidu_netdisk_release.py authorize            # once: open the page, enter the code
    python -B scripts/baidu_netdisk_release.py status               # token state + folder listing
    python -B scripts/baidu_netdisk_release.py upload --tag v0.8.0 --assets releases/0.8.0
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path.home() / ".config" / "baidu-netdisk"
APP_FILE = CONFIG / "app.json"
TOKEN_FILE = CONFIG / "token.dpapi"
OAUTH = "https://openapi.baidu.com/oauth/2.0"
XPAN = "https://pan.baidu.com/rest/2.0/xpan"
LOCATE = "https://d.pcs.baidu.com/rest/2.0/pcs/file"
CHUNK = 4 * 1024 * 1024
USER_AGENT = "pan.baidu.com"
REFRESH_MARGIN = 24 * 3600


def _dpapi(operation: str, data: bytes) -> bytes:
    sys.path.insert(0, str(ROOT))
    from twobyteasr.providers.llm_config import _dpapi as dpapi  # Windows DPAPI helper (current user)
    return dpapi(operation, data)


class BaiduNetdisk:
    """Minimal client; ``urlopen``, ``protect``/``unprotect``, ``sleep`` and ``now`` are replaceable for tests."""

    def __init__(self, app: dict, *, token_file: Path = TOKEN_FILE, urlopen=urllib.request.urlopen,
                 protect=None, unprotect=None, sleep=time.sleep, now=time.time, log=print):
        if not app.get("app_key") or not app.get("secret_key"):
            raise SystemExit("Baidu Netdisk: app.json needs app_key and secret_key")
        if any("贴" in str(app.get(key)) or " " in str(app.get(key)).strip() for key in ("app_key", "secret_key")):
            raise SystemExit("Baidu Netdisk: app.json still has the template text; paste the AppKey and SecretKey")
        self.app = app
        self.folder = "/apps/" + str(app.get("app_name") or "2ByteASR").strip("/")
        self.token_file = Path(token_file)
        self.urlopen = urlopen
        self.protect = protect or (lambda raw: _dpapi("protect", raw))
        self.unprotect = unprotect or (lambda raw: _dpapi("unprotect", raw))
        self.sleep, self.now, self.log = sleep, now, log
        self._secrets = {app["app_key"], app["secret_key"]}

    # -- HTTP ----------------------------------------------------------------------------------
    def _scrub(self, text: str) -> str:
        for secret in sorted(self._secrets, key=len, reverse=True):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _request(self, method: str, url: str, params: dict, *, form: dict | None = None,
                 body: bytes | None = None, content_type: str = "", timeout: int = 60) -> dict:
        full = url + "?" + urllib.parse.urlencode(params)
        data = body
        headers = {"User-Agent": USER_AGENT}
        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(full, data=data, method=method, headers=headers)
        try:
            with self.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raw = error.read()
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {"errno": -1, "error": self._scrub(raw[:300].decode("utf-8", "replace"))}

    # -- tokens --------------------------------------------------------------------------------
    def _save(self, payload: dict) -> None:
        record = {"access_token": payload["access_token"], "refresh_token": payload["refresh_token"],
                  "expires_at": int(self.now()) + int(payload.get("expires_in") or 2592000),
                  "scope": payload.get("scope", "")}
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        blob = base64.b64encode(self.protect(json.dumps(record).encode("utf-8"))).decode("ascii")
        self.token_file.write_text(json.dumps({"dpapi": blob, "saved": datetime.now(timezone.utc).isoformat()}),
                                   "utf-8")
        self._secrets |= {record["access_token"], record["refresh_token"]}

    def _load(self) -> dict | None:
        if not self.token_file.is_file():
            return None
        stored = json.loads(self.token_file.read_text("utf-8"))
        record = json.loads(self.unprotect(base64.b64decode(stored["dpapi"])))
        self._secrets |= {record["access_token"], record["refresh_token"]}
        return record

    def authorize(self, *, timeout: int = 300) -> None:
        code = self._request("GET", f"{OAUTH}/device/code", {
            "response_type": "device_code", "client_id": self.app["app_key"], "scope": "basic,netdisk"})
        if "device_code" not in code:
            raise SystemExit(f"Baidu Netdisk: no device code: {self._scrub(json.dumps(code, ensure_ascii=False))}")
        self.log(f"打开 {code['verification_url']} 输入用户码 {code['user_code']}（或用百度网盘 App 扫 {code['qrcode_url']}），"
                 f"登录后确认授权；{int(code.get('expires_in', 300))} 秒内有效。")
        interval = max(5, int(code.get("interval") or 5))
        deadline = self.now() + min(timeout, int(code.get("expires_in") or 300))
        while self.now() < deadline:
            self.sleep(interval)
            token = self._request("GET", f"{OAUTH}/token", {
                "grant_type": "device_token", "code": code["device_code"],
                "client_id": self.app["app_key"], "client_secret": self.app["secret_key"]})
            if "access_token" in token:
                self._save(token)
                self.log(f"已授权（{token.get('scope', '')}），令牌加密保存在 {self.token_file}")
                return
            if token.get("error") not in ("authorization_pending", "slow_down"):
                raise SystemExit(f"Baidu Netdisk: authorization failed: {token.get('error')} "
                                 f"{token.get('error_description', '')}")
        raise SystemExit("Baidu Netdisk: authorization timed out; run authorize again")

    def access_token(self) -> str:
        record = self._load()
        if record is None:
            raise SystemExit(f"Baidu Netdisk: not authorized yet; run `{Path(__file__).name} authorize`")
        if record["expires_at"] - self.now() > REFRESH_MARGIN:
            return record["access_token"]
        token = self._request("GET", f"{OAUTH}/token", {
            "grant_type": "refresh_token", "refresh_token": record["refresh_token"],
            "client_id": self.app["app_key"], "client_secret": self.app["secret_key"]})
        if "access_token" not in token:
            # A failed refresh invalidates the old refresh token (Baidu docs): authorize again.
            raise SystemExit(f"Baidu Netdisk: token refresh failed ({token.get('error')}); run authorize again")
        self._save(token)  # the refresh token is single-use: persist the new pair before anything else
        return token["access_token"]

    # -- files ---------------------------------------------------------------------------------
    def listing(self) -> list[dict]:
        result = self._request("GET", f"{XPAN}/file", {
            "method": "list", "access_token": self.access_token(), "dir": self.folder, "limit": 1000})
        if result.get("errno") not in (0, None):
            if result.get("errno") == -9:
                return []  # the app folder appears with the first upload
            raise SystemExit(f"Baidu Netdisk: list failed: errno {result.get('errno')}")
        return [{"name": item.get("server_filename"), "size": item.get("size"), "path": item.get("path"),
                 "mtime": item.get("server_mtime")} for item in result.get("list") or []]

    def upload(self, path: Path, *, retries: int = 3, chunk: int = CHUNK) -> dict:
        path = Path(path)
        size = path.stat().st_size
        target = f"{self.folder}/{path.name}"
        blocks, whole = [], hashlib.md5()
        with path.open("rb") as stream:
            first = stream.read(256 * 1024)
            stream.seek(0)
            for piece in iter(lambda: stream.read(chunk), b""):
                blocks.append(hashlib.md5(piece).hexdigest())
                whole.update(piece)
        if len(blocks) > 1024:
            raise SystemExit(f"Baidu Netdisk: {path.name} needs {len(blocks)} chunks (limit 1024)")
        token = self.access_token()
        pre = self._request("POST", f"{XPAN}/file", {"method": "precreate", "access_token": token}, form={
            "path": target, "size": size, "isdir": 0, "autoinit": 1, "rtype": 3,
            "block_list": json.dumps(blocks), "content-md5": whole.hexdigest(),
            "slice-md5": hashlib.md5(first).hexdigest()})
        if pre.get("errno") != 0:
            raise SystemExit(f"Baidu Netdisk: precreate {path.name} failed: errno {pre.get('errno')}")
        upload_id = pre["uploadid"]
        needed = pre.get("block_list") or [0]  # docs: an empty block_list means [0]
        started = time.monotonic()
        host = self._upload_host(token, target, upload_id)
        with path.open("rb") as stream:
            for index in needed:
                stream.seek(index * chunk)
                piece = stream.read(chunk)
                for attempt in range(1, retries + 1):
                    result = self._upload_chunk(host, token, target, upload_id, index, piece)
                    if result.get("md5") == blocks[index]:
                        break
                    self.log(f"baidu: chunk {index} of {path.name} attempt {attempt} failed "
                             f"(errno {result.get('errno')}); retrying")
                    self.sleep(2 * attempt)
                    host = self._upload_host(token, target, upload_id)
                else:
                    raise SystemExit(f"Baidu Netdisk: chunk {index} of {path.name} kept failing")
        created = self._request("POST", f"{XPAN}/file", {"method": "create", "access_token": token}, form={
            "path": target, "size": size, "isdir": 0, "rtype": 3, "uploadid": upload_id,
            "block_list": json.dumps(blocks)})
        if created.get("errno") != 0 or int(created.get("size") or -1) != size:
            raise SystemExit(f"Baidu Netdisk: create {path.name} failed: errno {created.get('errno')}, "
                             f"size {created.get('size')} vs {size}")
        seconds = max(time.monotonic() - started, 0.001)
        self.log(f"baidu: uploaded {created.get('path')} ({size / 2**20:.1f} MiB, {size / seconds / 2**20:.1f} MB/s, "
                 f"{len(needed)}/{len(blocks)} chunks sent)")
        return {"name": path.name, "path": created.get("path"), "size": size, "fs_id": created.get("fs_id"),
                "chunks": len(blocks), "chunks_sent": len(needed)}

    def _upload_host(self, token: str, target: str, upload_id: str) -> str:
        located = self._request("GET", LOCATE, {
            "method": "locateupload", "appid": 250528, "access_token": token, "path": target,
            "uploadid": upload_id, "upload_version": "2.0"})
        for server in located.get("servers") or []:
            if str(server.get("server", "")).startswith("https://"):
                return server["server"]
        return "https://d.pcs.baidu.com"

    def _upload_chunk(self, host: str, token: str, target: str, upload_id: str, index: int, piece: bytes) -> dict:
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"part\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode("ascii") + piece + \
            f"\r\n--{boundary}--\r\n".encode("ascii")
        return self._request("POST", f"{host}/rest/2.0/pcs/superfile2", {
            "method": "upload", "access_token": token, "type": "tmpfile", "path": target,
            "uploadid": upload_id, "partseq": index}, body=body,
            content_type=f"multipart/form-data; boundary={boundary}", timeout=300)


def release_files(assets: Path, version: str) -> list[Path]:
    names = [f"2ByteASR-Setup-{version}.exe", f"2ByteASR-{version}-macos-arm64-Setup.dmg", "SHA256SUMS.txt"]
    files = [assets / name for name in names if (assets / name).is_file()]
    if not files or files[0].name != names[0]:
        raise SystemExit(f"Baidu Netdisk: {names[0]} not found in {assets}")
    return files


def load_app(path: Path = APP_FILE) -> dict:
    if not path.is_file():
        raise SystemExit(f"Baidu Netdisk: create {path} with app_key and secret_key first")
    return json.loads(path.read_text("utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("authorize")
    sub.add_parser("status")
    up = sub.add_parser("upload")
    up.add_argument("--tag", required=True)
    up.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args(argv)
    client = BaiduNetdisk(load_app())
    if args.command == "authorize":
        client.authorize()
    elif args.command == "status":
        record = client._load()
        state = "not authorized" if record is None else \
            f"access token valid until {datetime.fromtimestamp(record['expires_at']).isoformat(timespec='minutes')}"
        print(json.dumps({"folder": client.folder, "token": state, "files": client.listing() if record else []},
                         ensure_ascii=False, indent=1))
    else:
        version = args.tag.lstrip("v")
        files = release_files(args.assets, version)
        results = [client.upload(path) for path in files]
        listed = {item["name"]: item["size"] for item in client.listing()}
        checks = [dict(result, listed_size=listed.get(result["name"]), ok=listed.get(result["name"]) == result["size"])
                  for result in results]
        report = {"tag": args.tag, "folder": client.folder, "checked_at": datetime.now(timezone.utc).isoformat(),
                  "files": checks, "all_ok": all(item["ok"] for item in checks)}
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        (args.assets / f"baidu-verification-{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                                       "utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=1))
        if not report["all_ok"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
