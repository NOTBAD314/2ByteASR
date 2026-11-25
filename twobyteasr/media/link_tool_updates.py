"""Versioned Windows download tools from the application's signed tools component."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid
import zipfile

from ..runtime_paths import get_runtime_paths
from ..storage.atomic_files import write_text_atomic
from .link_manifest import sha256

_UPDATE_LOCK = threading.Lock()
_COMPONENT = "tools"
_RECEIPT_NAMES = ("release.json", "release.sig", "index.json")
_ID = re.compile(r"[a-f0-9]{16}-[a-f0-9]{8}")


def _store():
    return get_runtime_paths().managed_runtime_root / "link-toolsets"


def _state(store):
    try:
        data = json.loads((store / "active.json").read_bytes())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _record(store, active, previous):
    write_text_atomic(store / "active.json", json.dumps({"active": active, "previous": previous}))


def _parse(data, signature):
    from ..app.update_manifest import parse_update_manifest, verify_manifest_signature
    verify_manifest_signature(data, signature)
    release = parse_update_manifest(data)
    if release.channel != "stable" or _COMPONENT not in release.components:
        raise ValueError("缺少可验证的 Windows 下载工具清单。")
    return release, release.components[_COMPONENT]


def _verified_tools(directory, *, check_all=True):
    from ..app.update_manifest import read_archive_index
    from .link_tools import probe_tool_versions
    manifest, signature, index = ((directory / name).read_bytes() for name in _RECEIPT_NAMES)
    release, component = _parse(manifest, signature)
    entries = read_archive_index(index, component.content_sha256, _COMPONENT)
    if len(entries) != component.file_count or sum(item.size for item in entries) != component.bytes:
        raise ValueError("下载工具的文件范围与签名清单不符。")
    tools = directory / "tools"
    yt_dlp = tools / "yt-dlp/yt-dlp.exe"
    records = {item.path: item for item in entries}
    probe_paths = (yt_dlp, tools / "node/node.exe", tools / "ffmpeg/bin/ffmpeg.exe",
                   tools / "ffmpeg/bin/ffprobe.exe")
    wanted = {path.relative_to(directory).as_posix() for path in probe_paths}
    if wanted - records.keys():
        raise ValueError("工具更新包缺少下载或媒体组件。")
    for item in entries:
        if not check_all and item.path not in wanted:
            continue
        target = (directory / item.path).resolve()
        if (not target.is_relative_to(directory.resolve()) or not target.is_file()
                or target.stat().st_size != item.size or sha256(target) != item.sha256):
            raise ValueError("下载工具的文件校验失败。")
    result = probe_tool_versions(yt_dlp, directory)
    result["toolset"] = component.content_sha256
    result["release"] = str(release.version)
    result["sha256"] = records[yt_dlp.relative_to(directory).as_posix()].sha256
    return result


def active_tools():
    if os.name != "nt":
        return None
    store = _store()
    key = _state(store).get("active", "")
    if not isinstance(key, str) or not _ID.fullmatch(key):
        return None
    try:
        return _verified_tools(store / key)
    except (OSError, ValueError, RuntimeError):
        # A damaged optional install must not displace the known bundled tools.
        return None


def check_latest(*, root):
    from ..app.updater import _stable_manifest
    if os.name != "nt":
        raise RuntimeError("独立工具更新目前支持 Windows。")
    source, manifest, signature = _stable_manifest(None)
    release, component = _parse(manifest, signature)
    active = active_tools()
    installed = active.get("toolset") if active else None
    if not installed:
        try:
            bundled = json.loads((Path(root) / "2byteasr_components.json").read_bytes())
            installed = bundled["components"]["tools"]["content_sha256"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return dict(release=str(release.version), component=component, manifest=manifest,
                signature=signature, available=installed != component.content_sha256,
                prefer_gitcode="gitcode.com" in source)


def install_latest(*, root, progress=None, cancel=None):
    from ..app.update_manifest import ARCHIVE_INDEX_NAME
    from ..app.updater import _check_free_space, _downloads_dir, _safe_extract, download_asset
    from .link_tools import check_cancel, ensure_tools

    with _UPDATE_LOCK:
        cancel_check = cancel.is_set if cancel is not None else None
        store = _store()
        info = check_latest(root=root)
        if not info["available"]:
            return ensure_tools(root=root, cancel=cancel_check)
        component = info["component"]
        archive_info = component.archive
        if archive_info is None:
            raise ValueError("签名清单没有独立工具元件包。")
        store.mkdir(parents=True, exist_ok=True)
        _check_free_space(store, component.bytes + archive_info.size)
        generation = component.content_sha256[:16] + "-" + uuid.uuid4().hex[:8]
        with tempfile.TemporaryDirectory(prefix="stage-", dir=store) as temporary:
            stage = Path(temporary)
            archive = download_asset(archive_info, _downloads_dir(), progress=progress, cancel=cancel,
                                     prefer_gitcode=info["prefer_gitcode"])
            payload = stage / "payload"
            payload.mkdir()
            _safe_extract(archive, _COMPONENT, component.content_sha256, payload)
            (payload / "release.json").write_bytes(info["manifest"])
            (payload / "release.sig").write_bytes(info["signature"])
            with zipfile.ZipFile(archive) as component_zip:
                (payload / "index.json").write_bytes(component_zip.read(ARCHIVE_INDEX_NAME))
            check_cancel(cancel_check)
            _verified_tools(payload)
            target = store / generation
            os.replace(payload, target)
            # Revalidate absolute executable paths before publishing the pointer.
            result = _verified_tools(target, check_all=False)
            check_cancel(cancel_check)
            _record(store, generation, _state(store).get("active", ""))
            return result


def rollback_tools(*, root):
    from .link_tools import ensure_tools
    with _UPDATE_LOCK:
        store = _store()
        selected = _state(store)
        old = selected.get("active", "")
        previous = selected.get("previous", "")
        if not old and not previous:
            raise ValueError("没有可回退的下载工具版本。")
        result = None
        if isinstance(previous, str) and _ID.fullmatch(previous):
            try:
                result = _verified_tools(store / previous)
            except (OSError, ValueError, RuntimeError):
                pass
        if result is None:
            previous = ""
            result = ensure_tools(root=root, use_managed=False)
        _record(store, previous, old)
        return result
