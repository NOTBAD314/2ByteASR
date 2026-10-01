"""Repository-level model downloader with explicit source failover.

Hugging Face mirror and official downloads share huggingface_hub. ModelScope
uses its official SDK. Each source downloads into its own project-owned staging
directory; files are only published after that source's manifest validates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from twobyteasr.processes import main_python_executable, run_hidden_subprocess


SOURCE_ORDER = ("MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL")
SOURCE_LABELS = {
    "MODELSCOPE": "ModelScope",
    "HF_MIRROR": "HF 镜像（可能回源官方）",
    "HF_OFFICIAL": "Hugging Face 官方",
}
SOURCE_HOSTS = {
    "MODELSCOPE": "modelscope.cn",
    "HF_MIRROR": "hf-mirror.com",
    "HF_OFFICIAL": "huggingface.co",
}


@dataclass(frozen=True)
class SourceManifest:
    mode: str
    repository: str
    revision: str
    files: tuple[str, ...]
    sha256: dict[str, str]


class SourceAttemptError(RuntimeError):
    pass


@contextmanager
def preparation_lock(path: Path):
    """OS-owned lock, released on cancellation/crash rather than stale lock files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        deadline = time.monotonic() + 1800
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('等待同一模型的准备任务释放资源超时')
                print('[等待] 另一个任务正在准备此模型', flush=True)
                time.sleep(2)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _emit(prefix: str, payload: dict) -> None:
    print(f"{prefix} {json.dumps(payload, ensure_ascii=False)}", flush=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("."):
        raise ValueError(f"无效模型文件路径：{value!r}")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"模型文件路径越界：{value!r}")
    return normalized


def source_manifest(spec: dict, mode: str) -> SourceManifest | None:
    declared = dict(spec.get("source_manifests") or {})
    key = "modelscope" if mode == "MODELSCOPE" else "hf"
    payload = dict(declared.get(key) or {})
    if payload.get('compatible') is False:
        return None
    if mode == "MODELSCOPE":
        repository = str(payload.get("repository") or spec.get("modelscope_repository") or "")
        revision = str(payload.get("revision") or spec.get("modelscope_revision") or "master")
    else:
        repository = str(payload.get("repository") or spec.get("repository") or "")
        revision = str(payload.get("revision") or spec.get("revision") or "main")
    if not repository:
        return None
    files = payload.get("files") or spec.get("required_files") or ()
    hash_source = payload.get("sha256")
    if hash_source is None and key not in declared:
        # Mirrors declared without source-specific manifests preserve the same
        # artifacts, so verify them against the shared dependency lock.
        hash_source = spec.get("sha256")
    hashes = {
        _safe_relative(name): str(value).lower()
        for name, value in dict(hash_source or {}).items()
    }
    return SourceManifest(
        mode=mode,
        repository=repository,
        revision=revision,
        files=tuple(dict.fromkeys(_safe_relative(item) for item in files)),
        sha256=hashes,
    )


def planned_sources(spec: dict, mode: str) -> list[SourceManifest]:
    normalized = str(mode or "AUTO").upper()
    modes = SOURCE_ORDER if normalized == "AUTO" else (normalized,)
    manifests = [source_manifest(spec, item) for item in modes]
    return [item for item in manifests if item is not None]


def validate_files(root: Path, manifest: SourceManifest) -> tuple[bool, str]:
    for relative in manifest.files:
        path = root / relative
        if not path.is_file():
            return False, f"缺少文件：{relative}"
        try:
            if path.stat().st_size <= 0:
                return False, f"空文件：{relative}"
        except OSError as exc:
            return False, f"无法读取 {relative}：{exc}"
        expected = manifest.sha256.get(relative)
        if expected:
            actual = _sha256(path)
            if actual.lower() != expected.lower():
                return False, f"SHA-256 不匹配：{relative}"
    return True, "ok"


def _artifact_url(manifest: SourceManifest, relative: str) -> str:
    path = quote(relative.replace("\\", "/"), safe="/")
    revision = quote(manifest.revision, safe="")
    if manifest.mode == "MODELSCOPE":
        return (
            f"https://modelscope.cn/api/v1/models/{manifest.repository}/repo"
            f"?Revision={revision}&FilePath={path}"
        )
    endpoint = "https://hf-mirror.com" if manifest.mode == "HF_MIRROR" else "https://huggingface.co"
    return f"{endpoint}/{manifest.repository}/resolve/{revision}/{path}"


