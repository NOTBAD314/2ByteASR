"""Reliable range downloader for large model files.

Completed chunks are kept beside the destination as ``.part.NNN`` files, so
closing the setup window or losing the network does not discard downloaded
data.  The final file is published atomically only after size and SHA-256
validation succeed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_THREADS = 4
RETRIES = 2
MODELSCOPE_LARGE_FILE_THREADS = 4
MODELSCOPE_LARGE_FILE_THRESHOLD = 2 * 1024**3
BLOCK_SIZE = 1 << 20
DEFAULT_MIN_PARALLEL_SIZE = 8 << 20
DEFAULT_STALL_TIMEOUT = 90
CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)

_metrics_lock = threading.Lock()
_network_bytes = 0
_request_count = 0
_actual_hosts = set()
_process_started = time.monotonic()
_first_request_at = None
_last_body_at = None
_reused_bytes = 0
_retry_count = 0
_attempt_context = None


class MeasuredSession(requests.Session):
    def send(self, request, **kwargs):
        global _request_count, _first_request_at
        with _metrics_lock:
            _request_count += 1
            if _first_request_at is None:
                _first_request_at = time.monotonic()
        response = super().send(request, **kwargs)
        with _metrics_lock:
            _actual_hosts.add(urlparse(response.url).hostname or '')
        if getattr(response, '_twobyte_measured', False):
            return response
        response._twobyte_measured = True
        original = response.iter_content
        def measured(*args, **kw):
            global _network_bytes, _last_body_at
            for block in original(*args, **kw):
                with _metrics_lock:
                    _network_bytes += len(block)
                    _last_body_at = time.monotonic()
                yield block
        response.iter_content = measured
        return response


def emit_progress(*, percent: float, downloaded: int, total: int, speed: float, phase: str,
                  file: str = "", file_index: int | None = None, file_total: int | None = None) -> None:
    payload = {
        "percent": round(max(0.0, min(float(percent), 100.0)), 2),
        "downloaded": int(downloaded),
        "total": int(total),
        "speed": round(max(0.0, float(speed)), 1),
        "phase": str(phase),
    }
    if file:
        payload["file"] = str(file)
    if file_index is not None:
        payload["file_index"] = int(file_index)
    if file_total is not None:
        payload["file_total"] = int(file_total)
    print(
        "[2BYTEASR_PROGRESS] " + json.dumps(payload, ensure_ascii=False),
        flush=True,
    )
    if _attempt_context is not None:
        _record_attempt('RUNNING', checkpoint=True)


def _emit_file_start(name: str, total_bytes: int, index: int | None = None, total: int | None = None) -> None:
    payload = {"file": str(name), "size": int(total_bytes)}
    if index is not None:
        payload["index"] = int(index)
    if total is not None:
        payload["total"] = int(total)
    print("[2BYTEASR_FILE] " + json.dumps(payload, ensure_ascii=False), flush=True)


def _session() -> requests.Session:
    session = MeasuredSession()
    session.headers["User-Agent"] = "2ByteASR-downloader/1.1"
    return session


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_file(path: Path, size: int, expected_sha256: str | None) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    return not expected_sha256 or _sha256(path).lower() == expected_sha256.lower()


def _validate_download_response(response, expected_name: str = "") -> None:
    response.raise_for_status()
    content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    content_length = response.headers.get("Content-Length")
    if content_length is not None and int(content_length or 0) <= 0:
        raise RuntimeError("来源返回空响应")
    suffix = Path(expected_name).suffix.lower()
    if content_type in {"text/html", "application/xhtml+xml"}:
        raise RuntimeError(f"来源返回 HTML，而不是模型文件（{response.url}）")
    if content_type in {"application/json", "application/problem+json"} and suffix != ".json":
        raise RuntimeError(f"来源返回 API JSON，而不是模型文件（{response.url}）")


def fetch_size(
    url: str,
    timeout: tuple[int, int] = (30, 60),
    expected_name: str = "",
) -> tuple[int, bool]:
    """Return (size, range_supported) without relying on HEAD.

    ModelScope's repository endpoint accepts GET but rejects HEAD, so probe
    with a one-byte range request and close the body immediately.
    """
    with _session().get(
        url,
        headers={"Range": "bytes=0-0"},
        stream=True,
        allow_redirects=True,
        timeout=timeout,
    ) as response:
        _validate_download_response(response, expected_name)
        # ModelScope currently preserves Content-Range but rewrites HTTP 206 to
        # HTTP 200 on its public API gateway.  A valid Content-Range is therefore
        # a stronger signal than the status code here.
        match = CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", "").strip())
        if match and match.group(3) != "*":
            return int(match.group(3)), True
        length = response.headers.get("Content-Length")
        if not length:
            raise RuntimeError("服务器未返回文件大小")
        return int(length), False


def rank_sources(urls: list[str]) -> list[tuple[str, int, bool]]:
    """Probe candidate mirrors concurrently and return the responsive ones fastest-first."""
    unique_urls = list(dict.fromkeys(urls))
    if len(unique_urls) == 1:
        size, range_supported = fetch_size(unique_urls[0])
        return [(unique_urls[0], size, range_supported)]

    print(f"[择源] 正在并行测速 {len(unique_urls)} 个候选源…", flush=True)

    results: queue.Queue[tuple[str, str, int | BaseException, bool, float]] = queue.Queue()

    def probe(url: str) -> None:
        started = time.monotonic()
        try:
            size, range_supported = fetch_size(url, timeout=(3, 8))
            results.put(("ok", url, size, range_supported, time.monotonic() - started))
        except BaseException as exc:
            results.put(("error", url, exc, False, time.monotonic() - started))

    for url in unique_urls:
        threading.Thread(target=probe, args=(url,), daemon=True).start()

    # A blocked official source must not add eight seconds for every tiny config
    # file.  Once one source answers, allow a short settling window for a faster
    # mirror to finish, then start the real transfer. Probe workers are daemons.
    ranked: list[tuple[str, int, bool, float]] = []
    pending = len(unique_urls)
    hard_deadline = time.monotonic() + 8.5
    settle_deadline: float | None = None
    while pending and time.monotonic() < hard_deadline:
        deadline = min(hard_deadline, settle_deadline) if settle_deadline else hard_deadline
        try:
            status, url, value, range_supported, elapsed = results.get(
                timeout=max(deadline - time.monotonic(), 0.01)
            )
        except queue.Empty:
            break
        pending -= 1
        if status == "ok":
            ranked.append((url, int(value), range_supported, elapsed))
            print(f"  [可用] {elapsed:.2f}s  {url}", flush=True)
            if settle_deadline is None:
                settle_deadline = time.monotonic() + 0.7
        else:
            print(f"  [跳过] {url}：{value}", file=sys.stderr, flush=True)
    ranked.sort(key=lambda item: item[3])
    if ranked:
        print(f"[择源] 优先使用：{ranked[0][0]}", flush=True)
    return [(url, size, range_supported) for url, size, range_supported, _ in ranked]


def _host_token(host: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(host or "unknown")).strip("_") or "unknown"


def _legacy_part_path(out_file: Path, index: int) -> Path:
    return out_file.with_name(f"{out_file.name}.part.{index:03d}")


def _host_part_path(out_file: Path, host: str, index: int) -> Path:
    return out_file.with_name(f"{out_file.name}.part.{_host_token(host)}.{index:03d}")


def _part_path(out_file: Path, index: int, host: str = "") -> Path:
    """Unsigned historical chunks cannot establish a matching file identity."""
    if not host:
        return _legacy_part_path(out_file, index)
    return _host_part_path(out_file, host, index)


def _stream_part_path(out_file: Path, host: str = "") -> Path:
    if not host:
        return out_file.with_name(f"{out_file.name}.part")
    return out_file.with_name(f"{out_file.name}.part.{_host_token(host)}")


def reuse_matching_parts(out_file, part_host, resume_root, expected_sha256):
    """Recover identical per-file chunks after unrelated manifest entries change.

    Caller holds the model lock. Identity includes origin URL, size, SHA and
    range layout; only same-source sibling stages are searched.
    """
    if not resume_root or not expected_sha256:
        return
    root = Path(resume_root).resolve()
    if not out_file.resolve().is_relative_to(root):
        raise ValueError('续传目录必须包含当前模型暂存路径')
    prefix = out_file.name + '.part.' + _host_token(part_host)
    for candidate in root.rglob(prefix + '*'):
        if candidate.parent == out_file.parent or not candidate.is_file() or candidate.is_symlink():
            continue
        if not candidate.resolve().is_relative_to(root):
            continue
        suffix = candidate.name[len(prefix):]
        if suffix and not re.fullmatch(r'\.\d{3}', suffix):
            continue
        target = out_file.parent / candidate.name
        if not target.exists() or target.stat().st_size < candidate.stat().st_size:
            os.replace(candidate, target)
            print(f'[恢复分片] {target.name}：{target.stat().st_size} 字节', flush=True)


def _measurement_payload(*, host, source_mode, size, sha256, url):
    return {
        "schema_version": 1,
        "source_mode": source_mode,
        "host": host,
        "size": int(size),
        "sha256": sha256 or "",
        "url": url,
        "network_payload_bytes": _network_bytes,
        "reused_bytes": _reused_bytes,
        "retry_count": _retry_count,
        "elapsed_s": round(time.monotonic()-_process_started, 6),
        "network_phase_s": round(max(0,(_last_body_at or _process_started)-(_first_request_at or _process_started)), 6),
        "network_mib_per_s": round(_network_bytes / max(.001,(_last_body_at or _process_started)-(_first_request_at or _process_started)) / 1024**2, 6),
        "http_requests": _request_count,
        "actual_hosts": sorted(_actual_hosts),
        "measurement": "response payload bytes consumed including retries; network phase is first request to last body byte, excludes later verification and TLS/HTTP framing",
    }


def _record_attempt(status, *, checkpoint=False, detail=''):
    if _attempt_context is None:
        return
    out_file, context = _attempt_context
    payload = _measurement_payload(**context)
    payload.update(status=status, detail=detail, recorded_at=time.time(),
                   complete_measurement=status != 'RUNNING')
    try:
        if checkpoint:
            target=out_file.with_name(out_file.name+'.attempt.json')
            temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf8')
            os.replace(temporary,target)
        else:
            with out_file.with_name(out_file.name+'.attempts.jsonl').open('a',encoding='utf8') as stream:
                stream.write(json.dumps(payload,ensure_ascii=False)+'\n')
    except OSError as exc:
        print(f'[测量记录失败] {exc}',file=sys.stderr,flush=True)


def write_download_meta(out_file: Path, *, host: str, source_mode: str, size: int, sha256: str | None, url: str) -> None:
    meta = out_file.with_name(f"{out_file.name}.download.json")
    meta.write_text(json.dumps(_measurement_payload(host=host,source_mode=source_mode,
        size=size,sha256=sha256,url=url), ensure_ascii=False), encoding="utf-8")


def _download_chunk(
    url: str,
    part: Path,
    start: int,
    end: int,
    errors: dict[int, BaseException],
    index: int,
    stop_event: threading.Event,
    expected_name: str = "",
) -> None:
    global _retry_count
    if stop_event.is_set():
        return
    expected_length = end - start + 1
    existing_length = part.stat().st_size if part.is_file() else 0
    if existing_length == expected_length:
        print(f"  [复用分片] {index + 1}")
        return
    if existing_length > expected_length:
        part.unlink(missing_ok=True)

    for attempt in range(1, RETRIES + 1):
        try:
            existing_length = part.stat().st_size if part.is_file() else 0
            if existing_length == expected_length:
                print(f"  [续传完成] {index + 1}")
                return
            if existing_length > expected_length:
                part.unlink(missing_ok=True)
                existing_length = 0
            resume_start = start + existing_length
            with _session().get(
                url,
                headers={"Range": f"bytes={resume_start}-{end}"},
                stream=True,
                allow_redirects=True,
                timeout=(30, 45),
            ) as response:
                _validate_download_response(response, expected_name or part.name)
                match = CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", "").strip())
                if not match or int(match.group(1)) != resume_start or int(match.group(2)) != end:
                    raise RuntimeError(
                        f"服务器未按范围返回数据（HTTP {response.status_code}，Content-Range 不匹配）"
                    )
                with part.open("ab" if existing_length else "wb") as handle:
                    for block in response.iter_content(BLOCK_SIZE):
                        if stop_event.is_set():
                            raise RuntimeError("当前源已停止")
                        if block:
                            handle.write(block)
            if part.stat().st_size != expected_length:
                raise RuntimeError(
                    f"分片长度不正确：{part.stat().st_size}/{expected_length} 字节"
                )
            return
        except BaseException as exc:  # keep worker failures visible to the caller
            if stop_event.is_set():
                return
            if attempt == RETRIES:
                errors[index] = exc
                return
            print(f"  分片 {index + 1} 第 {attempt} 次失败，正在重试：{exc}", file=sys.stderr)
            with _metrics_lock:
                _retry_count += 1


def _effective_threads(threads_requested: int, size: int, source_mode: str) -> int:
    threads = min(threads_requested, size)
    if (
        source_mode.upper() == "MODELSCOPE"
        and size >= MODELSCOPE_LARGE_FILE_THRESHOLD
    ):
        threads = min(threads, MODELSCOPE_LARGE_FILE_THREADS)
    return threads


def _publish_parts(
    out_file: Path,
    parts: list[Path],
    size: int,
    expected_sha256: str | None,
) -> None:
    assembling = out_file.with_name(f"{out_file.name}.assembling")
    assembling.unlink(missing_ok=True)
    try:
        with assembling.open("wb") as target:
            for part in parts:
                with part.open("rb") as source:
                    while block := source.read(BLOCK_SIZE):
                        target.write(block)
        if assembling.stat().st_size != size:
            raise RuntimeError(f"合并后大小不正确：{assembling.stat().st_size}/{size} 字节")
        if expected_sha256:
            actual = _sha256(assembling)
            if actual.lower() != expected_sha256.lower():
                for part in parts:
                    part.unlink(missing_ok=True)
                raise RuntimeError(f"SHA-256 不匹配：应为 {expected_sha256}，实际为 {actual}")
        os.replace(assembling, out_file)
    finally:
        assembling.unlink(missing_ok=True)
    for part in parts:
        part.unlink(missing_ok=True)


def stream_download(
    url: str,
    out_file: Path,
    size: int,
    expected_sha256: str | None,
    host: str = "",
) -> int:
    global _reused_bytes, _retry_count
    """Single-stream downloader with a resumable ``.part`` file."""
    partial = _stream_part_path(out_file, host)
    for attempt in range(1, RETRIES + 1):
        offset = partial.stat().st_size if partial.is_file() else 0
        if offset > size:
            partial.unlink(missing_ok=True)
            offset = 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            started_at = time.monotonic()
            last_report_at = started_at
            last_reported_bytes = offset
            with _session().get(
                url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=(30, 300),
            ) as response:
                _validate_download_response(response, out_file.name)
                content_range = CONTENT_RANGE.fullmatch(
                    response.headers.get("Content-Range", "").strip()
                )
                resumed = bool(
                    offset
                    and content_range
                    and int(content_range.group(1)) == offset
                    and content_range.group(3) != "*"
                    and int(content_range.group(3)) == size
                )
                if offset and not resumed:
                    partial.unlink(missing_ok=True)
                    offset = 0
                if attempt == 1:
                    _reused_bytes = offset
                mode = "ab" if resumed else "wb"
                with partial.open(mode) as handle:
                    for block in response.iter_content(BLOCK_SIZE):
                        if block:
                            handle.write(block)
                            current = handle.tell()
                            now = time.monotonic()
                            if now - last_report_at >= 1.0:
                                speed = max(current - last_reported_bytes, 0) / max(now - last_report_at, 0.001)
                                emit_progress(
                                    percent=current * 100 / size,
                                    downloaded=current,
                                    total=size,
                                    speed=speed,
                                    phase="download",
                                )
                                last_report_at = now
                                last_reported_bytes = current
            if partial.stat().st_size != size:
                raise RuntimeError(f"下载大小不正确：{partial.stat().st_size}/{size} 字节")
            if expected_sha256:
                actual = _sha256(partial)
                if actual.lower() != expected_sha256.lower():
                    partial.unlink(missing_ok=True)
                    raise RuntimeError(f"SHA-256 不匹配：应为 {expected_sha256}，实际为 {actual}")
            os.replace(partial, out_file)
            emit_progress(percent=100, downloaded=size, total=size, speed=0, phase="verify")
            return 0
        except BaseException as exc:
            if attempt == RETRIES:
                print(f"下载失败：{exc}", file=sys.stderr)
                return 1
            print(f"第 {attempt} 次失败，保留断点后重试：{exc}", file=sys.stderr)
            _retry_count += 1
    return 1


def download_from_source(
    url: str,
    out_file: Path,
    size: int,
    range_supported: bool,
    threads_requested: int,
    expected_sha256: str | None,
    min_parallel_size: int,
    stall_timeout: int,
    host: str = "",
    source_mode: str = "",
    resume_root: Path | None = None,
) -> int:
    """Download one candidate source; return non-zero so the caller can switch mirrors."""
    global _reused_bytes
    if _valid_file(out_file, size, expected_sha256):
        _reused_bytes += size
        print(f"[复用] {out_file} 已完整并通过校验（{size} 字节）")
        return 0
    # A changed revision, hash, range layout or origin never reuses old bytes.
    # Keep old partials for diagnosis; identity separates them without deletion.
    identity = hashlib.sha256(json.dumps([url,size,expected_sha256,threads_requested],sort_keys=True).encode()).hexdigest()[:12]
    part_host = host + '-' + identity
    reuse_matching_parts(out_file, part_host, resume_root, expected_sha256)
    if shutil.disk_usage(out_file.parent).free < size * 2 + 256 * 1024**2:
        raise OSError('磁盘空间不足：下载分片与原子合并需要额外空间')
    if out_file.exists():
        print(f"[重下] 已有文件大小或哈希不正确：{out_file}", file=sys.stderr)
        out_file.unlink()

    print(f"[下载] {url}")
    print(f"       大小 {size / 1024 / 1024:.0f} MB")
    # Structured marker so the GUI can show the real current file immediately
    try:
        print("[2BYTEASR_FILE] " + json.dumps({
            "file": out_file.name,
            "size": int(size),
        }, ensure_ascii=False), flush=True)
    except Exception:
        pass
    if not range_supported or size < min_parallel_size:
        reason = "小文件" if range_supported else "服务器不支持并行分片"
        print(f"       {reason}，使用可续传单流下载")
        result = stream_download(url, out_file, size, expected_sha256, host=part_host)
        if result == 0:
            write_download_meta(
                out_file, host=host, source_mode=source_mode, size=size,
                sha256=expected_sha256, url=url,
            )
        return result

    threads = _effective_threads(threads_requested, size, source_mode)
    print(f"       {threads} 线程分片；中断后会复用已完成分片")
    chunk_size = (size + threads - 1) // threads
    ranges = [
        (index, index * chunk_size, min(size - 1, (index + 1) * chunk_size - 1))
        for index in range(threads)
        if index * chunk_size < size
    ]
    parts = [_part_path(out_file, index, part_host) for index, _, _ in ranges]
    _reused_bytes = sum(min(p.stat().st_size, end-start+1) if p.is_file() else 0
                        for p, (_, start, end) in zip(parts, ranges))
    errors: dict[int, BaseException] = {}
    stop_event = threading.Event()
    pool = [
        threading.Thread(
            target=_download_chunk,
            args=(url, parts[index], start, end, errors, index, stop_event, out_file.name),
            daemon=True,
        )
        for index, start, end in ranges
    ]
    started_at = time.monotonic()
    last_report_at = started_at
    last_reported_bytes = sum(p.stat().st_size if p.is_file() else 0 for p in parts)
    for worker in pool:
        worker.start()
    last_progress_at = started_at
    highest_downloaded_bytes = 0
    while any(worker.is_alive() for worker in pool):
        for worker in pool:
            worker.join(timeout=0.2)
        now = time.monotonic()
        downloaded_bytes = sum(
            min(part.stat().st_size, end - start + 1) if part.is_file() else 0
            for part, (_, start, end) in zip(parts, ranges)
        )
        if downloaded_bytes > highest_downloaded_bytes:
            highest_downloaded_bytes = downloaded_bytes
            last_progress_at = now
        if now - last_progress_at >= stall_timeout:
            print(
                f"下载连续 {stall_timeout} 秒没有有效进展，停止当前源并准备切换。",
                file=sys.stderr,
                flush=True,
            )
            stop_event.set()
            for worker in pool:
                worker.join(timeout=50)
            print("已完成分片会保留；不会删除可续传内容。", file=sys.stderr, flush=True)
            return 1
        if now - last_report_at >= 1:
            interval = max(now - last_report_at, 0.001)
            speed = max(downloaded_bytes - last_reported_bytes, 0) / interval
            percent = min(downloaded_bytes * 100 / size, 100)
            print(
                f"[进度] {percent:5.1f}%  "
                f"{downloaded_bytes / 1024 / 1024:.1f}/{size / 1024 / 1024:.1f} MB  "
                f"{speed / 1024 / 1024:.2f} MB/s",
                flush=True,
            )
            emit_progress(
                percent=percent,
                downloaded=downloaded_bytes,
                total=size,
                speed=speed,
                phase="download",
            )
            last_report_at = now
            last_reported_bytes = downloaded_bytes

    elapsed = max(time.monotonic() - started_at, 0.001)
    downloaded_bytes = sum(
        min(part.stat().st_size, end - start + 1) if part.is_file() else 0
        for part, (_, start, end) in zip(parts, ranges)
    )
    print(
        f"[分片结束] {downloaded_bytes / 1024 / 1024:.1f} MB，耗时 {elapsed:.1f} 秒",
        flush=True,
    )

    if errors:
        for index, exc in sorted(errors.items()):
            print(f"分片 {index + 1} 下载失败：{exc}", file=sys.stderr)
        print("已完成的分片会保留；正在尝试下一个源。", file=sys.stderr)
        return 1
    try:
        emit_progress(percent=100, downloaded=size, total=size, speed=0, phase="verify")
        _publish_parts(out_file, parts, size, expected_sha256)
        write_download_meta(
            out_file, host=host, source_mode=source_mode, size=size,
            sha256=expected_sha256, url=url,
        )
    except BaseException as exc:
        print(f"文件合并或校验失败：{exc}", file=sys.stderr)
        return 1
    print(f"[完成] {out_file}（{size} 字节）")
    return 0


def _emit_source_line(url: str, source_mode: str, attempt: int, total: int, status: str) -> None:
    host = urlparse(url).hostname or ""
    try:
        from twobyteasr.download_sources import SOURCE_LABELS, emit_source_event

        class _Resolved:
            mode = source_mode or "AUTO"
            host = host
            label = SOURCE_LABELS.get(source_mode or "AUTO", source_mode or "自动")
            url = url

        print(emit_source_event(_Resolved(), attempt=attempt, total=total, status=status), flush=True)
    except Exception:
        print(
            "[2BYTEASR_SOURCE] "
            + json.dumps(
                {
                    "mode": source_mode or "AUTO",
                    "host": host,
                    "url": url,
                    "attempt": attempt,
                    "total": total,
                    "status": status,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


def _report_source_failure(exc: BaseException, url: str, source_mode: str) -> str:
    try:
        from twobyteasr.download_sources import (
            DownloadSourceError,
            classify_error_text,
            hostname_of,
            user_facing_error,
        )

        wrapped = DownloadSourceError(
            classify_error_text(str(exc)),
            source_mode=source_mode or "AUTO",
            host=hostname_of(url),
            detail=str(exc),
            url=url,
        )
        error = user_facing_error(wrapped)
        print(error.message, file=sys.stderr, flush=True)
        print(error.next_action, file=sys.stderr, flush=True)
        print(f"source_unavailable={error.category}" if error.category == "source_unavailable" else f"category={error.category}", flush=True)
        return error.category
    except Exception:
        print(f"当前来源失败：{exc}", file=sys.stderr, flush=True)
        return "unknown"


def main() -> int:
    global _network_bytes, _request_count, _actual_hosts, _process_started
    global _first_request_at, _last_body_at, _reused_bytes, _retry_count, _attempt_context
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument("--sha256")
    parser.add_argument("--source-mode", default="")
    parser.add_argument("--resume-root", type=Path)
    parser.add_argument(
        "--min-parallel-size",
        type=int,
        default=DEFAULT_MIN_PARALLEL_SIZE,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stall-timeout",
        type=int,
        default=DEFAULT_STALL_TIMEOUT,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.threads < 1 or args.threads > 32:
        parser.error("--threads 必须在 1 到 32 之间")
    if args.stall_timeout < 10:
        parser.error("--stall-timeout 不能小于 10 秒")
    if args.sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256):
        parser.error("--sha256 必须是 64 位十六进制字符串")

    out_file = Path(args.out).resolve()
    if not out_file.parent.is_dir():
        print(f"输出目录不存在：{out_file.parent}", file=sys.stderr)
        return 1

    source_mode = (args.source_mode or "").strip().upper()
    allow_fallback = source_mode in {"", "AUTO"}
    urls = list(dict.fromkeys(args.url))
    if not allow_fallback:
        urls = urls[:1]

    last_category = "unknown"
    for index, url in enumerate(urls, start=1):
        host = urlparse(url).hostname or ""
        _network_bytes=_request_count=_reused_bytes=_retry_count=0
        _actual_hosts=set()
        _process_started=time.monotonic()
        _first_request_at=_last_body_at=None
        context=dict(host=host,source_mode=source_mode or 'AUTO',size=0,sha256=args.sha256,url=url)
        _attempt_context=(out_file,context)
        _emit_source_line(url, source_mode or "AUTO", index, len(urls), "trying")
        try:
            size, range_supported = fetch_size(url, expected_name=Path(args.out).name)
            context['size']=size
        except BaseException as exc:
            _record_attempt('FAIL',detail=str(exc))
            last_category = _report_source_failure(exc, url, source_mode or "AUTO")
            if not allow_fallback:
                print("当前指定源不可用，不会自动改用其他源。", file=sys.stderr)
                print("请更换下载源后重试；已完成分片会保留。", flush=True)
                return 1
            print(f"[回退] {host or url} 不可用，按顺序尝试下一源。", flush=True)
            continue
        if index > 1:
            print(f"[回退] 第 {index}/{len(urls)} 个源：{host}", flush=True)
        try:
            result = download_from_source(
                url,out_file,size,range_supported,args.threads,args.sha256,
                args.min_parallel_size,args.stall_timeout,host=host,
                source_mode=source_mode or 'AUTO',resume_root=args.resume_root)
        except Exception as exc:
            if isinstance(exc,PermissionError) or '磁盘空间不足' in str(exc):
                _record_attempt('FAIL',detail=str(exc))
                category='permission' if isinstance(exc,PermissionError) else 'disk_space'
                print('[2BYTEASR_ERROR] '+json.dumps(dict(category=category,phase='weights_downloading',detail=str(exc)),ensure_ascii=False),flush=True)
                return 1
            _report_source_failure(exc,url,source_mode or 'AUTO')
            result=1
        _record_attempt('PASS' if result==0 else 'FAIL',detail='' if result==0 else 'See downloader stderr for artifact failure')
        if result == 0:
            _emit_source_line(url, source_mode or "AUTO", index, len(urls), "selected")
            return 0
        last_category = _report_source_failure(
            RuntimeError("下载未完成"), url, source_mode or "AUTO"
        )
        if not allow_fallback:
            print("当前指定源下载失败，不会自动改用其他源。", file=sys.stderr)
            print("请更换下载源后重试；已完成分片会保留。", flush=True)
            return 1
    print("所有候选下载源均失败；已完成分片仍会保留。", file=sys.stderr)
    if last_category == "source_unavailable":
        print("source_unavailable", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
