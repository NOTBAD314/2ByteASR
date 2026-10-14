"""Repository download using the same bounded HTTP client for every source.

Each source has separate staging. The product's lock authenticates all files
before publication, and a pending marker prevents partial installs being ready.
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
import threading
import queue
from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from twobyteasr.processes import main_python_executable, run_hidden_subprocess
from twobyteasr.download_diagnostics import redact, category, require_isolated_download_path


# AUTO: verified ModelScope copy, then the official host, then the third-party
# hf-mirror.com as the last resort (huggingface.co is unreachable from mainland
# China without a proxy). Every source must still deliver the locked SHA-256.
SOURCE_ORDER = ("MODELSCOPE", "HF_OFFICIAL", "HF_MIRROR")
SOURCE_MODES = ("MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL")
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
MODEL_SOURCES_FILE = Path(__file__).resolve().parents[1] / "scripts" / "model_download_sources.json"


def load_model_sources(path: Path | None = None) -> dict:
    """Alternate-source pins (repository + commit); never files or hashes."""
    try:
        payload = json.loads((path or MODEL_SOURCES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) and payload.get("schema") == 1 else {}


def effective_spec(model_key: str, spec: dict, sources: dict | None = None) -> dict:
    """Lock entry plus the verified ModelScope pin from ``model_download_sources.json``.

    The lock stays authoritative: an explicit incompatibility or an already
    pinned commit wins, a different repository is ignored, and files/hashes
    always come from the lock.
    """
    merged = dict(spec or {})
    pin = ((sources if sources is not None else load_model_sources()).get("modelscope") or {}).get(model_key) or {}
    repository = str(pin.get("repository") or "").strip()
    revision = str(pin.get("revision") or "").strip()
    if not repository or not revision:
        return merged
    declared = dict((merged.get("source_manifests") or {}).get("modelscope") or {})
    if declared.get("compatible") is False:
        return merged
    locked_repository = str(declared.get("repository") or merged.get("modelscope_repository") or "").strip()
    locked_revision = str(declared.get("revision") or merged.get("modelscope_revision") or "").strip()
    if locked_repository and locked_repository != repository:
        return merged
    if locked_revision and locked_revision != "master":
        return merged
    merged["modelscope_repository"] = repository
    merged["modelscope_revision"] = revision
    if declared:
        declared.update(repository=repository, revision=revision)
        merged["source_manifests"] = {**(merged.get("source_manifests") or {}), "modelscope": declared}
    return merged


@dataclass(frozen=True)
class SourceManifest:
    mode: str
    repository: str
    revision: str
    files: tuple[str, ...]
    sha256: dict[str, str]


class SourceAttemptError(RuntimeError):
    def __init__(self, message, *, download_category=''):
        super().__init__(message)
        self.download_category=download_category


@contextmanager
def preparation_lock(path: Path, *, timeout: float = 1800):
    """OS-owned lock, released on cancellation/crash rather than stale lock files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        deadline = time.monotonic() + timeout
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
    print(f"{prefix} {json.dumps(redact(payload), ensure_ascii=False)}", flush=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: str) -> str:
    normalized = str(value or "").replace("\\", "/")
    if not normalized or normalized.startswith(('.', '/')) or ':' in normalized:
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
    # An origin cannot weaken the product's file/identity contract. A different
    # version must be explicitly rejected, never accepted using two config hashes.
    files = tuple(dict.fromkeys([*(spec.get('required_files') or ()), *(payload.get('files') or ())]))
    hash_source = dict(spec.get('sha256') or {})
    for name, digest in (payload.get('sha256') or {}).items():
        if name in hash_source and hash_source[name].lower() != str(digest).lower():
            raise ValueError(f'{mode} 与产品锁定内容不一致：{name}')
        hash_source[name] = digest
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
    if normalized not in ('AUTO', *SOURCE_MODES):
        raise ValueError(f'不支持的下载来源：{normalized}')
    modes = SOURCE_ORDER if normalized == "AUTO" else (normalized,)
    manifests = [source_manifest(spec, item) for item in modes]
    return [item for item in manifests if item is not None]


