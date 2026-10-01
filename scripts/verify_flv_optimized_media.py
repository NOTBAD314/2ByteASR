"""Acceptance checks for FLV lossless remux + progressive waveform.

Runs the real ffmpeg/ffprobe/PyAV stack against a synthetic long FLV and
writes a JSON report: remux container/caching/validation, PyAV seek latency
(original vs optimized), waveform stage timings, zoom LOD behavior, warm
reopen, and child-process hygiene. Usage:

    python scripts/verify_flv_optimized_media.py [--minutes 32] [--keep]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"


def run(command, **kwargs):
    return subprocess.run([str(part) for part in command],
                          capture_output=True, text=True, **kwargs)


def probe(path: Path, extra=()) -> dict:
    result = run([FFPROBE, "-v", "error", *extra,
                  "-show_entries",
                  "format=duration,size:stream=index,codec_type,codec_name",
                  "-of", "json", path])
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=32)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    out_dir = ROOT / "tmp" / "flv-optimized-acceptance"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    report: dict = {"checks": {}, "failures": []}

    def check(name: str, ok: bool, detail=None) -> bool:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            report["failures"].append(name)
        print(("[PASS] " if ok else "[FAIL] ") + name +
              (f" :: {detail}" if detail else ""))
        return bool(ok)

    # ---------------------------------------------------------------- media
    seconds = args.minutes * 60
    flv = out_dir / "long.flv"
    print(f"generating {args.minutes}-minute synthetic FLV …")
    started = time.perf_counter()
    # Varying audio amplitude so the waveform/outline carry visible structure.
    encode = run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size=640x360:rate=30",
        "-f", "lavfi", "-i",
        (f"aevalsrc='0.55*sin(880*2*PI*t)*abs(sin(0.23*t))':d={seconds}:s=44100"),
        "-c:v", "libx264", "-preset", "ultrafast", "-g", "60",
        "-c:a", "aac", "-b:a", "96k", "-f", "flv", str(flv),
    ])
    if encode.returncode:
        print(encode.stderr[-1500:])
        return 2
    report["media_encode_s"] = round(time.perf_counter() - started, 2)
    source_probe = probe(flv)
    duration_s = float(source_probe["format"]["duration"])
    size_bytes = flv.stat().st_size
    print(f"FLV ready: {duration_s:.1f}s, {size_bytes/1e6:.1f} MB")

    # ------------------------------------------------- A: remux MP4 + cache
    from twobyteasr.indexed_media import IndexedMediaCache
    cache = IndexedMediaCache(root=out_dir / "seek-cache")

    remux_started = time.perf_counter()
    cache.resolve(str(flv))
    target = Path(cache.wait_optimized(str(flv), timeout=1800))
    remux_s = time.perf_counter() - remux_started
    report["remux_s"] = round(remux_s, 2)
    check("A1_remux_produced_optimized_copy",
          target.is_file() and target.suffix == ".mp4" and target != flv,
          f"{target.name} in {remux_s:.2f}s")

    optimized_probe = probe(target)
    src_codecs = sorted((s["codec_type"], s["codec_name"]) for s in source_probe["streams"])
    dst_codecs = sorted((s["codec_type"], s["codec_name"]) for s in optimized_probe["streams"])
    check("A2_stream_copy_same_codecs", src_codecs == dst_codecs, f"{src_codecs}")

    duration_delta = abs(float(optimized_probe["format"]["duration"]) - duration_s)
    check("A3_duration_preserved", duration_delta < 0.5, f"delta={duration_delta:.3f}s")

    # Packet counts prove no frames were dropped, added or re-encoded.
    def packets(path: Path) -> dict:
        payload = run([FFPROBE, "-v", "error", "-count_packets",
                       "-show_entries", "stream=codec_type,nb_read_packets",
                       "-of", "json", path])
        data = json.loads(payload.stdout)
        return {s["codec_type"]: int(s.get("nb_read_packets") or 0) for s in data["streams"]}
    src_packets, dst_packets = packets(flv), packets(target)
    check("A4_packet_counts_identical", src_packets == dst_packets,
          f"{src_packets} vs {dst_packets}")

    # Disk-bound remux throughput (sanity: far above encode speed).
    throughput = size_bytes / 1e6 / max(remux_s, 0.001)
    check("A5_remux_disk_bound_throughput", throughput > 25,
          f"{throughput:.0f} MB/s effective")

    # Second open: cache hit, no remux process, instant.
    def refuse(self, *a, **k):
        raise AssertionError("remux re-ran on warm cache")
    cache._remux = refuse.__get__(cache, type(cache))
    warm_started = time.perf_counter()
    warm = Path(cache.resolve(str(flv)))
    warm_ms = (time.perf_counter() - warm_started) * 1000
    check("A6_second_open_cache_hit", warm == target and warm_ms < 250,
          f"{warm_ms:.1f} ms")

    # ------------------------------------------- seek latency (PyAV/filmstrip)
    import av
    def seek_ms(path: Path, targets) -> float:
        container = av.open(str(path), timeout=(1.0, 1.0))
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 4
        stream.codec_context.thread_type = "AUTO"
        stream.codec_context.skip_frame = "NONKEY"
        origin = container.start_time or 0
        marks = []
        for target_s in targets:
            t0 = time.perf_counter()
            container.seek(
                int((target_s + origin / 1e6) / stream.time_base),
                stream=stream, backward=True,
            )
            frame = next(container.decode(stream), None)
            marks.append((time.perf_counter() - t0) * 1000)
            if frame is not None:
                frame = None
        container.close()
        return sum(marks) / len(marks)

    targets = [seconds * f for f in (0.2, 0.4, 0.6, 0.8, 0.95)]
    flv_seek_ms = seek_ms(flv, targets)
    mp4_seek_ms = seek_ms(target, targets)
    report["seek_avg_ms"] = {"flv": round(flv_seek_ms, 1), "optimized": round(mp4_seek_ms, 1)}
    check("C_seek_faster_on_optimized", mp4_seek_ms < flv_seek_ms,
          f"flv={flv_seek_ms:.0f}ms optimized={mp4_seek_ms:.0f}ms")

    # ---------------------------------------------- waveform: progressive run
    from twobyteasr.waveform_cache import (
        WaveformCache, generate_progressive_waveform_cache,
    )
    stages: list[tuple[str, float]] = []
    t_start = time.perf_counter()
    final = generate_progressive_waveform_cache(
        str(flv), FFMPEG,
        cache_root=out_dir / "waveform-cache",
        on_ready=lambda stage, path: stages.append((stage, time.perf_counter() - t_start)),
        decode_source_resolver=lambda: str(target),
        duration_ms=int(duration_s * 1000),
    )
    stage_map = {}
    for stage, elapsed in stages:
        stage_map.setdefault(stage, round(elapsed * 1000))
    report["waveform_stages_ms"] = stage_map
    check("C1_coarse_first_waveform_under_10s", 0 < stage_map.get("coarse", 1e9) < 10_000,
          f"{stage_map.get('coarse')} ms")
    check("C2_partial_snapshots_emitted", sum(1 for s, _ in stages if s == "partial") >= 2,
          f"{sum(1 for s, _ in stages if s == 'partial')} snapshots")
    check("C3_full_completed", stage_map.get("full") is not None,
          f"{stage_map.get('full')} ms")

    cache_obj = WaveformCache(final)
    coverage = cache_obj.metadata.coverage_end_ms
    check("C4_full_coverage", abs(coverage - duration_s * 1000) < 1000,
          f"coverage={coverage}ms duration={int(duration_s*1000)}ms")
    check("C5_outline_level_present",
          any(level.file == "outline.f32" for level in cache_obj.metadata.levels))

    # ---------------------------------------- D/E: zoom responsiveness + LOD
    zoom_cases = [
        ("1s", 1_000), ("10s", 10_000), ("1min", 60_000),
        ("10min", 600_000), ("whole", int(duration_s * 1000)),
    ]
    zoom_report = {}
    ok_zoom = True
    previous_level = None
    for label, span in zoom_cases:
        t0 = time.perf_counter()
        level, pairs = cache_obj.read_window(0, span, 1760)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        zoom_report[label] = {
            "level": level.file, "frames": int(level.frames),
            "points": int(len(pairs)), "read_ms": round(elapsed_ms, 2),
        }
        if elapsed_ms > 100 or len(pairs) == 0:
            ok_zoom = False
    report["zoom_lod"] = zoom_report
    check("E1_multizoom_lod_fast", ok_zoom, json.dumps(zoom_report))

    levels_seen = {info["level"] for info in zoom_report.values()}
    check("E2_lod_levels_switch_with_zoom", len(levels_seen) >= 2, str(levels_seen))

    # Partial-cache zoom responsiveness (simulate 20 % coverage).
    import copy
    partial_dir = out_dir / "partial-cache"
    shutil.copytree(final, partial_dir)
    meta = json.loads((partial_dir / "metadata.json").read_text(encoding="utf-8"))
    trimmed = copy.deepcopy(meta)
    for level in trimmed["levels"]:
        if level["file"].startswith("lod"):
            level["frames"] = max(1, level["frames"] // 5)
    trimmed["coverage_end_ms"] = int(duration_s * 1000 * 0.2)
    trimmed["duration_ms"] = trimmed["coverage_end_ms"]
    trimmed["incomplete"] = True
    (partial_dir / "metadata.json").write_text(json.dumps(trimmed))
    partial_cache = WaveformCache(partial_dir)
    partial_zoom = {}
    for label, span in zoom_cases:
        t0 = time.perf_counter()
        level, pairs = partial_cache.read_window(0, span, 1760)
        partial_zoom[label] = {
            "level": level.file, "points": int(len(pairs)),
            "read_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    report["partial_zoom_lod"] = partial_zoom
    ok_partial = all(info["read_ms"] < 100 for info in partial_zoom.values())
    # Covered range must answer at fine resolution; the tail falls back to outline.
    ok_partial = ok_partial and partial_zoom["1s"]["level"] == "lod0.f32"
    ok_partial = ok_partial and partial_zoom["whole"]["level"] == "outline.f32"
    check("D_partial_zoom_responds_all_levels", ok_partial, json.dumps(partial_zoom))

    # ------------------------------------------------- F: warm reopen timing
    warm_started = time.perf_counter()
    warm_stages = []
    warm_final = generate_progressive_waveform_cache(
        str(flv), FFMPEG, cache_root=out_dir / "waveform-cache",
        on_ready=lambda stage, path: warm_stages.append(stage),
        decode_source_resolver=lambda: str(target),
        duration_ms=int(duration_s * 1000),
    )
    warm_total_ms = (time.perf_counter() - warm_started) * 1000
    report["waveform_warm_reopen_ms"] = round(warm_total_ms, 1)
    check("F_warm_reopen_instant_and_complete",
          warm_stages == ["full"] and warm_total_ms < 1000 and warm_final == final,
          f"{warm_stages} in {warm_total_ms:.0f} ms")

    # ------------------------------------------- G: cancel hygiene + no zombies
    import psutil
    small = out_dir / "small.flv"
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=duration=20:size=320x240:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
         "-f", "flv", str(small)])
    cancel_cache = IndexedMediaCache(root=out_dir / "cancel-cache")
    for _ in range(3):
        cancel_cache.resolve(str(small))
    cancel_cache.cancel_all()
    deadline = time.perf_counter() + 8
    while time.perf_counter() < deadline and cancel_cache.status(str(small))["state"] in {"RUNNING", "PENDING"}:
        time.sleep(0.1)
    time.sleep(0.5)
    parent = psutil.Process()
    ffmpeg_children = [p.pid for p in parent.children(recursive=True)
                       if p.name().lower().startswith("ffmpeg")]
    check("G_no_orphan_ffmpeg_children", not ffmpeg_children, str(ffmpeg_children))

    # --------------------------------------------------------------- summary
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"report: {report_path}")
    if report["failures"]:
        print("FAILURES:", ", ".join(report["failures"]))
        return 1
    print("all checks passed")
    if not args.keep:
        pass  # keep evidence for inspection; tmp/ is gitignored
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
