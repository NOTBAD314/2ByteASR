"""Canonical isolated FunASR (SenseVoice / Fun-ASR) launcher for frozen runs.

The packaged host process ships without torch/funasr. This worker runs under
the resolved main venv, loads the model once, and transcribes every manifest
chunk in a single process (mirrors qwen_asr_worker.py).
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

_source_root = Path(__file__).resolve().parent
if _source_root.name == 'workers':
    _source_root = _source_root.parent
if str(_source_root) not in sys.path:
    sys.path.append(str(_source_root))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def _emit(event: str, **payload: object) -> None:
    print("[2BYTEASR_FUNASR] " + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _enable_unicode_sentencepiece_paths() -> None:
    """Use Python's Unicode file IO before SentencePiece's native parser.

    Some Windows wheels use narrow fopen for LoadFromFile and report existing
    Chinese paths as missing. The override lives only in this isolated worker;
    no installed third-party file or model is modified.
    """
    if os.name != "nt":
        return
    import sentencepiece as spm

    def load_from_file(processor, filename):
        return processor.LoadFromSerializedProto(Path(filename).read_bytes())

    spm.SentencePieceProcessor.LoadFromFile = load_from_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    parser.add_argument("--model-key")
    parser.add_argument("--model-dir")
    parser.add_argument("--probe-import", action="store_true")
    parser.add_argument("--expected-prefix")
    parser.add_argument("--expected-funasr-version")
    parser.add_argument("--diagnostics-dir")
    args = parser.parse_args()
    from twobyteasr.python_runtime_identity import interpreter_identity, save_identity
    import traceback
    identity = interpreter_identity()
    save_identity("worker-before-import", identity, args.diagnostics_dir)
    try:
        if args.expected_prefix and (Path(sys.prefix).resolve() != Path(args.expected_prefix).resolve()
                                     or sys.prefix == sys.base_prefix):
            raise RuntimeError("Worker did not start in the selected virtual environment")
        from funasr import AutoModel
        import funasr
        identity.update(import_passed=True, funasr_file=funasr.__file__)
        if args.expected_funasr_version and identity["distribution"]["version"] != args.expected_funasr_version:
            raise RuntimeError("Worker FunASR distribution differs from the selected runtime")
    except Exception:
        identity.update(import_passed=False, import_traceback=traceback.format_exc())
        save_identity("worker-import-failed", identity, args.diagnostics_dir)
        traceback.print_exc(file=sys.stderr)
        raise
    save_identity("worker-import-passed", identity, args.diagnostics_dir)
    if args.probe_import:
        return
    if not all((args.manifest, args.output, args.model_key, args.model_dir)):
        parser.error("manifest, output, model-key and model-dir are required for recognition")
    if args.model_key not in {"sensevoice", "funasr_nano", "paraformer"}:
        raise RuntimeError(f"Unsupported FunASR model key: {args.model_key}")
    from twobyteasr.model_integrity import verify_model_files
    _enable_unicode_sentencepiece_paths()

    model_dir = Path(args.model_dir)
    verify_model_files(args.model_key, model_dir, root=_source_root)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    jobs = manifest.get("jobs", [])
    if not jobs:
        raise RuntimeError("FunASR manifest is empty")
    try:
        import torch

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"
    load_started = time.perf_counter()
    _emit("loading", python=sys.executable, model_key=args.model_key, model_path=str(model_dir.resolve()), device=device, pid=os.getpid())
    model = AutoModel(model=str(model_dir), device=device, disable_update=True)
    load_ms = (time.perf_counter() - load_started) * 1000.0
    _emit("loaded", elapsed_ms=round(load_ms, 3))
    try:
        results = []
        inference_started = time.perf_counter()
        for job in jobs:
            options = {"input": str(job["path"]), "cache": {}, "batch_size_s": 60}
            if args.model_key == "sensevoice":
                options.update(language="auto", use_itn=True)
            elif args.model_key == "paraformer":
                options.update(pred_timestamp=True)
            try:
                rows = model.generate(**options)
            except TypeError:
                rows = model.generate(input=str(job["path"]))
            row = rows[0] if isinstance(rows, list) and rows else rows
            text = str(row.get("text", "") if isinstance(row, dict) else "")
            results.append(
                {
                    "segment_id": int(job["segment_id"]),
                    "start": float(job.get("start") or 0.0),
                    "end": float(job.get("end") or 0.0),
                    "text": text,
                }
            )
        if not any(item.get("text") for item in results):
            raise RuntimeError(f"{args.model_key} returned no text")
        inference_ms = (time.perf_counter() - inference_started) * 1000.0
        _atomic_write(
            Path(args.output),
            {"results": results, "load_ms": round(load_ms, 3), "inference_ms": round(inference_ms, 3)},
        )
        _emit("completed", raw_result_count=len(results), parsed_result_count=sum(bool(item.get("text")) for item in results), inference_ms=round(inference_ms, 3))
    finally:
        del model
        gc.collect()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        _emit("failed", error_type=type(exc).__name__, detail=str(exc))
        raise SystemExit(1)
