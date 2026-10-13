"""Isolated Qwen3-ForcedAligner worker (main managed runtime, source and frozen runs).

Each job aligns one text against one audio window of the shared task PCM.
Units come from ``twobyteasr.forced_alignment`` with spans in the original
text; the official model, processor and monotonic repair are used unchanged.
Two passes run per job: tokenizer words (nagisa for Japanese) and characters
inside words (the model's own per-unit slots). Raw slot values, repaired
values and the repair kind are all returned.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from pathlib import Path

PROTOCOL = "qwen-aligner-units-v1"
TAG_PROTOCOL = "ja-morphology-v1"


def _emit(event: str, **payload: object) -> None:
    print("[2BYTEASR_QWEN3_ALIGNER] " + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _tokenize(aligner, text: str, language: str):
    if language.lower() == "japanese":
        import nagisa
        return list(nagisa.tagging(text).words), "nagisa"
    if language.lower() == "korean":
        processor = aligner.aligner_processor
        if processor.ko_tokenizer is None:
            from soynlp.tokenizer import LTokenizer
            processor.ko_tokenizer = LTokenizer(scores=processor.ko_score)
        return list(processor.ko_tokenizer.tokenize(text)), "soynlp"
    return list(aligner.aligner_processor.tokenize_space_lang(text)), "space_lang"


def _align_batch(aligner, audios, unit_lists, torch):
    """``Qwen3ForcedAligner.align`` with caller-supplied units; returns raw and repaired slot times."""
    from twobyteasr.forced_alignment import slot_text
    inputs = aligner.processor(text=[slot_text(units) for units in unit_lists], audio=audios,
                               return_tensors="pt", padding=True)
    inputs = inputs.to(aligner.model.device).to(aligner.model.dtype)
    with torch.inference_mode():
        logits = aligner.model.thinker(**inputs).logits
        output_ids = logits.argmax(dim=-1)
        results = []
        step = float(aligner.timestamp_segment_time)
        for row, (input_id, output_id, units) in enumerate(zip(inputs["input_ids"], output_ids, unit_lists)):
            mask = input_id == aligner.timestamp_token_id
            raw = (output_id[mask] * aligner.timestamp_segment_time).to("cpu").numpy()
            if len(raw) != 2 * len(units):
                raise RuntimeError(f"aligner slot count {len(raw)} != 2 x {len(units)} units")
            fixed = aligner.aligner_processor.fix_timestamp(raw)
            # The slot's own posterior over the time classes that lie inside this
            # window (later classes are impossible here), renormalised: peak
            # probability, mass within one class of the peak, and spread.
            classes = min(logits.shape[-1], int(len(audios[row]) * 1000 / 16000 / step) + 2)
            probs = logits[row][mask][:, :classes].float().softmax(dim=-1)
            grid = torch.arange(classes, device=probs.device, dtype=probs.dtype) * step
            mean = probs @ grid
            spread = ((probs * (grid[None, :] - mean[:, None]) ** 2).sum(-1)).clamp_min(0).sqrt()
            peak = probs.argmax(dim=-1)
            padded = torch.nn.functional.pad(probs, (1, 1))
            local = padded.gather(1, peak[:, None]) + padded.gather(1, peak[:, None] + 1) + padded.gather(1, peak[:, None] + 2)
            posterior = {"p_max": [round(float(x), 4) for x in probs.max(dim=-1).values.cpu()],
                         "p_local": [round(float(x), 4) for x in local[:, 0].cpu()],
                         "spread_ms": [round(float(x), 1) for x in spread.cpu()]}
            results.append(([float(x) for x in raw], [float(x) for x in fixed], posterior))
    return results


def select_device(torch, requested: str = "auto"):
    """CUDA (bf16/fp16) when usable, otherwise CPU float32 (2026-10-13).

    The CPU route uses the same official model, processor and timestamp
    classes; only speed differs. ``TWOBYTEASR_ALIGNER_DEVICE=cpu`` forces CPU
    for comparisons on a CUDA machine.
    """
    requested = str(requested or "auto").lower()
    if requested not in {"auto", "cuda", "cpu"}:
        raise RuntimeError(f"Unsupported aligner device: {requested}")
    if requested != "cpu" and torch.cuda.is_available():
        return "cuda:0", (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16)
    if requested == "cuda":
        raise RuntimeError("Qwen3-ForcedAligner: CUDA was requested but is not available")
    return "cpu", torch.float32


def _tag_texts(manifest_path: Path, output: Path) -> None:
    """Model-free mode: nagisa words and part-of-speech tags for subtitle line breaking."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("protocol") != TAG_PROTOCOL:
        raise RuntimeError("Unsupported morphology protocol")
    texts = [str(text) for text in manifest.get("texts") or []]
    started = time.perf_counter()
    import nagisa
    loaded = time.perf_counter()
    results = []
    for text in texts:
        tagged = nagisa.tagging(text) if text.strip() else None
        results.append({"text": text, "words": [[word, tag] for word, tag in
                                                 zip(tagged.words, tagged.postags)] if tagged else []})
    _atomic_write(output, {"protocol": TAG_PROTOCOL, "tagger": "nagisa",
                           "tagger_version": getattr(nagisa, "__version__", ""), "results": results,
                           "load_ms": round((loaded - started) * 1000), "tag_ms": round((time.perf_counter() - loaded) * 1000)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir")
    parser.add_argument("--tag-only", action="store_true")
    args = parser.parse_args()
    if args.tag_only:
        _tag_texts(Path(args.manifest), Path(args.output))
        return
    if not args.model_dir:
        parser.error("--model-dir is required")
    root = Path(__file__).resolve().parent
    if root.name == "workers":
        root = root.parent
    sys.path.append(str(root))
    import numpy as np
    import torch
    from qwen_asr import Qwen3ForcedAligner
    from twobyteasr.model_integrity import verify_model_files
    from twobyteasr import forced_alignment as fa

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    policy = manifest.get("policy", {})
    if policy.get("version") != PROTOCOL or policy.get("audio_format") != "float32-mono-npy-v1":
        raise RuntimeError("Unsupported aligner worker protocol")
    sample_rate = int(policy.get("sample_rate", 0))
    batch_size = int(policy.get("batch_size", 0))
    passes = list(policy.get("passes") or ["word"])
    if sample_rate != 16000 or not 1 <= batch_size <= 16 or not set(passes) <= {"word", "char"}:
        raise RuntimeError("Invalid aligner worker policy")
    audio_spec = manifest.get("audio") or {}
    pcm = np.load(str(audio_spec["path"]), mmap_mode="r", allow_pickle=False)
    if pcm.dtype != np.float32 or pcm.ndim != 1 or pcm.size != int(audio_spec["samples"]):
        raise RuntimeError("Aligner input is not the declared mono float32 PCM")
    jobs = manifest.get("jobs") or []
    if not jobs:
        raise RuntimeError("Aligner manifest is empty")
    verify_model_files("qwen_aligner", Path(args.model_dir), root=root)
    device, dtype = select_device(torch, os.environ.get("TWOBYTEASR_ALIGNER_DEVICE", "auto"))
    load_started = time.perf_counter()
    _emit("loading", python=sys.executable, model_path=str(Path(args.model_dir).resolve()), pid=os.getpid(),
          jobs=len(jobs), device=device, dtype=str(dtype))
    aligner = Qwen3ForcedAligner.from_pretrained(str(args.model_dir), local_files_only=True,
                                                 device_map=device, dtype=dtype)
    load_ms = (time.perf_counter() - load_started) * 1000.0
    _emit("loaded", elapsed_ms=round(load_ms, 3))
    try:
        prepared = []
        results = {}
        for job in jobs:
            text = str(job.get("text") or "")
            language = str(job.get("language") or "Japanese")
            start = max(0, int(job["window_start_ms"]) * sample_rate // 1000)
            end = min(pcm.size, int(job["window_end_ms"]) * sample_rate // 1000)
            row = {"id": job["id"], "text": text, "language": language,
                   "window_start_ms": int(job["window_start_ms"]), "window_end_ms": int(job["window_end_ms"])}
            if end - start > fa.ALIGNER_MAX_SECONDS * sample_rate:
                row["status"] = "window_too_long"
            elif end - start < int(0.08 * sample_rate):
                row["status"] = "window_too_short"
            elif not fa.content_char_map(text):
                row["status"] = "no_alignable_text"
            else:
                words, tokenizer = _tokenize(aligner, text, language)
                try:
                    word_units = fa.word_units(text, words)
                    row["mapping"] = tokenizer
                except fa.UnitMappingError as exc:
                    # Tokenizer normalisation we cannot invert: align per character instead.
                    word_units = [fa.AlignUnit(c, a, b, "char", i) for i, (c, a, b) in enumerate(fa.content_char_map(text))]
                    row["mapping"] = f"{tokenizer}_fallback_chars"
                    row["mapping_error"] = str(exc)
                row["tokenizer_words"] = words
                row["status"] = "aligned"
                prepared.append((row, np.ascontiguousarray(pcm[start:end], dtype=np.float32), word_units,
                                 fa.char_units(text, word_units) if "char" in passes else None))
            results[str(job["id"])] = row
        prepared.sort(key=lambda item: item[1].size)
        started = time.perf_counter()
        done = 0
        for offset in range(0, len(prepared), batch_size):
            batch = prepared[offset:offset + batch_size]
            long_window = max(item[1].size for item in batch) > 60 * sample_rate
            groups = [[item] for item in batch] if long_window else [batch]
            for group in groups:
                audios = [item[1] for item in group]
                word_out = _align_batch(aligner, audios, [item[2] for item in group], torch)
                char_out = (_align_batch(aligner, audios, [item[3] for item in group], torch)
                            if "char" in passes else [None] * len(group))
                for (row, audio, units, chars), (raw, fixed, posterior), char_pair in zip(group, word_out, char_out):
                    window_ms = round(audio.size * 1000 / sample_rate)
                    word_timed = fa.timed_units(units, raw, fixed, row["window_start_ms"], posterior, window_ms)
                    char_timed = (fa.timed_units(chars, char_pair[0], char_pair[1], row["window_start_ms"], char_pair[2],
                                                 window_ms) if char_pair is not None else None)
                    segments, stats = fa.reliable_segments(word_timed, char_timed)
                    row["word_units"] = fa.unit_rows(word_timed)
                    row["char_units"] = fa.unit_rows(char_timed) if char_timed is not None else None
                    row["segments"] = fa.unit_rows(fa.cover_display_span(row["text"], segments))
                    row["stats"] = stats
            done += len(batch)
            _emit("progress", done=done, total=len(prepared))
        inference_ms = (time.perf_counter() - started) * 1000.0
        _atomic_write(Path(args.output), {
            "protocol": PROTOCOL, "policy": policy, "results": [results[str(job["id"])] for job in jobs],
            "audio_sha256": audio_spec.get("sha256"), "python": sys.executable, "pid": os.getpid(),
            "torch_version": torch.__version__, "dtype": str(dtype), "device": device,
            "backend": "torch-cuda" if device.startswith("cuda") else "torch-cpu", "model": fa.ALIGNER_REPO,
            "model_revision": fa.ALIGNER_REVISION, "code": fa.ALIGNER_CODE, "unit_policy": fa.UNIT_POLICY_VERSION,
            "load_ms": round(load_ms, 3), "inference_ms": round(inference_ms, 3)})
        _emit("completed", aligned=len(prepared), jobs=len(jobs), inference_ms=round(inference_ms, 3), device=device)
    finally:
        del aligner
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit("failed", error_type=type(exc).__name__, detail=str(exc))
        raise SystemExit(1)
