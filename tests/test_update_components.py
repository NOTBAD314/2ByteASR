# SPDX-License-Identifier: GPL-3.0-only
"""Component manifest, signed feed, update planning, download and staging."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import zipfile
from pathlib import Path

import pytest

from twobyteasr.app import update_manifest as um
from twobyteasr.app import updater


# ---------------------------------------------------------------- helpers


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, public


@pytest.fixture()
def trusted_key(monkeypatch):
    private, public = _keypair()
    monkeypatch.setitem(um.TRUSTED_UPDATE_KEYS, um.key_id_for(public), base64.b64encode(public).decode())
    return private


def _write(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _make_payload(root: Path, *, version="0.6.5", app_text=b"app-v1", renderer=b"renderer-v1") -> dict:
    _write(root, "2ByteASR.exe", b"MZ" + app_text)
    _write(root, "2ByteASRUpdater.exe", b"MZ-helper")
    _write(root, "twobyteasr/app/ui.py", b"print(1)\n" + app_text)
    _write(root, "twobyteasr/old_module.py", b"old")
    _write(root, "python310.dll", b"python-dll")
    _write(root, "PySide6/Qt6Core.dll", b"qt")
    _write(root, "renderer/service.mjs", b"service")
    _write(root, "renderer/node_modules/remotion/index.js", renderer)
    _write(root, "assets/fonts/a.otf", b"font")
    _write(root, "assets/app_icon.ico", b"icon")
    _write(root, "tools/ffmpeg/bin/ffmpeg.exe", b"ffmpeg")
    _write(root, "wheels/x.whl", b"wheel")
    _write(root, "licenses/LICENSE.txt", b"gpl")
    _write(root, "2byteasr_version.json", json.dumps({"version": version, "channel": "stable"}).encode())
    _write(root, "dependencies.lock.json", json.dumps({
        "environments": {"main": {"packages": ["a==1"]}}, "models": {"moss": {"revision": "r1"}}}).encode())
    for name in um.PRESERVED_FILES:
        _write(root, name, b"factory")
    manifest = um.build_installed_manifest(root, version=version, build={"git_sha": "x"})
    (root / um.COMPONENTS_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _component_zip(payload: Path, name: str, record: dict) -> bytes:
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(um.ARCHIVE_INDEX_NAME, json.dumps(
            {"component": name, "content_sha256": record["content_sha256"], "files": record["files"]}))
        for rel, _size, _sha in record["files"]:
            bundle.write(payload / rel, rel)
    return body.getvalue()


def _feed(new_payload: Path, new_manifest: dict, *, version="0.6.6", channel="stable", setup=b"SETUP",
          base="https://github.com/NOTBAD314/2ByteASR/releases/download/v0.6.6/", skip=()):
    files, components = {}, {}
    for name in um.COMPONENT_ORDER:
        record = new_manifest["components"][name]
        entry = {k: record[k] for k in ("content_sha256", "file_count", "bytes")}
        if name in skip:
            entry["archive"] = None
        else:
            data = _component_zip(new_payload, name, record)
            archive_name = f"2ByteASR-{version}-{name}-{record['content_sha256'][:12]}.zip"
            files[base + archive_name] = data
            entry["archive"] = {"name": archive_name, "size": len(data),
                                "sha256": hashlib.sha256(data).hexdigest(), "urls": [base + archive_name]}
        components[name] = entry
    files[base + "2ByteASR-Setup-0.6.6.exe"] = setup
    lock = json.loads((new_payload / "dependencies.lock.json").read_text("utf-8"))
    manifest = {
        "schema": um.UPDATE_SCHEMA, "product": um.PRODUCT, "app_id": um.APP_ID, "version": version,
        "tag": "v" + version, "channel": channel, "platform": "windows", "arch": "x64",
        "release_page": "https://github.com/NOTBAD314/2ByteASR/releases/tag/v" + version,
        "notes": {"zh": "修复若干问题", "en": "Fixes"},
        "setup": {"name": "2ByteASR-Setup-0.6.6.exe", "size": len(setup),
                  "sha256": hashlib.sha256(setup).hexdigest(), "urls": [base + "2ByteASR-Setup-0.6.6.exe"]},
        "components": components, "environments": um.environment_contracts(lock),
        "models": um.model_contracts(lock), "build": {"git_sha": "y"},
    }
    return manifest, files


class FakeResponse:
    def __init__(self, data=b"", status=200, headers=None, chunk=7):
        self.content = data
        self.status_code = status
        self.headers = headers or {"Content-Length": str(len(data))}
        self._chunk = chunk

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), self._chunk):
            yield self.content[start:start + self._chunk]

    def json(self):
        return json.loads(self.content.decode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _server(files: dict, *, ranges=True, log=None):
    def get(url, headers=None, timeout=None, stream=False, allow_redirects=True):
        if log is not None:
            log.append((url, dict(headers or {})))
        if url not in files:
            return FakeResponse(b"missing", status=404)
        data = files[url]
        start = 0
        header = (headers or {}).get("Range", "")
        if header and ranges:
            start = int(header.split("=")[1].split("-")[0])
            if start >= len(data):
                return FakeResponse(b"", status=416)
            part = data[start:]
            return FakeResponse(part, status=206, headers={"Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}",
                                                           "Content-Length": str(len(part))})
        return FakeResponse(data)
    return get


@pytest.fixture()
def isolated_state(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv(updater.STATE_ENV, str(state))
    monkeypatch.delenv(updater.FEED_ENV, raising=False)
    monkeypatch.delenv(updater.CHANNEL_ENV, raising=False)
    return state


# ---------------------------------------------------------------- versions


def test_semver_precedence_is_not_string_order():
    v = um.parse_version
    assert v("0.6.10") > v("0.6.9")
    assert v("0.6.5") > v("0.6.5-rc.2") > v("0.6.5-rc.1")
    assert v("1.0.0-alpha.10") > v("1.0.0-alpha.9")
    assert v("1.0.0-alpha.beta") > v("1.0.0-alpha.1")
    assert v("v0.6.5") == v("0.6.5")
    assert str(v("0.6.6-test.1")) == "0.6.6-test.1"
    with pytest.raises(um.ManifestError):
        v("0.6")
    with pytest.raises(um.ManifestError):
        v("0.6.5-01")


# --------------------------------------------------------------- components


def test_classification_keeps_user_files_out_of_every_component():
    assert um.classify("2byteasr_settings.json") is None
    assert um.classify("glossary.txt") is None
    assert um.classify("2byteasr_components.json") is None
    assert um.classify(".update-backup/x/2ByteASR.exe") is None
    assert um.classify("2ByteASR.exe") == "app"
    assert um.classify("base_library.zip") == "app"
    assert um.classify("twobyteasr/app/ui.py") == "app"
    assert um.classify("renderer/service.mjs") == "app"
    assert um.classify("renderer/node_modules/a/b.js") == "renderer"
    assert um.classify("renderer/public/fonts/x.otf") == "renderer"
    assert um.classify("assets/fonts/x.otf") == "assets"
    assert um.classify("assets/app_icon.ico") == "app"
    assert um.classify("python310.dll") == "python-runtime"
    assert um.classify("PySide6/Qt6Core.dll") == "python-runtime"
    for bad in ("../x", "/abs", "C:/x", "a//b", "a/./b", "a\\..\\b"):
        with pytest.raises(um.ManifestError):
            um.classify(bad)


def test_content_identity_ignores_version_and_detects_changes(tmp_path):
    first = _make_payload(tmp_path / "a", version="0.6.5")
    second = _make_payload(tmp_path / "b", version="0.6.6")
    third = _make_payload(tmp_path / "c", version="0.6.6", app_text=b"app-v2")
    for name in um.COMPONENT_ORDER:
        if name != "app":
            assert first["components"][name]["content_sha256"] == third["components"][name]["content_sha256"]
    assert first["components"]["app"]["content_sha256"] != third["components"]["app"]["content_sha256"]
    # The version file itself is an app file, so equal versions are needed for equal app hashes.
    assert first["components"]["renderer"] == second["components"]["renderer"]
    um.validate_installed_manifest(first)
    tampered = json.loads(json.dumps(first))
    tampered["components"]["app"]["files"][0][2] = "0" * 64
    with pytest.raises(um.ManifestError):
        um.validate_installed_manifest(tampered)


# --------------------------------------------------------------- signatures


def test_signature_accepts_only_embedded_keys(trusted_key):
    data = b'{"x":1}'
    signature = um.sign_manifest(data, trusted_key)
    assert um.verify_manifest_signature(data, signature)
    with pytest.raises(um.ManifestError):
        um.verify_manifest_signature(data + b" ", signature)
    other, _public = _keypair()
    with pytest.raises(um.ManifestError, match="未受信任"):
        um.verify_manifest_signature(data, um.sign_manifest(data, other))


def test_production_key_is_embedded_and_private_key_is_not_in_repository():
    root = Path(__file__).resolve().parents[1]
    assert um.TRUSTED_UPDATE_KEYS, "a public key must be embedded"
    for path in (root / "twobyteasr").rglob("*.py"):
        text = path.read_text("utf-8", errors="ignore")
        assert "PRIVATE KEY-----" not in text
        assert '"dpapi"' not in text or path.name == "update_manifest.py"


# ------------------------------------------------------------------- check


def test_check_verifies_signature_and_plans_only_changed_components(tmp_path, isolated_state, trusted_key):
    installed = tmp_path / "install"
    _make_payload(installed)
    new_payload = tmp_path / "new"
    new_manifest = _make_payload(new_payload, version="0.6.6", app_text=b"app-v2")
    manifest, files = _feed(new_payload, new_manifest)
    data = json.dumps(manifest).encode()
    files[updater.STABLE_FEED] = data
    files[updater.STABLE_FEED + ".sig"] = um.sign_manifest(data, trusted_key)
    check = updater.check_for_update(request_get=_server(files), root=installed)
    assert check.newer and check.latest_version == "0.6.6"
    assert check.plan.mode == "components"
    assert [a.name for a in check.plan.downloads] == ["app"]
    assert {a.name for a in check.plan.reused} == set(um.COMPONENT_ORDER) - {"app"}
    assert check.plan.download_bytes == manifest["components"]["app"]["archive"]["size"]
    assert check.plan.environment_changes == () and check.plan.model_changes == ()
    # Tampered manifest bytes are rejected even when the signature file is intact.
    files[updater.STABLE_FEED] = data.replace(b"0.6.6", b"0.6.7", 1)
    with pytest.raises(updater.UpdateError):
        updater.check_for_update(request_get=_server(files), root=installed)


def test_damaged_component_is_repaired_and_missing_manifest_falls_back_to_setup(tmp_path, isolated_state, trusted_key):
    installed = tmp_path / "install"
    _make_payload(installed)
    (installed / "tools/ffmpeg/bin/ffmpeg.exe").unlink()
    new_payload = tmp_path / "new"
    manifest_new = _make_payload(new_payload, version="0.6.6", app_text=b"app-v2")
    manifest, _files = _feed(new_payload, manifest_new)
    parsed = um.parse_update_manifest(json.dumps(manifest).encode())
    plan = updater.plan_update(parsed, installed)
    assert {a.name: a.reason for a in plan.downloads} == {"app": "changed", "tools": "repair"}
    (installed / um.COMPONENTS_FILENAME).unlink()
    plan = updater.plan_update(parsed, installed)
    assert plan.mode == "setup" and plan.download_bytes == len(b"SETUP")
    manifest2, _ = _feed(new_payload, manifest_new, skip=("app",))
    _make_payload(installed)
    plan = updater.plan_update(um.parse_update_manifest(json.dumps(manifest2).encode()), installed)
    assert plan.mode == "setup" and "没有单独的元件包" in plan.fallback_reason


def test_network_failures_back_off_and_do_not_raise_outside_check(tmp_path, isolated_state, monkeypatch):
    installed = tmp_path / "install"
    _make_payload(installed)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TWOBYTEASR_TEST_ROOT", raising=False)
    monkeypatch.delenv("TWOBYTEASR_ACCEPTANCE_DIR", raising=False)
    monkeypatch.delenv(updater.DISABLE_ENV, raising=False)

    def offline(url, **kwargs):
        raise ConnectionError("offline")

    assert updater.automatic_check_due()
    with pytest.raises(updater.UpdateError):
        updater.check_for_update(request_get=offline, root=installed)
    assert not updater.automatic_check_due()  # backed off; no retry storm on every start
    cache = json.loads((isolated_state / "check.json").read_text("utf-8"))
    assert cache["failures"] == 1 and cache["next_attempt_at"] > cache["last_failure_at"] + 3000


def test_channel_mismatch_and_wrong_platform_are_rejected(tmp_path, isolated_state, trusted_key):
    installed = tmp_path / "install"
    _make_payload(installed)
    new_payload = tmp_path / "new"
    manifest, files = _feed(new_payload, _make_payload(new_payload, version="0.6.6"), channel="qa-local")
    data = json.dumps(manifest).encode()
    files[updater.STABLE_FEED] = data
    files[updater.STABLE_FEED + ".sig"] = um.sign_manifest(data, trusted_key)
    with pytest.raises(updater.UpdateError, match="渠道"):
        updater.check_for_update(request_get=_server(files), root=installed)
    manifest["platform"] = "macos"
    with pytest.raises(um.ManifestError):
        um.parse_update_manifest(json.dumps(manifest).encode())
    manifest["platform"] = "windows"
    manifest["setup"]["urls"] = ["http://evil.example/x.exe"]
    with pytest.raises(um.ManifestError):
        um.parse_update_manifest(json.dumps(manifest).encode())


# ----------------------------------------------------------------- download


class _Asset:
    def __init__(self, data, name="a.zip"):
        self.name, self.size, self.sha256 = name, len(data), hashlib.sha256(data).hexdigest()
        self.urls = ("https://example.org/" + name,)


def test_download_resumes_with_ranges(tmp_path, isolated_state):
    data = bytes(range(256)) * 40
    asset = _Asset(data)
    folder = tmp_path / "dl"
    folder.mkdir()
    (folder / "a.zip.part").write_bytes(data[:1000])
    log = []
    path = updater.download_asset(asset, folder, request_get=_server({asset.urls[0]: data}, log=log),
                                  sleep=lambda s: None)
    assert path.read_bytes() == data
    assert log[0][1].get("Range") == "bytes=1000-"


def test_download_restarts_when_server_ignores_ranges(tmp_path, isolated_state):
    data = b"x" * 5000
    asset = _Asset(data)
    folder = tmp_path / "dl"
    folder.mkdir()
    (folder / "a.zip.part").write_bytes(b"y" * 1200)  # stale bytes must not survive
    path = updater.download_asset(asset, folder, request_get=_server({asset.urls[0]: data}, ranges=False),
                                  sleep=lambda s: None)
    assert path.read_bytes() == data


def test_download_rejects_corruption_and_never_marks_partial_files(tmp_path, isolated_state):
    data = b"z" * 3000
    asset = _Asset(data)
    folder = tmp_path / "dl"
    with pytest.raises(updater.UpdateError):
        updater.download_asset(asset, folder, request_get=_server({asset.urls[0]: b"z" * 2999 + b"!"}),
                               attempts_per_url=2, sleep=lambda s: None)
    assert not (folder / "a.zip").exists() and not (folder / "a.zip.verified").exists()
    assert not (folder / "a.zip.part").exists()
    with pytest.raises(updater.UpdateError):  # missing asset (404) on every mirror
        updater.download_asset(asset, folder, request_get=_server({}), attempts_per_url=1, sleep=lambda s: None)


def test_download_cancel_keeps_partial_for_resume(tmp_path, isolated_state):
    data = b"c" * 5000
    asset = _Asset(data)
    cancel = threading.Event()
    seen = []

    def progress(received, total):
        seen.append(received)
        if received > 100:
            cancel.set()

    with pytest.raises(updater.UpdateCancelled):
        updater.download_asset(asset, tmp_path / "dl", progress=progress, cancel=cancel,
                               request_get=_server({asset.urls[0]: data}), sleep=lambda s: None)
    assert (tmp_path / "dl" / "a.zip.part").exists()


# ------------------------------------------------------------------ staging


def test_prepare_stages_verified_files_and_writes_controlled_plan(tmp_path, isolated_state, trusted_key):
    installed = tmp_path / "install"
    _make_payload(installed)
    new_payload = tmp_path / "new"
    _write(new_payload, "twobyteasr/new_module.py", b"new")
    new_manifest = _make_payload(new_payload, version="0.6.6", app_text=b"app-v2")
    (new_payload / "twobyteasr/old_module.py").unlink()
    new_manifest = um.build_installed_manifest(new_payload, version="0.6.6")
    manifest, files = _feed(new_payload, new_manifest)
    data = json.dumps(manifest).encode()
    files[updater.STABLE_FEED] = data
    files[updater.STABLE_FEED + ".sig"] = um.sign_manifest(data, trusted_key)
    getter = _server(files)
    check = updater.check_for_update(request_get=getter, root=installed)
    prepared = updater.prepare_update(check, request_get=getter, root=installed, wait_pid=4321)
    plan = prepared.plan_path.read_text("utf-8").splitlines()
    assert plan[0] == "2BYTEASR-UPDATE-PLAN\t1"
    assert "wait_pid\t4321" in plan
    replaced = {line.split("\t", 1)[1] for line in plan if line.startswith("REPLACE\t")}
    removed = {line.split("\t", 1)[1] for line in plan if line.startswith("REMOVE\t")}
    assert "2ByteASR.exe" in replaced and "twobyteasr/new_module.py" in replaced
    assert "twobyteasr/old_module.py" in removed
    assert not (replaced | removed) & set(um.PRESERVED_FILES)
    assert not any(p.startswith(("renderer/node_modules", "tools/", "wheels/")) for p in replaced | removed)
    assert plan[-1] == f"END\t{len(replaced) + len(removed) + 1}"
    staged = json.loads((prepared.staging / um.COMPONENTS_FILENAME).read_text("utf-8"))
    assert staged["version"] == "0.6.6"
    assert um.validate_installed_manifest(staged)["components"]["renderer"] == \
        json.loads((installed / um.COMPONENTS_FILENAME).read_text("utf-8"))["components"]["renderer"]
    assert (prepared.staging / "twobyteasr/new_module.py").read_bytes() == b"new"
    assert not prepared.staging.is_relative_to(installed)
    # A second preparation reuses the verified archive instead of downloading again.
    log = []
    updater.prepare_update(check, request_get=_server(files, log=log), root=installed)
    assert not [url for url, _ in log if url.endswith(".zip")]


def test_archive_with_extra_or_tampered_member_is_rejected(tmp_path, isolated_state):
    payload = tmp_path / "p"
    manifest = _make_payload(payload)
    record = manifest["components"]["app"]
    good = _component_zip(payload, "app", record)
    archive = tmp_path / "a.zip"
    body = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as source, zipfile.ZipFile(body, "w") as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr("2byteasr_settings.json", b"{}")
    archive.write_bytes(body.getvalue())
    with pytest.raises(updater.UpdateError):
        updater._safe_extract(archive, "app", record["content_sha256"], tmp_path / "s1")
    body = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as source, zipfile.ZipFile(body, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            target.writestr(item, b"MZ-evil" if item.filename == "2ByteASR.exe" else data)
    archive.write_bytes(body.getvalue())
    with pytest.raises(updater.UpdateError, match="校验不符"):
        updater._safe_extract(archive, "app", record["content_sha256"], tmp_path / "s2")


# ------------------------------------------------------------------ GitCode
# 2026-10-14: on a mainland line github.com failed outright while GitCode
# served the same release files at ~14 MB/s.

GITHUB_V066 = "https://github.com/NOTBAD314/2ByteASR/releases/download/v0.6.6/"
GITCODE_V066 = "https://gitcode.com/Notbad314/2ByteASR/releases/download/v0.6.6/"


def _signed_sources(tmp_path, trusted_key, *, github_version="0.6.6", gitcode_version="0.6.6"):
    """GitHub and GitCode copies of one signed release (each may carry its own version)."""
    installed = tmp_path / "install"
    _make_payload(installed)
    files = {}
    for host, version in (("github", github_version), ("gitcode", gitcode_version)):
        if version is None:
            continue
        payload = tmp_path / f"new-{host}-{version}"
        manifest, feed = _feed(payload, _make_payload(payload, version=version, app_text=b"app-" + version.encode()),
                               version=version, base=f"https://github.com/NOTBAD314/2ByteASR/releases/download/v{version}/")
        data = json.dumps(manifest).encode()
        signature = um.sign_manifest(data, trusted_key)
        if host == "github":
            files.update(feed)
            files[updater.STABLE_FEED] = data
            files[updater.STABLE_FEED + ".sig"] = signature
        else:
            files.update({updater.gitcode_url(url): blob for url, blob in feed.items()})
            files[updater.GITCODE_LATEST_API] = json.dumps({"tag_name": "v" + version}).encode()
            manifest_url = f"https://gitcode.com/Notbad314/2ByteASR/releases/download/v{version}/{um.UPDATE_MANIFEST_NAME}"
            files[manifest_url] = data
            files[manifest_url + ".sig"] = signature
    return installed, files


def _unreachable(files, *hosts, log=None):
    serve = _server(files, log=log)

    def get(url, **kwargs):
        if url.split("/")[2] in hosts or any(url.startswith(prefix) for prefix in updater.GITHUB_MIRRORS):
            if log is not None:
                log.append((url, {}))
            raise ConnectionError("connection aborted")
        return serve(url, **kwargs)
    return get


def test_gitcode_answers_and_serves_downloads_when_github_is_unreachable(tmp_path, isolated_state, trusted_key):
    installed, files = _signed_sources(tmp_path, trusted_key, github_version=None)
    log = []
    getter = _unreachable(files, "github.com", log=log)
    check = updater.check_for_update(request_get=getter, root=installed)
    assert check.newer and check.latest_version == "0.6.6" and check.from_gitcode
    assert check.source == GITCODE_V066 + um.UPDATE_MANIFEST_NAME
    assert check.installer_url == GITCODE_V066 + "2ByteASR-Setup-0.6.6.exe"
    assert check.release_url == "https://gitcode.com/Notbad314/2ByteASR/releases/tag/v0.6.6"
    log.clear()
    prepared = updater.prepare_update(check, request_get=getter, root=installed, wait_pid=1)
    downloads = [url for url, _ in log if url.endswith(".zip")]
    assert downloads and all(url.startswith(GITCODE_V066) for url in downloads)  # GitCode first, github.com never needed
    assert prepared.version == "0.6.6"
    # The cached check (no network) still knows where the manifest came from.
    assert updater.check_for_update(request_get=getter, root=installed, use_cache=True).from_gitcode


def test_a_lagging_mirror_never_hides_a_newer_release(tmp_path, isolated_state, trusted_key):
    installed, files = _signed_sources(tmp_path, trusted_key, github_version="0.6.7", gitcode_version="0.6.6")
    check = updater.check_for_update(request_get=_server(files), root=installed)
    assert check.latest_version == "0.6.7" and not check.from_gitcode
    assert check.installer_url.startswith("https://github.com/")
    installed, files = _signed_sources(tmp_path / "b", trusted_key, github_version="0.6.6", gitcode_version="0.6.7")
    check = updater.check_for_update(request_get=_server(files), root=installed)
    assert check.latest_version == "0.6.7" and check.from_gitcode


def test_unsigned_or_odd_gitcode_answers_never_win(tmp_path, isolated_state, trusted_key):
    installed, files = _signed_sources(tmp_path, trusted_key, github_version="0.6.6", gitcode_version="0.6.7")
    gitcode_manifest = "https://gitcode.com/Notbad314/2ByteASR/releases/download/v0.6.7/" + um.UPDATE_MANIFEST_NAME
    files[gitcode_manifest] = files[gitcode_manifest].replace(b"0.6.7", b"0.6.8", 1)  # signature no longer matches
    check = updater.check_for_update(request_get=_server(files), root=installed)
    assert check.latest_version == "0.6.6" and not check.from_gitcode
    files[updater.GITCODE_LATEST_API] = json.dumps({"tag_name": "../../evil"}).encode()
    assert not updater.check_for_update(request_get=_server(files), root=installed).from_gitcode
    # GitHub down and GitCode unusable: one error naming both sources.
    with pytest.raises(updater.UpdateError, match="GitHub.*\n?.*GitCode|GitCode.*\n?.*GitHub"):
        updater.check_for_update(request_get=_unreachable(files, "github.com"), root=installed)


def test_slow_source_does_not_hold_the_answer_beyond_the_grace(tmp_path, isolated_state, trusted_key, monkeypatch):
    installed, files = _signed_sources(tmp_path, trusted_key)
    release = threading.Event()
    serve = _server(files)

    def slow_github(url, **kwargs):
        if url.startswith("https://github.com/"):
            release.wait(10)  # a github.com that hangs, as on a mainland line
        return serve(url, **kwargs)
    monkeypatch.setattr(updater, "SOURCE_GRACE_SECONDS", 0.2)
    import time as _time
    started = _time.monotonic()
    check = updater.check_for_update(request_get=slow_github, root=installed)
    release.set()
    assert check.from_gitcode and _time.monotonic() - started < 5


def test_download_candidates_follow_the_answering_source():
    url = GITHUB_V066 + "2ByteASR-0.6.6-app-abc.zip"
    assert updater._candidates(url) == (url, GITCODE_V066 + "2ByteASR-0.6.6-app-abc.zip",
                                        *(prefix + url for prefix in updater.GITHUB_MIRRORS))
    assert updater._candidates(url, prefer_gitcode=True)[:2] == (GITCODE_V066 + "2ByteASR-0.6.6-app-abc.zip", url)
    # The GitHub "latest" feed has no GitCode twin (GitCode lacks releases/latest/download).
    assert updater._candidates(updater.STABLE_FEED) == (updater.STABLE_FEED,
                                                       *(prefix + updater.STABLE_FEED for prefix in updater.GITHUB_MIRRORS))
    assert updater._candidates("http://127.0.0.1:9/feed.json") == ("http://127.0.0.1:9/feed.json",)


def test_mirrors_follow_the_mainland_measurement():
    # 2026-10-22 mainland line: gh-proxy.org 0.9-2.8 MB/s, ghfast.top 0.9-1.7 MB/s, ghproxy.net 0.02 MB/s.
    assert updater.GITHUB_MIRRORS == ("https://gh-proxy.org/", "https://ghfast.top/", "https://ghproxy.net/")
    url = GITHUB_V066 + "2ByteASR-0.6.6-app-abc.zip"
    assert [u.split("/")[2] for u in updater._asset_sources([url])] == \
        ["github.com", "gitcode.com", "gh-proxy.org", "ghfast.top", "ghproxy.net"]


def test_manifest_listing_gitcode_first_does_not_change_this_programs_order(tmp_path, isolated_state, trusted_key):
    # release_pipeline.py feed --gitcode-first lists [GitCode, GitHub] for older programs;
    # here the source that answered the check still decides.
    url = GITHUB_V066 + "2ByteASR-0.6.6-app-abc.zip"
    listed = [updater.gitcode_url(url), url]
    assert updater._asset_sources(listed) == updater._asset_sources([url])
    assert updater._asset_sources(listed, prefer_gitcode=True) == updater._asset_sources([url], prefer_gitcode=True)
    installed, files = _signed_sources(tmp_path, trusted_key, gitcode_version=None)
    manifest = json.loads(files[updater.STABLE_FEED])
    for record in [manifest["setup"]] + [c["archive"] for c in manifest["components"].values() if c["archive"]]:
        record["urls"] = [updater.gitcode_url(record["urls"][0]), record["urls"][0]]
    files[updater.STABLE_FEED] = json.dumps(manifest).encode()
    files[updater.STABLE_FEED + ".sig"] = um.sign_manifest(files[updater.STABLE_FEED], trusted_key)
    check = updater.check_for_update(request_get=_server(files), root=installed)
    assert not check.from_gitcode and check.installer_url == GITHUB_V066 + "2ByteASR-Setup-0.6.6.exe"


# ------------------------------------------------------------- slow sources
# 2026-10-22 mainland line: github.com connected and then sent ~40 KB/s without
# an error (849 MB = about six hours); GitCode served the same file at ~14 MB/s.


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RatedResponse(FakeResponse):
    """A source that sends ``rate`` bytes per second on a fake clock."""

    def __init__(self, data, rate, clock, **kwargs):
        super().__init__(data, **kwargs)
        self._rate, self._clock = rate, clock

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), chunk_size):
            block = self.content[start:start + chunk_size]
            self._clock.now += len(block) / self._rate
            yield block


def _rated_server(files, rates, clock, *, no_ranges=(), log=None):
    def get(url, headers=None, **kwargs):
        host = url.split("/")[2]
        response = _server(files, ranges=host not in no_ranges, log=log)(url, headers=headers, **kwargs)
        if host in rates and response.status_code < 400:
            return RatedResponse(response.content, rates[host], clock,
                                 status=response.status_code, headers=response.headers)
        return response
    return get


def _release_asset(size_mib: int):
    data = bytes(range(256)) * (4096 * size_mib)
    asset = _Asset(data, name="2ByteASR-0.6.6-app-abc.zip")
    asset.urls = (GITHUB_V066 + asset.name,)
    return data, asset, {url: data for url in updater._asset_sources(asset.urls)}


def _hosts(log):
    return [url.split("/")[2] for url, _headers in log]


def _resumed_at(entry):
    return int(entry[1]["Range"].split("=")[1].rstrip("-"))


KB = 1024
MB = 1024 * 1024


def test_slow_source_hands_the_partial_file_to_the_next_one(tmp_path, isolated_state):
    data, asset, files = _release_asset(8)
    clock, log = FakeClock(), []
    getter = _rated_server(files, {"github.com": 40 * KB, "gitcode.com": 14 * MB}, clock, log=log)
    path = updater.download_asset(asset, tmp_path / "dl", request_get=getter, clock=clock, sleep=lambda s: None)
    assert path.read_bytes() == data
    assert _hosts(log) == ["github.com", "gitcode.com"]
    # About 30 s of github.com is kept and resumed, not downloaded again.
    assert 30 * 40 * KB <= _resumed_at(log[1]) < 2 * MB
    assert clock.now < 40  # before: 8 MiB at 40 KB/s = 205 s


def test_when_every_source_is_slow_each_is_judged_once_and_the_fastest_finishes(tmp_path, isolated_state):
    data, asset, files = _release_asset(16)
    rates = {"github.com": 40 * KB, "gitcode.com": 100 * KB, "gh-proxy.org": 60 * KB,
             "ghfast.top": 50 * KB, "ghproxy.net": 20 * KB}
    clock, log = FakeClock(), []
    path = updater.download_asset(asset, tmp_path / "dl", request_get=_rated_server(files, rates, clock, log=log),
                                  clock=clock, sleep=lambda s: None)
    assert path.read_bytes() == data
    assert _hosts(log) == ["github.com", "gitcode.com", "gh-proxy.org", "ghfast.top", "ghproxy.net", "gitcode.com"]
    offsets = [_resumed_at(entry) for entry in log[1:]]
    assert offsets == sorted(offsets) and len(set(offsets)) == len(offsets)  # every switch resumes, never restarts


def test_a_mirror_that_ignores_range_never_wipes_the_bytes_already_here(tmp_path, isolated_state):
    data, asset, files = _release_asset(16)
    folder = tmp_path / "dl"
    clock, log = FakeClock(), []
    # github.com is slow; GitCode ignores Range and is slow too; gh-proxy.org resumes fast.
    getter = _rated_server(files, {"github.com": 40 * KB, "gitcode.com": 20 * KB, "gh-proxy.org": 2 * MB},
                           clock, no_ranges={"gitcode.com"}, log=log)
    path = updater.download_asset(asset, folder, request_get=getter, clock=clock, sleep=lambda s: None)
    assert path.read_bytes() == data
    assert _hosts(log) == ["github.com", "gitcode.com", "gh-proxy.org"]
    assert _resumed_at(log[2]) == _resumed_at(log[1])  # GitCode's restart from zero was dropped, github's bytes kept
    assert not list(folder.glob("*.fresh")) and not list(folder.glob("*.part"))


def test_a_range_ignoring_source_takes_over_once_it_has_more(tmp_path, isolated_state):
    data, asset, files = _release_asset(8)
    clock, log = FakeClock(), []
    getter = _rated_server(files, {"github.com": 40 * KB, "gitcode.com": 14 * MB}, clock,
                           no_ranges={"gitcode.com"}, log=log)
    seen = []
    path = updater.download_asset(asset, tmp_path / "dl", request_get=getter, clock=clock, sleep=lambda s: None,
                                  progress=lambda received, total: seen.append(received))
    assert path.read_bytes() == data and _hosts(log) == ["github.com", "gitcode.com"]
    assert seen == sorted(seen)  # progress never jumps back while the new copy catches up


def test_nearly_finished_download_stays_on_its_source(tmp_path, isolated_state):
    data, asset, files = _release_asset(2)  # at 40 KB/s the rest after 30 s arrives within a minute
    clock, log = FakeClock(), []
    getter = _rated_server(files, {"github.com": 40 * KB, "gitcode.com": 14 * MB}, clock, log=log)
    path = updater.download_asset(asset, tmp_path / "dl", request_get=getter, clock=clock, sleep=lambda s: None)
    assert path.read_bytes() == data and _hosts(log) == ["github.com"]


def test_slow_switch_keeps_the_answering_source_first(tmp_path, isolated_state):
    data, asset, files = _release_asset(8)
    clock, log = FakeClock(), []
    # GitCode answered the check but crawls on this network; github.com is fast.
    getter = _rated_server(files, {"gitcode.com": 30 * KB, "github.com": 10 * MB}, clock, log=log)
    path = updater.download_asset(asset, tmp_path / "dl", request_get=getter, clock=clock, sleep=lambda s: None,
                                  prefer_gitcode=True)
    assert path.read_bytes() == data and _hosts(log) == ["gitcode.com", "github.com"]
