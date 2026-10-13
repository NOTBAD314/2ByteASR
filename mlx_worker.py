"""Apple Silicon MLX speech worker (2026-10-13), run in the managed ``mlx`` runtime.

Modes
-----
``--mode probe``  imports, MLX version, Metal availability, default device.
``--mode asr``    Qwen3-ASR (mlx-community 8-bit) on each job window of the task
                  PCM. mlx-audio returns text per window (its own segments are
                  20-minute chunks, not sentence times), so each window's bounds
                  are the only times this mode produces; word times come from
                  the aligner.
``--mode align``  Qwen3-ForcedAligner (MLX 8-bit) with the same units, slot text,
                  official monotonic repair and receipt as qwen_aligner_worker.py
                  (protocol ``qwen-aligner-units-v1``), so the app consumes MLX
                  and PyTorch alignments identically.

The implementation is mlx-audio's community port (MIT), pinned in
packaging/macos/requirements-mlx.txt. Not yet verified on a real Mac by
2ByteASR; never treat a successful import as a quality result.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

ALIGN_PROTOCOL = "qwen-aligner-units-v1"
ASR_PROTOCOL = "mlx-qwen3-asr-windows-v1"


def _emit(event: str, **payload: object) -> None:
    print("[2BYTEASR_MLX] " + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _device_info() -> dict:
    import mlx.core as mx
    info = {"mlx_version": getattr(mx, "__version__", ""), "default_device": str(mx.default_device())}
    try:
        info["metal_available"] = bool(mx.metal.is_available())
    except Exception as exc:  # older/newer mlx layouts
        info["metal_available"] = None
        info["metal_error"] = exc.__class__.__name__
    if not info.get("metal_available"):
        # No Metal device (e.g. a virtual machine): run on the MLX CPU backend
        # and say so in every receipt.
        mx.set_default_device(mx.cpu)
        info["default_device"] = str(mx.default_device())
    return info


def _load_pcm(manifest: dict):
    import numpy as np
    spec = manifest.get("audio") or {}
    pcm = np.load(str(spec["path"]), mmap_mode="r", allow_pickle=False)
    if pcm.dtype != np.float32 or pcm.ndim != 1 or pcm.size != int(spec["samples"]):
        raise RuntimeError("MLX input is not the declared mono float32 PCM")
    return pcm, spec


def _window(pcm, job, sample_rate=16000):
    import numpy as np
    start = max(0, int(job["window_start_ms"]) * sample_rate // 1000)
    end = min(pcm.size, int(job["window_end_ms"]) * sample_rate // 1000)
    return np.ascontiguousarray(pcm[start:end], dtype=np.float32)


def run_asr(manifest: dict, model_dir: Path, output: Path) -> None:
    from mlx_audio.stt import load
    policy = manifest.get("policy") or {}
    if policy.get("version") != ASR_PROTOCOL or int(policy.get("sample_rate", 0)) != 16000:
        raise RuntimeError("Unsupported MLX ASR protocol")
    pcm, spec = _load_pcm(manifest)
    device = _device_info()
    started = time.perf_counter()
    _emit("loading", model_dir=str(model_dir), jobs=len(manifest.get("jobs") or []), **device)
    model = load(str(model_dir))
    load_ms = (time.perf_counter() - started) * 1000
    _emit("loaded", elapsed_ms=round(load_ms, 1))
    results = []
    inference_started = time.perf_counter()
    jobs = manifest.get("jobs") or []
    for index, job in enumerate(jobs, 1):
        audio = _window(pcm, job)
        row = {"id": str(job["id"]), "window_start_ms": int(job["window_start_ms"]),
               "window_end_ms": int(job["window_end_ms"])}
        if audio.size < 1600:
            row.update(status="window_too_short", text="")
        else:
            out = model.generate(audio, language=job.get("language") or None,
                                 max_tokens=int(policy.get("max_tokens", 2048)))
            row.update(status="transcribed", text=str(getattr(out, "text", "") or "").strip(),
                       language=str(next((s.get("language") for s in getattr(out, "segments", None) or []
                                          if isinstance(s, dict) and s.get("language")), "") or ""),
                       generation_tokens=int(getattr(out, "generation_tokens", 0) or 0))
        results.append(row)
        _emit("progress", done=index, total=len(jobs))
    _atomic_write(output, {"protocol": ASR_PROTOCOL, "policy": policy, "audio_sha256": spec.get("sha256"),
                           "results": results, "python": sys.executable, "pid": os.getpid(), "device": device,
                           "load_ms": round(load_ms, 1),
                           "inference_ms": round((time.perf_counter() - inference_started) * 1000, 1)})
    _emit("completed", jobs=len(jobs))
    del model
    gc.collect()


def _align_batch(model, audio, units, fa):
    import numpy as np
    import mlx.core as mx
    features, mask, audio_tokens = model._preprocess_audio(audio)
    text = fa.slot_text(units).replace("<|audio_pad|>", "<|audio_pad|>" * audio_tokens)
    ids = mx.array(model._tokenizer.encode(text, return_tensors="np", add_special_tokens=False))
    logits = model(ids, input_features=features, feature_attention_mask=mask)
    mx.eval(logits)
    # The 8-bit model computes in bfloat16, which numpy cannot take through
    # the buffer protocol (first real Mac run, 2026-10-14): cast in MLX first.
    logits_np = np.array((logits[0] if logits.ndim == 3 else logits).astype(mx.float32))
    ids_np = np.array(ids[0] if ids.ndim > 1 else ids)
    slots = ids_np == model.config.timestamp_token_id
    step = float(model.config.timestamp_segment_time)
    slot_logits = logits_np[slots]
    raw = slot_logits.argmax(axis=-1) * step
    if len(raw) != 2 * len(units):
        raise RuntimeError(f"aligner slot count {len(raw)} != 2 x {len(units)} units")
    fixed = model.aligner_processor.fix_timestamp(raw)
    # Same posterior summary as the PyTorch worker: classes inside the window.
    classes = min(slot_logits.shape[-1], int(len(audio) * 1000 / 16000 / step) + 2)
    window = slot_logits[:, :classes]
    window = window - window.max(axis=-1, keepdims=True)
    probs = np.exp(window)
    probs /= probs.sum(axis=-1, keepdims=True)
    grid = np.arange(classes, dtype=np.float32) * step
    mean = probs @ grid
    spread = np.sqrt(np.clip((probs * (grid[None, :] - mean[:, None]) ** 2).sum(-1), 0, None))
    peak = probs.argmax(axis=-1)
    padded = np.pad(probs, ((0, 0), (1, 1)))
    rows = np.arange(len(peak))
    local = padded[rows, peak] + padded[rows, peak + 1] + padded[rows, peak + 2]
    posterior = {"p_max": [round(float(x), 4) for x in probs.max(axis=-1)],
                 "p_local": [round(float(x), 4) for x in local],
                 "spread_ms": [round(float(x), 1) for x in spread]}
    mx.clear_cache()
    return [float(x) for x in raw], [float(x) for x in fixed], posterior


def run_align(manifest: dict, model_dir: Path, output: Path, root: Path) -> None:
    from mlx_audio.stt import load
    from twobyteasr import forced_alignment as fa
    policy = manifest.get("policy") or {}
    if policy.get("version") != ALIGN_PROTOCOL or policy.get("audio_format") != "float32-mono-npy-v1":
        raise RuntimeError("Unsupported aligner worker protocol")
    passes = list(policy.get("passes") or ["word"])
    pcm, spec = _load_pcm(manifest)
    device = _device_info()
    started = time.perf_counter()
    _emit("loading", model_dir=str(model_dir), **device)
    model = load(str(model_dir))
    load_ms = (time.perf_counter() - started) * 1000
    _emit("loaded", elapsed_ms=round(load_ms, 1))
    results = {}
    jobs = manifest.get("jobs") or []
    inference_started = time.perf_counter()
    for index, job in enumerate(jobs, 1):
        text = str(job.get("text") or "")
        language = str(job.get("language") or "Chinese")
        audio = _window(pcm, job)
        row = {"id": job["id"], "text": text, "language": language,
               "window_start_ms": int(job["window_start_ms"]), "window_end_ms": int(job["window_end_ms"])}
        if audio.size > fa.ALIGNER_MAX_SECONDS * 16000:
            row["status"] = "window_too_long"
        elif audio.size < int(0.08 * 16000):
            row["status"] = "window_too_short"
        elif not fa.content_char_map(text):
            row["status"] = "no_alignable_text"
        else:
            processor = model.aligner_processor
            words = (processor.tokenize_japanese(text) if language.lower() == "japanese" else
                     processor.tokenize_korean(text) if language.lower() == "korean" else
                     processor.tokenize_space_lang(text))
            tokenizer = {"japanese": "mlx_japanese", "korean": "mlx_korean"}.get(language.lower(), "space_lang")
            try:
                word_units = fa.word_units(text, words)
                row["mapping"] = tokenizer
            except fa.UnitMappingError as exc:
                word_units = [fa.AlignUnit(c, a, b, "char", i) for i, (c, a, b) in enumerate(fa.content_char_map(text))]
                row["mapping"] = f"{tokenizer}_fallback_chars"
                row["mapping_error"] = str(exc)
            row["tokenizer_words"] = words
            row["status"] = "aligned"
            window_ms = round(audio.size * 1000 / 16000)
            raw, fixed, posterior = _align_batch(model, audio, word_units, fa)
            word_timed = fa.timed_units(word_units, raw, fixed, row["window_start_ms"], posterior, window_ms)
            char_timed = None
            if "char" in passes:
                chars = fa.char_units(text, word_units)
                c_raw, c_fixed, c_posterior = _align_batch(model, audio, chars, fa)
                char_timed = fa.timed_units(chars, c_raw, c_fixed, row["window_start_ms"], c_posterior, window_ms)
            segments, stats = fa.reliable_segments(word_timed, char_timed)
            row["word_units"] = fa.unit_rows(word_timed)
            row["char_units"] = fa.unit_rows(char_timed) if char_timed is not None else None
            row["segments"] = fa.unit_rows(fa.cover_display_span(text, segments))
            row["stats"] = stats
        results[str(job["id"])] = row
        _emit("progress", done=index, total=len(jobs))
    _atomic_write(output, {
        "protocol": ALIGN_PROTOCOL, "policy": policy, "results": [results[str(job["id"])] for job in jobs],
        "audio_sha256": spec.get("sha256"), "python": sys.executable, "pid": os.getpid(),
        "backend": "mlx", "device": device.get("default_device"), "device_info": device,
        "model": "mlx-community/Qwen3-ForcedAligner-0.6B-8bit", "code": fa.ALIGNER_CODE,
        "unit_policy": fa.UNIT_POLICY_VERSION, "load_ms": round(load_ms, 1),
        "inference_ms": round((time.perf_counter() - inference_started) * 1000, 1)})
    _emit("completed", jobs=len(jobs))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["probe", "asr", "align"])
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    parser.add_argument("--model-dir")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if root.name == "workers":
        root = root.parent
    sys.path.append(str(root))
    if args.mode == "probe":
        import platform
        info = _device_info()
        import mlx_audio
        import mlx_audio.stt  # noqa: F401  (the loader both modes use)
        info["mlx_audio_version"] = getattr(mlx_audio, "__version__", "")
        payload = {"protocol": "mlx-probe-v1", "ok": True, "python": sys.executable,
                   "machine": platform.machine(), **info}
        if args.output:
            _atomic_write(Path(args.output), payload)
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return
    if not args.output or not args.manifest or not args.model_dir:
        parser.error("--manifest, --output and --model-dir are required for asr/align")
    output = Path(args.output)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    from twobyteasr.model_integrity import verify_model_files
    model_dir = Path(args.model_dir)
    verify_model_files(manifest.get("model_key") or "", model_dir, root=root)
    if args.mode == "asr":
        run_asr(manifest, model_dir, output)
    else:
        run_align(manifest, model_dir, output, root)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit("failed", error_type=type(exc).__name__, detail=str(exc))
        raise SystemExit(1)
