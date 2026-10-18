# SPDX-License-Identifier: GPL-3.0-only
"""In-app update: signed feed, component plan, verified download and hand-off.

Flow (all network and disk work runs off the GUI thread):

1. ``check_for_update`` fetches the release's signed update manifest
   (stable: ``releases/latest/download``; prerelease: the releases API), checks
   the Ed25519 signature against the embedded keys and compares versions with
   Semantic Versioning precedence.  Results are cached; automatic checks run at
   most once a day and back off after failures, so no network is needed for the
   program to work.
2. ``plan_update`` compares the manifest with the installed component list
   (``2byteasr_components.json``).  Only components whose content hash differs,
   or whose installed files are missing, are downloaded.  Environments and
   models keep their own contracts and are never re-downloaded here.
3. ``prepare_update`` downloads those archives (resume when the server allows
   ranges, restart cleanly when it does not, retries with back-off), verifies
   every archive and every extracted file, and writes a staging folder plus a
   helper plan.  Everything is pinned to the one manifest picked in step 1.
4. After the user saved work and agreed to quit, ``launch_update_helper`` starts
   the separate updater (``2ByteASRUpdater.exe``) from a copy outside the
   install folder.  It replaces files transactionally and rolls back on error.

When the install has no component list (versions before 0.6.5) or a needed
component has no separate archive, the fallback is the release Setup: the
full program package that keeps environments, models and user data.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from twobyteasr.update_manifest import (
    ARCHIVE_INDEX_NAME,
    COMPONENT_LABELS,
    COMPONENT_ORDER,
    COMPONENTS_FILENAME,
    INSTALLED_SCHEMA,
    PRESERVED_FILES,
    UPDATE_MANIFEST_NAME,
    UPDATE_SIGNATURE_NAME,
    UPDATER_EXE_NAME,
    APP_ID,
    ARCH,
    PLATFORM,
    PRODUCT,
    FileEntry,
    ManifestError,
    UpdateManifest,
    component_record,
    content_sha256,
    entries_from_record,
    environment_contracts,
    file_sha256,
    load_installed_manifest,
    model_contracts,
    parse_update_manifest,
    parse_version,
    quick_component_intact,
    read_archive_index,
    verify_manifest_signature,
)

REPOSITORY = "NOTBAD314/2ByteASR"
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases"
STABLE_FEED = f"https://github.com/{REPOSITORY}/releases/latest/download/{UPDATE_MANIFEST_NAME}"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=20"
# Download fallbacks for networks where github.com is slow.  Manifests are
# signed and archives hashed, so a mirror can delay but not alter an update.
# Tried in order after github.com and GitCode.  gh-proxy.org (2026-10-17) is
# last: identical bytes from a Japan exit, not yet measured on a mainland line;
# it sometimes ignores Range, and _download_once then restarts from zero.
GITHUB_MIRRORS = ("https://ghfast.top/", "https://ghproxy.net/", "https://gh-proxy.org/")
USER_AGENT = "2ByteASR-updater"
AUTO_CHECK_INTERVAL = 24 * 3600
MANUAL_RECHECK_SECONDS = 60
MAX_BACKOFF = 24 * 3600
CONNECT_TIMEOUT = 6
READ_TIMEOUT = 20

FEED_ENV = "TWOBYTEASR_UPDATE_FEED"          # explicit manifest URL (QA/local feeds)
CHANNEL_ENV = "TWOBYTEASR_UPDATE_CHANNEL"    # override the installed channel
STATE_ENV = "TWOBYTEASR_UPDATE_STATE_DIR"    # override the state folder
DISABLE_ENV = "TWOBYTEASR_DISABLE_UPDATE_CHECK"
CONFIRM_ENV = "TWOBYTEASR_UPDATE_CONFIRM"
QA_AUTO_ENV = "TWOBYTEASR_UPDATE_AUTO_IN_QA"
AUTO_DELAY_ENV = "TWOBYTEASR_UPDATE_AUTO_DELAY_MS"
AUTO_DELAY_MS = 30_000


def automatic_check_delay_ms() -> int:
    try:
        return max(0, int(os.environ.get(AUTO_DELAY_ENV, "") or AUTO_DELAY_MS))
    except ValueError:
        return AUTO_DELAY_MS


class UpdateError(RuntimeError):
    """The update could not be checked, downloaded, or safely prepared."""


class UpdateCancelled(UpdateError):
    """The user cancelled the download."""


# --------------------------------------------------------------------------
# Locations


def install_root() -> Path:
    from twobyteasr.runtime_paths import detect_install_root
    return detect_install_root()


def version_path(root: Path | None = None) -> Path:
    return (root or install_root()) / "2byteasr_version.json"


def state_root() -> Path:
    override = os.environ.get(STATE_ENV, "").strip()
    if override:
        return Path(override)
    from twobyteasr.runtime_paths import user_data_root
    return user_data_root() / "updates"


def _version_payload(path: Path | None = None) -> dict:
    try:
        payload = json.loads((path or version_path()).read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def normalize_version(value: str) -> str:
    try:
        return str(parse_version(value))
    except ManifestError as exc:
        raise UpdateError(str(exc)) from exc


def current_version(path: Path | None = None) -> str:
    try:
        return normalize_version(_version_payload(path).get("version", ""))
    except UpdateError:
        return "0.0.0"


def installed_channel(path: Path | None = None) -> str:
    override = os.environ.get(CHANNEL_ENV, "").strip()
    if override:
        return override
    value = str(_version_payload(path).get("channel") or "stable").strip().lower()
    return "stable" if value in ("stable", "release", "") else "prerelease"


def automatic_checks_allowed() -> bool:
    if os.environ.get(DISABLE_ENV, "").strip() in ("1", "true", "yes"):
        return False
    if os.environ.get(QA_AUTO_ENV, "").strip() == "1":
        return True  # explicit QA opt-in (startup/responsiveness measurement with a test feed)
    # Acceptance audits, tests and QA profiles never phone home on their own.
    for name in ("TWOBYTEASR_ACCEPTANCE_DIR", "TWOBYTEASR_TEST_ROOT", "PYTEST_CURRENT_TEST"):
        if os.environ.get(name):
            return False
    return True


# --------------------------------------------------------------------------
# Results


@dataclass(frozen=True)
class ComponentAction:
    name: str
    reason: str            # "changed" | "repair" | "reuse"
    download_bytes: int     # archive bytes still to download (0 when cached/reused)
    archive_bytes: int
    installed_bytes: int
    detail: str = ""

    @property
    def label(self) -> str:
        return COMPONENT_LABELS.get(self.name, self.name)


@dataclass(frozen=True)
class UpdatePlan:
    mode: str                               # "components" | "setup" | "none"
    actions: tuple[ComponentAction, ...]
    download_bytes: int
    setup_bytes: int
    fallback_reason: str = ""
    environment_changes: tuple[str, ...] = ()
    model_changes: tuple[str, ...] = ()

    @property
    def downloads(self) -> tuple[ComponentAction, ...]:
        return tuple(a for a in self.actions if a.reason != "reuse")

    @property
    def reused(self) -> tuple[ComponentAction, ...]:
        return tuple(a for a in self.actions if a.reason == "reuse")


@dataclass(frozen=True)
class UpdateCheck:
    current_version: str
    channel: str
    manifest: UpdateManifest | None
    newer: bool
    plan: UpdatePlan | None
    source: str
    checked_at: float
    manifest_sha256: str = ""
    from_cache: bool = False

    @property
    def latest_version(self) -> str:
        return str(self.manifest.version) if self.manifest else self.current_version

    @property
    def release_url(self) -> str:
        return self.manifest.release_page if self.manifest else RELEASE_PAGE

    @property
    def installer_url(self) -> str:
        return self.manifest.setup.urls[0] if self.manifest and self.manifest.setup else self.release_url

    @property
    def can_self_update(self) -> bool:
        return bool(self.newer and self.plan and self.plan.mode == "components")


# --------------------------------------------------------------------------
# HTTP


def _http_get(url: str, *, headers: Mapping[str, str] | None = None, stream: bool = False,
              timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), request_get: Callable | None = None):
    import requests
    getter = request_get or requests.get
    merged = {"User-Agent": USER_AGENT}
    merged.update(headers or {})
    return getter(url, headers=merged, timeout=timeout, stream=stream, allow_redirects=True)


def _candidates(url: str) -> tuple[str, ...]:
    if url.startswith("https://github.com/"):
        return (url,) + tuple(prefix + url for prefix in GITHUB_MIRRORS)
    return (url,)


def _fetch_bytes(url: str, *, request_get: Callable | None, limit: int = 4 * 1024 * 1024) -> bytes:
    errors = []
    for attempt, candidate in enumerate(_candidates(url)):
        try:
            response = _http_get(candidate, request_get=request_get)
            status = int(getattr(response, "status_code", 200))
            if status == 404:
                raise UpdateError("发布中没有更新清单（404）")
            if status >= 400:
                raise UpdateError(f"HTTP {status}")
            data = response.content
            if len(data) > limit:
                raise UpdateError("响应过大")
            return data
        except UpdateError as exc:
            errors.append(f"{candidate.split('/')[2]}：{exc}")
            if "404" in str(exc) and attempt == 0:
                break  # the release exists but has no manifest: mirrors cannot help
        except Exception as exc:  # noqa: BLE001 - network errors vary by stack
            errors.append(f"{candidate.split('/')[2]}：{' '.join(str(exc).split())[:120]}")
    raise UpdateError("无法取得更新信息。\n" + "\n".join(errors))


def _prerelease_feed(request_get: Callable | None) -> str:
    response = _http_get(RELEASES_API, headers={"Accept": "application/vnd.github+json"},
                         request_get=request_get)
    status = int(getattr(response, "status_code", 200))
    if status in (403, 429):
        reset = getattr(response, "headers", {}).get("X-RateLimit-Reset", "")
        raise UpdateError(f"GitHub API 暂时限流（HTTP {status}），稍后自动重试。{reset}")
    if status >= 400:
        raise UpdateError(f"GitHub API HTTP {status}")
    best = None
    for release in response.json():
        if not isinstance(release, dict) or release.get("draft"):
            continue
        try:
            version = parse_version(str(release.get("tag_name") or ""))
        except ManifestError:
            continue
        asset = next((a for a in release.get("assets") or ()
                      if isinstance(a, dict) and a.get("name") == UPDATE_MANIFEST_NAME), None)
        if asset and (best is None or version > best[0]):
            best = (version, str(asset.get("browser_download_url") or ""))
    if not best or not best[1]:
        raise UpdateError("没有找到带更新清单的发布")
    return best[1]


# --------------------------------------------------------------------------
# Cache and back-off


def _cache_path() -> Path:
    return state_root() / "check.json"


def _read_cache() -> dict:
    try:
        payload = json.loads(_cache_path().read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(payload: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass  # a read-only profile must not break the program


def automatic_check_due(now: float | None = None) -> bool:
    if not automatic_checks_allowed():
        return False
    now = time.time() if now is None else now
    cache = _read_cache()
    if now < float(cache.get("next_attempt_at") or 0):
        return False
    return now - float(cache.get("checked_at") or 0) >= AUTO_CHECK_INTERVAL


def _record_failure(error: str) -> None:
    cache = _read_cache()
    failures = int(cache.get("failures") or 0) + 1
    delay = min(MAX_BACKOFF, 3600 * (2 ** (failures - 1)))
    cache.update(failures=failures, last_error=error[:400], last_failure_at=time.time(),
                 next_attempt_at=time.time() + delay * (0.85 + 0.3 * random.random()))
    _write_cache(cache)


# --------------------------------------------------------------------------
# Check


def check_for_update(*, request_get: Callable | None = None, use_cache: bool = False,
                     root: Path | None = None) -> UpdateCheck:
    """Fetch, verify and plan.  ``use_cache`` returns a recent cached result."""
    root = root or install_root()
    current = current_version(version_path(root))
    channel = installed_channel(version_path(root))
    cache = _read_cache()
    feed = os.environ.get(FEED_ENV, "").strip()
    if use_cache and cache.get("manifest") and time.time() - float(cache.get("checked_at") or 0) < MANUAL_RECHECK_SECONDS:
        try:
            return _evaluate(bytes.fromhex(cache["manifest"]), bytes.fromhex(cache["signature"]),
                             current, channel, cache.get("source", ""), float(cache["checked_at"]),
                             root, from_cache=True, allow_http_local=bool(feed))
        except (UpdateError, ManifestError, KeyError, ValueError):
            pass
    try:
        if feed:
            manifest_url = feed
        elif channel == "stable":
            manifest_url = STABLE_FEED
        elif channel == "prerelease":
            manifest_url = _prerelease_feed(request_get)
        else:
            raise UpdateError(f"渠道 {channel} 没有配置更新地址")
        manifest_bytes = _fetch_bytes(manifest_url, request_get=request_get)
        # The signature sits next to the manifest under the same pinned name.
        signature_bytes = _fetch_bytes(manifest_url + UPDATE_SIGNATURE_NAME[len(UPDATE_MANIFEST_NAME):],
                                       request_get=request_get, limit=64 * 1024)
        result = _evaluate(manifest_bytes, signature_bytes, current, channel, manifest_url, time.time(),
                           root, allow_http_local=bool(feed))
    except (UpdateError, ManifestError) as exc:
        _record_failure(str(exc))
        raise UpdateError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - report network stack errors compactly
        _record_failure(str(exc))
        raise UpdateError(" ".join(str(exc).split())[:300] or exc.__class__.__name__) from exc
    _write_cache({"checked_at": result.checked_at, "source": manifest_url, "failures": 0,
                  "next_attempt_at": 0, "manifest": manifest_bytes.hex(), "signature": signature_bytes.hex(),
                  "latest_version": result.latest_version, "current_version": current})
    return result


def _evaluate(manifest_bytes: bytes, signature_bytes: bytes, current: str, channel: str, source: str,
              checked_at: float, root: Path, *, from_cache: bool = False,
              allow_http_local: bool = False) -> UpdateCheck:
    verify_manifest_signature(manifest_bytes, signature_bytes)
    manifest = parse_update_manifest(manifest_bytes, allow_http_local=allow_http_local)
    if manifest.channel != channel and not (channel == "prerelease" and manifest.channel == "stable"):
        raise UpdateError(f"更新清单渠道 {manifest.channel} 与本机 {channel} 不符，已忽略")
    newer = manifest.version > parse_version(current)
    plan = plan_update(manifest, root) if newer else None
    return UpdateCheck(current, channel, manifest, newer, plan, source, checked_at,
                       hashlib.sha256(manifest_bytes).hexdigest(), from_cache)


# --------------------------------------------------------------------------
# Plan


def _installed_lock(root: Path) -> dict:
    try:
        return json.loads((root / "dependencies.lock.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def plan_update(manifest: UpdateManifest, root: Path | None = None) -> UpdatePlan:
    root = root or install_root()
    setup_bytes = manifest.setup.size if manifest.setup else 0
    lock = _installed_lock(root)
    env_now, models_now = environment_contracts(lock), model_contracts(lock)
    env_changes = tuple(sorted(r for r, h in manifest.environments.items() if env_now.get(r) != h))
    model_changes = tuple(sorted(k for k, h in manifest.models.items() if models_now.get(k) and models_now.get(k) != h))
    try:
        installed = load_installed_manifest(root)
    except ManifestError as exc:
        return UpdatePlan("setup", (), setup_bytes, setup_bytes, str(exc), env_changes, model_changes)
    actions = []
    fallback = ""
    for name in COMPONENT_ORDER:
        remote = manifest.components[name]
        local = installed["components"].get(name)
        if local and local.get("content_sha256") == remote.content_sha256:
            intact, detail = quick_component_intact(root, local)
            if intact:
                actions.append(ComponentAction(name, "reuse", 0, 0, remote.bytes))
                continue
            reason = "repair"
        else:
            reason, detail = "changed", ""
        if remote.archive is None:
            fallback = fallback or f"{COMPONENT_LABELS.get(name, name)}需要更新，但此版本没有单独的元件包"
            actions.append(ComponentAction(name, reason, 0, 0, remote.bytes, detail))
            continue
        cached = _cached_archive(remote.archive.name, remote.archive.sha256)
        actions.append(ComponentAction(name, reason, 0 if cached else remote.archive.size,
                                       remote.archive.size, remote.bytes, detail))
    if fallback:
        return UpdatePlan("setup", tuple(actions), setup_bytes, setup_bytes, fallback, env_changes, model_changes)
    return UpdatePlan("components", tuple(actions), sum(a.download_bytes for a in actions), setup_bytes, "",
                      env_changes, model_changes)


# --------------------------------------------------------------------------
# Download


def _downloads_dir() -> Path:
    return state_root() / "downloads"


def _verified_marker(path: Path) -> Path:
    return path.with_name(path.name + ".verified")


def _cached_archive(name: str, sha256: str) -> bool:
    path = _downloads_dir() / name
    marker = _verified_marker(path)
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
        return record.get("sha256") == sha256 and path.is_file() and path.stat().st_size == record.get("size")
    except (OSError, ValueError):
        return False


def _check_free_space(folder: Path, needed: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if free < needed:
        raise UpdateError(f"磁盘空间不足：需要约 {needed / 1048576:.0f} MB，{folder.anchor} 可用 {free / 1048576:.0f} MB。")


def download_asset(asset, folder: Path, *, progress: Callable[[int, int], None] | None = None,
                   cancel: threading.Event | None = None, request_get: Callable | None = None,
                   attempts_per_url: int = 3, sleep: Callable[[float], None] = time.sleep) -> Path:
    """Download one asset with resume, retries and SHA-256 verification."""
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / asset.name
    if _cached_archive(asset.name, asset.sha256):
        if progress:
            progress(asset.size, asset.size)
        return output
    partial = output.with_name(output.name + ".part")
    errors = []
    for url in [c for base in asset.urls for c in _candidates(base)]:
        for attempt in range(attempts_per_url):
            if cancel is not None and cancel.is_set():
                raise UpdateCancelled("已取消下载")
            try:
                _download_once(url, partial, asset, progress=progress, cancel=cancel, request_get=request_get)
                actual = file_sha256(partial)
                if partial.stat().st_size != asset.size or actual != asset.sha256:
                    partial.unlink(missing_ok=True)  # never resume from a bad file
                    raise UpdateError(f"校验不符（{actual[:12]}…），已丢弃")
                os.replace(partial, output)
                _verified_marker(output).write_text(json.dumps({"sha256": asset.sha256, "size": asset.size}),
                                                    encoding="utf-8")
                return output
            except UpdateCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - retry with back-off, then next mirror
                errors.append(f"{url.split('/')[2]}：{' '.join(str(exc).split())[:160]}")
                if attempt + 1 < attempts_per_url:
                    sleep(min(8.0, 1.0 * (2 ** attempt)))
    raise UpdateError(f"{asset.name} 下载失败。\n" + "\n".join(errors[-6:]))


def _download_once(url: str, partial: Path, asset, *, progress, cancel, request_get) -> None:
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > asset.size:
        partial.unlink()
        offset = 0
    if offset == asset.size:
        return  # complete; the caller verifies it
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    response = _http_get(url, headers=headers, stream=True, timeout=(CONNECT_TIMEOUT, 45),
                         request_get=request_get)
    with response:
        status = int(getattr(response, "status_code", 200))
        if status == 416:
            partial.unlink(missing_ok=True)
            raise UpdateError("服务器拒绝续传范围，将重新下载")
        if status >= 400:
            raise UpdateError(f"HTTP {status}")
        mode = "ab"
        if offset and status == 206:
            content_range = str(response.headers.get("Content-Range", ""))
            if not content_range.startswith(f"bytes {offset}-"):
                mode, offset = "wb", 0
                partial.unlink(missing_ok=True)
                raise UpdateError("续传范围不一致，将重新下载")
        elif offset:
            mode, offset = "wb", 0  # server ignored Range: start over from zero
        received = offset
        with partial.open(mode) as stream:
            for block in response.iter_content(chunk_size=1024 * 1024):
                if cancel is not None and cancel.is_set():
                    raise UpdateCancelled("已取消下载")
                if not block:
                    continue
                stream.write(block)
                received += len(block)
                if received > asset.size:
                    raise UpdateError("下载内容超过清单大小")
                if progress:
                    progress(received, asset.size)


# --------------------------------------------------------------------------
# Staging


@dataclass(frozen=True)
class PreparedUpdate:
    version: str
    from_version: str
    staging: Path
    plan_path: Path
    helper: Path
    replace: tuple[str, ...]
    remove: tuple[str, ...]
    downloaded_bytes: int = 0
    reused_components: tuple[str, ...] = ()
    record: dict = field(default_factory=dict)


def _safe_extract(archive: Path, component: str, expected_content: str, target: Path) -> list[FileEntry]:
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)):
            raise UpdateError(f"元件包有重复成员：{archive.name}")
        try:
            index = read_archive_index(bundle.read(ARCHIVE_INDEX_NAME), expected_content, component)
        except KeyError as exc:
            raise UpdateError(f"元件包缺少索引：{archive.name}") from exc
        except ManifestError as exc:
            raise UpdateError(str(exc)) from exc
        expected = {item.path: item for item in index}
        members = [n for n in names if n != ARCHIVE_INDEX_NAME and not n.endswith("/")]
        if set(members) != set(expected):
            raise UpdateError(f"元件包内容与索引不一致：{archive.name}")
        for name in members:
            item = expected[name]
            destination = (target / name).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise UpdateError(f"元件包路径越界：{name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with bundle.open(name) as source, destination.open("wb") as sink:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    sink.write(block)
                    digest.update(block)
                    size += len(block)
            if size != item.size or digest.hexdigest() != item.sha256:
                raise UpdateError(f"解压后文件校验不符：{name}")
    return index


def prepare_update(check: UpdateCheck, *, progress: Callable[[str, int, int], None] | None = None,
                   cancel: threading.Event | None = None, request_get: Callable | None = None,
                   root: Path | None = None, wait_pid: int | None = None) -> PreparedUpdate:
    """Download and verify everything one manifest needs; write the helper plan."""
    root = root or install_root()
    if not check.can_self_update or check.manifest is None or check.plan is None:
        raise UpdateError("这次更新需要使用完整安装包。")
    manifest = check.manifest
    installed = load_installed_manifest(root)
    downloads = [a for a in check.plan.actions if a.reason != "reuse"]
    total_download = sum(manifest.components[a.name].archive.size for a in downloads
                         if not _cached_archive(manifest.components[a.name].archive.name,
                                                manifest.components[a.name].archive.sha256))
    # Short folder names keep the deepest renderer file below the 260-character
    # Windows path limit inside the staging copy as well.
    staging = state_root() / "s" / check.manifest_sha256[:12]
    extracted_bytes = sum(manifest.components[a.name].bytes for a in downloads)
    _check_free_space(state_root(), total_download + extracted_bytes + 64 * 1024 * 1024)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    done = 0
    new_components: dict[str, dict] = {}
    replace: list[str] = []
    remove: list[str] = []
    for action in downloads:
        remote = manifest.components[action.name]
        base = done

        def report(received, total, _name=action.name, _base=base):
            if progress:
                progress(_name, _base + received, max(total_download, 1))

        archive = download_asset(remote.archive, _downloads_dir(), progress=report, cancel=cancel,
                                 request_get=request_get)
        if not _cached_archive(remote.archive.name, remote.archive.sha256):
            raise UpdateError(f"{remote.archive.name} 未通过校验")
        done += remote.archive.size if action.download_bytes else 0
        entries = _safe_extract(archive, action.name, remote.content_sha256, staging)
        new_components[action.name] = component_record(entries, include_files=True)
        old = {item.path: item for item in entries_from_record(installed["components"].get(action.name) or {})}
        new_paths = {item.path for item in entries}
        for item in entries:
            previous = old.get(item.path)
            target = root / item.path
            current_size = target.stat().st_size if target.is_file() else -1
            if previous != item or current_size != item.size:
                replace.append(item.path)
        remove.extend(sorted(path for path in old if path not in new_paths))
    for name in COMPONENT_ORDER:
        if name not in new_components:
            record = installed["components"].get(name)
            if record is None or record.get("content_sha256") != manifest.components[name].content_sha256:
                raise UpdateError(f"元件 {name} 状态不一致，请改用完整安装包。")
            new_components[name] = record
    for name, record in new_components.items():
        if content_sha256(entries_from_record(record)) != manifest.components[name].content_sha256:
            raise UpdateError(f"元件 {name} 内容与更新清单不一致")
    new_manifest = {
        "schema": INSTALLED_SCHEMA, "product": PRODUCT, "app_id": APP_ID, "version": str(manifest.version),
        "platform": PLATFORM, "arch": ARCH, "build": dict(manifest.build), "preserved_files": list(PRESERVED_FILES),
        "components": {name: new_components[name] for name in COMPONENT_ORDER},
    }
    (staging / COMPONENTS_FILENAME).write_text(json.dumps(new_manifest, ensure_ascii=False), encoding="utf-8")
    helper_source = staging / UPDATER_EXE_NAME if (staging / UPDATER_EXE_NAME).is_file() else root / UPDATER_EXE_NAME
    if not helper_source.is_file():
        raise UpdateError("更新程序缺失，请改用完整安装包。")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    helper = state_root() / "helper" / f"2ByteASRUpdater-{stamp}.exe"
    helper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(helper_source, helper)
    plan_path = state_root() / "plans" / f"plan-{stamp}.txt"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "2BYTEASR-UPDATE-PLAN\t1",
        f"install_root\t{root}",
        f"staging_root\t{staging}",
        f"from_version\t{check.current_version}",
        f"to_version\t{manifest.version}",
        f"wait_pid\t{int(wait_pid if wait_pid is not None else os.getpid())}",
        "restart\t1",
        "confirm_seconds\t150",
        f"log\t{state_root() / 'update-helper.log'}",
        f"result\t{state_root() / 'last-result.json'}",
    ]
    lines += [f"REPLACE\t{rel}" for rel in replace]
    lines += [f"REMOVE\t{rel}" for rel in remove]
    lines.append(f"MANIFEST\t{COMPONENTS_FILENAME}")
    lines.append(f"END\t{len(replace) + len(remove) + 1}")
    plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    record = {"version": str(manifest.version), "from": check.current_version, "staging": str(staging),
              "plan": str(plan_path), "helper": str(helper), "replace": len(replace), "remove": len(remove),
              "components": [a.name for a in downloads], "download_bytes": done,
              "prepared_at": time.time(), "manifest_sha256": check.manifest_sha256}
    (state_root() / "prepared.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return PreparedUpdate(str(manifest.version), check.current_version, staging, plan_path, helper,
                          tuple(replace), tuple(remove), done, tuple(a.name for a in check.plan.reused), record)


def launch_update_helper(prepared: PreparedUpdate, *, wait_pid: int | None = None) -> subprocess.Popen:
    """Start the detached updater from outside the install folder."""
    if wait_pid is not None:
        text = prepared.plan_path.read_text(encoding="utf-8")
        lines = [f"wait_pid\t{int(wait_pid)}" if line.startswith("wait_pid\t") else line
                 for line in text.splitlines()]
        prepared.plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [str(prepared.helper), "--apply", str(prepared.plan_path)]
    detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    environment = {k: v for k, v in os.environ.items() if k != CONFIRM_ENV}
    for flags in (detached | 0x01000000, detached):  # try CREATE_BREAKAWAY_FROM_JOB first
        try:
            return subprocess.Popen(command, cwd=str(prepared.helper.parent), close_fds=True, env=environment,
                                    creationflags=flags if os.name == "nt" else 0)
        except OSError:
            continue
    raise UpdateError("无法启动更新程序。")


# --------------------------------------------------------------------------
# After restart


def confirm_started(version: str | None = None) -> bool:
    """Called once the new program is interactive; tells the helper to keep it."""
    target = os.environ.pop(CONFIRM_ENV, "").strip()
    if not target:
        return False
    try:
        Path(target).write_text(json.dumps({"version": version or current_version(), "pid": os.getpid(),
                                            "at": time.time()}), encoding="utf-8")
        return True
    except OSError:
        return False


def last_result() -> dict:
    try:
        payload = json.loads((state_root() / "last-result.json").read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def cleanup_after_update() -> list[str]:
    """Remove staging and finished downloads once the installed version is current."""
    removed = []
    prepared = state_root() / "prepared.json"
    try:
        record = json.loads(prepared.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    if record and record.get("version") != current_version():
        return removed  # prepared but not applied yet: keep for the next attempt
    for name in ("s", "helper", "plans", "downloads"):
        folder = state_root() / name
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(name)
    prepared.unlink(missing_ok=True)
    return removed


def format_bytes(value: int) -> str:
    if value >= 1024 ** 3:
        return f"{value / 1024 ** 3:.2f} GB"
    if value >= 1024 ** 2:
        return f"{value / 1024 ** 2:.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} B"


__all__ = [
    "RELEASE_PAGE", "UpdateCancelled", "UpdateCheck", "UpdateError", "UpdatePlan", "PreparedUpdate",
    "automatic_check_delay_ms", "automatic_check_due", "automatic_checks_allowed", "check_for_update", "cleanup_after_update",
    "confirm_started", "current_version", "download_asset", "format_bytes", "installed_channel",
    "last_result", "launch_update_helper", "normalize_version", "plan_update", "prepare_update",
]