def validate_files(root: Path, manifest: SourceManifest, *, check_indexes=True) -> tuple[bool, str]:
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
        if check_indexes and relative.endswith('.index.json'):
            try:
                index = json.loads(path.read_text('utf-8'))
                for shard in set((index.get('weight_map') or {}).values()):
                    shard = _safe_relative(shard)
                    member = (Path(relative).parent / shard).as_posix()
                    if member not in manifest.files:
                        return False, f'分片索引引用未声明文件：{member}'
            except (ValueError, TypeError, AttributeError) as exc:
                return False, f'分片索引无效：{relative} ({exc})'
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
    url=f"{endpoint}/{manifest.repository}/resolve/{revision}/{path}"
    return url


def _download_direct(manifest: SourceManifest, staging: Path, relative: str) -> Path:
    """Download through the resumable HTTP client with at most one retry."""
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    downloader = Path(__file__).resolve().parents[1] / "scripts" / "download_file_fast.py"
    interpreter = os.environ.get('TWOBYTEASR_DOWNLOAD_PYTHON') or main_python_executable(downloader.parent.parent)
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
    last_error={}
    output = queue.Queue()
    def read_output():
        try:
            for line in process.stdout: output.put(line)
        finally: output.put(None)
    reader=threading.Thread(target=read_output,daemon=True)
    reader.start()
    started=last_activity=time.monotonic()
    while True:
        now=time.monotonic()
        if now-last_activity>150 or now-started>6*3600:
            process.kill();process.wait(timeout=10)
            raise SourceAttemptError('network_timeout: 下载进程超过 150 秒没有反馈或超过单文件 6 小时限制；分片已保留')
        try: line=output.get(timeout=.5)
        except queue.Empty: continue
        if line is None: break
        last_activity=time.monotonic()
        print(redact(line), end='', flush=True)
        if line.startswith('[2BYTEASR_ERROR] '):
            try: last_error=json.loads(line.split(' ',1)[1])
            except ValueError: pass
        if not line.startswith('[2BYTEASR_PROGRESS]'):
            recent.append(redact(line.rstrip()))
    if process.wait() != 0:
        raise SourceAttemptError(
            f"{relative}（退出码 {process.returncode}）：" + str(last_error.get('detail') or '\n'.join(recent)),
            download_category=last_error.get('category','')
        )
    return target


# Failures that say "the line is unreliable right now", not "this source is
# blocked / wrong": worth another try once the source has proven reachable.
TRANSIENT_CATEGORIES = frozenset({'network_timeout', 'connection', 'rate_limited'})
FILE_RETRIES_ONCE_REACHABLE = 3


def download_source(
    manifest: SourceManifest,
    staging: Path,
    *,
    only_files: Iterable[str] | None = None,
) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    requested = tuple(_safe_relative(item) for item in (only_files or manifest.files))
    delivered = 0  # files this source actually served in this attempt
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
        retries = 0
        while True:
            try:
                path = _download_direct(manifest, staging, relative)
                break
            except Exception as exc:
                kind = category(exc)
                # A blocked source fails on its first file and moves on quickly;
                # one that already served files only hiccupped (e.g. hf-mirror.com
                # answering slowly from mainland China), so wait and try again.
                if delivered and kind in TRANSIENT_CATEGORIES and retries < FILE_RETRIES_ONCE_REACHABLE:
                    retries += 1
                    delay = min(30, 2 ** (retries + 1))
                    print(f'[重试] {relative}：来源暂时没有响应（{kind}），{delay} 秒后第 {retries} 次重试；已下载部分保留',
                          flush=True)
                    time.sleep(delay)
                    continue
                raise SourceAttemptError(f"{relative}: {type(exc).__name__}: {exc}",download_category=kind) from exc
        delivered += 1
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
    if model_key in {'diarizen', 'diarizen_embedding', 'vibevoice_1_5b', 'vibevoice_7b'}:
        raise ValueError('DiariZen / VibeVoice models have been removed; no download was started.')
    require_isolated_download_path(destination)
    require_isolated_download_path(staging_root)
    spec = effective_spec(model_key, spec)
    with preparation_lock(staging_root / model_key / '.prepare.lock'):
        return _download_model_locked(model_key=model_key, spec=spec, destination=destination,
                                      mode=mode, staging_root=staging_root, only_files=only_files)


