"""Feasibility probe: open-source MOSS-Transcribe-Diarize on CPU (2026-10-13).

Same weights, processor and prompt as ``moss_worker.py``, but float32 on CPU
(the upstream example's non-CUDA dtype) and plain SDPA. Measures load time,
prefill (first token), decode rate, total wall time and peak resident memory
for one clip. It is a measurement, not a product path.

Run with the MOSS runtime's Python and CUDA hidden::

    set CUDA_VISIBLE_DEVICES=-1
    .venv-moss/Scripts/python.exe scripts/moss_cpu_feasibility.py --audio clip.wav --seconds 60 --out result.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _peak_rss_bytes() -> int:
    """Peak resident memory of this process, from the OS (no extra packages)."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL('kernel32')
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = kernel32.K32GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        if not get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.PeakWorkingSetSize)
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == 'darwin' else peak * 1024)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', required=True)
    parser.add_argument('--seconds', type=float, default=60.0)
    parser.add_argument('--out', required=True)
    parser.add_argument('--threads', type=int, default=0)
    args = parser.parse_args()
    import numpy as np
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoProcessor
    from moss_transcribe_diarize import parse_transcript
    from moss_transcribe_diarize.inference_utils import build_transcription_messages, load_audio_item
    from moss_worker import DEFAULT_PROMPT, resolve_model
    if args.threads:
        torch.set_num_threads(args.threads)
    stop = threading.Event()
    result = {'device': 'cpu', 'dtype': 'float32', 'cuda_visible': torch.cuda.is_available(),
              'torch': torch.__version__, 'transformers': transformers.__version__,
              'threads': torch.get_num_threads(), 'cpu': os.environ.get('PROCESSOR_IDENTIFIER', ''),
              'logical_cpus': os.cpu_count()}
    audio = np.asarray(load_audio_item(args.audio, sampling_rate=16000), dtype=np.float32)
    audio = audio[:int(args.seconds * 16000)]
    result['audio_seconds'] = round(len(audio) / 16000, 3)
    started = time.perf_counter()
    model_source = resolve_model('', ROOT)
    model = AutoModelForCausalLM.from_pretrained(model_source, trust_remote_code=True, dtype='auto',
                                                 attn_implementation='sdpa').to(dtype=torch.float32).eval()
    processor = AutoProcessor.from_pretrained(model_source, trust_remote_code=True)
    result['load_seconds'] = round(time.perf_counter() - started, 2)
    messages = build_transcription_messages(args.audio, prompt=DEFAULT_PROMPT)
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    first = {}

    class Streamer:
        count = 0

        def put(self, value):
            self.count += 1
            if self.count == 2 and 'first_token' not in first:
                first['first_token'] = time.perf_counter()

        def end(self):
            pass

    gen_started = time.perf_counter()
    with torch.inference_mode():
        inputs = processor(text=text, audio=[audio], return_tensors='pt')
        prompt_len = int(inputs['attention_mask'][0].sum().item())
        outputs = model.generate(**inputs, max_new_tokens=int(args.seconds * 24) + 256, do_sample=False,
                                 num_beams=1, streamer=Streamer())
    done = time.perf_counter()
    generated = outputs[0][prompt_len:]
    raw = processor.batch_decode([generated], skip_special_tokens=True)[0] if hasattr(processor, 'batch_decode') \
        else processor.tokenizer.decode(generated, skip_special_tokens=True)
    segments = [dict(start=float(s.start), end=float(s.end), speaker=str(s.speaker), text=str(s.text))
                for s in parse_transcript(raw)]
    stop.set()
    peak = {'rss': _peak_rss_bytes()}
    prefill = (first.get('first_token', done) - gen_started)
    decode = max(1e-6, done - first.get('first_token', gen_started))
    result.update(input_tokens=prompt_len, generated_tokens=int(generated.numel()),
                  prefill_seconds=round(prefill, 2), decode_seconds=round(decode, 2),
                  decode_tokens_per_second=round(max(0, int(generated.numel()) - 1) / decode, 2),
                  generate_seconds=round(done - gen_started, 2), wall_seconds=round(done - started, 2),
                  real_time_factor=round((done - gen_started) / max(1e-6, result['audio_seconds']), 3),
                  peak_rss_gb=round(peak['rss'] / 1024 ** 3, 2), segments=segments,
                  speakers=sorted({s['speaker'] for s in segments}))
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'segments'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
