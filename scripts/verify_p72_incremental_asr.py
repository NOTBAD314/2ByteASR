"""P7.2 real SenseVoice and long-media structural ASR evidence.

The 10-minute case runs the installed SenseVoice model on real recorded media.
The 1h/2h cases exercise real FFmpeg chunk decoding, manifests, and resume with
a deterministic recognizer so their model inference status stays explicit.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p72" / "asr-runtime"
SOURCE_PROJECT = ROOT / "tmp" / "p66-runtime" / "formal" / "p66-real-hour.2byteproj"
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
MODEL = ROOT / "models" / "SenseVoiceSmall"
RUN = OUTPUT / f"run-{int(time.time())}-{os.getpid()}"
RUN.mkdir(parents=True, exist_ok=True)
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(RUN / "child-processes.jsonl")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil

from twobyteasr import asr
from twobyteasr.incremental_asr import ASRChunkSpec, CueDelta, IncrementalASRPipeline
from twobyteasr.processes import popen_hidden_subprocess, stop_process_tree
from twobyteasr.runtime_cache import RuntimeCacheManager


TEN_MINUTES_MS = 10 * 60 * 1000
STRUCTURAL_DURATIONS = {"1h": 60 * 60 * 1000, "2h": 2 * 60 * 60 * 1000}


def progress(message: str) -> None:
    print(f"[p72-asr] {message}", flush=True)


def descendants() -> set[int]:
    result = {os.getpid()}
    try:
        result.update(item.pid for item in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return result


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return round(ordered[index], 3)


def source_media() -> Path:
    payload = json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))
    path = Path(str(payload["media"]["path"])).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


class MetricPipeline(IncrementalASRPipeline):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.decode_spans: list[dict[str, object]] = []
        self._decode_lock = threading.Lock()
        self.max_decode_depth = 0
        self._decode_depth = 0

    def _extract_chunk(self, spec: ASRChunkSpec, target: Path) -> None:
        started = time.perf_counter()
        with self._decode_lock:
            self._decode_depth += 1
            self.max_decode_depth = max(self.max_decode_depth, self._decode_depth)
        try:
            super()._extract_chunk(spec, target)
        finally:
            finished = time.perf_counter()
            with self._decode_lock:
                self._decode_depth -= 1
                self.decode_spans.append({
                    "chunk_index": spec.index,
                    "start_monotonic": started,
                    "end_monotonic": finished,
                    "elapsed_ms": round((finished - started) * 1000.0, 3),
                    "bytes": target.stat().st_size if target.is_file() else 0,
                })


class GPUSampler:
    def __init__(self) -> None:
        self.samples: list[dict[str, object]] = []
        self.process = None
        self.thread = None

    def start(self) -> None:
        self.process = popen_hidden_subprocess(
            ["nvidia-smi", "dmon", "-s", "um", "-d", "1"],
            purpose="P7.2 ASR GPU sampler",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        def read() -> None:
            assert self.process is not None
            for line in self.process.stdout:
                values = line.strip().split()
                if not values or values[0].startswith("#") or len(values) < 9:
                    continue
                try:
                    self.samples.append({
                        "monotonic": time.perf_counter(),
                        "sm_percent": int(values[1]),
                        "memory_percent": int(values[2]),
                        "framebuffer_mb": int(values[7]),
                    })
                except (TypeError, ValueError):
                    continue

        self.thread = threading.Thread(target=read, name="p72-gpu-sampler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.process is not None:
            stop_process_tree(self.process)
        if self.thread is not None:
            self.thread.join(timeout=3.0)

    def summary(self) -> dict[str, object]:
        sm = [float(item["sm_percent"]) for item in self.samples]
        memory = [int(item["framebuffer_mb"]) for item in self.samples]
        return {
            "sample_count": len(self.samples),
            "sm_p50_percent": percentile(sm, 0.50),
            "sm_p95_percent": percentile(sm, 0.95),
            "sm_max_percent": max(sm, default=0.0),
            "framebuffer_max_mb": max(memory, default=0),
            "samples": self.samples,
        }


def model_revision() -> str:
    weights = MODEL / "model.pt"
    stat = weights.stat()
    return f"SenseVoiceSmall:{stat.st_size}:{stat.st_mtime_ns}"


def real_recognizer(spans: list[dict[str, object]], started_event=None):
    def recognize(path: Path, spec: ASRChunkSpec):
        started = time.perf_counter()
        if started_event is not None:
            started_event.set()
        duration = max(0.02, (spec.end_ms - spec.start_ms) / 1000.0)
        try:
            rows = asr.transcribe_primary_reference(
                "sensevoice", str(path), [{"start": 0.0, "end": duration}],
                None, duration,
            )
        except RuntimeError as exc:
            if "没有生成有效文字" in str(exc):
                rows = []
            else:
                raise
        finished = time.perf_counter()
        spans.append({
            "chunk_index": spec.index,
            "start_monotonic": started,
            "end_monotonic": finished,
            "elapsed_ms": round((finished - started) * 1000.0, 3),
            "cue_count": len(rows),
        })
        return rows

    return recognize


def overlap_evidence(
    decode_spans: list[dict[str, object]],
    recognize_spans: list[dict[str, object]],
) -> list[dict[str, object]]:
    decoded = {int(item["chunk_index"]): item for item in decode_spans}
    rows = []
    for recognition in recognize_spans:
        index = int(recognition["chunk_index"])
        following = decoded.get(index + 1)
        if following is None:
            continue
        overlap_ms = max(0.0, min(
            float(recognition["end_monotonic"]),
            float(following["end_monotonic"]),
        ) - max(
            float(recognition["start_monotonic"]),
            float(following["start_monotonic"]),
        )) * 1000.0
        rows.append({
            "recognize_chunk": index,
            "decode_chunk": index + 1,
            "overlap_ms": round(overlap_ms, 3),
        })
    return rows


def run_real_ten_minutes(source: Path, cache: RuntimeCacheManager) -> dict[str, object]:
    events: list[dict[str, object]] = []
    recognize_spans: list[dict[str, object]] = []
    started = time.perf_counter()

    def event_sink(delta: CueDelta) -> None:
        events.append({
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "chunk_index": delta.chunk_index,
            "cue_count": len(delta.cues),
            "reused": delta.reused,
            "sample_text": str(delta.cues[0].get("text", ""))[:120] if delta.cues else "",
        })

    pipeline = MetricPipeline(
        source,
        duration_ms=TEN_MINUTES_MS,
        backend="sensevoice",
        model_revision=model_revision(),
        settings={"sample_rate": 16_000, "case": "real-10m"},
        ffmpeg_path=FFMPEG,
        cache_root=RUN / "real-sensevoice-cache",
        recognize_chunk=real_recognizer(recognize_spans),
        event_sink=event_sink,
        cache_manager=cache,
    )
    rows = pipeline.run()
    elapsed = time.perf_counter() - started
    resume_events: list[dict[str, object]] = []
    resume_started = time.perf_counter()
    resumed = MetricPipeline(
        source,
        duration_ms=TEN_MINUTES_MS,
        backend="sensevoice",
        model_revision=model_revision(),
        settings={"sample_rate": 16_000, "case": "real-10m"},
        ffmpeg_path=FFMPEG,
        cache_root=RUN / "real-sensevoice-cache",
        recognize_chunk=lambda *_args: (_ for _ in ()).throw(
            AssertionError("completed real chunk was recognized again")
        ),
        event_sink=lambda delta: resume_events.append(delta.to_payload()),
        cache_manager=cache,
    )
    resumed_rows = resumed.run()
    resume_ms = (time.perf_counter() - resume_started) * 1000.0
    overlaps = overlap_evidence(pipeline.decode_spans, recognize_spans)
    first = next((event for event in events if event["cue_count"]), None)
    return {
        "source": str(source),
        "duration_ms": TEN_MINUTES_MS,
        "wall_seconds": round(elapsed, 3),
        "time_to_first_cue_ms": first["elapsed_ms"] if first else None,
        "audio_throughput_x": round((TEN_MINUTES_MS / 1000.0) / elapsed, 3),
        "rtf": round(elapsed / (TEN_MINUTES_MS / 1000.0), 4),
        "cue_count": len(rows),
        "chunk_count": len(pipeline.specs()),
        "events": events,
        "recognize_spans": recognize_spans,
        "decode_spans": pipeline.decode_spans,
        "decode_depth_max": pipeline.max_decode_depth,
        "decode_asr_overlaps": overlaps,
        "overlap_pair_count": sum(item["overlap_ms"] > 0 for item in overlaps),
        "resume_ms": round(resume_ms, 3),
        "resume_reused_chunks": sum(bool(item["reused"]) for item in resume_events),
        "resume_cue_count": len(resumed_rows),
        "manifest": str(pipeline.manifest_path),
    }


def run_real_cancel_resume(source: Path, cache: RuntimeCacheManager) -> dict[str, object]:
    cancelled = threading.Event()
    recognize_started = threading.Event()
    recognize_spans: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    outcome: dict[str, object] = {}
    pipeline = MetricPipeline(
        source,
        duration_ms=120_000,
        backend="sensevoice",
        model_revision=model_revision(),
        settings={"sample_rate": 16_000, "case": "real-cancel-resume"},
        ffmpeg_path=FFMPEG,
        cache_root=RUN / "cancel-resume-cache",
        recognize_chunk=real_recognizer(recognize_spans, recognize_started),
        event_sink=lambda delta: events.append(delta.to_payload()),
        cancelled=cancelled.is_set,
        cache_manager=cache,
    )

    def execute() -> None:
        try:
            pipeline.run()
            outcome["result"] = "completed"
        except BaseException as exc:
            outcome["result"] = type(exc).__name__
            outcome["error"] = str(exc)

    thread = threading.Thread(target=execute, name="p72-real-asr-cancel")
    thread.start()
    if not recognize_started.wait(120.0):
        raise TimeoutError("SenseVoice cancellation case did not start recognition")
    time.sleep(0.25)
    cancel_started = time.perf_counter()
    cancelled.set()
    thread.join(timeout=180.0)
    cancel_ms = (time.perf_counter() - cancel_started) * 1000.0
    if thread.is_alive():
        raise TimeoutError("SenseVoice cancellation did not settle")

    resume_events: list[dict[str, object]] = []
    resume_spans: list[dict[str, object]] = []
    resume_started = time.perf_counter()
    resumed = MetricPipeline(
        source,
        duration_ms=120_000,
        backend="sensevoice",
        model_revision=model_revision(),
        settings={"sample_rate": 16_000, "case": "real-cancel-resume"},
        ffmpeg_path=FFMPEG,
        cache_root=RUN / "cancel-resume-cache",
        recognize_chunk=real_recognizer(resume_spans),
        event_sink=lambda delta: resume_events.append(delta.to_payload()),
        cache_manager=cache,
    )
    rows = resumed.run()
    return {
        "cancel_request_to_settled_ms": round(cancel_ms, 3),
        "cancel_outcome": outcome,
        "completed_before_cancel": sum(item.get("reused") is False for item in events),
        "resume_wall_seconds": round(time.perf_counter() - resume_started, 3),
        "resume_reused_chunks": sum(bool(item["reused"]) for item in resume_events),
        "resume_generated_chunks": sum(not bool(item["reused"]) for item in resume_events),
        "resume_cue_count": len(rows),
        "manifest": str(pipeline.manifest_path),
    }


def run_structural(source: Path, label: str, duration_ms: int) -> dict[str, object]:
    cache = RuntimeCacheManager(
        memory_budget_bytes=32 * 1024 * 1024,
        disk_budget_bytes=1024 * 1024 * 1024,
    )
    events: list[dict[str, object]] = []
    started = time.perf_counter()
    pipeline = MetricPipeline(
        source,
        duration_ms=duration_ms,
        backend="structural-fixture",
        model_revision="no-model-v1",
        settings={"sample_rate": 16_000, "benchmark_duration_ms": duration_ms},
        ffmpeg_path=FFMPEG,
        cache_root=RUN / "structural-chunks" / label,
        recognize_chunk=lambda _path, spec: [{
            "start": 0.0,
            "end": min(1.0, (spec.end_ms - spec.start_ms) / 1000.0),
            "text": f"structural chunk {spec.index}",
            "source": "structural-fixture",
        }],
        event_sink=lambda delta: events.append(delta.to_payload()),
        cache_manager=cache,
    )
    rows = pipeline.run()
    elapsed = time.perf_counter() - started
    resume_events: list[dict[str, object]] = []
    resume_started = time.perf_counter()
    resumed = MetricPipeline(
        source,
        duration_ms=duration_ms,
        backend="structural-fixture",
        model_revision="no-model-v1",
        settings={"sample_rate": 16_000, "benchmark_duration_ms": duration_ms},
        ffmpeg_path=FFMPEG,
        cache_root=RUN / "structural-chunks" / label,
        recognize_chunk=lambda *_args: (_ for _ in ()).throw(
            AssertionError("completed structural chunk was recognized again")
        ),
        event_sink=lambda delta: resume_events.append(delta.to_payload()),
        cache_manager=cache,
    )
    resumed_rows = resumed.run()
    return {
        "label": label,
        "duration_ms": duration_ms,
        "chunk_count": len(pipeline.specs()),
        "wall_seconds": round(elapsed, 3),
        "decode_throughput_x": round((duration_ms / 1000.0) / elapsed, 3),
        "decoded_bytes": sum(int(item["bytes"]) for item in pipeline.decode_spans),
        "cue_count": len(rows),
        "decode_depth_max": pipeline.max_decode_depth,
        "resume_ms": round((time.perf_counter() - resume_started) * 1000.0, 3),
        "resume_reused_chunks": sum(bool(item["reused"]) for item in resume_events),
        "resume_cue_count": len(resumed_rows),
        "manifest": str(pipeline.manifest_path),
    }


def child_records() -> list[dict[str, object]]:
    path = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("root_pid") == os.getpid():
            rows.append(row)
    return rows


def main() -> int:
    result: dict[str, object] = {
        "schema": "2byteasr.p72-incremental-asr.v1",
        "evidence_class": "REAL MEDIA + REAL SENSEVOICE / STRUCTURAL LONG-MEDIA",
        "real_user_click": False,
        "run_root": str(RUN),
        "real_model_scope": "10m plus 2m cancel/resume",
        "one_hour_real_model": "NOT VERIFIED",
        "two_hour_real_model": "NOT VERIFIED",
    }
    before_pids = descendants()
    sampler = GPUSampler()
    cache = RuntimeCacheManager(
        memory_budget_bytes=64 * 1024 * 1024,
        disk_budget_bytes=2 * 1024 * 1024 * 1024,
    )
    try:
        source = source_media()
        result["source"] = str(source)
        result["source_size"] = source.stat().st_size
        sampler.start()
        asr.begin_local_asr_session(persistent=True)
        progress("running real SenseVoice on 10 minutes")
        result["sensevoice_10m"] = run_real_ten_minutes(source, cache)
        progress("running real SenseVoice cancellation and resume")
        result["sensevoice_cancel_resume"] = run_real_cancel_resume(source, cache)
        result["model_session"] = asr.local_asr_session_state()
        asr.end_local_asr_session(force=True)
        sampler.stop()
        result["gpu"] = sampler.summary()

        structural = {}
        for label, duration_ms in STRUCTURAL_DURATIONS.items():
            progress(f"running {label} structural decode and resume")
            structural[label] = run_structural(source, label, duration_ms)
        result["structural"] = structural
        result["cache_telemetry"] = cache.snapshot()
        result["child_process_records"] = child_records()
        child_starts = [
            row for row in result["child_process_records"]
            if row.get("phase") == "start"
        ]
        ten = result["sensevoice_10m"]
        cancel = result["sensevoice_cancel_resume"]
        result["checks"] = {
            "real_first_cue_emitted": ten["time_to_first_cue_ms"] is not None,
            "real_all_chunks_completed": ten["chunk_count"] == len(ten["events"]),
            "real_resume_reused_all_chunks": ten["resume_reused_chunks"] == ten["chunk_count"],
            "decode_depth_bounded_one": ten["decode_depth_max"] <= 1,
            "decode_asr_overlap_observed": ten["overlap_pair_count"] > 0,
            "cancelled": cancel["cancel_outcome"].get("result") == "InterruptedError",
            "cancel_resume_reused_completed": cancel["resume_reused_chunks"] > 0,
            "structural_1h_reused_all": structural["1h"]["resume_reused_chunks"] == structural["1h"]["chunk_count"],
            "structural_2h_reused_all": structural["2h"]["resume_reused_chunks"] == structural["2h"]["chunk_count"],
            "all_children_hidden": all(bool(row.get("hidden")) for row in child_starts),
            "no_child_windows": all(not row.get("windows") for row in child_starts),
        }
        result["pass"] = all(result["checks"].values())
    except BaseException as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["pass"] = False
    finally:
        try:
            asr.end_local_asr_session(force=True)
        except Exception:
            pass
        try:
            sampler.stop()
        except Exception:
            pass
        remaining = descendants() - before_pids - {os.getpid()}
        result["remaining_child_pids"] = sorted(remaining)
        result["no_remaining_children"] = not remaining
        result["pass"] = bool(result.get("pass") and result["no_remaining_children"])
    target = RUN / "runtime-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = OUTPUT / "latest-result.json"
    latest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target, flush=True)
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
