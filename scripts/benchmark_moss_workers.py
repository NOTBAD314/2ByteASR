"""Compare one versus multiple isolated MOSS workers on identical jobs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _worker_command(manifest: Path, output: Path) -> list[str]:
    return [
        str(PROJECT_ROOT / ".venv-moss" / "Scripts" / "python.exe"),
        str(PROJECT_ROOT / "moss_worker.py"),
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--model",
        "OpenMOSS-Team/MOSS-Transcribe-Diarize",
        "--title",
        "performance benchmark",
    ]


def _write_manifest(path: Path, jobs: list[dict]) -> None:
    path.write_text(
        json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(media: str, job_count: int, worker_count: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="2byteasr_moss_bench_") as folder:
        root = Path(folder)
        assignments = [[] for _ in range(worker_count)]
        for index in range(job_count):
            assignments[index % worker_count].append(
                {
                    "chunk_id": index + 1,
                    "audio": media,
                    "offset": float(index * 1000),
                    "duration": 90.0,
                }
            )
        processes = []
        outputs = []
        started = time.perf_counter()
        for worker_index, jobs in enumerate(assignments, 1):
            manifest = root / f"manifest-{worker_index}.json"
            output = root / f"output-{worker_index}.json"
            _write_manifest(manifest, jobs)
            outputs.append(output)
            processes.append(
                subprocess.Popen(
                    _worker_command(manifest, output),
                    cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            )
        logs = []
        for process in processes:
            stdout, _ = process.communicate()
            logs.append(stdout)
            if process.returncode:
                raise RuntimeError(stdout[-4000:])
        elapsed = time.perf_counter() - started
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in outputs]
        return {
            "workers": worker_count,
            "jobs": job_count,
            "elapsed_seconds": round(elapsed, 3),
            "generated_tokens": sum(int(item.get("generated_tokens", 0)) for item in payloads),
            "peak_reserved_gb_per_worker": [
                item.get("performance", {}).get("peak_reserved_gb", 0)
                for item in payloads
            ],
            "model_load_seconds": [
                item.get("performance", {}).get("model_load_seconds", 0)
                for item in payloads
            ],
            "logs": logs,
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("media")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    result = run(os.path.abspath(args.media), args.jobs, args.workers)
    logs = result.pop("logs")
    for index, log in enumerate(logs, 1):
        print(f"--- worker {index} ---")
        print(log.rstrip())
    print("BENCHMARK_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
