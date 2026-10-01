"""Verify the production frozen executable across caller working directories."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "2ByteASR" / "2ByteASR.exe"


def _stages(path: Path) -> list[str]:
    values: list[str] = []
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        stage = str(payload.get("stage") or "").strip().upper()
        if stage:
            values.append(stage)
    return values


def _startup_log_segment(path: Path, pid: int) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = f"pid={pid}"
    start = text.rfind(marker)
    return text[start:] if start >= 0 else text[-12000:]


def _probe_before_launch(output: Path, probe_kind: str) -> dict[str, object]:
    probe_code = {
        "gpu": (
            "from twobyteasr.hardware import collect_gpu_telemetry",
            "collect_gpu_telemetry()",
        ),
        "firered": (
            "from twobyteasr.asr import probe_firered_environment",
            "probe_firered_environment()",
        ),
        "qwen": (
            "from twobyteasr.asr import probe_qwen_environment",
            "probe_qwen_environment()",
        ),
    }.get(probe_kind)
    if not probe_code:
        raise ValueError(f"unknown probe kind: {probe_kind}")
    import_code, expression = probe_code
    code = (
        f"import json; {import_code}; "
        f"result = {expression}; "
        "print(json.dumps(result, ensure_ascii=False))"
    )
    completed = subprocess.run(
        [str(ROOT / ".venv-main" / "Scripts" / "python.exe"), "-B", "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    record: dict[str, object] = {
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-4000:],
        "stderr": (completed.stderr or "")[-4000:],
    }
    try:
        payload = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (IndexError, ValueError):
        payload = {}
    record["payload"] = payload
    record["ok"] = bool(
        completed.returncode == 0
        and payload
        and (payload.get("ready") is True or payload.get("status") == "READY")
    )
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def _launch_once(
    label: str,
    cwd: Path,
    root: Path,
    *,
    timeout: float,
    probe_kind: str = "",
) -> dict[str, object]:
    run_root = root / label
    run_root.mkdir(parents=True, exist_ok=True)
    localappdata = run_root / "localappdata"
    trace = run_root / "startup-trace.jsonl"
    child_log = run_root / "child-processes.jsonl"
    startup_log = EXE.parent / "2byteasr-startup.log"
    env = dict(os.environ)
    env.update(
        {
            "LOCALAPPDATA": str(localappdata),
            "TWOBYTEASR_USER_DATA_ROOT": str(localappdata / "2ByteASR"),
            "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
            "TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE": "1",
            "TWOBYTEASR_STARTUP_TRACE": str(trace),
            "TWOBYTEASR_CHILD_PROCESS_LOG": str(child_log),
            "TWOBYTEASR_STARTUP_RUN_ID": uuid.uuid4().hex,
            "TWOBYTEASR_LAUNCH_MODE": "packaged",
        }
    )
    probe_result = (
        _probe_before_launch(run_root / f"{probe_kind}-probe.json", probe_kind)
        if probe_kind
        else None
    )
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(EXE)],
        cwd=str(cwd),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.time() + timeout
    stages: list[str] = []
    while time.time() < deadline:
        stages = _stages(trace)
        if "INTERACTIVE" in stages or process.poll() is not None:
            break
        time.sleep(0.2)
    if process.poll() is None:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    stages = _stages(trace)
    log_segment = _startup_log_segment(startup_log, process.pid)
    return {
        "label": label,
        "cwd": str(cwd),
        "exe": str(EXE),
        "pid": process.pid,
        "exit_code": process.returncode,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "probe_kind": probe_kind,
        "home_ui_reached": "INTERACTIVE" in stages,
        "stages": stages,
        "numpy_startup_error": "Error importing numpy" in log_segment,
        "environment_startup_error": "运行环境不完整" in log_segment,
        "probe_failed": bool(probe_result is not None and not probe_result.get("ok")),
        "startup_log_tail": log_segment[-4000:],
        "gpu_probe_before": probe_result,
        "trace": str(trace),
        "child_process_log": str(child_log),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--probe-before", action="store_true")
    args = parser.parse_args()
    exe = EXE.resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"production executable missing: {exe}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    neutral = (output / "neutral-cwd").resolve()
    neutral.mkdir(parents=True, exist_ok=True)
    cases = [
        ("project-root", ROOT, ""),
        ("dist-directory", exe.parent, ""),
        ("desktop", ROOT.parent, ""),
        ("arbitrary-cwd", neutral, ""),
        ("after-firered-gpu-probe", ROOT, "firered" if args.probe_before else ""),
        ("after-qwen-gpu-probe", ROOT, "qwen" if args.probe_before else ""),
        ("relaunch-1", ROOT, ""),
        ("relaunch-2", ROOT, ""),
    ]
    records = [
        _launch_once(label, cwd, output, timeout=args.timeout, probe_kind=probe_kind)
        for label, cwd, probe_kind in cases
    ]
    payload = {
        "schema": "P9A-R7.1-startup-matrix-v1",
        "production_exe": str(exe),
        "cases": records,
        "all_home_ui_reached": all(bool(item["home_ui_reached"]) for item in records),
        "any_numpy_startup_error": any(bool(item["numpy_startup_error"]) for item in records),
        "any_environment_startup_error": any(bool(item["environment_startup_error"]) for item in records),
        "any_probe_failed": any(bool(item["probe_failed"]) for item in records),
    }
    result_path = output / "startup-matrix.json"
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if (
        payload["all_home_ui_reached"]
        and not payload["any_numpy_startup_error"]
        and not payload["any_environment_startup_error"]
        and not payload["any_probe_failed"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
