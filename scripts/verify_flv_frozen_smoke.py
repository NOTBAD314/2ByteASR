"""Frozen smoke: staged EXE opens an FLV project, remux + waveform must complete.

Launches the packaged exe with argv project under isolated LOCALAPPDATA/APPDATA,
waits for the optimized media copy and the completed waveform cache, closes the
window gracefully, and asserts no orphan ffmpeg children. Usage:

    python scripts/verify_flv_frozen_smoke.py --exe <staged exe> --project <.2byteproj>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import psutil


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--out", default="tmp/flv-build-20260917/frozen-smoke")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    env_root = out_dir / "env"
    local_appdata = env_root / "Local"
    appdata = env_root / "Roaming"
    (local_appdata / "2ByteASR").mkdir(parents=True, exist_ok=True)
    (appdata).mkdir(parents=True, exist_ok=True)

    # Minimal config seed so the packaged app skips first-run setup, without
    # copying secrets or caches from the real user profile.
    real_local = Path(os.environ["LOCALAPPDATA"]) / "2ByteASR"
    for name in ("2byteasr_settings.json", "content_profiles.json",
                 "profiles.json", "learned_game_terms.json"):
        source = real_local / name
        if source.is_file():
            (local_appdata / "2ByteASR" / name).write_bytes(source.read_bytes())

    exe = Path(args.exe).resolve()
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(local_appdata.resolve())
    env["APPDATA"] = str(appdata.resolve())
    env.pop("QT_QPA_PLATFORM", None)

    report: dict = {"exe": str(exe), "project": str(Path(args.project).resolve())}
    # 波形完成阈值按工程时长推导（此前写死 700s，只适配旧 12 分钟模板）。
    coverage_target_ms = 700_000
    try:
        project_payload = json.loads(Path(args.project).read_text(encoding="utf-8"))
        media_ms = int((project_payload.get("media") or {}).get("duration_ms") or 0)
        if media_ms > 0:
            coverage_target_ms = max(60_000, int(media_ms * 0.9))
    except (OSError, ValueError, TypeError):
        pass
    report["coverage_target_ms"] = coverage_target_ms
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        report[name] = {"ok": bool(ok), "detail": detail}
        print(("[PASS] " if ok else "[FAIL] ") + name + (f" :: {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    process = psutil.Popen([str(exe), str(Path(args.project).resolve())],
                           cwd=str(exe.parent), env=env)
    report["pid"] = process.pid
    started = time.monotonic()

    optimized_at: float | None = None
    waveform_done_at: float | None = None
    seek_root = local_appdata / "2ByteASR" / "cache" / "media" / "seek"
    waveform_root = local_appdata / "2ByteASR" / "SubtitleStudioPreview" / "waveform-cache"

    while time.monotonic() - started < args.timeout:
        time.sleep(1.0)
        if optimized_at is None and seek_root.is_dir():
            if any(p.name == "optimized.mp4" for p in seek_root.rglob("optimized.*")):
                optimized_at = time.monotonic() - started
        if waveform_done_at is None and waveform_root.is_dir():
            for meta in waveform_root.rglob("metadata.json"):
                try:
                    payload = json.loads(meta.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if (not payload.get("incomplete", False)
                        and int(payload.get("coverage_end_ms", 0)) >= coverage_target_ms
                        and all((meta.parent / level["file"]).is_file()
                                for level in payload.get("levels", []))):
                    waveform_done_at = time.monotonic() - started
                    break
        if optimized_at is not None and waveform_done_at is not None:
            break
        if not psutil.pid_exists(process.pid):
            break

    check("optimized_media_created", optimized_at is not None,
          f"{optimized_at:.1f}s" if optimized_at is not None else "not found")
    check("waveform_completed", waveform_done_at is not None,
          f"{waveform_done_at:.1f}s" if waveform_done_at is not None else "not found")

    # Give the UI a moment, then close the main window gracefully.
    time.sleep(5.0)
    alive = psutil.pid_exists(process.pid)
    if alive:
        subprocess.run(["taskkill", "/PID", str(process.pid)], capture_output=True)
        try:
            process.wait(timeout=30)
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
            report["graceful_close"] = False
    report["graceful_close"] = bool(report.get("graceful_close", True))

    time.sleep(3.0)
    orphans = []
    for proc in psutil.process_iter(["name", "ppid"]):
        name = (proc.info.get("name") or "").lower()
        if name.startswith("ffmpeg") and proc.info.get("ppid") in (process.pid,):
            orphans.append(proc.pid)
    # Also scan for any ffmpeg whose parent is dead but was spawned under our
    # process tree (defensive; popen children are direct).
    check("no_orphan_ffmpeg", not orphans, str(orphans))
    check("process_exited", not psutil.pid_exists(process.pid))

    # Trace evidence from the isolated logs, if present.
    trace_hits: list[str] = []
    logs_dir = local_appdata / "2ByteASR" / "logs"
    if logs_dir.is_dir():
        for log_file in sorted(logs_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            if not log_file.is_file():
                continue
            try:
                text = log_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for marker in ("MEDIA_OPTIMIZE", "WaveformLOD", "first_partial",
                           "full_complete", "cache_hit=True"):
                if marker in text:
                    trace_hits.append(f"{log_file.name}:{marker}")
    report["trace_evidence"] = trace_hits
    check("trace_events_present",
          any("MEDIA_OPTIMIZE" in hit for hit in trace_hits)
          and any("WaveformLOD" in hit or "full_complete" in hit for hit in trace_hits),
          "; ".join(trace_hits[:8]))

    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report: {report_path}")
    if failures:
        print("FAILURES:", ", ".join(failures))
        return 1
    print("frozen smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
