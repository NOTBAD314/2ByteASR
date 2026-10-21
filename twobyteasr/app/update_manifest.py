# SPDX-License-Identifier: GPL-3.0-only
"""Component inventory, signed update manifests and version ordering.

Shared by the release build (source checkout) and the installed program.

A frozen payload is split into a few *components* by path.  A component's
identity is the SHA-256 of its canonical file list (path, size, SHA-256), so
identical content keeps the same identity across application versions and is
never downloaded again just because the version number changed.

The installed program carries ``2byteasr_components.json`` (the exact program
file list).  Each release carries a small update manifest, signed with
Ed25519; the program only trusts the public keys embedded below.  SHA-256
values inside the signed manifest protect each download's integrity; they are
not a publisher signature on their own.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

INSTALLED_SCHEMA = "2byteasr-components/1"
UPDATE_SCHEMA = "2byteasr-update/1"
SIGNATURE_SCHEMA = "2byteasr-signature/1"
ARCHIVE_INDEX_NAME = "__component__.json"
COMPONENTS_FILENAME = "2byteasr_components.json"
UPDATE_MANIFEST_NAME = "2ByteASR-update.json"
UPDATE_SIGNATURE_NAME = UPDATE_MANIFEST_NAME + ".sig"
UPDATER_EXE_NAME = "2ByteASRUpdater.exe"
APP_ID = "{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}"
PRODUCT = "2ByteASR"
PLATFORM = "windows"
ARCH = "x64"
CHANNELS = ("stable", "prerelease")

# Factory defaults the installer writes only when missing and never removes.
# Updates never ship, replace or delete them.
PRESERVED_FILES = ("2byteasr_settings.json", "game_profiles.json", "glossary.txt")
META_FILES = (COMPONENTS_FILENAME,)
# Program-owned bookkeeping folders inside the install root.
STATE_DIRS = (".update-state", ".update-backup")

COMPONENT_ORDER = ("app", "python-runtime", "assets", "renderer", "tools", "wheels", "licenses")
COMPONENT_LABELS = {
    "app": "主程序",
    "python-runtime": "程序运行库",
    "assets": "界面字体",
    "renderer": "高级字幕渲染器",
    "tools": "媒体工具",
    "wheels": "环境安装包缓存",
    "licenses": "许可证与第三方材料",
}
_DIR_COMPONENTS = {
    "twobyteasr": "app",
    "scripts": "app",
    "workers": "app",
    "docs": "app",
    "lexicons": "app",
    "third_party": "app",
    "renderer": "app",       # own renderer code; node_modules/public are split below
    "assets": "app",         # small images/themes; fonts are split below
    "tools": "tools",
    "wheels": "wheels",
    "licenses": "licenses",
}
# Large, rarely changing sub-trees of otherwise app-owned folders.
_SUBTREE_COMPONENTS = (
    ("renderer/node_modules/", "renderer"),
    ("renderer/public/", "renderer"),
    ("assets/fonts/", "assets"),
)
_APP_ROOT_NAMES = {"2byteasr.exe", "base_library.zip", "license", UPDATER_EXE_NAME.lower()}
_APP_ROOT_SUFFIXES = (".py", ".md", ".json", ".txt")

# Ed25519 public keys trusted for update manifests (key id -> raw key, base64).
# The private key never enters the repository, the installer or a manifest.
TRUSTED_UPDATE_KEYS: dict[str, str] = {
    # 2026-10-11 release key; private half DPAPI-protected on the build machine.
    "21f1cb35659cfffd": "idoW/Krfikfe7JY22oXVK3BOJQuXW+Lo7yNbas/oozc=",
}

_SEMVER = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """A manifest, signature or archive is malformed or untrusted."""


# --------------------------------------------------------------------------
# Versions (Semantic Versioning 2.0 precedence, never string ordering)


@dataclass(frozen=True, order=False)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple = ()

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def __str__(self) -> str:
        core = f"{self.major}.{self.minor}.{self.patch}"
        return core + ("-" + ".".join(str(p) for p in self.prerelease) if self.prerelease else "")

    def _key(self):
        # A release sorts after every prerelease of the same core version.
        # Numeric identifiers sort numerically and before alphanumeric ones.
        pre = tuple((0, part, "") if isinstance(part, int) else (1, 0, part) for part in self.prerelease)
        return (self.major, self.minor, self.patch, 0 if self.prerelease else 1, pre)

    def __lt__(self, other: "Version") -> bool:
        return self._key() < other._key()

    def __le__(self, other: "Version") -> bool:
        return self._key() <= other._key()

    def __gt__(self, other: "Version") -> bool:
        return self._key() > other._key()

    def __ge__(self, other: "Version") -> bool:
        return self._key() >= other._key()


def parse_version(value: str) -> Version:
    match = _SEMVER.match(str(value or "").strip())
    if not match:
        raise ManifestError(f"无法识别版本号：{value!r}")
    parts = []
    for item in (match.group("pre") or "").split(".") if match.group("pre") else ():
        if item.isdigit():
            if len(item) > 1 and item.startswith("0"):
                raise ManifestError(f"版本号预发布段不能有前导零：{value!r}")
            parts.append(int(item))
        else:
            parts.append(item)
    return Version(int(match.group("major")), int(match.group("minor")), int(match.group("patch")), tuple(parts))


# --------------------------------------------------------------------------
# Components


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    sha256: str

    def as_list(self) -> list:
        return [self.path, self.size, self.sha256]


def normalize_relpath(value: str) -> str:
    """Validated forward-slash path relative to the install root."""
    text = str(value or "").replace("\\", "/")
    path = PurePosixPath(text)
    if (not text or text.startswith("/") or ":" in text or path.is_absolute()
            or any(part in ("", ".", "..") for part in path.parts) or text != path.as_posix()):
        raise ManifestError(f"不安全的程序文件路径：{value!r}")
    return text


def classify(relpath: str) -> str | None:
    """Component of one install-root path; None for preserved/meta/state files."""
    rel = normalize_relpath(relpath)
    lowered = rel.lower()
    if lowered in PRESERVED_FILES or lowered in META_FILES:
        return None
    parts = rel.split("/")
    if parts[0].lower() in STATE_DIRS:
        return None
    if len(parts) > 1:
        for prefix, component in _SUBTREE_COMPONENTS:
            if lowered.startswith(prefix):
                return component
        return _DIR_COMPONENTS.get(parts[0].lower(), "python-runtime")
    if lowered in _APP_ROOT_NAMES or lowered.endswith(_APP_ROOT_SUFFIXES):
        return "app"
    return "python-runtime"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def content_sha256(entries: Iterable[FileEntry]) -> str:
    ordered = sorted(entries, key=lambda item: item.path)
    seen: set[str] = set()
    digest = hashlib.sha256()
    for item in ordered:
        folded = item.path.casefold()
        if folded in seen:
            raise ManifestError(f"同一路径重复（Windows 不区分大小写）：{item.path}")
        seen.add(folded)
        digest.update(f"{item.path}\t{int(item.size)}\t{item.sha256}\n".encode("utf-8"))
    return digest.hexdigest()


def scan_payload(root: Path) -> dict[str, list[FileEntry]]:
    """Hash every program file of a payload, grouped by component."""
    root = Path(root)
    grouped: dict[str, list[FileEntry]] = {name: [] for name in COMPONENT_ORDER}
    for current, dirs, names in os.walk(root):
        dirs.sort()
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink():
                raise ManifestError(f"载荷不应包含符号链接：{path}")
            rel = path.relative_to(root).as_posix()
            component = classify(rel)
            if component is None:
                continue
            grouped[component].append(FileEntry(rel, path.stat().st_size, file_sha256(path)))
    return grouped


def component_record(entries: list[FileEntry], *, include_files: bool) -> dict:
    record = {
        "content_sha256": content_sha256(entries),
        "file_count": len(entries),
        "bytes": sum(item.size for item in entries),
    }
    if include_files:
        record["files"] = [item.as_list() for item in sorted(entries, key=lambda e: e.path)]
    return record


def build_installed_manifest(root: Path, *, version: str, build: Mapping | None = None) -> dict:
    parse_version(version)
    grouped = scan_payload(root)
    return {
        "schema": INSTALLED_SCHEMA,
        "product": PRODUCT,
        "app_id": APP_ID,
        "version": version,
        "platform": PLATFORM,
        "arch": ARCH,
        "build": dict(build or {}),
        "preserved_files": list(PRESERVED_FILES),
        "components": {name: component_record(grouped[name], include_files=True) for name in COMPONENT_ORDER},
    }


def entries_from_record(record: Mapping) -> list[FileEntry]:
    entries = []
    for row in record.get("files") or ():
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ManifestError("元件文件清单格式错误")
        path, size, sha = row
        if not isinstance(size, int) or size < 0 or not _SHA256.match(str(sha)):
            raise ManifestError(f"元件文件记录无效：{path!r}")
        entries.append(FileEntry(normalize_relpath(path), size, str(sha)))
    return entries


def validate_installed_manifest(payload: Mapping) -> dict:
    if not isinstance(payload, Mapping) or payload.get("schema") != INSTALLED_SCHEMA:
        raise ManifestError("已安装元件清单格式不受支持")
    if payload.get("app_id") != APP_ID:
        raise ManifestError("已安装元件清单不属于本程序")
    parse_version(str(payload.get("version")))
    components = payload.get("components")
    if not isinstance(components, Mapping):
        raise ManifestError("已安装元件清单缺少元件")
    for name, record in components.items():
        entries = entries_from_record(record)
        if content_sha256(entries) != record.get("content_sha256"):
            raise ManifestError(f"已安装元件清单内容哈希不一致：{name}")
        for item in entries:
            if classify(item.path) != name:
                raise ManifestError(f"文件不属于元件 {name}：{item.path}")
    return dict(payload)


def load_installed_manifest(install_root: Path) -> dict:
    path = Path(install_root) / COMPONENTS_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError("当前安装没有元件清单（0.6.5 之前的版本或手工复制的程序）") from exc
    except (OSError, ValueError) as exc:
        raise ManifestError(f"无法读取已安装元件清单：{exc}") from exc
    return validate_installed_manifest(payload)


def quick_component_intact(install_root: Path, record: Mapping) -> tuple[bool, str]:
    """Cheap presence/size check of an installed component (no hashing)."""
    root = Path(install_root)
    for item in entries_from_record(record):
        target = root / item.path
        try:
            size = target.stat().st_size
        except OSError:
            return False, f"缺少 {item.path}"
        if size != item.size:
            return False, f"大小不符 {item.path}"
    return True, ""


# --------------------------------------------------------------------------
# Environment and model contracts (informational for the update dialog)


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def environment_contracts(lock: Mapping) -> dict[str, str]:
    """Per-role digest of what a managed Python environment must contain."""
    shared = {"runtime": lock.get("runtime"), "managed_bootstrap": lock.get("managed_bootstrap")}
    contracts = {}
    for role, spec in sorted((lock.get("environments") or {}).items()):
        payload = {"role": role, "environment": spec, "python": (lock.get("python") or {}).get(role), **shared}
        contracts[role] = hashlib.sha256(_canonical(payload)).hexdigest()
    return contracts


def model_contracts(lock: Mapping) -> dict[str, str]:
    """Per-model digest of revision and required files (the download contract)."""
    contracts = {}
    for key, spec in sorted((lock.get("models") or {}).items()):
        contracts[key] = hashlib.sha256(_canonical(spec)).hexdigest()
    return contracts


# --------------------------------------------------------------------------
# Signatures


def key_id_for(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


def sign_manifest(manifest_bytes: bytes, private_raw: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    key = Ed25519PrivateKey.from_private_bytes(private_raw)
    public_raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    document = {
        "schema": SIGNATURE_SCHEMA,
        "algorithm": "ed25519",
        "key_id": key_id_for(public_raw),
        "signed_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "signature": base64.b64encode(key.sign(manifest_bytes)).decode("ascii"),
    }
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def verify_manifest_signature(manifest_bytes: bytes, signature_bytes: bytes,
                              trusted_keys: Mapping[str, str] | None = None) -> str:
    """Return the key id that signed ``manifest_bytes``; raise if untrusted."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    keys = TRUSTED_UPDATE_KEYS if trusted_keys is None else trusted_keys
    try:
        document = json.loads(signature_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ManifestError("更新清单签名文件无法解析") from exc
    if not isinstance(document, Mapping) or document.get("schema") != SIGNATURE_SCHEMA \
            or document.get("algorithm") != "ed25519":
        raise ManifestError("更新清单签名格式不受支持")
    key_id = str(document.get("key_id") or "")
    encoded = keys.get(key_id)
    if not encoded:
        raise ManifestError(f"更新清单由未受信任的密钥签名（{key_id or '无'}）")
    try:
        signature = base64.b64decode(str(document.get("signature") or ""), validate=True)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded)).verify(signature, manifest_bytes)
    except (InvalidSignature, ValueError) as exc:
        raise ManifestError("更新清单签名校验失败，已拒绝") from exc
    return key_id


