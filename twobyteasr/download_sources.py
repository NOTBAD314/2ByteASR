"""Download source registry and resolver (Change Group 2).

Four user-facing modes map to concrete hosts/URLs used by the real
downloader.  AUTO is sequential (ModelScope when declared, Hugging Face
official, then the third-party HF mirror).  Explicit modes never silently add
another source.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

SOURCE_MODES = ("AUTO", "MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL")

SOURCE_LABELS = {
    "AUTO": "自动",
    "MODELSCOPE": "ModelScope",
    "HF_MIRROR": "HF 镜像（可能回源官方）",
    "HF_OFFICIAL": "Hugging Face 官方",
}

SOURCE_HOSTS = {
    "MODELSCOPE": "modelscope.cn",
    "HF_MIRROR": "hf-mirror.com",
    "HF_OFFICIAL": "huggingface.co",
}

_LEGACY_ALIASES = {
    "auto": "AUTO",
    "modelscope": "MODELSCOPE",
    "hfmirror": "HF_MIRROR",
    "hf_mirror": "HF_MIRROR",
    "huggingface": "HF_OFFICIAL",
    "hf_official": "HF_OFFICIAL",
    "hf-official": "HF_OFFICIAL",
}

ERROR_CATEGORIES = (
    "source_unavailable",
    "network_timeout",
    "http_access",
    "checksum",
    "disk",
    "cancelled",
    "unknown",
)

_NEXT_ACTIONS = {
    "source_unavailable": "请更换下载源后重试；已完成的分片会保留。",
    "network_timeout": "请稍后重试或更换下载源；已下载分片可续传。",
    "http_access": "请检查访问权限或更换下载源后重试。",
    "checksum": "请更换下载源重新校验；错误文件不会当作已完成。",
    "disk": "请清理磁盘空间后点“继续重试”。",
    "cancelled": "下载已暂停。点“继续重试”即可从断点续传。",
    "unknown": "请重试或更换下载源；已完成分片会保留。",
}


class UnknownSourceModeError(ValueError):
    """Caller asked for a source that is not one of the four product modes."""


class DownloadSourceError(RuntimeError):
    def __init__(self, category, source_mode="", host="", detail="", url=""):
        self.category = category
        self.source_mode = source_mode
        self.host = host
        self.detail = detail
        self.url = url
        super().__init__(detail or category)


class SourceUnavailableError(DownloadSourceError):
    def __init__(self, source_mode, host="", detail="", url=""):
        super().__init__(
            "source_unavailable",
            source_mode=source_mode,
            host=host,
            detail=detail,
            url=url,
        )


@dataclass(frozen=True)
class ResolvedSource:
    mode: str
    host: str
    url: str
    label: str
    repository: str = ""
    revision: str = ""


@dataclass
class UserFacingError:
    source_mode: str
    host: str
    category: str
    message: str
    next_action: str
    details: str = ""


def normalize_source_mode(value):
    text = str(value or "").strip()
    if not text:
        raise UnknownSourceModeError("下载源不能为空")
    compact = text.replace("-", "").replace("_", "").replace(" ", "").lower()
    if text.upper() in SOURCE_MODES:
        return text.upper()
    mapped = _LEGACY_ALIASES.get(compact)
    if mapped:
        return mapped
    raise UnknownSourceModeError(f"不支持的下载源：{value}")


def user_facing_source_choices():
    return [
        {"mode": mode, "label": SOURCE_LABELS[mode], "host": SOURCE_HOSTS.get(mode, "")}
        for mode in SOURCE_MODES
    ]


def modelscope_declared(spec):
    if not isinstance(spec, dict):
        return False
    manifest = (spec.get('source_manifests') or {}).get('modelscope') or {}
    return manifest.get('compatible') is not False and bool(str(manifest.get('repository') or spec.get("modelscope_repository") or "").strip())


def _modelscope_repository(spec):
    declared = str((spec or {}).get("modelscope_repository") or "").strip()
    if not declared:
        return ""
    org = str(os.environ.get("2BYTEASR_MODELSCOPE_ORG") or "").strip()
    if org:
        return f"{org}/{declared.split('/')[-1]}"
    return declared


def _modelscope_url(spec, relative):
    repository = _modelscope_repository(spec)
    revision = str(spec.get("modelscope_revision") or "master")
    encoded_revision = quote(revision, safe="")
    encoded_path = quote(str(relative).replace("\\", "/"), safe="/")
    return (
        f"https://modelscope.cn/api/v1/models/{repository}/repo"
        f"?Revision={encoded_revision}&FilePath={encoded_path}"
    )


def _hf_url(base, spec, relative):
    repository = str(spec.get("repository") or "").strip()
    revision = str(spec.get("revision") or "main")
    path = str(relative).replace("\\", "/")
    return f"{base.rstrip('/')}/{repository}/resolve/{revision}/{path}"


def resolve_artifact(model_key, relative, spec, mode):
    """Return ordered concrete sources for one artifact.  Never invent a source."""
    del model_key  # reserved for lock lookup / diagnostics
    spec = spec or {}
    mode = normalize_source_mode(mode)
    if mode == "AUTO":
        # Same order as repository_download.SOURCE_ORDER; the third-party
        # mirror is the last resort and still has to match the locked hashes.
        planned = []
        if modelscope_declared(spec):
            planned.append("MODELSCOPE")
        planned.extend(("HF_OFFICIAL", "HF_MIRROR"))
        return [item for item in (_one_source(spec, relative, name) for name in planned) if item]

    resolved = _one_source(spec, relative, mode)
    if resolved is None:
        host = SOURCE_HOSTS.get(mode, "")
        raise SourceUnavailableError(
            mode,
            host=host,
            detail=f"{SOURCE_LABELS[mode]} 未声明可用仓库，无法解析 {relative}",
        )
    return [resolved]


def _one_source(spec, relative, mode):
    if mode == "MODELSCOPE":
        if not modelscope_declared(spec):
            return None
        return ResolvedSource(
            mode=mode,
            host=SOURCE_HOSTS[mode],
            url=_modelscope_url(spec, relative),
            label=SOURCE_LABELS[mode],
            repository=_modelscope_repository(spec),
            revision=str(spec.get("modelscope_revision") or "master"),
        )
    if mode == "HF_MIRROR":
        return ResolvedSource(
            mode=mode,
            host=SOURCE_HOSTS[mode],
            url=_hf_url("https://hf-mirror.com", spec, relative),
            label=SOURCE_LABELS[mode],
            repository=str(spec.get("repository") or ""),
            revision=str(spec.get("revision") or ""),
        )
    if mode == "HF_OFFICIAL":
        return ResolvedSource(
            mode=mode,
            host=SOURCE_HOSTS[mode],
            url=_hf_url("https://huggingface.co", spec, relative),
            label=SOURCE_LABELS[mode],
            repository=str(spec.get("repository") or ""),
            revision=str(spec.get("revision") or ""),
        )
    return None


def resolve_from_lock(model_key, relative, mode, *, lock_path=None):
    path = lock_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "dependencies.lock.json",
    )
    with open(path, "r", encoding="utf-8") as stream:
        payload = json.load(stream)
    spec = (payload.get("models") or {}).get(model_key)
    if not isinstance(spec, dict):
        raise SourceUnavailableError(
            normalize_source_mode(mode),
            detail=f"依赖清单没有模型 {model_key}",
        )
    return resolve_artifact(model_key, relative, spec, mode)


# Runtime bootstrap fallbacks shared with the macOS preparer.  Measured from a
# mainland China line without proxy on 2026-10-14: GitHub release assets were
# very slow (uv: 64 KiB in 45 s), releases.astral.sh / npmmirror / PyPI mirrors
# answered within ~1 s.  Every candidate serves the identical file, so callers
# keep checking the SHA-256 they already lock.
_RUNTIME_SOURCES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "scripts", "runtime_sources.json")
_DEFAULT_PYPI_MIRRORS = (
    ("阿里云 PyPI 镜像", "https://mirrors.aliyun.com/pypi/simple"),
    ("清华 PyPI 镜像", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("腾讯云 PyPI 镜像", "https://mirrors.cloud.tencent.com/pypi/simple"),
    ("中科大 PyPI 镜像", "https://mirrors.ustc.edu.cn/pypi/simple"),
)
_DEFAULT_PYTHON_MIRRORS = (
    ("npmmirror", "https://registry.npmmirror.com/-/binary/python-build-standalone"),
    ("中科大镜像", "https://mirrors.ustc.edu.cn/github-release/astral-sh/python-build-standalone"),
)


def _runtime_sources():
    try:
        with open(_RUNTIME_SOURCES_FILE, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def pip_index_urls():
    """PyPI index URLs in trial order: official first, then the domestic mirrors.

    Only for installs that pin every file by hash (``--require-hashes`` or a
    hashed constraint file); a mirror lagging behind PyPI then fails instead of
    installing a different build.
    """
    mirrors = [(m.get("label", ""), m.get("url", "")) for m in _runtime_sources().get("pypi_mirrors") or []]
    urls = ["https://pypi.org/simple"]
    for _label, url in mirrors or _DEFAULT_PYPI_MIRRORS:
        url = str(url).rstrip("/")
        if url.startswith("https://") and url not in urls:
            urls.append(url)
    return urls


def bootstrap_urls(url):
    """Ordered URLs serving the same bootstrap archive as ``url`` (official first).

    Covers the three bootstrap files: uv release archives and
    python-build-standalone archives on GitHub, and wheels on
    files.pythonhosted.org.  Anything else is returned unchanged.
    """
    url = str(url or "")
    parsed = urlparse(url)
    path = parsed.path
    candidates = [url]
    if parsed.hostname == "github.com" and path.startswith("/astral-sh/uv/releases/download/"):
        candidates.append("https://releases.astral.sh/github/uv/releases/download/"
                          + path[len("/astral-sh/uv/releases/download/"):])
    elif parsed.hostname == "github.com" and path.startswith("/astral-sh/python-build-standalone/releases/download/"):
        tail = path[len("/astral-sh/python-build-standalone/releases/download/"):]
        candidates.append("https://releases.astral.sh/github/python-build-standalone/releases/download/" + tail)
        mirrors = [(m.get("label", ""), m.get("url", "")) for m in _runtime_sources().get("python_mirrors") or []]
        for _label, base in mirrors or _DEFAULT_PYTHON_MIRRORS:
            candidates.append(str(base).rstrip("/") + "/" + tail)
    elif parsed.hostname == "files.pythonhosted.org" and path.startswith("/packages/"):
        for index in pip_index_urls()[1:]:
            candidates.append(index[: -len("/simple")] + path if index.endswith("/simple") else index)
    return list(dict.fromkeys(item for item in candidates if item.startswith("https://")))


def host_token(host):
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(host or "unknown")).strip("_")
    return cleaned or "unknown"


def hostname_of(url):
    return urlparse(str(url)).hostname or ""


def classify_error_text(text):
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("暂停", "cancelled", "canceled")):
        return "cancelled"
    if any(token in lowered for token in ("sha-256", "sha256", "哈希", "校验")):
        return "checksum"
    if any(token in lowered for token in ("磁盘", "disk", "no space", "空间不足")):
        return "disk"
    if any(token in lowered for token in ("404", "not found", "缺少模型", "未声明")):
        return "source_unavailable"
    if any(token in lowered for token in ("403", "401", "forbidden", "unauthorized", "access")):
        return "http_access"
    if any(
        token in lowered
        for token in ("timeout", "timed out", "连接", "connection", "reset", "unreachable")
    ):
        return "network_timeout"
    return "unknown"


def user_facing_error(exc):
    if isinstance(exc, DownloadSourceError):
        category = exc.category
        mode = exc.source_mode or "AUTO"
        host = exc.host or SOURCE_HOSTS.get(mode, "")
        detail = exc.detail or str(exc)
    else:
        detail = str(exc)
        category = classify_error_text(detail)
        mode = "AUTO"
        host = ""
    label = SOURCE_LABELS.get(mode, mode)
    host_bit = f"（{host}）" if host else ""
    category_zh = {
        "source_unavailable": "当前来源没有所需文件",
        "network_timeout": "网络超时或连接中断",
        "http_access": "服务器拒绝访问",
        "checksum": "文件校验失败",
        "disk": "磁盘空间或权限不足",
        "cancelled": "下载已取消",
        "unknown": "下载未完成",
    }[category]
    return UserFacingError(
        source_mode=mode,
        host=host,
        category=category,
        message=f"{label}{host_bit}失败：{category_zh}。",
        next_action=_NEXT_ACTIONS[category],
        details=detail,
    )


def completed_artifact_is_valid(path, size, expected_sha256=None):
    if not path or not os.path.isfile(path):
        return False
    if os.path.getsize(path) != int(size):
        return False
    if not expected_sha256:
        return True
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().lower() == str(expected_sha256).lower()


def emit_source_event(resolved, *, attempt, total, status="trying"):
    payload = {
        "mode": resolved.mode,
        "host": resolved.host,
        "label": resolved.label,
        "url": resolved.url,
        "attempt": int(attempt),
        "total": int(total),
        "status": status,
    }
    return "[2BYTEASR_SOURCE] " + json.dumps(payload, ensure_ascii=False)


def print_artifact_json(model_key, relative, mode, lock_path=None):
    items = resolve_from_lock(model_key, relative, mode, lock_path=lock_path)
    print(
        json.dumps(
            [
                {
                    "mode": item.mode,
                    "host": item.host,
                    "url": item.url,
                    "label": item.label,
                    "repository": item.repository,
                    "revision": item.revision,
                }
                for item in items
            ],
            ensure_ascii=False,
        )
    )


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--mode", default="AUTO")
    parser.add_argument("--lock", default="")
    args = parser.parse_args(argv)
    try:
        print_artifact_json(args.model, args.file, args.mode, lock_path=args.lock or None)
    except DownloadSourceError as exc:
        error = user_facing_error(exc)
        print(error.message, file=sys.stderr)
        print(error.next_action, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