def partial_source_manifest(model_key: str, spec: dict, sources: dict | None = None) -> SourceManifest | None:
    """A ModelScope copy that carries only some of the locked files unchanged.

    Fun-ASR Nano on ModelScope differs from the lock only in ``model.pt``; its
    other nine files are byte-identical. ``modelscope_partial`` in
    ``model_download_sources.json`` names those files, and only files that the
    lock also lists with a SHA-256 are taken.
    """
    pin = ((sources if sources is not None else load_model_sources()).get('modelscope_partial') or {}).get(model_key) or {}
    repository = str(pin.get('repository') or '').strip()
    revision = str(pin.get('revision') or '').strip()
    hashes = {_safe_relative(k): str(v).lower() for k, v in (spec.get('sha256') or {}).items()}
    required = {_safe_relative(item) for item in spec.get('required_files') or ()}
    files = tuple(item for item in (_safe_relative(f) for f in pin.get('files') or ()) if item in required and item in hashes)
    if not repository or not revision or not files:
        return None
    return SourceManifest('MODELSCOPE', repository, revision, files, {f: hashes[f] for f in files})


def prefetch_partial_source(model_key: str, spec: dict, destination: Path, staging_root: Path,
                            only_files: Iterable[str] | None = None) -> None:
    """AUTO only: fetch the files a partial ModelScope copy shares with the lock first.

    The full sources that follow reuse them (``reuse_verified_from_other_sources``),
    so on a line where Hugging Face is blocked or slow only the differing file has
    to come from there. Failures here are not fatal.
    """
    manifest = partial_source_manifest(model_key, spec)
    if manifest is None:
        return
    wanted = [f for f in manifest.files if (not only_files or f in set(only_files))
              and not ((destination / f).is_file() and _sha256(destination / f) == manifest.sha256[f])]
    if not wanted:
        return
    identity = hashlib.sha256(json.dumps([manifest.repository, manifest.revision, manifest.sha256],
                                         sort_keys=True).encode()).hexdigest()[:16]
    staging = staging_root / model_key / 'modelscope_partial' / identity
    print(f'[自动] ModelScope 上这个模型有 {len(manifest.files)} 个文件与锁定版本完全相同，先从 ModelScope 取得；'
          f'其余文件再按顺序从其他来源下载', flush=True)
    try:
        download_source(manifest, staging, only_files=wanted)
    except Exception as exc:  # noqa: BLE001 - the full sources still follow
        print(f'[自动] ModelScope 部分文件没有取得（{category(exc)}），改由其他来源下载', flush=True)


def reuse_verified_from_other_sources(staging_root: Path, model_key: str, staging: Path,
                                      files: Iterable[str], sha256: dict[str, str]) -> list[str]:
    """Bring complete, hash-verified files from another source's staging into ``staging``.

    Switching from a failed source must not download again what that source
    already delivered intact. Only whole files whose SHA-256 equals the locked
    value are taken; partial files of another origin are never combined.
    """
    reused = []
    model_root = staging_root / model_key
    if not model_root.is_dir():
        return reused
    others = [path for path in model_root.glob('*/*') if path.is_dir() and path.resolve() != staging.resolve()]
    for relative in files:
        expected = (sha256.get(relative) or '').lower()
        target = staging / relative
        if not expected or target.is_file():
            continue  # download_source verifies (or replaces) what is already staged
        for other in others:
            candidate = other / relative
            try:
                if not candidate.is_file() or candidate.is_symlink() or candidate.stat().st_size <= 0:
                    continue
            except OSError:
                continue
            if _sha256(candidate) != expected:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.reusing')
            temporary.unlink(missing_ok=True)
            try:
                os.link(candidate, temporary)
            except OSError:
                shutil.copy2(candidate, temporary)
            os.replace(temporary, target)
            measurement = Path(str(candidate) + '.download.json')
            if measurement.is_file():
                shutil.copy2(measurement, Path(str(target) + '.download.json'))
            _emit('[2BYTEASR_CACHE]', dict(file=relative, bytes=target.stat().st_size,
                origin='verified file from ' + other.parent.name, network_bytes=0))
            reused.append(relative)
            break
    return reused