def _download_direct(manifest: SourceManifest, staging: Path, relative: str) -> Path:
    """Download through the resumable HTTP client with at most one retry."""
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    downloader = Path(__file__).resolve().parents[1] / "scripts" / "download_file_fast.py"
    interpreter = main_python_executable(downloader.parent.parent)
    if not interpreter:
        raise SourceAttemptError(
            "主运行环境尚未配置；请先运行“配置或修复 2ByteASR”"
        )
    command = [
        interpreter,
        str(downloader),
        "--url",
        _artifact_url(manifest, relative),
        "--out",
        str(target),
        "--source-mode",
        manifest.mode,
        "--resume-root",
        str(staging.parent),
    ]
    expected = manifest.sha256.get(relative)
    if expected:
        command.extend(("--sha256", expected))
    process = run_hidden_subprocess(
        command,
        purpose="model repository artifact download",
        runner=subprocess.Popen,
        cwd=str(downloader.parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    recent = deque(maxlen=12)
    for line in process.stdout:
        print(line, end='', flush=True)
        if not line.startswith('[2BYTEASR_PROGRESS]'):
            recent.append(line.rstrip())
    if process.wait() != 0:
        raise SourceAttemptError(
            f"{relative}（退出码 {process.returncode}）：" + '\n'.join(recent)
        )
    return target


def download_source(
    manifest: SourceManifest,
    staging: Path,
    *,
    only_files: Iterable[str] | None = None,
) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    requested = tuple(_safe_relative(item) for item in (only_files or manifest.files))
    for index, relative in enumerate(requested, start=1):
        cached=staging/relative
        expected=manifest.sha256.get(relative)
        if expected and cached.is_file() and _sha256(cached)==expected:
            _emit('[2BYTEASR_CACHE]',dict(file=relative,bytes=cached.stat().st_size,
                origin='verified staging',network_bytes=0))
            continue
        _emit("[2BYTEASR_FILE]", {
            "file": relative,
            "index": index,
            "total": len(requested),
            "phase": "downloading",
        })
        try:
            path = _download_direct(manifest, staging, relative)
        except Exception as exc:
            raise SourceAttemptError(f"{relative}: {type(exc).__name__}: {exc}") from exc
        if not path.is_file() or path.stat().st_size <= 0:
            raise SourceAttemptError(f"来源没有返回有效模型文件：{relative}")
        expected = manifest.sha256.get(relative)
        if expected:
            actual = _sha256(path)
            if actual.lower() != expected.lower():
                raise SourceAttemptError(f"SHA-256 不匹配：{relative}")


def publish_files(staging: Path, destination: Path, files: Iterable[str]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative in files:
        source = staging / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".publishing")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)


def download_model(
    *,
    model_key: str,
    spec: dict,
    destination: Path,
    mode: str,
    staging_root: Path,
    only_files: Iterable[str] | None = None,
) -> str:
    with preparation_lock(staging_root / model_key / '.prepare.lock'):
        return _download_model_locked(model_key=model_key, spec=spec, destination=destination,
                                      mode=mode, staging_root=staging_root, only_files=only_files)


def _download_model_locked(*, model_key, spec, destination, mode, staging_root, only_files=None):
    declared = spec.get('source_manifests') or {}
    for source in (SOURCE_ORDER if str(mode).upper() == 'AUTO' else (str(mode).upper(),)):
        payload = declared.get('modelscope' if source == 'MODELSCOPE' else 'hf') or {}
        if payload.get('compatible') is False:
            _emit('[2BYTEASR_SOURCE]', dict(mode=source, status='skipped',
                category='revision_incompatible', detail=payload.get('reason', '该来源未提供锁定版本的相同文件')))
    candidates = planned_sources(spec, mode)
    if not candidates:
        raise RuntimeError(f"{mode} 未提供当前锁定版本的兼容文件，请选择 AUTO 或其他已声明来源。")
    requested_only = tuple(only_files or ())
    failures: list[str] = []
    for attempt, manifest in enumerate(candidates, start=1):
        _emit("[2BYTEASR_SOURCE]", {
            "mode": manifest.mode,
            "label": SOURCE_LABELS[manifest.mode],
            "host": SOURCE_HOSTS[manifest.mode],
            "attempt": attempt,
            "total": len(candidates),
            "status": "trying",
        })
        identity = hashlib.sha256(json.dumps([manifest.repository,manifest.revision,manifest.sha256],sort_keys=True).encode()).hexdigest()[:16]
        staging = staging_root / model_key / manifest.mode.lower() / identity
        try:
            if not requested_only:
                ready, _reason = validate_files(destination, manifest)
                if ready:
                    _emit("[2BYTEASR_SOURCE]", {
                        "mode": manifest.mode,
                        "label": SOURCE_LABELS[manifest.mode],
                        "host": SOURCE_HOSTS[manifest.mode],
                        "attempt": attempt,
                        "total": len(candidates),
                        "status": "selected",
                    })
                    return manifest.mode
            files = requested_only or manifest.files
            # A missing small file must not redownload healthy multi-GB weights.
            # Reuse only bytes authenticated by this exact source manifest.
            for relative in files:
                original=destination/relative;cached=staging/relative
                expected=manifest.sha256.get(relative)
                if expected and original.is_file() and not cached.is_file() and _sha256(original)==expected:
                    cached.parent.mkdir(parents=True,exist_ok=True)
                    pending=cached.with_name(cached.name+'.cache-copy')
                    shutil.copy2(original,pending);os.replace(pending,cached)
                    _emit('[2BYTEASR_CACHE]',dict(file=relative,bytes=original.stat().st_size,
                        origin='verified installed file',network_bytes=0))
            download_source(manifest, staging, only_files=requested_only or None)
            probe_manifest = SourceManifest(
                manifest.mode, manifest.repository, manifest.revision,
                tuple(files), {key: value for key, value in manifest.sha256.items() if key in files},
            )
            ok, reason = validate_files(staging, probe_manifest)
            if not ok:
                raise SourceAttemptError(reason)
            publish_files(staging, destination, files)
            _emit("[2BYTEASR_SOURCE]", {
                "mode": manifest.mode,
                "label": SOURCE_LABELS[manifest.mode],
                "host": SOURCE_HOSTS[manifest.mode],
                "attempt": attempt,
                "total": len(candidates),
                "status": "selected",
            })
            metadata = {
                "schema_version": 1,
                "source_mode": manifest.mode,
                "repository": manifest.repository,
                "revision": manifest.revision,
            }
            (destination / ".2byteasr-source.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return manifest.mode
        except Exception as exc:
            detail = str(exc).replace("\r", " ").replace("\n", " ")
            failures.append(f"{manifest.mode}: {detail}")
            _emit("[2BYTEASR_SOURCE]", {
                "mode": manifest.mode,
                "label": SOURCE_LABELS[manifest.mode],
                "host": SOURCE_HOSTS[manifest.mode],
                "attempt": attempt,
                "total": len(candidates),
                "status": "failed",
                "category": "source_unavailable",
                "detail": detail[:500],
            })
            if str(mode).upper() != "AUTO":
                break
    raise RuntimeError("所有候选来源均失败：\n" + "\n".join(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--mode", default="AUTO", choices=("AUTO", *SOURCE_ORDER))
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--staging-root", type=Path)
    parser.add_argument("--file", action="append", default=[])
    args = parser.parse_args(argv)

    lock_path = args.lock.resolve()
    root = lock_path.parent
    payload = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    spec = dict((payload.get("models") or {}).get(args.model) or {})
    if not spec:
        print(f"依赖清单中没有模型：{args.model}", file=sys.stderr)
        return 2
    destination = (args.destination or (root / str(spec.get("path") or ""))).resolve()
    staging_root = (args.staging_root or (root / "tmp" / "model-downloads")).resolve()
    try:
        selected = download_model(
            model_key=args.model,
            spec=spec,
            destination=destination,
            mode=args.mode,
            staging_root=staging_root,
            only_files=args.file,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    print(f"[2BYTEASR_PHASE] {json.dumps({'phase': 'weights_ready', 'source': selected}, ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
