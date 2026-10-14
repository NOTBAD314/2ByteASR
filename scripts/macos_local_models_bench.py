# SPDX-License-Identifier: GPL-3.0-only
"""MOSS and FireRed on a Mac: Apple GPU (MPS) and CPU, timed (2026-10-14).

Runs on a GitHub macOS runner (or any Apple Silicon Mac). Steps:

1. Records the machine: model, memory, GPU / Metal support, free disk.
2. Builds two private PyTorch runtimes with uv from the locked versions in
   ``dependencies.lock.json`` (MOSS: Python 3.12 + transformers 5.14.1 + the
   vendored ``moss_transcribe_diarize``; FireRed: Python 3.10 + transformers
   4.57.6 + kaldi features) and records whether PyTorch can use MPS.
3. Downloads the two locked models at their pinned revisions (Hugging Face).
4. Synthesizes two-speaker Chinese speech with macOS ``say`` (Tingting and
   Meijia; TTS voices, not real speech) into a short and a long clip.
5. Runs the production workers (``moss_worker.py``, ``firered_aed_worker.py``)
   with ``--device mps`` and ``--device cpu``, each under ``/usr/bin/time -l``
   for wall time and peak memory, and scores the text against the script.

It measures speed, memory and whether the device works; it is not an accuracy
benchmark (synthetic voices). Results go to ``--output`` as JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))

LINES = (
    ("Tingting", "大家好，今天我们继续打排位，先看一下这把的阵容。"),
    ("Meijia", "我觉得这局可以先拿下中路，然后再去打小龙。"),
    ("Tingting", "这把我用捷风，先买一把豌豆，再给队友扔个烟。"),
    ("Meijia", "对面的狙击手一直在架点，我们换个方向进攻吧。"),
    ("Tingting", "好的，三二一一起上，注意左边有人。"),
    ("Meijia", "漂亮，这波我们拿下了，经济领先三千。"),
)


def run(command, *, env=None, cwd=None, timeout=None, log=None):
    started = time.monotonic()
    done = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if log is not None:
        Path(log).write_text((done.stdout or "") + "\n--- stderr ---\n" + (done.stderr or ""), encoding="utf-8")
    return done, round(time.monotonic() - started, 2)


def machine() -> dict:
    info = {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0]}
    for key in ("hw.model", "hw.memsize", "machdep.cpu.brand_string", "hw.ncpu", "hw.perflevel0.physicalcpu"):
        done = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True)
        info[key] = done.stdout.strip()
    done = subprocess.run(["system_profiler", "SPDisplaysDataType", "-json"], capture_output=True, text=True)
    try:
        displays = json.loads(done.stdout).get("SPDisplaysDataType", [])
        info["gpus"] = [{k: v for k, v in item.items() if k in (
            "sppci_model", "sppci_cores", "spdisplays_mtlgpufamilysupport", "spdisplays_metal", "sppci_device_type")}
            for item in displays]
    except ValueError:
        info["gpus_raw"] = done.stdout[-1500:]
    usage = shutil.disk_usage(Path.home())
    info["disk_free_gb"] = round(usage.free / 2**30, 1)
    return info


def make_runtime(name: str, python: str, packages: list[str], work: Path, extra_editable=None) -> dict:
    venv = work / f"venv-{name}"
    record = {"name": name, "python_request": python, "packages": packages}
    done, seconds = run(["uv", "venv", "--python", python, str(venv)], log=work / f"venv-{name}.log")
    if done.returncode:
        record.update(ok=False, error=done.stderr[-1500:])
        return record
    py = venv / "bin" / "python"
    install = ["uv", "pip", "install", "--python", str(py), *packages]
    done, seconds2 = run(install, log=work / f"pip-{name}.log", timeout=1800)
    if done.returncode:
        record.update(ok=False, error=done.stderr[-2000:])
        return record
    if extra_editable:
        done, _ = run(["uv", "pip", "install", "--python", str(py), "--no-deps", "-e", str(extra_editable)],
                      log=work / f"pip-{name}-editable.log")
        if done.returncode:
            record.update(ok=False, error=done.stderr[-1500:])
            return record
    probe = ("import json,torch;print(json.dumps({'torch':torch.__version__,"
             "'mps_built':torch.backends.mps.is_built(),'mps_available':torch.backends.mps.is_available()}))")
    done, _ = run([str(py), "-c", probe])
    try:
        record["torch"] = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        record["torch_probe_error"] = (done.stderr or done.stdout)[-1500:]
    if record.get("torch", {}).get("mps_available"):
        # A tiny MPS matmul proves kernels run, not only that the backend reports itself.
        done, _ = run([str(py), "-c", "import torch;a=torch.ones(256,256,device='mps');print(float((a@a).sum().cpu()))"])
        record["mps_matmul"] = done.stdout.strip() or done.stderr[-500:]
    record.update(ok=True, python=str(py), seconds=round(seconds + seconds2, 1))
    return record


def download(model_key: str, work: Path) -> dict:
    entry = LOCK["models"][model_key]
    target = work / "models" / Path(entry["path"]).name
    record = {"model": model_key, "repository": entry["repository"], "revision": entry.get("revision"),
              "path": str(target)}
    code = ("import sys;from huggingface_hub import snapshot_download;"
            "snapshot_download(repo_id=sys.argv[1],revision=sys.argv[2],local_dir=sys.argv[3])")
    started = time.monotonic()
    done = subprocess.run([sys.executable, "-c", code, entry["repository"], entry.get("revision") or "main", str(target)],
                          capture_output=True, text=True, timeout=3600)
    record["seconds"] = round(time.monotonic() - started, 1)
    record["ok"] = done.returncode == 0
    if done.returncode:
        record["error"] = done.stderr[-1500:]
    else:
        record["size_gb"] = round(sum(p.stat().st_size for p in target.rglob("*") if p.is_file()) / 2**30, 2)
    return record


def synthesize(work: Path, repeats: int) -> dict:
    """One clip: the scripted lines ``repeats`` times, 0.6 s pauses, 16 kHz mono."""
    import array
    pieces, text, voices = [], [], set()
    pause = array.array("h", [0] * 9600)
    for round_index in range(repeats):
        for index, (voice, line) in enumerate(LINES):
            path = work / f"tts-{voice}-{index}.wav"
            if not path.is_file():
                done = subprocess.run(["say", "-v", voice, "--data-format=LEI16@16000", "-o", str(path), line],
                                      capture_output=True)
                if done.returncode or not path.is_file():
                    done = subprocess.run(["say", "--data-format=LEI16@16000", "-o", str(path), line],
                                          capture_output=True)
                    voice = "default"
            with wave.open(str(path), "rb") as stream:
                frames = stream.readframes(stream.getnframes())
                rate, channels = stream.getframerate(), stream.getnchannels()
            samples = array.array("h", frames)
            if channels == 2:
                samples = samples[::2]
            if rate != 16000:
                raise RuntimeError(f"say produced {rate} Hz")
            pieces.append(samples)
            pieces.append(pause)
            text.append(line)
            voices.add(voice)
    out = work / f"clip-x{repeats}.wav"
    with wave.open(str(out), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        for piece in pieces:
            stream.writeframes(piece.tobytes())
    with wave.open(str(out), "rb") as stream:
        seconds = stream.getnframes() / 16000
    return {"path": str(out), "seconds": round(seconds, 2), "text": "".join(text), "voices": sorted(voices)}


def _content(text: str) -> str:
    return "".join(ch for ch in text if "一" <= ch <= "鿿" or ch.isalnum())


def cer(reference: str, hypothesis: str) -> float:
    a, b = _content(reference), _content(hypothesis)
    if not a:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return round(previous[-1] / len(a), 4)


def timed(command, *, env, log: Path, timeout: int):
    """Run under /usr/bin/time -l: wall seconds and peak resident memory."""
    done, seconds = run(["/usr/bin/time", "-l", *command], env=env, cwd=str(ROOT), timeout=timeout, log=log)
    peak = None
    match = re.search(r"(\d+)\s+maximum resident set size", done.stderr or "")
    if match:
        peak = round(int(match.group(1)) / 2**30, 3)   # bytes on macOS
    return done, seconds, peak


def run_moss(runtime: dict, model: dict, clip: dict, device: str, work: Path, timeout: int,
             dtype: str = "auto") -> dict:
    suffix = "" if dtype == "auto" else f"-{dtype}"
    out = work / f"moss-{device}{suffix}-{Path(clip['path']).stem}.json"
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTORCH_ENABLE_MPS_FALLBACK="0")
    command = [runtime["python"], "-I", str(ROOT / "moss_worker.py"), "--audio", clip["path"], "--output", str(out),
               "--model", model["path"], "--device", device, "--dtype", dtype]
    try:
        done, seconds, peak = timed(command, env=env, log=out.with_suffix(".log"), timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"model": "moss", "device": device, "requested_dtype": dtype, "clip_seconds": clip["seconds"],
                "ok": False, "error": "timeout"}
    record = {"model": "moss", "device": device, "requested_dtype": dtype, "clip_seconds": clip["seconds"],
              "exit": done.returncode,
              "wall_seconds": seconds, "peak_rss_gb": peak, "realtime_factor": round(seconds / clip["seconds"], 3)}
    try:
        payload = json.loads(out.read_text(encoding="utf-8"))
        execution = payload.get("execution") or {}
        text = "".join(seg["text"] for chunk in payload.get("chunks") or [] for seg in chunk.get("segments") or [])
        speakers = sorted({seg["speaker"] for chunk in payload.get("chunks") or [] for seg in chunk.get("segments") or []})
        record.update(ok=done.returncode == 0 and bool(text), device_kind=execution.get("device_kind"),
                      dtype=execution.get("dtype"), model_load_seconds=execution.get("model_load_seconds"),
                      first_token_seconds=execution.get("first_token_seconds"),
                      decode_tokens_per_second=execution.get("decode_tokens_per_second"),
                      complete=execution.get("complete"), speakers=speakers, cer=cer(clip["text"], text),
                      text_head=text[:80], error=execution.get("error"))
    except (OSError, ValueError) as exc:
        record.update(ok=False, error=f"{type(exc).__name__}: {exc}", stderr_tail=(done.stderr or "")[-1500:])
    return record


def run_firered(runtime: dict, model: dict, clip: dict, device: str, work: Path, timeout: int,
                chunk_seconds: float = 30.0, dtype: str = "auto") -> dict:
    stem = Path(clip["path"]).stem
    chunk_dir = work / f"firered-chunks-{stem}"
    chunk_dir.mkdir(exist_ok=True)
    jobs = []
    with wave.open(clip["path"], "rb") as stream:
        total = stream.getnframes()
        step = int(chunk_seconds * 16000)
        for index, start in enumerate(range(0, total, step)):
            stream.setpos(start)
            frames = stream.readframes(min(step, total - start))
            path = chunk_dir / f"c{index:03d}.wav"
            if not path.is_file():
                with wave.open(str(path), "wb") as piece:
                    piece.setnchannels(1)
                    piece.setsampwidth(2)
                    piece.setframerate(16000)
                    piece.writeframes(frames)
            jobs.append({"segment_id": index + 1, "path": str(path), "offset": start / 16000,
                         "duration": len(frames) / 2 / 16000})
    manifest = work / f"firered-{stem}.manifest.json"
    manifest.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    suffix = "" if dtype == "auto" else f"-{dtype}"
    out = work / f"firered-{device}{suffix}-{stem}.json"
    env = dict(os.environ, PYTORCH_ENABLE_MPS_FALLBACK="0")
    command = [runtime["python"], str(ROOT / "firered_aed_worker.py"), "--manifest", str(manifest),
               "--output", str(out), "--model-dir", model["path"], "--device", device]
    if dtype != "auto":
        command += ["--mps-dtype", dtype]
    try:
        done, seconds, peak = timed(command, env=env, log=out.with_suffix(".log"), timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"model": "firered", "device": device, "requested_dtype": dtype, "clip_seconds": clip["seconds"],
                "ok": False, "error": "timeout"}
    record = {"model": "firered", "device": device, "requested_dtype": dtype, "clip_seconds": clip["seconds"],
              "exit": done.returncode,
              "wall_seconds": seconds, "peak_rss_gb": peak, "realtime_factor": round(seconds / clip["seconds"], 3),
              "chunks": len(jobs)}
    try:
        payload = json.loads(out.read_text(encoding="utf-8"))
        text = "".join(row.get("text") or "" for row in payload.get("results") or [])
        telemetry = payload.get("telemetry") or {}
        record.update(ok=done.returncode == 0 and bool(text), device_kind=telemetry.get("device_kind"),
                      model_device=telemetry.get("device"), dtype=telemetry.get("dtype"),
                      load_ms=payload.get("load_ms"), inference_ms=payload.get("inference_ms"),
                      timestamps=sum(len(row.get("timestamp") or []) for row in payload.get("results") or []),
                      cer=cer(clip["text"], text), text_head=text[:80])
    except (OSError, ValueError) as exc:
        failure = re.findall(r'"event": "failed".*', done.stdout or "")
        record.update(ok=False, error=(failure[-1] if failure else f"{type(exc).__name__}: {exc}")[:1500],
                      stderr_tail=(done.stderr or "")[-1500:])
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--devices", default="mps,cpu")
    parser.add_argument("--models", default="moss,firered")
    parser.add_argument("--long-repeats", type=int, default=8, help="long clip = the script repeated N times")
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--moss-dtypes", default="auto",
                        help="MOSS --dtype values to compare on each device, e.g. auto,bfloat16,float16")
    parser.add_argument("--firered-dtypes", default="auto",
                        help="FireRed Apple GPU precision to compare: auto,float16 (auto = the worker default)")
    parser.add_argument("--clips", default="short,long")
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    result = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "machine": machine(), "runtimes": {}, "models": {},
              "clips": {}, "runs": []}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    save()
    envs = LOCK["environments"]
    wanted = [m.strip() for m in args.models.split(",") if m.strip()]
    devices = [d.strip() for d in args.devices.split(",") if d.strip()]
    if "moss" in wanted:
        e = envs["moss"]
        packages = [f"torch=={e['torch']}", f"torchaudio=={e['torchaudio']}",
                    *(f"{k}=={v}" for k, v in e["packages"].items()),
                    "numpy<3", "av>=14.0", "librosa>=0.11.0", "numba>=0.61.0", "soundfile>=0.12", "soxr>=0.5",
                    "packaging", "psutil"]
        result["runtimes"]["moss"] = make_runtime("moss", e["python"], packages, work,
                                                  extra_editable=ROOT / "third_party" / "MOSS-Transcribe-Diarize")
        save()
    if "firered" in wanted:
        e = envs["main"]
        packages = [f"torch=={e['torch']}", f"torchaudio=={e['torchaudio']}",
                    *(f"{k}=={v}" for k, v in e["packages"].items() if k != "speechbrain"),
                    "sentencepiece", "numpy<3", "packaging"]
        result["runtimes"]["firered"] = make_runtime("firered", e["python"], packages, work)
        save()
    keys = {"moss": "moss", "firered": "firered_aed"}
    for name in wanted:
        if result["runtimes"].get(name, {}).get("ok"):
            result["models"][name] = download(keys[name], work)
            save()
    result["clips"]["short"] = synthesize(work, 1)
    result["clips"]["long"] = synthesize(work, max(1, args.long_repeats))
    save()
    for name in wanted:
        runtime, model = result["runtimes"].get(name, {}), result["models"].get(name, {})
        if not (runtime.get("ok") and model.get("ok")):
            continue
        dtypes = [d.strip() for d in (args.moss_dtypes if name == "moss" else args.firered_dtypes).split(",") if d.strip()]
        clips = [c.strip() for c in args.clips.split(",") if c.strip()]
        for device in devices:
            if device == "mps" and not runtime.get("torch", {}).get("mps_available"):
                result["runs"].append({"model": name, "device": "mps", "ok": False, "skipped": True,
                                       "error": "PyTorch reports MPS unavailable on this machine"})
                save()
                continue
            for dtype in dtypes:
                for clip_name in clips:
                    if name == "moss":
                        record = run_moss(runtime, model, result["clips"][clip_name], device, work, args.timeout,
                                          dtype=dtype)
                    else:
                        record = run_firered(runtime, model, result["clips"][clip_name], device, work, args.timeout,
                                             dtype=dtype if device == "mps" else "auto")
                    record["clip"] = clip_name
                    result["runs"].append(record)
                    save()
                    if not record.get("ok") and clip_name == "short":
                        break
    result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save()
    print(json.dumps({"machine": result["machine"].get("hw.model"),
                      "runs": [{k: r.get(k) for k in ("model", "device", "requested_dtype", "clip", "ok", "wall_seconds",
                                                       "realtime_factor", "peak_rss_gb", "cer", "error")}
                               for r in result["runs"]]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