def _download_model_locked(*, model_key, spec, destination, mode, staging_root, only_files=None):
    from .model_download_cache import write_transaction, discard_published_staging
    declared = spec.get('source_manifests') or {}
    for source in (SOURCE_ORDER if str(mode).upper() == 'AUTO' else (str(mode).upper(),)):
        payload = declared.get('modelscope' if source == 'MODELSCOPE' else 'hf') or {}
        if payload.get('compatible') is False:
            _emit('[2BYTEASR_SOURCE]', dict(mode=source, status='skipped',
                category='revision_incompatible', detail=payload.get('reason', '该来源未提供锁定版本的相同文件')))
    candidates = planned_sources(spec, mode)
    if not candidates:
        raise RuntimeError(f"{mode} 未提供当前锁定版本的兼容文件，请选择 AUTO 或其他已声明来源。")
    if str(mode).upper() == 'AUTO':
        prefetch_partial_source(model_key, spec, destination, staging_root, only_files)
    requested_only = tuple(only_files or ())
    failures: list[str] = []
    last_category='unknown'
    # AUTO: every source once; then sources that failed only because the line was
    # unreliable get one more round, continuing from their verified files/parts.
    schedule = list(candidates)
    second_round: list[SourceManifest] = []
    attempt = 0
    while attempt < len(schedule):
        manifest = schedule[attempt]
        attempt += 1
        _emit("[2BYTEASR_SOURCE]", {
            "mode": manifest.mode,
            "label": SOURCE_LABELS[manifest.mode],
            "host": SOURCE_HOSTS[manifest.mode],
            "attempt": attempt,
            "total": len(schedule),
            "status": "trying",
        })
        identity = hashlib.sha256(json.dumps([manifest.repository,manifest.revision,manifest.sha256],sort_keys=True).encode()).hexdigest()[:16]
        staging = staging_root / model_key / manifest.mode.lower() / identity
        files = requested_only or manifest.files
        try:
            if not requested_only:
                ready, _reason = validate_files(destination, manifest)
                if ready and not (destination / '.2byteasr-install-pending.json').exists():
                    _emit("[2BYTEASR_SOURCE]", {
                        "mode": manifest.mode,
                        "label": SOURCE_LABELS[manifest.mode],
                        "host": SOURCE_HOSTS[manifest.mode],
                        "attempt": attempt,
                        "total": len(schedule),
                        "status": "selected",
                    })
                    return manifest.mode
            write_transaction(staging, model_key=model_key, destination=destination,
                              files=files, state='downloading')
            # A missing small file must not redownload healthy multi-GB weights.
            # Reuse only bytes authenticated by this exact source manifest.
            reused_installed = []
            for relative in files:
                original=destination/relative
                expected=manifest.sha256.get(relative)
                if expected and original.is_file() and _sha256(original)==expected:
                    reused_installed.append(relative)
                    _emit('[2BYTEASR_CACHE]',dict(file=relative,bytes=original.stat().st_size,
                        origin='verified installed file',network_bytes=0))
            pending_files = tuple(relative for relative in files if relative not in reused_installed)
            if pending_files:
                reuse_verified_from_other_sources(staging_root, model_key, staging, pending_files, manifest.sha256)
                download_source(manifest, staging, only_files=pending_files)
            probe_manifest = SourceManifest(
                manifest.mode, manifest.repository, manifest.revision,
                pending_files, {key: value for key, value in manifest.sha256.items() if key in pending_files},
            )
            ok, reason = validate_files(staging, probe_manifest, check_indexes=False)
            if not ok:
                raise SourceAttemptError(reason)
            destination.mkdir(parents=True, exist_ok=True)
            pending_marker = destination / '.2byteasr-install-pending.json'
            pending_marker.write_text(json.dumps(dict(model=model_key, source=manifest.mode, started=time.time())), 'utf-8')
            publish_files(staging, destination, pending_files)
            installed_probe = SourceManifest(manifest.mode, manifest.repository, manifest.revision,
                tuple(files), {key: value for key, value in manifest.sha256.items() if key in files})
            ok, reason = validate_files(destination, installed_probe)
            if not ok:
                raise SourceAttemptError('安装后校验失败：' + reason)
            _emit("[2BYTEASR_SOURCE]", {
                "mode": manifest.mode,
                "label": SOURCE_LABELS[manifest.mode],
                "host": SOURCE_HOSTS[manifest.mode],
                "attempt": attempt,
                "total": len(schedule),
                "status": "selected",
            })
            metadata = {
                "schema_version": 1,
                "source_mode": manifest.mode,
                "repository": manifest.repository,
                "revision": manifest.revision,
                "completed_at": time.time(),
                "files": [],
            }
            for relative in files:
                item = dict(file=relative, size=(destination / relative).stat().st_size,
                    expected_sha256=manifest.sha256.get(relative), verification='locked_sha256' if manifest.sha256.get(relative) else 'size_only',
                    reused_installed=relative in reused_installed)
                measurement = staging / (relative + '.download.json')
                if measurement.is_file():
                    item['transfer'] = json.loads(measurement.read_text('utf-8'))
                metadata['files'].append(item)
            receipt = destination / '.2byteasr-source.json'
            temporary = receipt.with_suffix('.pending')
            temporary.write_text(json.dumps(redact(metadata), ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temporary, receipt)
            pending_marker.unlink(missing_ok=True)
            write_transaction(staging, model_key=model_key, destination=destination,
                              files=files, state='published')
            cleanup = discard_published_staging(staging, staging_root=staging_root)
            if cleanup['failures']:
                write_transaction(staging, model_key=model_key, destination=destination,
                                  files=files, state='cleanup_failed', detail=str(cleanup['failures']))
            _emit('[2BYTEASR_STAGING_CLEANUP]', cleanup)
            return manifest.mode
        except Exception as exc:
            last_category=category(exc)
            detail = redact(str(exc)).replace("\r", " ").replace("\n", " ")
            failures.append(f"{manifest.mode}: {detail}")
            if staging.exists():
                write_transaction(staging, model_key=model_key, destination=destination,
                                  files=files, state='paused', detail=detail)
            _emit("[2BYTEASR_SOURCE]", {
                "mode": manifest.mode,
                "label": SOURCE_LABELS[manifest.mode],
                "host": SOURCE_HOSTS[manifest.mode],
                "attempt": attempt,
                "total": len(schedule),
                "status": "failed",
                "category": category(exc),
                "detail": detail[:500],
            })
            if str(mode).upper() != "AUTO":
                break
            if attempt <= len(candidates) and category(exc) in TRANSIENT_CATEGORIES:
                second_round.append(manifest)
        if attempt == len(candidates) == len(schedule) and second_round:
            print('[自动] 每个来源都试过一次；网络暂时异常的来源再试一轮，已校验的文件不会重下', flush=True)
            schedule.extend(second_round)
    _emit('[2BYTEASR_ERROR]',dict(model=model_key,phase='weights_downloading',category=last_category,
        detail='；'.join(failures)))
    raise RuntimeError("所有候选来源均失败：\n" + "\n".join(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--mode", default="AUTO", choices=("AUTO", *SOURCE_MODES))
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
