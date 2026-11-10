"""Canonical isolated FireRedASR2-AED launcher used by source and frozen runs."""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path


def _emit(event: str, **payload: object) -> None:
    print("[2BYTEASR_FIRERED_AED] " + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _install_timestamp_receipts(model):
    """Observe the pre-fallback hypothesis for the exact returned timestamp list.

    FireRed catches forced_align errors, then _get_and_fix_timestamp creates
    uniform times. Inspecting the hypothesis here also avoids relying on batch
    position: its feature extractor may sort utterances before decoding.
    """
    from twobyteasr.recognition.firered_checkpoints import VERSION
    original=model._get_and_fix_timestamp
    receipts={}
    def observed(hyp,hyp_ids,duration):
        measured=hyp.get('timestamp') is not None
        result=original(hyp,hyp_ids,duration)
        receipts[id(result)]=dict(evidence_version=VERSION,transcription_status='success',
            alignment_status='aligned' if measured else 'failed_or_unavailable',
            timestamp_source='ctc_forced_alignment' if measured else 'uniform_window_estimate',
            timestamp_reliability='measured' if measured else 'estimated')
        return result
    model._get_and_fix_timestamp=observed
    return receipts


def _install_forced_align_dtype_probe(torch):
    """Record and repair the real torchaudio forced_align boundary when present."""
    try:
        import torchaudio.functional as functional
    except Exception:
        return None
    original = getattr(functional, "forced_align", None)
    if not callable(original):
        return None

    def wrapped(log_probs, targets, *args, **kwargs):
        payload = {
            "log_probs_dtype": str(getattr(log_probs, "dtype", "")),
            "log_probs_device": str(getattr(log_probs, "device", "")),
            "targets_dtype": str(getattr(targets, "dtype", "")),
            "targets_device": str(getattr(targets, "device", "")),
        }
        _emit("align_dtype", **payload)
        allowed = {torch.float16, torch.float32, torch.float64}
        if getattr(log_probs, "dtype", None) not in allowed:
            log_probs = log_probs.float()
            _emit("align_dtype_cast", from_dtype=payload["log_probs_dtype"], to_dtype=str(log_probs.dtype))
        device = getattr(log_probs, "device", None)
        if getattr(device, "type", "") == "mps":
            # torchaudio forced_align has no MPS kernel (2026-10-14): align on
            # the CPU and hand the result back on the model's device.
            result = original(log_probs.float().cpu(), targets.cpu(), *args, **kwargs)
            return tuple(item.to(device) if hasattr(item, "to") else item for item in result)
        return original(log_probs, targets, *args, **kwargs)

    functional.forced_align = wrapped
    return functional, original


def _resolve_device(torch, requested: str) -> str:
    """cuda | mps | cpu for ``--device`` (2026-10-14).

    ``auto`` keeps "requires CUDA" off macOS; on macOS it prefers the Apple GPU
    (MPS) and falls back to the CPU.
    """
    requested = str(requested or "auto").lower()
    if requested in ("auto", "cuda") and torch.cuda.is_available():
        return "cuda"
    if requested == "cuda" or (requested == "auto" and sys.platform != "darwin"):
        raise RuntimeError("FireRedASR2-AED requires CUDA")
    mps = getattr(torch.backends, "mps", None)
    if requested in ("auto", "mps") and mps is not None and mps.is_available():
        return "mps"
    if requested == "mps":
        raise RuntimeError("FireRedASR2-AED: Apple GPU (MPS) is not available to PyTorch on this computer")
    return "cpu"


def _atomic_write(path: Path, payload: object) -> None:
    from twobyteasr.storage.atomic_files import write_text_atomic
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False))


