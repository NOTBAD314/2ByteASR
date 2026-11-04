"""Isolated NeMo SALM inference using pinned, fully local Canary resources."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--model-dir',required=True)
    args=parser.parse_args()
    sys.stdout.reconfigure(encoding='utf8');sys.stderr.reconfigure(encoding='utf8')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    root=Path(__file__).resolve().parent
    if root.name=='workers':root=root.parent
    sys.path.append(str(root))
    from twobyteasr.model_integrity import verify_model_files
    from twobyteasr.runtime_paths import resolve_model_dir
    verify_model_files('canary_qwen',Path(args.model_dir),root=root)
    tokenizer=verify_model_files('canary_qwen_tokenizer',resolve_model_dir('Canary-Qwen3-Tokenizer'),root=root)
    import torch
    from safetensors.torch import load_model
    from nemo.collections.speechlm2.models import SALM
    device='cuda' if torch.cuda.is_available() and not os.environ.get('2BYTEASR_CPU_ONLY') else 'cpu'
    began=time.monotonic()
    cfg=json.loads((Path(args.model_dir)/'config.json').read_text('utf8'))
    cfg.update(pretrained_llm=str(tokenizer),pretrained_weights=False)
    # Equivalent to the upstream HFHubMixin load, with local tokenizer/config.
    # Strict state loading refuses missing/unexpected model parameters.
    model=SALM(cfg).to(dtype=torch.bfloat16 if device=='cuda' else torch.float32)
    load_model(model,str(Path(args.model_dir)/'model.safetensors'),strict=True)
    model=model.to(device).eval()
    load_s=time.monotonic()-began
    print('[2BYTEASR_CANARY] '+json.dumps(dict(event='loaded',device=device,load_s=load_s)),flush=True)
    rows=[]
    for job in json.loads(Path(args.manifest).read_text('utf8'))['jobs']:
        with torch.inference_mode():
            ids=model.generate(prompts=[[{'role':'user','content':f'Transcribe the following: {model.audio_locator_tag}','audio':[job['path']]}]],max_new_tokens=256)
        text=model.tokenizer.ids_to_text(ids[0].cpu()).strip()
        rows.append(dict(start=job['start'],end=job['end'],text=text,source='canary_qwen'))
    target=Path(args.output);pending=target.with_suffix('.pending')
    pending.write_text(json.dumps(dict(results=rows,model_loaded=True,load_s=load_s,device=device),ensure_ascii=False),'utf8')
    os.replace(pending,target)


if __name__=='__main__':main()
