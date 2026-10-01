"""Isolated GLM-ASR adapter; Transformers 5 never enters the main runtime."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time
import wave


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--model-dir',required=True)
    args=parser.parse_args()
    sys.stdout.reconfigure(encoding='utf8');sys.stderr.reconfigure(encoding='utf8')
    root=Path(__file__).resolve().parent
    if root.name=='workers':root=root.parent
    sys.path.append(str(root))
    from twobyteasr.model_integrity import verify_model_files
    verify_model_files('glm_asr_nano',Path(args.model_dir),root=root)
    import numpy as np
    import torch
    from transformers import AutoProcessor,GlmAsrForConditionalGeneration
    device='cuda' if torch.cuda.is_available() and not os.environ.get('2BYTEASR_CPU_ONLY') else 'cpu'
    began=time.monotonic()
    processor=AutoProcessor.from_pretrained(args.model_dir,local_files_only=True)
    model=GlmAsrForConditionalGeneration.from_pretrained(args.model_dir,local_files_only=True,
        dtype=torch.bfloat16 if device=='cuda' else torch.float32).to(device).eval()
    load_s=time.monotonic()-began
    print('[2BYTEASR_GLM] '+json.dumps(dict(event='loaded',device=device,load_s=load_s)),flush=True)
    jobs=json.loads(Path(args.manifest).read_text('utf8'))['jobs']
    rows=[]
    for job in jobs:
        with wave.open(job['path'],'rb') as stream:
            if stream.getnchannels()!=1 or stream.getframerate()!=16000 or stream.getsampwidth()!=2:
                raise ValueError('GLM worker requires 16 kHz mono PCM16')
            audio=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
        inputs=processor.apply_transcription_request(audio).to(model.device,dtype=model.dtype)
        with torch.inference_mode():
            generated=model.generate(**inputs,do_sample=False,max_new_tokens=512)
        text=processor.batch_decode(generated[:,inputs.input_ids.shape[1]:],skip_special_tokens=True)[0].strip()
        rows.append(dict(start=job['start'],end=job['end'],text=text,source='glm_asr_nano'))
    target=Path(args.output);pending=target.with_suffix('.pending')
    pending.write_text(json.dumps(dict(results=rows,model_loaded=True,load_s=load_s,device=device),ensure_ascii=False),'utf8')
    os.replace(pending,target)


if __name__=='__main__':main()
