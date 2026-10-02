import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from twobyteasr.updater import (
    UpdateError,
    check_for_update,
    current_version,
    download_update,
    normalize_version,
    release_from_payload,
)


class FakeResponse:
    def __init__(self, *, payload=None, content=b"", text=None, status=200):
        self._payload = payload
        self._content = content
        self.text = text if text is not None else content.decode("utf-8", errors="replace")
        self.status_code = status
        self.headers = {"Content-Length": str(len(content))}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload

    def iter_content(self, chunk_size):
        del chunk_size
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _release(version="0.1.15", *, update=True):
    assets = [
        {
            "name": f"2ByteASR-Setup-{version}.exe",
            "browser_download_url": f"https://github.com/x/2ByteASR-Setup-{version}.exe",
        }
    ]
    if update:
        assets += [
            {
                "name": f"2ByteASR-Update-{version}.zip",
                "browser_download_url": f"https://github.com/x/2ByteASR-Update-{version}.zip",
            },
            {
                "name": f"2ByteASR-Update-{version}.zip.sha256",
                "browser_download_url": f"https://github.com/x/2ByteASR-Update-{version}.zip.sha256",
            },
        ]
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/x/releases/tag/v{version}",
        "body": "release notes",
        "assets": assets,
    }


def test_version_metadata_and_semver_normalization(tmp_path):
    metadata = tmp_path / "version.json"
    metadata.write_text(json.dumps({"version": "v0.1.15"}), encoding="utf-8")
    assert current_version(metadata) == "0.1.15"
    assert normalize_version("v1.2.3") == "1.2.3"
    with pytest.raises(UpdateError):
        normalize_version("next")


def test_release_prefers_exact_versioned_update_asset():
    info = release_from_payload(_release(), "0.1.14")
    assert info.newer is True
    assert info.latest_version == "0.1.15"
    assert info.package_name == "2ByteASR-Update-0.1.15.zip"
    assert info.can_self_update is True


def test_old_release_without_update_asset_falls_back_to_installer():
    info = release_from_payload(_release(update=False), "0.1.14")
    assert info.newer is True
    assert info.can_self_update is False
    assert info.installer_url.endswith("2ByteASR-Setup-0.1.15.exe")


def test_update_check_uses_release_payload():
    payload = _release()

    def fake_get(url, **kwargs):
        assert "releases/latest" in url
        assert kwargs["timeout"]
        return FakeResponse(payload=payload)

    assert check_for_update(request_get=fake_get).latest_version == "0.1.15"


def test_download_verifies_sha256_before_promoting_partial_file(tmp_path):
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr("HOTFIX.json", '{"files": [], "delete": []}')
    package = body.getvalue()
    checksum = hashlib.sha256(package).hexdigest()
    info = release_from_payload(_release(), "0.1.14")

    def fake_get(url, **kwargs):
        if url.endswith(".sha256"):
            return FakeResponse(text=f"{checksum}  {info.package_name}")
        return FakeResponse(content=package)

    output, actual = download_update(info, tmp_path, request_get=fake_get)
    assert output.read_bytes() == package
    assert actual == checksum
    assert not output.with_suffix(".zip.part").exists()


def test_download_rejects_checksum_mismatch(tmp_path):
    info = release_from_payload(_release(), "0.1.14")

    def fake_get(url, **kwargs):
        if url.endswith(".sha256"):
            return FakeResponse(text=f"{'0' * 64}  {info.package_name}")
        return FakeResponse(content=b"tampered")

    with pytest.raises(UpdateError, match="更新包下载失败"):
        download_update(info, tmp_path, request_get=fake_get)
    assert not any(tmp_path.iterdir())


def test_powershell_update_helper_is_path_confined_and_waits_for_app():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "apply_update.ps1").read_text(encoding="utf-8-sig")
    assert "Get-FileHash" in source
    assert "Wait-Process" in source
    # P1-7：路径边界校验已收敛到公共 helper（update-path-safety.ps1），
    # 不再内联 StartsWith 实现；语义不变（canonicalize + root containment）。
    assert "Assert-PathInsideRoot" in source
    assert "update-path-safety.ps1" in source
    assert "HOTFIX.json" in source
    assert "Start-Process -FilePath $launcher" in source
