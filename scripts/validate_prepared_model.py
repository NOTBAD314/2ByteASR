"""Production readiness check through the same adapters/workers used by tasks.

Runs in the managed main interpreter after locked files have been verified.
Receipts distinguish files/runtime readiness from actual model execution.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import wave


def moss_has_speech(output):
    """The full-context worker (2026-10-06) reports segments per chunk; older ones at the top level."""
    segments=list(output.get('segments') or [])+[s for chunk in output.get('chunks') or []
                                                 for s in chunk.get('segments') or []]
    return any(x.get('text') and x.get('speaker') for x in segments)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    root=args.root.resolve();sys.path.append(str(root))
    sys.stdout.reconfigure(encoding='utf8');sys.stderr.reconfigure(encoding='utf8')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    from twobyteasr.runtime_paths import get_runtime_paths,user_data_root
    from twobyteasr.runtime_registry import resolve_runtime_python
    contract=json.loads((root/'dependencies.lock.json').read_text('utf8'))
    model=args.model
    if model == 'omni_asr_llm_7b':
        print('[2BYTEASR_PHASE] '+json.dumps(dict(phase='weights_ready',model=model)),flush=True)
        print('[仅权重] Windows 推理适配尚不可用，文件准备完成不代表模型可执行。',flush=True)
        return 0
    import numpy as np
    import torch
    from twobyteasr import asr
    sample=root/'assets/diagnostics/speech_en.wav'
    with wave.open(str(sample),'rb') as stream:
        rate=stream.getframerate()
        audio=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
    duration=len(audio)/rate
    role={'moss':'moss','firered_llm':'firered_llm','glm_asr_nano':'glm_asr','canary_qwen':'canary'}.get(model,'main')
    cuda=torch.cuda.is_available() and not os.environ.get('2BYTEASR_CPU_ONLY')
    device=torch.cuda.get_device_name(0) if cuda else 'cpu'
    code_hash=hashlib.sha256()
    for path in [Path(__file__),root/'twobyteasr/asr.py',sample,*sorted(root.glob('*_worker.py'))]:
        code_hash.update(path.read_bytes())
    signature=hashlib.sha256(json.dumps(dict(model=contract['models'][model],runtime=resolve_runtime_python(role),install_root=str(root),
        resources={key:contract['models'][key] for key in contract['models'][model].get('required_models',[])},
        device=device,validator_code=code_hash.hexdigest()),sort_keys=True).encode()).hexdigest()
    receipts=user_data_root()/'model-readiness';receipts.mkdir(parents=True,exist_ok=True)
    receipt=receipts/(model+'.json')
    try:previous=json.loads(receipt.read_text('utf8')) if receipt.is_file() else {}
    except (ValueError,OSError):previous={}
    if not args.force and previous.get('signature')==signature and previous.get('inference_verified'):
        print('[2BYTEASR_PHASE] '+json.dumps(dict(phase='ready',model=model,cached_validation=True)),flush=True)
        return 0
    result=dict(model=model,signature=signature,started=time.time(),files_verified=True,runtime_ready=True,
        model_loaded=False,inference_verified=False,device=device,python=sys.executable,root=str(root),
        sample=str(sample),sample_kind='bundled offline synthetic speech; readiness only, not accuracy benchmark')
    try:
        print('[2BYTEASR_PHASE] '+json.dumps(dict(phase='model_loading',model=model)),flush=True)
        if model in {'moss','qwen_asr','qwen_aligner','firered_aed','firered_llm'} and not cuda:
            raise RuntimeError('hardware_unsupported: 此模型的当前正式适配需要可用的 NVIDIA CUDA；权重与运行库已保留。')
        chunks=[dict(audio=(audio,rate),start=0.,end=duration)]
        if model in {'sensevoice','paraformer','funasr_nano'}:
            output=asr._transcribe_funasr_worker(model,chunks)
        elif model=='whisper_turbo':
            output=asr.transcribe_whisper_reference(str(sample),[dict(start=0.,end=duration)],shared_audio=audio)
        elif model=='qwen_asr':
            # Same keyword contract as the production call (no glossary context for the readiness sample).
            with tempfile.TemporaryDirectory(prefix='qwen_readiness_') as evidence_root:
                output=asr._transcribe_qwen_worker(audio,chunks,asr.resolve_qwen_asr_local_source(),
                                                   context='',evidence_root=evidence_root)
        elif model=='qwen_aligner':
            import subtitle_core
            subtitle_core.FIRERED_ASR_BACKEND='qwen_aligner'
            output=asr.transcribe_qwen_aligner_reference(audio,[dict(start=0.,end=duration,
                text='Hello this is a local speech recognition test the weather is sunny today')])
            if not output or not all(0<=x['start']<x['end']<=duration+.2 for x in output):
                raise RuntimeError('对齐 worker 没有返回有效时间戳')
        elif model=='ja_ctc_aligner':
            from twobyteasr import ctc_alignment
            payload=ctc_alignment.run_worker(audio,[dict(id='readiness',text='こんにちはきょうはいいてんきです',
                window_start_ms=0,window_end_ms=int(duration*1000))])
            output=payload['results'][0]
            chars=output.get('chars') or []
            if output.get('status')!='aligned' or not chars or not all(0<=c['start_ms']<c['end_ms']<=duration*1000+200 for c in chars):
                raise RuntimeError('CTC 对齐 worker 没有返回有效字符时间')
        elif model=='firered_aed':
            output=asr._transcribe_firered_worker(audio,duration,str(get_runtime_paths().model_root/'FireRedASR2-AED'))
        elif model=='firered_llm':
            output=asr.transcribe_firered_llm_reference(str(sample),[dict(start=0.,end=duration)],shared_audio=audio)
        elif model in {'glm_asr_nano','canary_qwen'}:
            output=asr.transcribe_primary_reference(model,str(sample),[dict(start=0.,end=duration)],audio,duration)
        else:
            with tempfile.TemporaryDirectory(prefix='model_readiness_') as directory:
                temporary=Path(directory);output_path=temporary/'output.json'
                model_path=get_runtime_paths().model_root/Path(contract['models'][model]['path']).name
                if model=='moss':
                    worker=root/'workers/moss_worker.py'
                    if not worker.is_file():worker=root/'moss_worker.py'
                    command=[resolve_runtime_python('moss'),'-I',str(worker),'--audio',str(sample),'--output',str(output_path),'--model',str(model_path)]
                elif model=='speaker_embedding':
                    npy=temporary/'audio.npy';np.save(npy,audio)
                    manifest=temporary/'manifest.json'
                    manifest.write_text(json.dumps(dict(audio_npy=str(npy),sample_rate=rate,model_dir=str(model_path),audio_seconds=duration,threads=4,
                        chunks=[dict(offset=0.,duration=duration,segments=[dict(start=0.,end=duration,speaker='S01')])])),'utf8')
                    worker=root/'workers/speaker_embed_worker.py'
                    if not worker.is_file():worker=root/'speaker_embed_worker.py'
                    command=[resolve_runtime_python('main'),'-I',str(worker),'--manifest',str(manifest),'--output',str(output_path)]
                elif model=='firered_vad':
                    command=[resolve_runtime_python('main'),'-I',str(root/'firered_vad_worker.py'),'--wav',str(sample),'--model-dir',str(model_path/'VAD'),'--output',str(output_path)]
                else:raise RuntimeError('没有正式 readiness adapter: '+model)
                subprocess.run(command,check=True,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                output=json.loads(output_path.read_text('utf8'))
                if model=='moss' and not moss_has_speech(output):
                    raise RuntimeError('MOSS 没有返回实际文字与说话人分段')
                if model=='speaker_embedding' and not all(len(v)>10 and .99<float(np.linalg.norm(v))<1.01 for v in output.values()):
                    raise RuntimeError('说话人向量维度或归一化不正确')
                if model=='firered_vad' and not output.get('regions'):
                    raise RuntimeError('VAD 没有返回语音区间')
        if not output:raise RuntimeError('正式 adapter 返回空结果')
        result.update(model_loaded=True,inference_verified=True,output=output,status='PASS')
        print('[2BYTEASR_PHASE] '+json.dumps(dict(phase='ready',model=model)),flush=True)
    except Exception as exc:
        category='hardware_unsupported' if 'hardware_unsupported' in str(exc) or 'out of memory' in str(exc).lower() else 'model_load_failed'
        result.update(status='BLOCKED' if category=='hardware_unsupported' else 'FAIL',category=category,error=traceback.format_exc())
        print('[2BYTEASR_INSTALL_ERROR] '+json.dumps(dict(phase='model_loading',category=category,message=str(exc)),ensure_ascii=False),flush=True)
        traceback.print_exc()
    result['elapsed_s']=time.time()-result['started']
    pending=receipt.with_suffix('.pending');pending.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8');os.replace(pending,receipt)
    return 0 if result.get('inference_verified') else 1


if __name__=='__main__':raise SystemExit(main())
