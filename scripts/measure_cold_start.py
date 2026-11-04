"""Measure real 2ByteASR process startup milestones across launch paths."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _launch(command: list[str], trace: Path, timeout: float) -> dict:
    env = dict(os.environ)
    env.update(
        TWOBYTEASR_STARTUP_TRACE=str(trace),
        TWOBYTEASR_STARTUP_RUN_ID=uuid.uuid4().hex,
        TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE="1",
        LOCALAPPDATA=str((ROOT / "tmp" / "cold-start-localappdata").resolve()),
    )
    kwargs = {"cwd": str(ROOT), "env": env, "shell": False}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs.update(
            startupinfo=startupinfo,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    process = subprocess.Popen(command, **kwargs)
    deadline = time.monotonic() + timeout
    milestones: dict[str, dict] = {}
    while time.monotonic() < deadline:
        if trace.is_file():
            try:
                records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
                milestones = {record["stage"]: record for record in records}
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass
        if "INTERACTIVE" in milestones and (
            "BACKGROUND_READY" in milestones or time.monotonic() + 0.5 >= deadline
        ):
            break
        time.sleep(0.05)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=3)
    if "INTERACTIVE" not in milestones:
        raise RuntimeError(f"launch did not reach INTERACTIVE: {' '.join(command)}")
    return {
        "process_to_first_paint_ms": milestones.get("FIRST_PAINT", {}).get("elapsed_ms"),
        "process_to_interactive_ms": milestones["INTERACTIVE"]["elapsed_ms"],
        "background_ready_ms": milestones.get("BACKGROUND_READY", {}).get("elapsed_ms"),
        "milestones": {name: item["elapsed_ms"] for name, item in milestones.items()},
    }


def _summary(samples: list[dict]) -> dict:
    result = {"samples": samples}
    for key in (
        "process_to_first_paint_ms",
        "process_to_interactive_ms",
        "background_ready_ms",
    ):
        values = [float(item[key]) for item in samples if item.get(key) is not None]
        result[key] = {
            "mean": round(statistics.fmean(values), 3),
            "median": round(statistics.median(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        } if values else None
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output", default="performance-p21.1-cold-start.json")
    parser.add_argument("--target", choices=("all", "source", "current_build"), default="all")
    args = parser.parse_args()
    pythonw = ROOT / ".venv-main" / "Scripts" / "pythonw.exe"
    launcher = ROOT / "2ByteASR.exe"
    targets = {"source": [str(pythonw), str(ROOT / "quick_start.py")]}
    if launcher.is_file():
        targets["current_build"] = [str(launcher)]
    if args.target != "all":
        targets = {args.target: targets[args.target]}
    trace_root = ROOT / "tmp" / "cold-start-traces"
    trace_root.mkdir(parents=True, exist_ok=True)
    report = {
        "packaging": {
            "current_build": "C# launcher + pythonw + installed directory (onedir)",
            "onedir_comparison": "same artifact as current_build",
            "onefile": False,
        },
        "runs_per_target": args.runs,
        "targets": {},
    }
    for name, command in targets.items():
        samples = []
        for index in range(args.runs):
            trace = trace_root / f"{name}-{index + 1}.jsonl"
            if trace.exists():
                trace.unlink()
            samples.append(_launch(command, trace, args.timeout))
            time.sleep(3.0)
        report["targets"][name] = _summary(samples)
    output = (ROOT / args.output).resolve()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
