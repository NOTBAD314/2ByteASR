"""Private-runtime installer, invoked by native bootstrap with isolated Python."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + '.pending')
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf8')
    os.replace(pending, path)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def phase(name, **fields):
    print('[2BYTEASR_PHASE] ' + json.dumps(dict(phase=name, model='nemotron', **fields)), flush=True)


def download(url, path, expected):
    from twobyteasr import network_policy
    if path.is_file() and digest(path) == expected:
        print('[Nemotron] Verified reuse: ' + path.name, flush=True)
        return
    pending = path.with_suffix(path.suffix + '.partial')
    if pending.is_file() and digest(pending) == expected:
        os.replace(pending, path)
        print('[Nemotron] Recovered verified complete partial: ' + path.name, flush=True)
        return
    start = pending.stat().st_size if pending.exists() else 0
    headers = {'Range': f'bytes={start}-'} if start else {}
    begun = time.monotonic()
    with network_policy.get(url, headers=headers, stream=True, timeout=(30, 120)) as response:
        if response.status_code == 416 and start:
            # This partial has already failed the expected digest. Keep it for
            # diagnosis and restart this one file once without a Range header.
            os.replace(pending, pending.with_suffix('.invalid'))
            return download(url, path, expected)
        if response.status_code not in (200, 206):
            response.raise_for_status()
        if response.status_code == 206:
            if not response.headers.get('Content-Range', '').startswith(f'bytes {start}-'):
                raise RuntimeError('Invalid resumed Content-Range')
        else:
            start = 0
        total = start + int(response.headers.get('Content-Length') or 0)
        free = shutil.disk_usage(path.parent).free
        if total and free < total - start + 256 * 1024 * 1024:
            raise RuntimeError('Insufficient disk space for remaining model bytes')
        size, last = start, 0.
        with pending.open('ab' if start else 'wb') as stream:
            for chunk in response.iter_content(1024 * 1024):
                stream.write(chunk)
                size += len(chunk)
                now = time.monotonic()
                if now - last >= 1:
                    last = now
                    phase('weights_downloading', file=path.name, downloaded=size, total=total,
                          bytes_per_second=round((size-start)/max(.01, now-begun)),
                          remaining_bytes=max(0, total-size), free_bytes=free)
        if total and size != total:
            raise RuntimeError('Incomplete download; partial file retained')
    if digest(pending) != expected:
        os.replace(pending, pending.with_suffix('.invalid'))
        raise RuntimeError('Model SHA256 mismatch: ' + path.name)
    os.replace(pending, path)


def main():
    parser = argparse.ArgumentParser()
    for key in ('root', 'runtime', 'models', 'source', 'sample'):
        parser.add_argument('--'+key, default='')
    args = parser.parse_args()
    root, runtime = Path(args.root).resolve(), Path(args.runtime).resolve()
    sys.path.append(str(root))  # Frozen GUI contains incompatible cp310 extensions.
    from twobyteasr.runtime_paths import user_data_root
    lock = json.loads((root/'dependencies.lock.json').read_text('utf8'))
    spec = lock['models']['nemotron']
    folder = Path(args.models).resolve()/Path(spec['path']).name
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = runtime/'nemotron-readiness.json'
    previous = json.loads(receipt_path.read_text('utf8')) if receipt_path.is_file() else {}
    if not args.sample and previous.get('inference_verified') and (Path(previous.get('validation_dir', str(runtime)))/'validation-input.npy').is_file():
        import numpy as np
        import soundfile as sf
        stored = Path(previous.get('validation_dir', str(runtime)))/'validation-input.npy'
        expected = previous.get('validation_input_sha256')
        if expected and digest(stored) == expected:
            sample = runtime/'retained-validation-sample.wav'
            sf.write(sample, np.load(stored, allow_pickle=False), 16000, subtype='FLOAT')
            args.sample = str(sample)
    attempt_root = runtime/('attempt-'+str(time.time_ns()))
    attempt_root.mkdir()
    attempt_path = attempt_root/'readiness.json'
    receipt = dict(schema_version=1, model_revision=spec['revision'], python=sys.executable,
                   runtime_ready=True, weights_ready=False, model_loaded=False,
                   inference_verified=False, started_at=time.time(), model_path=str(folder))
    save(attempt_path, receipt)
    stage = 'weights_downloading'
    try:
        from twobyteasr.repository_download import download_model
        receipt['source_mode'] = download_model(model_key='nemotron', spec=spec,
            destination=folder, mode=args.source,
            staging_root=Path(args.models).resolve()/'.downloads')
        receipt.update(weights_ready=True, files={n: dict(bytes=(folder/n).stat().st_size,
                       sha256=digest(folder/n)) for n in spec['required_files']})
        save(attempt_path, receipt)
        stage = 'model_loading'
        phase(stage)
        import numpy as np
        import torch
        from transformers import AutoProcessor, AutoModelForAudioFrameClassification
        from twobyteasr.nemotron_stream import MODE, probabilities
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        receipt.update(torch=torch.__version__, cuda_build=torch.version.cuda, device=device,
                       gpu=torch.cuda.get_device_name() if device == 'cuda' else '', cuda_kernel_verified=False)
        if device == 'cuda':
            probe = torch.arange(1024, device='cuda', dtype=torch.float32)
            if not torch.isfinite((probe[:, None] @ probe[None, :]).sum()).item():
                raise RuntimeError('CUDA tensor operation produced nonfinite result')
            torch.cuda.synchronize()
            receipt['cuda_kernel_verified'] = True
        begun = time.monotonic()
        processor = AutoProcessor.from_pretrained(folder, local_files_only=True)
        processor.set_streaming_mode(MODE)
        model = AutoModelForAudioFrameClassification.from_pretrained(folder, local_files_only=True).to(device).eval()
        receipt.update(model_loaded=True, load_seconds=time.monotonic()-begun)
        stage = 'model_forward'
        phase(stage)
        for _, values in probabilities(np.zeros(32000, dtype=np.float32), processor, model, torch):
            if not np.isfinite(values).all():
                raise RuntimeError('Model forward produced nonfinite output')
        receipt['forward_verified'] = True
        del model, processor
        if device == 'cuda':
            torch.cuda.empty_cache()
        if args.sample:
            stage = 'inference_verifying'
            phase(stage)
            sample_path = Path(args.sample).resolve()
            import soundfile as sf
            wave, rate = sf.read(sample_path, dtype='float32')
            if wave.ndim != 1 or rate != 16000 or not 1 <= len(wave)/rate <= 60:
                raise RuntimeError('Validation sample must be 1-60 seconds of 16k mono human audio')
            np.save(attempt_root/'validation-input.npy', wave)
            worker = root/'workers'/'nemotron_worker.py'
            if not worker.is_file():
                worker = root/'nemotron_worker.py'
            request = dict(audio_array=str(attempt_root/'validation-input.npy'), model_path=str(folder),
                           output=str(attempt_root/'validation-result.json'), probabilities=str(attempt_root/'validation-activity.npy'))
            begun = time.monotonic()
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(worker)], input=json.dumps(request),
                                    text=True, encoding='utf-8', capture_output=True, timeout=600,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), cwd=str(runtime))
            (attempt_root/'validation-worker.log').write_text(result.stdout+'\n'+result.stderr, 'utf8')
            if result.returncode:
                raise RuntimeError('Worker inference failed: '+result.stderr[-1200:])
            output = json.loads((attempt_root/'validation-result.json').read_text('utf8'))
            activity = np.load(attempt_root/'validation-activity.npy')[:output['frame_count']]
            if activity.shape[1:] != (8,) or not len(activity) or not np.isfinite(activity).all():
                raise RuntimeError('Invalid worker activity artifact')
            intervals = []
            for speaker in range(8):
                edges = np.diff(np.r_[False, activity[:, speaker] >= .5, False].astype(int))
                for a, b in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
                    intervals.append(dict(speaker=speaker+1, start=a*output['frame_step_seconds'],
                                          end=b*output['frame_step_seconds']))
            receipt.update(inference_verified=True, sample_sha256=digest(sample_path),
                           validation_input_sha256=digest(attempt_root/'validation-input.npy'),
                           audio_seconds=len(wave)/rate, inference_seconds=time.monotonic()-begun,
                           worker=output, intervals=intervals)
        else:
            # Always validate the independent worker protocol. Silence proves
            # protocol/load only; it must never be called human inference.
            np.save(attempt_root/'validation-input.npy', np.zeros(32000, dtype=np.float32))
            worker = root/'workers'/'nemotron_worker.py'
            if not worker.is_file(): worker = root/'nemotron_worker.py'
            request = dict(audio_array=str(attempt_root/'validation-input.npy'), model_path=str(folder),
                           output=str(attempt_root/'validation-result.json'), probabilities=str(attempt_root/'validation-activity.npy'))
            result = subprocess.run([sys.executable,'-I','-X','utf8',str(worker)], input=json.dumps(request),
                text=True,encoding='utf-8',capture_output=True,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=str(runtime))
            (attempt_root/'validation-worker.log').write_text(result.stdout+'\n'+result.stderr,'utf8')
            if result.returncode: raise RuntimeError('Worker protocol failed: '+result.stderr[-1200:])
            receipt['worker_protocol_verified'] = True
        receipt.update(completed_at=time.time(), error=None, validation_dir=str(attempt_root))
        save(attempt_path, receipt)
        # Publish only after actual load/forward; readiness layers remain separate.
        registry_path = user_data_root()/'runtimes'/'registry.json'
        old = json.loads(registry_path.read_text('utf8')) if registry_path.is_file() else {}
        old.setdefault('schema_version', 1)
        old.setdefault('runtimes', {})['nemotron'] = dict(runtime_id='nemotron-'+runtime.name,
            python_executable=sys.executable, root=str(runtime), source='private-native-bootstrap',
            registered_at=time.time(), readiness=str(attempt_path))
        save(registry_path, old)
        save(receipt_path, receipt)
        phase('runtime_ready', inference_verified=receipt['inference_verified'], device=device)
    except Exception as exc:
        receipt.update(error=dict(phase=stage, message=str(exc)), completed_at=time.time())
        save(attempt_path, receipt)
        print('[2BYTEASR_INSTALL_ERROR] '+json.dumps(dict(phase=stage, message=str(exc))), flush=True)
        raise


if __name__ == '__main__':
    main()
