"""Bounded, resumable ASR chunks and immutable CueDelta events."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .processes import popen_hidden_subprocess
from .resource_governor import GLOBAL_RESOURCE_GOVERNOR, ResourceGovernor, ResourceKind
from .runtime_cache import CacheIdentity, GLOBAL_RUNTIME_CACHE, RuntimeCacheManager


ASR_MANIFEST_SCHEMA = 1


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class CueDelta:
    source_path: str
    manifest_key: str
    backend: str
    chunk_index: int
    state: str
    cues: tuple[Mapping[str, object], ...]
    reused: bool = False
    replacement_mapping: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "cues",
            tuple(_freeze(dict(item)) for item in self.cues),
        )
        object.__setattr__(
            self,
            "replacement_mapping",
            MappingProxyType({
                str(key): tuple(str(item) for item in value)
                for key, value in self.replacement_mapping.items()
            }),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "manifest_key": self.manifest_key,
            "backend": self.backend,
            "chunk_index": self.chunk_index,
            "state": self.state,
            "cues": [_thaw(item) for item in self.cues],
            "reused": self.reused,
            "replacement_mapping": {
                key: list(value) for key, value in self.replacement_mapping.items()
            },
        }


@dataclass(frozen=True)
class ASRChunkSpec:
    index: int
    start_ms: int
    end_ms: int


@dataclass
class ASRChunkRecord:
    index: int
    start_ms: int
    end_ms: int
    status: str = "PENDING"
    cues: list[dict[str, object]] = field(default_factory=list)
    error: str = ""
    elapsed_ms: float = 0.0


class IncrementalASRPipeline:
    """Decode and recognize one bounded source range at a time."""

    def __init__(
        self,
        source_path: str | os.PathLike[str],
        *,
        duration_ms: int,
        backend: str,
        model_revision: str,
        settings: Mapping[str, object] | None,
        ffmpeg_path: str | os.PathLike[str],
        cache_root: str | os.PathLike[str],
        recognize_chunk: Callable[[Path, ASRChunkSpec], Iterable[Mapping[str, object]]],
        event_sink: Callable[[CueDelta], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        chunk_ms: int = 45_000,
        overlap_ms: int = 500,
        cache_manager: RuntimeCacheManager | None = None,
        governor: ResourceGovernor | None = None,
    ) -> None:
        self.source = Path(source_path).resolve()
        self.duration_ms = max(1, int(duration_ms))
        self.backend = str(backend)
        self.model_revision = str(model_revision)
        self.settings = dict(settings or {})
        self.ffmpeg_path = Path(ffmpeg_path).resolve()
        self.cache_root = Path(cache_root).resolve()
        self.recognize_chunk = recognize_chunk
        self.event_sink = event_sink
        self.cancelled = cancelled or (lambda: False)
        self.chunk_ms = max(5_000, int(chunk_ms))
        self.overlap_ms = max(0, min(self.chunk_ms // 4, int(overlap_ms)))
        self.cache_manager = cache_manager or GLOBAL_RUNTIME_CACHE
        self.governor = governor or GLOBAL_RESOURCE_GOVERNOR
        self.identity = CacheIdentity.for_file(
            "asr-chunks",
            self.source,
            schema=ASR_MANIFEST_SCHEMA,
            settings={
                **self.settings,
                "duration_ms": self.duration_ms,
                "chunk_ms": self.chunk_ms,
                "overlap_ms": self.overlap_ms,
            },
            model=f"{self.backend}:{self.model_revision}",
        )
        self.root = self.cache_root / self.identity.key
        self.manifest_path = self.root / "manifest.json"
        self._manifest_lock = threading.Lock()

    def specs(self) -> tuple[ASRChunkSpec, ...]:
        result: list[ASRChunkSpec] = []
        cursor = 0
        index = 0
        step = max(1, self.chunk_ms - self.overlap_ms)
        while cursor < self.duration_ms:
            end = min(self.duration_ms, cursor + self.chunk_ms)
            result.append(ASRChunkSpec(index=index, start_ms=cursor, end_ms=end))
            if end >= self.duration_ms:
                break
            cursor += step
            index += 1
        return tuple(result)

    def run(self) -> tuple[dict[str, object], ...]:
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = self._load_manifest()
        records = {
            int(item["index"]): ASRChunkRecord(**item)
            for item in manifest.get("chunks", [])
            if isinstance(item, Mapping)
        }
        all_cues: list[dict[str, object]] = []
        specs = self.specs()

        def completed(spec: ASRChunkSpec) -> bool:
            record = records.get(spec.index)
            return bool(
                record is not None
                and record.status == "COMPLETE"
                and record.start_ms == spec.start_ms
                and record.end_ms == spec.end_ms
            )

        decode_future: Future[None] | None = None
        decode_index = -1

        def start_decode(executor: ThreadPoolExecutor, start_index: int) -> None:
            nonlocal decode_future, decode_index
            if decode_future is not None:
                return
            for candidate in specs[start_index:]:
                if completed(candidate):
                    continue
                target = self.root / "chunks" / f"{candidate.index:06d}.wav"
                decode_index = candidate.index
                decode_future = executor.submit(self._extract_chunk, candidate, target)
                return

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr-decode-ahead") as decoder:
            start_decode(decoder, 0)
            for spec_offset, spec in enumerate(specs):
                self._raise_if_cancelled()
                record = records.get(spec.index) or ASRChunkRecord(
                    index=spec.index,
                    start_ms=spec.start_ms,
                    end_ms=spec.end_ms,
                )
                records[spec.index] = record
                if completed(spec):
                    rows = tuple(dict(item) for item in record.cues)
                    all_cues.extend(rows)
                    self.cache_manager.telemetry.record(
                        "hit", key=f"{self.identity.key}:{spec.index}", tier="asr_manifest",
                    )
                    self._emit(spec, rows, reused=True)
                    continue
                record.status = "RUNNING"
                record.error = ""
                self._save_manifest(records)
                started = time.perf_counter()
                chunk_path = self.root / "chunks" / f"{spec.index:06d}.wav"
                try:
                    if decode_future is None or decode_index != spec.index:
                        self._extract_chunk(spec, chunk_path)
                    else:
                        decode_future.result()
                        decode_future = None
                        decode_index = -1
                    # One bounded slot decodes N+1 while the ASR owner consumes N.
                    start_decode(decoder, spec_offset + 1)
                    self._raise_if_cancelled()
                    with self.governor.lease(
                        ResourceKind.ASR,
                        foreground=False,
                        cancelled=self.cancelled,
                    ) as allowed:
                        if not allowed:
                            raise InterruptedError("ASR cancelled")
                        raw_rows = tuple(self.recognize_chunk(chunk_path, spec))
                    rows = self._normalize_rows(spec, raw_rows)
                    record.cues = [dict(item) for item in rows]
                    record.status = "COMPLETE"
                    record.elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
                    self._save_manifest(records)
                    all_cues.extend(rows)
                    self.cache_manager.telemetry.record(
                        "generate",
                        key=f"{self.identity.key}:{spec.index}",
                        generation_ms=record.elapsed_ms,
                        completed=True,
                    )
                    self._emit(spec, rows, reused=False)
                except BaseException as exc:
                    record.status = "CANCELLED" if isinstance(exc, InterruptedError) or self.cancelled() else "FAILED"
                    record.error = str(exc)
                    record.elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
                    self._save_manifest(records)
                    if record.status == "CANCELLED":
                        self.cache_manager.record_cancel(f"{self.identity.key}:{spec.index}")
                    raise
        return tuple(all_cues)

    def _emit(self, spec: ASRChunkSpec, rows: tuple[dict[str, object], ...], *, reused: bool) -> None:
        if self.event_sink is None:
            return
        self.event_sink(CueDelta(
            source_path=str(self.source),
            manifest_key=self.identity.key,
            backend=self.backend,
            chunk_index=spec.index,
            state="provisional",
            cues=rows,
            reused=reused,
        ))

    def _normalize_rows(
        self,
        spec: ASRChunkSpec,
        rows: Iterable[Mapping[str, object]],
    ) -> tuple[dict[str, object], ...]:
        result: list[dict[str, object]] = []
        chunk_seconds = max(0.001, (spec.end_ms - spec.start_ms) / 1000.0)
        for row_index, raw in enumerate(rows):
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            try:
                relative_start = max(0.0, float(raw.get("start") or 0.0))
                relative_end = max(relative_start + 0.02, float(raw.get("end") or chunk_seconds))
            except (TypeError, ValueError):
                relative_start, relative_end = 0.0, chunk_seconds
            start_ms = spec.start_ms + round(min(chunk_seconds, relative_start) * 1000)
            end_ms = spec.start_ms + round(min(chunk_seconds, relative_end) * 1000)
            end_ms = max(start_ms + 20, min(spec.end_ms, end_ms))
            stable = hashlib.sha256(
                f"{self.identity.key}:{spec.index}:{row_index}".encode("utf-8")
            ).hexdigest()[:20]
            result.append({
                "id": f"asr-{stable}",
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
                "speaker_id": str(raw.get("speaker") or raw.get("speaker_id") or "S00"),
                "state": "provisional",
                "chunk_index": spec.index,
                "source": str(raw.get("source") or self.backend),
            })
        return tuple(result)

    def _extract_chunk(self, spec: ASRChunkSpec, target: Path) -> None:
        if not self.ffmpeg_path.is_file():
            raise FileNotFoundError(self.ffmpeg_path)
        if target.is_file() and target.stat().st_size > 44:
            self.cache_manager.telemetry.record(
                "disk_hit", key=f"{self.identity.key}:pcm:{spec.index}",
                bytes=target.stat().st_size,
            )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp.wav")
        command = [
            str(self.ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{spec.start_ms / 1000.0:.3f}",
            "-t", f"{(spec.end_ms - spec.start_ms) / 1000.0:.3f}",
            "-i", str(self.source), "-map", "0:a:0", "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary),
        ]
        process = popen_hidden_subprocess(command, purpose="ffmpeg incremental ASR chunk")
        try:
            while process.poll() is None:
                if self.cancelled():
                    process.kill()
                    raise InterruptedError("ASR chunk extraction cancelled")
                time.sleep(0.03)
            if process.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 44:
                raise RuntimeError(f"ASR chunk extraction failed ({process.returncode})")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _load_manifest(self) -> dict[str, object]:
        if not self.manifest_path.is_file():
            return {}
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if (
                int(payload.get("schema_version", 0)) == ASR_MANIFEST_SCHEMA
                and str(payload.get("identity_key")) == self.identity.key
            ):
                return payload
        except (OSError, ValueError, TypeError):
            pass
        return {}

    def _save_manifest(self, records: Mapping[int, ASRChunkRecord]) -> None:
        payload = {
            "schema_version": ASR_MANIFEST_SCHEMA,
            "identity_key": self.identity.key,
            "source": dict(self.identity.source),
            "backend": self.backend,
            "model_revision": self.model_revision,
            "settings": self.settings,
            "chunk_ms": self.chunk_ms,
            "overlap_ms": self.overlap_ms,
            "updated_at": time.time(),
            "chunks": [asdict(records[index]) for index in sorted(records)],
        }
        with self._manifest_lock:
            temporary = self.manifest_path.with_name(f".{self.manifest_path.name}.{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.manifest_path)

    def _raise_if_cancelled(self) -> None:
        if self.cancelled():
            raise InterruptedError("ASR cancelled")


__all__ = [
    "ASR_MANIFEST_SCHEMA", "ASRChunkSpec", "ASRChunkRecord", "CueDelta",
    "IncrementalASRPipeline",
]