def main() -> None:
    # numpy and scipy each load OpenBLAS, which commits about 24 MB per CPU
    # thread at import (1.5 GB on a 32-thread CPU). Features come from
    # kaldi_native_fbank and the model runs in torch; nothing here uses that BLAS.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument('--batch-size', type=int, default=0)
    parser.add_argument('--device', default=os.environ.get('TWOBYTEASR_FIRERED_DEVICE', 'auto'),
                        choices=('auto', 'cuda', 'mps', 'cpu'))
    # Apple GPU precision (2026-10-14): float16, as on CUDA. On a 7 GB GitHub Mac it gave
    # the same text and 866 word times as float32 (one word 40 ms apart) and decoded
    # 2.6x faster (4-minute clip 412 s instead of 803 s). float32 stays selectable.
    parser.add_argument('--mps-dtype', default=os.environ.get('TWOBYTEASR_FIRERED_MPS_DTYPE', 'float16'),
                        choices=('float32', 'float16'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if root.name == 'workers':
        root = root.parent
    sys.path.append(str(root))
    source = root / "third_party" / "FireRedASR2S"
    sys.path.insert(0, str(source))
    import torch
    from twobyteasr.recognition.native_tokenizer_paths import prepare_sentencepiece_unicode_paths
    prepare_sentencepiece_unicode_paths()
    from twobyteasr import read_only_weights
    from twobyteasr.model_integrity import verify_model_files
    from fireredasr2s.fireredasr2 import FireRedAsr2, FireRedAsr2Config

    verify_model_files("firered_aed", Path(args.model_dir), root=root)
    kind = _resolve_device(torch, args.device)
    cuda = kind == "cuda"
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    jobs = manifest.get('jobs', [])
    checkpoint_root = manifest.get('checkpoint_root')
    checkpoint_identity = manifest.get('checkpoint_identity')
    from twobyteasr.recognition.firered_checkpoints import read_row, save_row, batch_budget
    all_jobs=list(jobs)
    reused={}
    if checkpoint_root and checkpoint_identity:
        for job in jobs:
            row=read_row(checkpoint_root,job,checkpoint_identity)
            if row is not None:reused[str(job['segment_id'])]=row
        jobs=[job for job in jobs if str(job['segment_id']) not in reused]
        _emit('checkpoints_reused', completed_chunks=len(reused), total_chunks=len(all_jobs))
        if reused:
            ready=[dict(reused[str(job['segment_id'])],offset=job['offset'],duration=job['duration'])
                   for job in all_jobs if str(job['segment_id']) in reused]
            _emit('batch_completed',completed_chunks=len(reused),total_chunks=len(all_jobs),
                elapsed_ms=0.,reused=True,rows=ready)
        if not jobs:
            _atomic_write(Path(args.output),dict(results=[reused[str(j['segment_id'])] for j in all_jobs],
                load_ms=0.,inference_ms=0.,reused_chunks=len(reused)))
            return
    if not jobs:
        raise RuntimeError("FireRedASR2-AED manifest is empty")
    model = None
    dtype_probe = None
    original_bf16_check = None
    telemetry = {'audio_read_ms':0., 'features_ms':0., 'cpu_to_gpu_ms':0.,
                 'encoder_ms':0., 'decode_ms':0., 'alignment_ms':0., 'batches':[],
                 'warmup':'first_batch_included', 'oom_retries':0,'batch_retries':0}
    restores=[]
    def synchronize():
        if kind == "cuda":
            torch.cuda.synchronize()
        elif kind == "mps":
            torch.mps.synchronize()
    def measure(owner, name, key, *, cuda=False):
        original=getattr(owner,name)
        def measured(*args,**kwargs):
            if cuda:synchronize()
            tick=time.perf_counter()
            try:return original(*args,**kwargs)
            finally:
                if cuda:synchronize()
                telemetry[key]+=(time.perf_counter()-tick)*1000
        setattr(owner,name,measured);restores.append((owner,name,original))
    try:
        if cuda:
            torch.cuda.reset_peak_memory_stats()
        load_started = time.perf_counter()
        _emit("loading", python=sys.executable, model_path=str(Path(args.model_dir).resolve()), pid=os.getpid())
        # FireRed's config selects BF16 on newer CUDA cards, while torchaudio
        # forced_align accepts FP16/FP32/FP64 log-probabilities only.
        original_bf16_check = getattr(torch.cuda, "is_bf16_supported", None)
        if callable(original_bf16_check):
            torch.cuda.is_bf16_supported = lambda *args, **kwargs: False
        dtype_probe = _install_forced_align_dtype_probe(torch)
        # The library only knows CUDA or CPU: MPS loads on the CPU in float32
        # and is moved to the Apple GPU below (2026-10-14).
        config = FireRedAsr2Config(
            use_gpu=cuda, use_half=cuda, beam_size=3, nbest=1,
            decode_max_len=0, softmax_smoothing=1.25,
            aed_length_penalty=0.6, eos_penalty=1.0, return_timestamp=True,
        )
        # 2026-10-15: on Windows the 4.4 GB checkpoint is mapped read-only
        # instead of read into private memory (twobyteasr/read_only_weights.py).
        model, weights_loader = read_only_weights.load(
            torch, lambda: FireRedAsr2.from_pretrained("aed", str(args.model_dir), config),
            lambda loaded: [loaded.model], torch_load_mmap=True,
            report=lambda error_type, detail: _emit("read_only_load_failed", error_type=error_type, detail=detail))
        _emit("device", kind=kind, requested=args.device)
        if kind == "mps":
            if args.mps_dtype == "float16":
                model.model.half()
            model.model.to("mps")
        try:
            parameter = next(model.model.parameters())
            _emit("model_dtype", dtype=str(parameter.dtype), device=str(parameter.device))
        except Exception:
            pass
        load_ms=(time.perf_counter()-load_started)*1000
        _emit("loaded", elapsed_ms=round(load_ms,3), weights_loader=weights_loader)
        import kaldiio
        measure(kaldiio,'load_mat','audio_read_ms')
        measure(model.model.encoder,'forward','encoder_ms',cuda=True)
        measure(model.model.decoder,'batch_beam_search','decode_ms',cuda=True)
        measure(model.model,'get_token_timestamp_torchaudio','alignment_ms',cuda=True)
        timestamp_receipts=_install_timestamp_receipts(model)
        if cuda:
            measure(torch.Tensor,'cuda','cpu_to_gpu_ms',cuda=True)
        extractor=model.feat_extractor
        half_on_mps=kind=='mps' and args.mps_dtype=='float16'   # read here: __call__'s *args shadows args
        class TimedFeatures:
            def __call__(self,*args,**kwargs):
                tick=time.perf_counter();reading=telemetry['audio_read_ms']
                try:
                    out=extractor(*args,**kwargs)
                    if kind=='mps' and isinstance(out,tuple) and len(out)>=2 and out[0] is not None:
                        moved=time.perf_counter()
                        feats=out[0].to('mps')
                        if half_on_mps:feats=feats.half()
                        out=(feats,out[1].to('mps'))+tuple(out[2:])
                        telemetry['cpu_to_gpu_ms']+=(time.perf_counter()-moved)*1000
                    return out
                finally:telemetry['features_ms']+=(time.perf_counter()-tick)*1000-(telemetry['audio_read_ms']-reading)
        model.feat_extractor=TimedFeatures()
        results = list(reused.values())
        inference_started = time.perf_counter()
        import psutil
        free_vram=torch.cuda.mem_get_info()[0] if cuda else 0
        batch_size=batch_budget(free_vram,psutil.virtual_memory().available,requested=args.batch_size)
        _emit('batch_budget', batch_size=batch_size, free_vram_bytes=free_vram,
              available_ram_bytes=psutil.virtual_memory().available)
        offset=0
        while offset<len(jobs):
            # Acquire the batch budget before feature extraction/audio loading.
            live_free=torch.cuda.mem_get_info()[0] if cuda else 0
            batch_size=min(batch_size,batch_budget(live_free,psutil.virtual_memory().available,
                                                  requested=args.batch_size))
            batch=jobs[offset:offset+batch_size];tick=time.perf_counter()
            try:
                values=model.transcribe([str(job['segment_id']) for job in batch],[str(job['path']) for job in batch])
                if len(values)!=len(batch) or {str(v.get('uttid')) for v in values}!={str(j['segment_id']) for j in batch}:
                    raise RuntimeError('FireRed inference did not return every input chunk (possible caught CUDA failure)')
            except (torch.cuda.OutOfMemoryError, RuntimeError) as exc:
                if batch_size<=1:raise
                batch_size=max(1,batch_size//2);telemetry['batch_retries']+=1
                if 'out of memory' in str(exc).lower():telemetry['oom_retries']+=1
                gc.collect()
                if cuda:torch.cuda.empty_cache()
                elif kind=='mps':torch.mps.empty_cache()
                _emit('concurrency_reduced',batch_size=batch_size,error_type=type(exc).__name__)
                continue
            by_id={str(value.get('uttid')):value for value in values}
            batch_rows=[]
            for index,job in enumerate(batch):
                value=by_id[str(job['segment_id'])]
                timestamps=[]
                for item in value.get('timestamp') or []:
                    if len(item)<3:continue
                    token,start,end=item[0],float(item[1]),float(item[2])
                    if str(token).strip() and end>start:timestamps.append({'text':str(token),'start':start,'end':end})
                row={'segment_id':int(job['segment_id']),'text':str(value.get('text') or ''),
                     'confidence':float(value.get('confidence',0.) or 0.),'timestamp':timestamps}
                row.update(timestamp_receipts.get(id(value.get('timestamp')),dict(
                    transcription_status='success',alignment_status='unknown',
                    timestamp_source='unknown',timestamp_reliability='unknown')))
                results.append(row)
                if checkpoint_root and checkpoint_identity:
                    saved=save_row(checkpoint_root,job,checkpoint_identity,row)
                    _emit('checkpoint_saved' if saved else 'checkpoint_not_reusable',
                        path=saved, segment_id=job['segment_id'],alignment_status=row['alignment_status'],
                        timestamp_source=row['timestamp_source'])
                batch_rows.append(dict(row,offset=job['offset'],duration=job['duration']))
            offset+=len(batch)
            elapsed_ms=(time.perf_counter()-tick)*1000
            telemetry['batches'].append({'size':len(batch),'elapsed_ms':round(elapsed_ms,3)})
            _emit('batch_completed',completed_chunks=offset+len(reused),total_chunks=len(all_jobs),
                processed_start=round(float(batch[0]['offset']),3),
                processed_end=round(float(batch[-1]['offset'])+float(batch[-1]['duration']),3),
                elapsed_ms=round(elapsed_ms,3),rows=batch_rows)
        if not any(item.get("timestamp") or item.get("text") for item in results):
            raise RuntimeError("FireRedASR2-AED returned no parsed output")
        results.sort(key=lambda row:int(row['segment_id']))
        telemetry['reused_chunks']=len(reused)
        telemetry.update(device=str(next(model.model.parameters()).device),dtype=str(next(model.model.parameters()).dtype),
            batch_size=batch_size,beam_size=3,coverage='full_audio_overlapping_windows',chunk_count=len(all_jobs),computed_chunks=len(jobs),
            chunk_seconds=[round(float(job['duration']),3) for job in jobs],
            device_kind=kind,
            peak_allocated_bytes=(torch.cuda.max_memory_allocated() if cuda else
                                  int(torch.mps.driver_allocated_memory()) if kind == 'mps' else None),
            peak_reserved_bytes=torch.cuda.max_memory_reserved() if cuda else None,
            first_result_ms=round(load_ms+telemetry['batches'][0]['elapsed_ms'],3))
        _atomic_write(Path(args.output), {"results": results, "load_ms":round(load_ms,3),
            "inference_ms":round((time.perf_counter()-inference_started)*1000,3),'telemetry':telemetry})
        _emit("completed", raw_result_count=len(results), parsed_segment_count=sum(bool(item.get("timestamp") or item.get("text")) for item in results))
    finally:
        for owner,name,original in reversed(restores):setattr(owner,name,original)
        if dtype_probe is not None:
            functional, original = dtype_probe
            functional.forced_align = original
        if original_bf16_check is not None:
            torch.cuda.is_bf16_supported = original_bf16_check
        if model is not None:
            del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif getattr(getattr(torch, "mps", None), "empty_cache", None) and sys.platform == "darwin":
            try:
                torch.mps.empty_cache()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit("failed", error_type=type(exc).__name__, detail=str(exc))
        raise SystemExit(1)
