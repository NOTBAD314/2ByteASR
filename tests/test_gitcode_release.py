# SPDX-License-Identifier: GPL-3.0-only
"""release_pipeline.py gitcode: mirror a published release to GitCode (no network)."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import sys
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.app import update_manifest as um

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gitcode_release as gc  # noqa: E402

_spec = importlib.util.spec_from_file_location("release_pipeline_gitcode", ROOT / "scripts/release_pipeline.py")
pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline)
TOKEN = "tok3n-not-for-logs"
GH = "https://github.com/NOTBAD314/2ByteASR/releases/download/"


@pytest.fixture()
def signer(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setitem(um.TRUSTED_UPDATE_KEYS, um.key_id_for(public), base64.b64encode(public).decode())
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def _release_folder(tmp_path, signer):
    assets = tmp_path / "releases" / "0.7.2"
    assets.mkdir(parents=True)
    own = {"2ByteASR-Setup-0.7.2.exe": b"setup" * 100, "2ByteASR-0.7.2-app-aaa.zip": b"app" * 50}
    for name, data in own.items():
        (assets / name).write_bytes(data)
    older = b"renderer-archive"
    manifest = {"tag": "v0.7.2", "version": "0.7.2", "components": {
        "app": {"archive": {"name": "2ByteASR-0.7.2-app-aaa.zip", "size": len(own["2ByteASR-0.7.2-app-aaa.zip"]),
                            "sha256": hashlib.sha256(own["2ByteASR-0.7.2-app-aaa.zip"]).hexdigest(),
                            "urls": [GH + "v0.7.2/2ByteASR-0.7.2-app-aaa.zip"]}},
        "renderer": {"archive": {"name": "2ByteASR-0.7.0-renderer-bbb.zip", "size": len(older),
                                 "sha256": hashlib.sha256(older).hexdigest(),
                                 "urls": [GH + "v0.7.0/2ByteASR-0.7.0-renderer-bbb.zip"]}},
        "assets": {"archive": None}}}
    data = json.dumps(manifest).encode()
    (assets / um.UPDATE_MANIFEST_NAME).write_bytes(data)
    (assets / um.UPDATE_SIGNATURE_NAME).write_bytes(um.sign_manifest(data, signer))
    names = sorted([*own, um.UPDATE_MANIFEST_NAME, um.UPDATE_SIGNATURE_NAME])
    (assets / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256((assets / n).read_bytes()).hexdigest()}  {n}\n" for n in names), "ascii")
    return assets, older


class FakeGitCode:
    """In-memory GitCode: releases by tag, OBS uploads, latest marker; records every request."""

    def __init__(self):
        self.releases: dict[str, dict] = {}
        self.files: dict[tuple[str, str], bytes] = {}
        self.latest = ""
        self.requests: list[str] = []
        self.patches: list[tuple[str, dict]] = []

    def urlopen(self, request, timeout=None):
        url = request.full_url
        self.requests.append(f"{request.get_method()} {url}")
        parsed = urllib.parse.urlparse(url)
        path, query = parsed.path, dict(urllib.parse.parse_qsl(parsed.query))
        method = request.get_method()
        if parsed.hostname == "obs.example":
            tag, name = path.strip("/").split("/", 1)
            body = request.data.read() if hasattr(request.data, "read") else request.data
            self.files[(tag, name)] = body
            self.releases[tag]["assets"].append({"name": name, "browser_download_url": f"{gc.DOWNLOAD}{tag}/{name}"})
            return self._answer(200, {})
        prefix = "/api/v5/repos/Notbad314/2ByteASR/releases"
        assert path.startswith(prefix), url
        rest = path[len(prefix):]
        if method == "POST" and rest == "":
            body = json.loads(request.data)
            assert query.get("access_token") == TOKEN
            self.releases[body["tag_name"]] = {"tag_name": body["tag_name"], "name": body["name"], "assets": []}
            self.latest = body["tag_name"]  # GitCode: the newest created release counts as latest
            return self._answer(200, self.releases[body["tag_name"]])
        if method == "GET" and rest.startswith("/tags/"):
            tag = urllib.parse.unquote(rest[len("/tags/"):])
            return self._answer(200, self.releases[tag]) if tag in self.releases else self._answer(404, {"error": "nf"})
        if method == "GET" and rest.endswith("/upload_url"):
            tag = urllib.parse.unquote(rest[1:-len("/upload_url")])
            return self._answer(200, {"url": f"https://obs.example/{tag}/{query['file_name']}", "headers": {"x-obs-acl": "public-read"}})
        if method == "PATCH":
            tag = urllib.parse.unquote(rest[1:])
            self.patches.append((tag, json.loads(request.data)))
            if json.loads(request.data).get("release_status") == "latest":
                self.latest = tag
            return self._answer(200, self.releases[tag])
        if method == "GET" and rest == "/latest":
            return self._answer(200, {"tag_name": self.latest})
        raise AssertionError(url)

    @staticmethod
    def _answer(status, payload):
        if status >= 400:
            raise gc.urllib.error.HTTPError("u", status, "x", {}, io.BytesIO(json.dumps(payload).encode()))
        body = json.dumps(payload).encode()
        return SimpleNamespace(status=status, read=lambda: body, headers={},
                               __enter__=None, __exit__=None)


class _Ctx:
    def __init__(self, inner):
        self.inner = inner
        self.status = inner.status
        self.headers = inner.headers

    def read(self, *args):
        return self.inner.read()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture()
def gitcode(monkeypatch, tmp_path):
    fake = FakeGitCode()
    real_client = gc.GitCode

    def client(token="", **kwargs):
        return real_client(token, urlopen=lambda request, timeout=None: _Ctx(fake.urlopen(request, timeout)),
                           log=kwargs.get("log", print))
    monkeypatch.setattr(gc, "GitCode", client)
    monkeypatch.setenv("GITCODE_TOKEN", TOKEN)
    pushes = []
    monkeypatch.setattr(gc, "push_refs", lambda repo, refs, token, log=print: pushes.append(refs))
    fetched = []

    def fetch(url, target, size, sha256, urlopen=None):
        fetched.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fake.github_files[url])
        assert hashlib.sha256(target.read_bytes()).hexdigest() == sha256
        return target
    monkeypatch.setattr(gc, "fetch_verified", fetch)

    def verify(url, size, sha256, opener=None):
        tag, name = url[len(gc.DOWNLOAD):].split("/", 1)
        data = fake.files.get((tag, urllib.parse.unquote(name)))
        ok = data is not None and len(data) == size and (not sha256 or hashlib.sha256(data).hexdigest() == sha256)
        return {"url": url, "ok": ok, "length": len(data or b"")}
    monkeypatch.setattr(gc, "verify_download", verify)
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "_run", lambda command, **kw: None)  # git fetch
    fake.pushes, fake.fetched = pushes, fetched
    return fake


def _args(assets, **extra):
    base = dict(assets=str(assets), tag="v0.7.2", title="2ByteASR 0.7.2", notes_file=None, token_file=None,
                skip_push=False, full=False, verify_proxy=None)
    base.update(extra)
    return SimpleNamespace(**base)


def test_first_mirror_uploads_release_files_and_referenced_archives(tmp_path, signer, gitcode, monkeypatch, capsys):
    assets, older = _release_folder(tmp_path, signer)
    gitcode.github_files = {GH + "v0.7.0/2ByteASR-0.7.0-renderer-bbb.zip": older}
    monkeypatch.setattr(pipeline, "_release_by_tag", lambda tag: {"tag_name": tag, "draft": False, "name": "t", "body": "b"})
    pipeline.cmd_gitcode(_args(assets))
    assert gitcode.pushes == [["+refs/remotes/origin/main:refs/heads/main", "refs/tags/v0.7.2:refs/tags/v0.7.2",
                               "refs/tags/v0.7.0:refs/tags/v0.7.0"]]
    own = {name for tag, name in gitcode.files if tag == "v0.7.2"}
    assert own == {p.name for p in pipeline.upload_list(assets)}
    assert gitcode.files[("v0.7.0", "2ByteASR-0.7.0-renderer-bbb.zip")] == older
    assert gitcode.releases["v0.7.0"]["name"] == "2ByteASR 0.7.0（程序内更新组件镜像）"
    assert gitcode.latest == "v0.7.2"  # created after v0.7.0's mirror, still marked latest
    report = json.loads(next(assets.glob("gitcode-verification-*.json")).read_text("utf-8"))
    assert report["all_ok"] and report["latest_tag"] == "v0.7.2" and len(report["referenced"]) == 1
    assert TOKEN not in capsys.readouterr().out + json.dumps(report)


def test_rerun_uploads_nothing_and_still_verifies(tmp_path, signer, gitcode, monkeypatch):
    assets, older = _release_folder(tmp_path, signer)
    gitcode.github_files = {GH + "v0.7.0/2ByteASR-0.7.0-renderer-bbb.zip": older}
    monkeypatch.setattr(pipeline, "_release_by_tag", lambda tag: {"tag_name": tag, "draft": False, "name": "t", "body": "b"})
    pipeline.cmd_gitcode(_args(assets))
    before = [r for r in gitcode.requests if "obs.example" in r]
    pipeline.cmd_gitcode(_args(assets, skip_push=True))
    after = [r for r in gitcode.requests if "obs.example" in r]
    assert after == before and len(gitcode.fetched) == 1


def test_unpublished_or_mismatched_release_is_refused(tmp_path, signer, gitcode, monkeypatch):
    assets, _older = _release_folder(tmp_path, signer)
    monkeypatch.setattr(pipeline, "_release_by_tag", lambda tag: {"tag_name": tag, "draft": True})
    with pytest.raises(SystemExit, match="not published"):
        pipeline.cmd_gitcode(_args(assets))
    monkeypatch.setattr(pipeline, "_release_by_tag", lambda tag: {"tag_name": tag, "draft": False})
    with pytest.raises(SystemExit, match="belongs to v0.7.2"):
        pipeline.cmd_gitcode(_args(assets, tag="v0.7.3"))
    assert not gitcode.requests


HELD_BACK = {um.UPDATE_MANIFEST_NAME, um.UPDATE_SIGNATURE_NAME}
RELEASE_COMMIT = "a" * 40


def _draft_with_published_v071(gitcode, monkeypatch, **draft):
    release = {"tag_name": "v0.7.2", "draft": True, "name": "t", "body": "b", "target_commitish": RELEASE_COMMIT,
               **draft}
    monkeypatch.setattr(pipeline, "_release_by_tag", lambda tag: release)
    monkeypatch.setattr(pipeline, "_published_latest_tag", lambda: "v0.7.1")
    gitcode.releases["v0.7.1"] = {"tag_name": "v0.7.1", "name": "2ByteASR 0.7.1", "body": "0.7.1 的说明",
                                  "assets": []}
    gitcode.latest = "v0.7.1"
    tagged = []
    monkeypatch.setattr(pipeline, "_tag_commit", lambda tag, commit: tagged.append((tag, commit)))
    return release, tagged


def test_before_publish_uploads_all_but_the_manifest_and_keeps_the_published_release_latest(
        tmp_path, signer, gitcode, monkeypatch):
    # 2026-10-22 owner decision: with feed --gitcode-first, GitCode must hold the files
    # before GitHub publishes, or old programs that start on GitCode fall back to a slow github.com.
    assets, older = _release_folder(tmp_path, signer)
    gitcode.github_files = {GH + "v0.7.0/2ByteASR-0.7.0-renderer-bbb.zip": older}
    release, tagged = _draft_with_published_v071(gitcode, monkeypatch)
    pipeline.cmd_gitcode(_args(assets, before_publish=True))
    own = {name for tag, name in gitcode.files if tag == "v0.7.2"}
    assert own == {p.name for p in pipeline.upload_list(assets)} - HELD_BACK
    assert ("v0.7.0", "2ByteASR-0.7.0-renderer-bbb.zip") in gitcode.files
    # Nobody can see the new version on GitCode: no manifest there, and 0.7.1 is latest again, notes unchanged.
    assert gitcode.latest == "v0.7.1"
    assert gitcode.patches[-1] == ("v0.7.1", {"name": "2ByteASR 0.7.1", "body": "0.7.1 的说明",
                                              "release_status": "latest"})
    assert tagged == [("v0.7.2", RELEASE_COMMIT)]  # a draft has no tag on GitHub yet
    assert "refs/tags/v0.7.2:refs/tags/v0.7.2" in gitcode.pushes[0]
    report = json.loads(next(assets.glob("gitcode-verification-*.json")).read_text("utf-8"))
    assert report["all_ok"] and report["before_publish"] and report["latest_tag"] == "v0.7.1"
    assert {row["name"] for row in report["assets"]}.isdisjoint(HELD_BACK)
    # Right after GitHub publishes: only the two held-back files go up, then the release is latest.
    release["draft"] = False
    sent = len([r for r in gitcode.requests if "obs.example" in r])
    pipeline.cmd_gitcode(_args(assets, skip_push=True))
    later = [r.rsplit("/", 1)[1] for r in gitcode.requests if "obs.example" in r][sent:]
    assert sorted(later) == sorted(HELD_BACK)
    assert gitcode.latest == "v0.7.2" and len(gitcode.fetched) == 1


def test_before_publish_refuses_what_it_cannot_do_safely(tmp_path, signer, gitcode, monkeypatch):
    assets, _older = _release_folder(tmp_path, signer)
    _draft_with_published_v071(gitcode, monkeypatch, target_commitish="release/v0.7.2")
    with pytest.raises(SystemExit, match="needs the release commit"):
        pipeline.cmd_gitcode(_args(assets, before_publish=True))
    _draft_with_published_v071(gitcode, monkeypatch)
    gitcode.releases["v0.7.1"]["body"] = ""  # mark_latest would wipe the notes of the release users have now
    with pytest.raises(SystemExit, match="must stay marked latest"):
        pipeline.cmd_gitcode(_args(assets, before_publish=True))
    assert not [r for r in gitcode.requests if r.startswith("POST") or "obs.example" in r]


def test_release_tag_for_a_draft_points_at_its_commit(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args], cwd=repo,
                              check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "release")
    commit = git("rev-parse", "HEAD")
    monkeypatch.setattr(pipeline, "ROOT", repo)
    pipeline._tag_commit("v9.9.9", commit)
    pipeline._tag_commit("v9.9.9", commit)  # again: already there, nothing to do
    assert git("rev-parse", "refs/tags/v9.9.9") == commit
    with pytest.raises(SystemExit, match="points at"):
        pipeline._tag_commit("v9.9.9", "b" * 40)


def test_referenced_archives_lists_only_older_tags():
    manifest = {"components": {
        "app": {"archive": {"name": "a.zip", "size": 1, "sha256": "x", "urls": [GH + "v0.7.2/a.zip"]}},
        "wheels": {"archive": {"name": "w.zip", "size": 2, "sha256": "y", "urls": [GH + "v0.6.5/w.zip"]}},
        "assets": {"archive": None}}}
    assert gc.referenced_archives(manifest, "v0.7.2") == [
        {"name": "w.zip", "size": 2, "sha256": "y", "tag": "v0.6.5", "github": GH + "v0.6.5/w.zip"}]


def test_feed_lists_gitcode_first_only_when_asked():
    # release_pipeline.py feed --gitcode-first (2026-10-22, not used in a release yet):
    # 0.6.5-0.8.2 try listed URLs in order; 0.6.5-0.8.1 never ask GitCode themselves.
    github = GH + "v0.7.2/a.zip"
    gitcode = "https://gitcode.com/Notbad314/2ByteASR/releases/download/v0.7.2/a.zip"
    assert pipeline.listed_urls([github]) == [github]
    assert pipeline.listed_urls([github], gitcode_first=True) == [gitcode, github]
    # A reused archive from a manifest that listed GitCode first is normalised either way.
    assert pipeline.listed_urls([gitcode, github]) == [github]
    assert pipeline.listed_urls([gitcode, github], gitcode_first=True) == [gitcode, github]
    assert pipeline.listed_urls(["http://127.0.0.1:9/a.zip"], gitcode_first=True) == ["http://127.0.0.1:9/a.zip"]
    assert pipeline._github_listed([gitcode, github]) == github
    # The gitcode step still finds the older tag of a reused archive.
    manifest = {"components": {"wheels": {"archive": {
        "name": "w.zip", "size": 2, "sha256": "y",
        "urls": pipeline.listed_urls([GH + "v0.6.5/w.zip"], gitcode_first=True)}}}}
    assert gc.referenced_archives(manifest, "v0.7.2") == [
        {"name": "w.zip", "size": 2, "sha256": "y", "tag": "v0.6.5", "github": GH + "v0.6.5/w.zip"}]


def test_push_never_shows_the_token(tmp_path):
    seen = {}

    def run(command, **kwargs):
        seen["command"], seen["env"] = command, kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=f"pushed with {TOKEN}", stderr="")
    lines = []
    gc.push_refs(tmp_path, ["refs/tags/v1:refs/tags/v1"], TOKEN, run=run, log=lines.append)
    assert TOKEN not in " ".join(seen["command"]) and TOKEN not in "\n".join(lines)
    assert seen["env"]["GITCODE_PUSH_TOKEN"] == TOKEN and seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