# --------------------------------------------------------------------------
# Update manifest


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str
    urls: tuple[str, ...]


@dataclass(frozen=True)
class RemoteComponent:
    name: str
    content_sha256: str
    file_count: int
    bytes: int
    archive: Asset | None


@dataclass(frozen=True)
class UpdateManifest:
    version: Version
    tag: str
    channel: str
    release_page: str
    published: str
    notes: Mapping[str, str]
    setup: Asset | None
    components: Mapping[str, RemoteComponent]
    environments: Mapping[str, str]
    models: Mapping[str, str]
    build: Mapping
    raw: Mapping = field(repr=False, compare=False, default_factory=dict)

    def note_for(self, language: str) -> str:
        return str(self.notes.get(language) or self.notes.get("zh") or "").strip()


def _https(url: str, *, allow_http_local: bool = False) -> str:
    text = str(url or "")
    if text.startswith("https://"):
        return text
    if allow_http_local and re.match(r"^http://(127\.0\.0\.1|localhost)(:\d+)?/", text):
        return text
    raise ManifestError(f"不接受的下载地址：{text[:80]!r}")


def _asset(value, *, allow_http_local: bool) -> Asset | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ManifestError("附件记录格式错误")
    name = str(value.get("name") or "")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ManifestError(f"附件名称无效：{name!r}")
    size, sha = value.get("size"), str(value.get("sha256") or "")
    if not isinstance(size, int) or size <= 0 or not _SHA256.match(sha):
        raise ManifestError(f"附件大小或 SHA-256 无效：{name}")
    urls = tuple(_https(u, allow_http_local=allow_http_local) for u in value.get("urls") or ())
    if not urls:
        raise ManifestError(f"附件没有下载地址：{name}")
    return Asset(name, size, sha, urls)


