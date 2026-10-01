"""Run MOSS-Transcribe-Diarize in its isolated Transformers 5 environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_PROMPT = (
    "请将音频转写为文本，每一段需以起始时间戳和说话人编号"
    "（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，"
    "并在段末标注结束时间戳，以清晰标明该段语音范围。"
)


def parsed_speaker_label(value, chunk_id):
    label = str(value).strip('[] ') if value is not None else ''
    if not label:
        raise RuntimeError(f'MOSS 第 {chunk_id} 块说话人标签解析失败：标签为空，未默认归入 S00。')
    return label


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio")
    parser.add_argument("--manifest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--checkpoint-dir", default="")
    parser.add_argument("--run-signature", default="")
    return parser.parse_args()


def media_duration(path):
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        return max(0.0, float(completed.stdout.strip()))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


class ModelIntegrityError(RuntimeError):
    pass


def _vendored_model_root():
    """Registered MODEL_ROOT: 2BYTEASR_MODEL_ROOT env, then runtime_paths.json."""
    override = os.environ.get("2BYTEASR_MODEL_ROOT", "").strip()
    if override and os.path.isdir(override):
        return override
    base = (Path(os.environ.get("LOCALAPPDATA") or Path.home())).resolve()
    config = (base / "2ByteASR" / "runtime_paths.json").resolve()
    try:
        with config.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        candidate = str(payload.get("model_root") or "").strip()
        if candidate and os.path.isdir(candidate):
            return candidate
    except (OSError, ValueError):
        pass
    return ""


def _vendored_verify_model_files(model_name, model_root, *, install_root):
    """Minimal stand-in for twobyteasr.model_integrity.verify_model_files.

    Importing the package executes twobyteasr/__init__, whose service-chain
    side effects load the GUI bundle's cp310 .pyd files and break this 3.12
    worker ("Module use of python310.dll conflicts"). Same contract here:
    required files must exist inside the model directory, sha256-pinned
    files must match, and the location must be a known root.
    """
    lock_path = (Path(install_root) / "dependencies.lock.json").resolve()
    with lock_path.open(encoding="utf-8") as stream:
        lock = json.load(stream)
    try:
        spec = lock["models"][model_name]
    except KeyError as exc:
        raise ModelIntegrityError(f"依赖锁中没有模型：{model_name}") from exc
    target = Path(model_root).resolve()
    allowed = [(Path(install_root).resolve())]
    registered = _vendored_model_root()
    if registered:
        allowed.append(Path(registered).resolve())
    inside = any(target.is_relative_to(root) for root in allowed)
    if not inside and not target.is_dir():
        raise ModelIntegrityError(f"拒绝校验未知位置的模型：{target}")

    def _safe(relative):
        candidate = (target / relative).resolve()
        if candidate == target or candidate.is_relative_to(target):
            return candidate
        raise ModelIntegrityError(f"模型锁包含非法路径：{relative}")

    for relative in dict.fromkeys(spec.get("required_files", ())):
        candidate = _safe(relative)
        if not candidate.is_file():
            raise ModelIntegrityError(
                f"模型必需文件缺失：{candidate}\n"
                "请重新运行 download_models.bat，程序会断点续传并只补下载缺失文件。"
            )
    for relative, expected in (spec.get("sha256") or {}).items():
        candidate = _safe(relative)
        if not candidate.is_file():
            raise ModelIntegrityError(
                f"模型关键文件缺失：{candidate}\n"
                "请重新运行 download_models.bat，程序会断点续传并只补下载缺失文件。"
            )
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != str(expected).lower():
            raise ModelIntegrityError(
                f"模型文件校验失败，已拒绝加载：{candidate.name}。"
                f"请删除损坏文件 {candidate} 后重新运行 download_models.bat。"
            )
    return target


def resolve_model(requested, install_root):
    script_local = (Path(__file__).resolve().parent / "models" / "MOSS-Transcribe-Diarize")
    if (script_local / "config.json").is_file():
        return str(script_local)
    # Registered MODEL_ROOT: env override, then the persisted runtime_paths.json.
    override = os.environ.get("2BYTEASR_MODEL_ROOT", "").strip()
    if override:
        found = Path(override) / "MOSS-Transcribe-Diarize"
        if (found / "config.json").is_file():
            return str(found)
    base = (Path(os.environ.get("LOCALAPPDATA") or Path.home())).resolve()
    runtime_paths_file = (base / "2ByteASR" / "runtime_paths.json").resolve()
    try:
        with runtime_paths_file.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        model_root = str(payload.get("model_root") or "").strip()
        if model_root:
            found = Path(model_root) / "MOSS-Transcribe-Diarize"
            if (found / "config.json").is_file():
                return str(found)
    except (OSError, ValueError):
        pass
    # Last resort: models shipped beside the install root.
    found = Path(install_root) / "models" / "MOSS-Transcribe-Diarize"
    if (found / "config.json").is_file():
        return str(found)
    return requested


def atomic_write_json(path, payload):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def load_chunk_checkpoint(checkpoint_dir, run_signature, job, job_index):
    checkpoint_dir = str(job.get("checkpoint_dir") or checkpoint_dir or "")
    run_signature = str(job.get("run_signature") or run_signature or "")
    if not checkpoint_dir or not run_signature:
        return None
    path = Path(checkpoint_dir) / f"chunk_{int(job.get('chunk_id', job_index)):03d}.json"
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if payload.get("run_signature") != run_signature:
            return None
        if abs(float(payload.get("offset", -1)) - float(job.get("offset", 0.0))) > 0.001:
            return None
        result = payload.get("result")
        if not isinstance(result, dict) or not result.get("segments"):
            return None
        return result
    except (OSError, ValueError, TypeError):
        return None


def save_chunk_checkpoint(checkpoint_dir, run_signature, result):
    checkpoint_dir = str(result.get("checkpoint_dir") or checkpoint_dir or "")
    run_signature = str(result.get("run_signature") or run_signature or "")
    if not checkpoint_dir or not run_signature:
        return
    path = Path(checkpoint_dir) / f"chunk_{int(result['chunk_id']):03d}.json"
    atomic_write_json(
        path,
        {
            "run_signature": run_signature,
            "offset": result["offset"],
            "result": result,
        },
    )


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Source checkout workers live beside dependencies.lock.json; packaged
    # workers live beside the executable. Resolve both without assuming a
    # parent directory layout.
    install_root = script_dir if os.path.isfile(os.path.join(script_dir, "dependencies.lock.json")) else os.path.dirname(script_dir)
    args = parse_args()
    if not args.audio and not args.manifest:
        raise ValueError("--audio 与 --manifest 至少提供一个。")
    # Transformers 的 trust_remote_code 默认写入用户级 ~/.cache；在 Windows
    # 受限目录或便携式工作流中可能没有权限，改用本次任务旁的临时缓存。
    module_cache = Path(args.output).resolve().parent / ".hf_modules_cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_MODULES_CACHE", str(module_cache))

    # P0: Print exact interpreter + torch + CUDA reality at the very start of the worker
    # so logs always show which python and whether it is CPU-only or real CUDA.
    try:
        import sys as _sys
        import torch as _torch
        import subprocess as _subprocess
        print("[MOSS ENV]", flush=True)
        print("Python:", _sys.executable, flush=True)
        print("Torch:", _torch.__version__, flush=True)
        print("Torch __file__:", getattr(_torch, "__file__", None), flush=True)
        cu = getattr(getattr(_torch, "version", None), "cuda", None)
        print("Torch CUDA runtime:", cu, flush=True)
        avail = False
        try:
            avail = bool(_torch.cuda.is_available())
        except Exception:
            avail = False
        print("CUDA available:", avail, flush=True)
        try:
            if avail and _torch.cuda.device_count() > 0:
                print("GPU:", _torch.cuda.get_device_name(0), flush=True)
            else:
                print("GPU: (none visible)", flush=True)
        except Exception as _ge:
            print("GPU: error", _ge, flush=True)
        try:
            _ns = _subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], timeout=8, stderr=_subprocess.STDOUT)
            print("nvidia-smi:", _ns.decode("utf-8", errors="replace").strip()[:300], flush=True)
        except Exception as _ne:
            print("nvidia-smi inside worker:", _ne, flush=True)
    except Exception as _pe:
        print("[MOSS ENV] probe failed:", _pe, flush=True)

    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    from moss_transcribe_diarize import parse_transcript
    from moss_transcribe_diarize.inference_utils import (
        build_transcription_messages,
        generate_transcription,
        resolve_device,
    )

    device = resolve_device("auto")
    if device.type != "cuda":
        raise RuntimeError("MOSS 当前工作流要求 CUDA GPU。")
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model_source = resolve_model(args.model, install_root)
    _vendored_verify_model_files("moss", model_source, install_root=install_root)
    prompt = DEFAULT_PROMPT

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    model_load_started = time.perf_counter()
    print(f"加载 MOSS：{model_source}", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_source,
        trust_remote_code=True,
        dtype="auto",
    ).to(dtype=dtype).to(device).eval()
    processor = AutoProcessor.from_pretrained(model_source, trust_remote_code=True)
    model_load_seconds = time.perf_counter() - model_load_started
    print(f"MOSS 模型加载完成：{model_load_seconds:.1f} 秒。", flush=True)
    if args.manifest:
        with open(args.manifest, "r", encoding="utf-8") as file:
            jobs = json.load(file).get("jobs", [])
    else:
        jobs = [{"chunk_id": 1, "audio": args.audio, "offset": 0.0}]
    if not jobs:
        raise ValueError("MOSS manifest 中没有任务。")

    chunk_results = []
    chunk_timings = []
    for job_index, job in enumerate(jobs, 1):
        cached = load_chunk_checkpoint(
            args.checkpoint_dir,
            args.run_signature,
            job,
            job_index,
        )
        if cached is not None:
            cached["group_id"] = str(job.get("group_id", cached.get("group_id", "default")))
            cached["checkpoint_dir"] = str(job.get("checkpoint_dir", cached.get("checkpoint_dir", "")))
            cached["run_signature"] = str(job.get("run_signature", cached.get("run_signature", "")))
            chunk_results.append(cached)
            print(
                f"[块 {job_index}/{len(jobs)}] 命中断点缓存："
                f"{len(cached['segments'])} 段。",
                flush=True,
            )
            continue
        audio_path = str(job["audio"])
        duration = float(job.get("duration") or media_duration(audio_path))
        max_new_tokens = max(2048, min(8192, int(math.ceil(duration * 12.0))))
        print(
            f"[块 {job_index}/{len(jobs)}] {float(job.get('offset', 0.0)):.1f}s 起，"
            f"音频 {duration:.1f}s，最多 {max_new_tokens} tokens",
            flush=True,
        )
        chunk_started = time.perf_counter()
        last_report = {"tokens": 0}

        def report_tokens(count):
            if count - last_report["tokens"] >= 100:
                last_report["tokens"] = count
                print(f"[块 {job_index}/{len(jobs)}] 已生成 {count} tokens", flush=True)

        messages = build_transcription_messages(audio_path, prompt=prompt)
        result = generate_transcription(
            model,
            processor,
            messages,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            device=device,
            dtype=dtype,
            token_callback=report_tokens,
        )
        generated_tokens = int(result.get("generated_tokens", 0))
        if generated_tokens >= int(max_new_tokens * 0.96) and max_new_tokens < 8192:
            retry_tokens = min(8192, int(math.ceil(max_new_tokens * 1.5)))
            print(
                f"[块 {job_index}/{len(jobs)}] 输出接近 token 上限，"
                f"提高到 {retry_tokens} 后重试一次。",
                flush=True,
            )
            last_report["tokens"] = 0
            result = generate_transcription(
                model,
                processor,
                messages,
                max_new_tokens=retry_tokens,
                do_sample=False,
                device=device,
                dtype=dtype,
                token_callback=report_tokens,
            )
            max_new_tokens = retry_tokens
        segments = []
        for segment in parse_transcript(result["text"]):
            start = max(0.0, float(segment.start))
            end = max(start + 0.01, float(segment.end))
            text = str(segment.text).strip()
            if not text:
                continue
            segments.append(
                {
                    "start": start,
                    "end": end,
                    "speaker": parsed_speaker_label(segment.speaker, job_index),
                    "text": text,
                }
            )
        segments.sort(key=lambda item: (item["start"], item["end"]))
        if not segments:
            raise RuntimeError(f"MOSS 第 {job_index} 块无法解析为说话人时间段。")
        chunk_result = {
            "chunk_id": int(job.get("chunk_id", job_index)),
            "group_id": str(job.get("group_id", "default")),
            "offset": float(job.get("offset", 0.0)),
            "duration": duration,
            "max_new_tokens": max_new_tokens,
            "prompt_tokens": int(result.get("prompt_len", 0)),
            "generated_tokens": int(result.get("generated_tokens", 0)),
            "raw_text": result["text"],
            "segments": segments,
            "checkpoint_dir": str(job.get("checkpoint_dir", "")),
            "run_signature": str(job.get("run_signature", "")),
        }
        chunk_results.append(chunk_result)
        save_chunk_checkpoint(
            args.checkpoint_dir,
            args.run_signature,
            chunk_result,
        )
        chunk_elapsed = time.perf_counter() - chunk_started
        chunk_timings.append(
            {
                "chunk_id": int(job.get("chunk_id", job_index)),
                "audio_seconds": round(duration, 3),
                "elapsed_seconds": round(chunk_elapsed, 3),
            }
        )
        print(
            f"[块 {job_index}/{len(jobs)} 完成] {len(segments)} 段，"
            f"{len({item['speaker'] for item in segments})} 位说话人，"
            f"生成 {int(result.get('generated_tokens', 0))} tokens，"
            f"耗时 {chunk_elapsed:.1f} 秒",
            flush=True,
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    payload = {
        "model": model_source,
        "title": args.title,
        "chunks": chunk_results,
        "generated_tokens": sum(item["generated_tokens"] for item in chunk_results),
        "performance": {
            "model_load_seconds": round(model_load_seconds, 3),
            "chunk_timings": chunk_timings,
            "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
            "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / 1024**3, 3),
        },
    }
    if len(chunk_results) == 1:
        payload.update(chunk_results[0])
    atomic_write_json(args.output, payload)
    print(
        f"全部完成：{len(chunk_results)} 块；峰值显存保留 "
        f"{payload['performance']['peak_reserved_gb']:.2f} GB。",
        flush=True,
    )


if __name__ == "__main__":
    main()
