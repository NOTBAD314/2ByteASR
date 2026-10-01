"""Local identical-PCM forensic baseline. Never downloads or changes settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if not out.is_relative_to(root/'tmp'):
        raise ValueError('Diagnostics must stay in tmp')
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1',
        HF_HOME=str(out/'hf'), TORCH_HOME=str(out/'torch'))
    sys.path.insert(0, str(root))
    import faulthandler
    faulthandler.dump_traceback_later(90, repeat=True)
    print('importing local dependencies', flush=True)
    import numpy as np
    import torch
    import transformers
    from transformers import AutoModelForAudioFrameClassification, AutoProcessor
    from twobyteasr.nemotron_stream import probabilities, MODEL_REVISION, RUNTIME_REVISION, MODE
    print('loading pinned model', flush=True)
    audio = np.load(args.audio)
    model_path = root/'models/Nemotron-3-Diarization'
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForAudioFrameClassification.from_pretrained(model_path, local_files_only=True).to('cuda').eval()
    metadata = dict(audio_path=str(args.audio.resolve()), audio_sha256=hashlib.sha256(audio.tobytes()).hexdigest(),
        samples=len(audio), sample_rate=16000, duration=len(audio)/16000, channels=1,
        model_revision=MODEL_REVISION, runtime_revision=RUNTIME_REVISION, transformers=transformers.__version__,
        torch=torch.__version__, python=sys.version, cuda=torch.version.cuda, device=torch.cuda.get_device_name(),
        model_config=model.config.to_dict(), processor_config=processor.to_dict(),
        weights_sha256=hashlib.sha256((model_path/'model.safetensors').read_bytes()).hexdigest(),
        manual_reference_available=False, paths={})
    # Official minimal offline call, exactly as the pinned HF model documents.
    with torch.inference_mode():
        started = time.perf_counter()
        print('official offline', flush=True)
        inputs = processor(audio, sampling_rate=16000).to(model.device, dtype=model.dtype)
        outputs = model(**inputs)
        raw = outputs.logits.detach().float().cpu()
        np.save(out/'official-offline-logits.npy', raw[0].numpy())
        np.save(out/'official-offline-activity.npy', raw[0].sigmoid().numpy())
        save(out/'official-offline-segments.json', processor.extract_speaker_dict(raw, inputs.attention_mask.cpu())[0])
        metadata['paths']['official_offline'] = dict(seconds=time.perf_counter()-started, shape=list(raw.shape),
            valid_frames=int(inputs.attention_mask.sum()), frame_step_seconds=processor.feature_extractor.hop_length/16000)
        # Independent official streaming recipe: carry the returned cache once,
        # advance with processor-derived offsets, final remainder has no lookahead.
        processor.set_streaming_mode(MODE)
        print('official streaming', flush=True)
        first = processor.num_samples_first_audio_chunk
        chunks = []; cache = None; cursor = 0; start = 0; steps = []
        started = time.perf_counter()
        while True:
            size = first if cursor == 0 else processor.num_samples_per_audio_chunk
            last = start+size > len(audio)
            chunk = audio[start:] if last else audio[start:start+size]
            batch = processor(chunk, sampling_rate=16000, is_streaming=True,
                is_first_audio_chunk=cursor == 0, is_last_audio_chunk=last).to(model.device, dtype=model.dtype)
            result = model(**batch, speaker_cache=cache)
            steps.append(dict(origin_frame=cursor, input_start_sample=start, input_samples=len(chunk),
                frames=int(batch.attention_mask.sum()), lookahead_encoder_frames=int(batch.get('num_lookahead_frames',0)),
                output_shape=list(result.logits.shape), continued_cache=cache is not None, last=last))
            cache = result.speaker_cache
            chunks.append(result.logits.detach().float().cpu())
            if last: break
            cursor += processor.num_mel_frames_per_step
            start = processor.audio_chunk_start(cursor)
        raw = torch.cat(chunks, 1)
        np.save(out/'official-stream-logits.npy', raw[0].numpy())
        np.save(out/'official-stream-activity.npy', raw[0].sigmoid().numpy())
        save(out/'official-stream-segments.json', processor.extract_speaker_dict(raw)[0])
        save(out/'official-stream-chunks.json', steps)
        metadata['paths']['official_stream'] = dict(seconds=time.perf_counter()-started, shape=list(raw.shape), mode=MODE)
        raw_chunks = []
        print('project integration', flush=True)
        hook = model.register_forward_hook(lambda module, args, output: raw_chunks.append(output.logits.detach().float().cpu()))
        started = time.perf_counter()
        try:
            integrated = np.concatenate([values for _, values in probabilities(audio, processor, model, torch)])
        finally:
            hook.remove()
        np.save(out/'project-activity.npy', integrated)
        np.save(out/'project-logits.npy', torch.cat(raw_chunks, 1)[0].numpy())
        metadata['paths']['project_stream'] = dict(seconds=time.perf_counter()-started, shape=list(integrated.shape),
            official_stream_max_abs_difference=float(np.max(np.abs(integrated-raw[0].sigmoid().numpy()))))
    save(out/'receipt.json', metadata)
    print(json.dumps(metadata['paths']), flush=True)
    faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__': main()