def parse_update_manifest(data: bytes, *, allow_http_local: bool = False) -> UpdateManifest:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ManifestError("更新清单不是有效 JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != UPDATE_SCHEMA:
        raise ManifestError("更新清单格式不受支持（可能需要先用安装包升级）")
    if payload.get("product") != PRODUCT or payload.get("app_id") != APP_ID:
        raise ManifestError("更新清单不属于本程序")
    if payload.get("platform") != PLATFORM or payload.get("arch") != ARCH:
        raise ManifestError("更新清单不适用于本平台")
    version = parse_version(str(payload.get("version")))
    channel = str(payload.get("channel") or "")
    if not channel:
        raise ManifestError("更新清单缺少渠道")
    components = {}
    for name, record in (payload.get("components") or {}).items():
        if name not in COMPONENT_ORDER or not isinstance(record, Mapping):
            raise ManifestError(f"未知元件：{name!r}")
        content = str(record.get("content_sha256") or "")
        if not _SHA256.match(content):
            raise ManifestError(f"元件内容哈希无效：{name}")
        components[name] = RemoteComponent(
            name, content, int(record.get("file_count") or 0), int(record.get("bytes") or 0),
            _asset(record.get("archive"), allow_http_local=allow_http_local))
    missing = [name for name in COMPONENT_ORDER if name not in components]
    if missing:
        raise ManifestError("更新清单缺少元件：" + ", ".join(missing))
    notes = payload.get("notes") or {}
    return UpdateManifest(
        version=version,
        tag=str(payload.get("tag") or ""),
        channel=channel,
        release_page=_https(str(payload.get("release_page") or "https://github.com/")),
        published=str(payload.get("published") or ""),
        notes={str(k): str(v) for k, v in notes.items()} if isinstance(notes, Mapping) else {},
        setup=_asset(payload.get("setup"), allow_http_local=allow_http_local),
        components=components,
        environments={str(k): str(v) for k, v in (payload.get("environments") or {}).items()},
        models={str(k): str(v) for k, v in (payload.get("models") or {}).items()},
        build=dict(payload.get("build") or {}),
        raw=payload,
    )


def read_archive_index(data: bytes, expected_content: str, component: str) -> list[FileEntry]:
    """Validate the file list stored inside a component archive."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ManifestError("元件包索引无法解析") from exc
    if payload.get("component") != component or payload.get("content_sha256") != expected_content:
        raise ManifestError(f"元件包与清单不一致：{component}")
    entries = entries_from_record(payload)
    if content_sha256(entries) != expected_content:
        raise ManifestError(f"元件包文件清单哈希不一致：{component}")
    for item in entries:
        if classify(item.path) != component:
            raise ManifestError(f"元件包含不属于 {component} 的路径：{item.path}")
    return entries


__all__ = [name for name in globals() if not name.startswith("_")]
