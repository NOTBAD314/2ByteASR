# SPDX-License-Identifier: GPL-3.0-only
"""scripts/baidu_netdisk_release.py: authorization, single-use refresh tokens, chunked upload (no network)."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import baidu_netdisk_release as bd  # noqa: E402

APP = {"app_key": "AK-not-for-logs", "secret_key": "SK-not-for-logs", "app_name": "2ByteASR"}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeBaidu:
    """Answers the official endpoints the script calls; records every request."""

    def __init__(self, *, pending=1, missing=None):
        self.requests, self.pending, self.missing = [], pending, missing
        self.refresh_count = 0
        self.chunks = {}

    def __call__(self, request, timeout=None):
        url = urllib.parse.urlsplit(request.full_url)
        query = dict(urllib.parse.parse_qsl(url.query))
        form = dict(urllib.parse.parse_qsl(request.data.decode())) if request.data and \
            request.get_header("Content-type") == "application/x-www-form-urlencoded" else {}
        self.requests.append((url.path, query, form))
        if url.path.endswith("/device/code"):
            return self._json({"device_code": "DEV", "user_code": "ABCD", "verification_url": "https://openapi.baidu.com/device",
                               "qrcode_url": "https://openapi.baidu.com/device/qrcode/x/ABCD", "expires_in": 300, "interval": 5})
        if url.path.endswith("/oauth/2.0/token"):
            if query["grant_type"] == "device_token":
                if self.pending:
                    self.pending -= 1
                    return self._json({"error": "authorization_pending"})
                return self._json({"access_token": "AT0", "refresh_token": "RT0", "expires_in": 2592000, "scope": "basic netdisk"})
            assert query["grant_type"] == "refresh_token"
            assert query["refresh_token"] == f"RT{self.refresh_count}", "a used refresh token was sent again"
            self.refresh_count += 1
            return self._json({"access_token": f"AT{self.refresh_count}", "refresh_token": f"RT{self.refresh_count}",
                               "expires_in": 2592000})
        if query.get("method") == "precreate":
            blocks = json.loads(form["block_list"])
            self.expected = blocks
            needed = list(range(len(blocks))) if self.missing is None else self.missing
            return self._json({"errno": 0, "uploadid": "UP1", "return_type": 1, "block_list": needed,
                               "path": form["path"]})
        if query.get("method") == "locateupload":
            return self._json({"error_code": 0, "servers": [{"server": "http://plain.example"},
                                                             {"server": "https://c3.pcs.baidu.com"}]})
        if query.get("method") == "upload":
            body = request.data
            piece = body[body.index(b"\r\n\r\n") + 4:body.rindex(b"\r\n--")]
            self.chunks[int(query["partseq"])] = piece
            return self._json({"md5": hashlib.md5(piece).hexdigest()})
        if query.get("method") == "create":
            return self._json({"errno": 0, "path": form["path"], "size": int(form["size"]), "fs_id": 42})
        if query.get("method") == "list":
            return self._json({"errno": 0, "list": [{"server_filename": "x.exe", "size": 1, "path": "/apps/2ByteASR/x.exe"}]})
        raise AssertionError(f"unexpected request {url.path} {query}")

    @staticmethod
    def _json(payload):
        return FakeResponse(json.dumps(payload).encode())


def _client(tmp_path, fake, clock):
    logs = []
    client = bd.BaiduNetdisk(APP, token_file=tmp_path / "token.dpapi", urlopen=fake,
                             protect=lambda raw: raw[::-1], unprotect=lambda raw: raw[::-1],
                             sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds), now=lambda: clock[0],
                             log=logs.append)
    return client, logs


def test_device_code_authorization_saves_the_token_without_printing_secrets(tmp_path):
    fake, clock = FakeBaidu(pending=2), [1000.0]
    client, logs = _client(tmp_path, fake, clock)
    client.authorize()
    stored = (tmp_path / "token.dpapi").read_text("utf-8")
    assert "AT0" not in stored and "RT0" not in stored  # only the protected blob is on disk
    assert client.access_token() == "AT0"
    assert "ABCD" in logs[0] and "https://openapi.baidu.com/device" in logs[0]
    assert not any(secret in line for line in logs for secret in ("SK-not-for-logs", "AT0", "RT0"))
    polls = [query for path, query, _form in fake.requests if path.endswith("/token")]
    assert len(polls) == 3 and all(query["grant_type"] == "device_token" for query in polls)
    assert clock[0] - 1000.0 >= 15  # polled no faster than every 5 s


def test_refresh_token_is_single_use_and_saved_before_use(tmp_path):
    fake, clock = FakeBaidu(pending=0), [0.0]
    client, _logs = _client(tmp_path, fake, clock)
    client.authorize()
    clock[0] += 2592000 - 3600  # inside the one-day margin
    assert client.access_token() == "AT1"
    reloaded, _ = _client(tmp_path, fake, clock)
    clock[0] += 2592000 - 3600
    assert reloaded.access_token() == "AT2"  # used RT1 (saved), never RT0 again
    assert fake.refresh_count == 2


def test_chunked_upload_sends_only_requested_chunks_and_checks_size(tmp_path):
    fake, clock = FakeBaidu(pending=0), [0.0]
    client, logs = _client(tmp_path, fake, clock)
    client.authorize()
    data = bytes(range(256)) * 41  # 10,496 bytes -> 3 chunks of 4,096
    path = tmp_path / "2ByteASR-Setup-0.8.0.exe"
    path.write_bytes(data)
    result = client.upload(path, chunk=4096)
    assert result == {"name": path.name, "path": "/apps/2ByteASR/2ByteASR-Setup-0.8.0.exe", "size": len(data),
                      "fs_id": 42, "chunks": 3, "chunks_sent": 3}
    assert b"".join(fake.chunks[i] for i in range(3)) == data
    precreate = next(form for _p, query, form in fake.requests if query.get("method") == "precreate")
    assert precreate["path"] == "/apps/2ByteASR/2ByteASR-Setup-0.8.0.exe" and precreate["rtype"] == "3"
    assert json.loads(precreate["block_list"]) == [hashlib.md5(data[i:i + 4096]).hexdigest() for i in (0, 4096, 8192)]
    assert precreate["content-md5"] == hashlib.md5(data).hexdigest()
    hosts = {path for path, query, _f in fake.requests if query.get("method") == "upload"}
    assert hosts == {"/rest/2.0/pcs/superfile2"}
    assert not any("SK-not-for-logs" in line or "AT0" in line for line in logs)


def test_resumed_upload_skips_chunks_the_server_already_has(tmp_path):
    fake, clock = FakeBaidu(pending=0, missing=[2]), [0.0]
    client, _logs = _client(tmp_path, fake, clock)
    client.authorize()
    path = tmp_path / "a.dmg"
    path.write_bytes(b"x" * 9000)
    result = client.upload(path, chunk=4096)
    assert result["chunks"] == 3 and result["chunks_sent"] == 1 and list(fake.chunks) == [2]


def test_release_files_and_missing_setup(tmp_path):
    for name in ("2ByteASR-Setup-0.8.0.exe", "2ByteASR-0.8.0-macos-arm64-Setup.dmg", "SHA256SUMS.txt", "other.zip"):
        (tmp_path / name).write_bytes(b"1")
    assert [p.name for p in bd.release_files(tmp_path, "0.8.0")] == [
        "2ByteASR-Setup-0.8.0.exe", "2ByteASR-0.8.0-macos-arm64-Setup.dmg", "SHA256SUMS.txt"]
    with pytest.raises(SystemExit):
        bd.release_files(tmp_path, "0.9.0")


def test_app_file_must_have_keys():
    with pytest.raises(SystemExit):
        bd.BaiduNetdisk({"app_key": "x"})
