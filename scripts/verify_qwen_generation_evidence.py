"""Replay exact saved PCM windows locally; record actual generation stops."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--audio',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--limit',type=int);p.add_argument('--window',type=int)
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):p.error('fresh output under source/tmp required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile');sys.path.insert(0,str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    import numpy as np
    evidence=json.loads(a.evidence.read_text('utf8'));audio=np.load(a.audio,mmap_mode='r',allow_pickle=False)
    jobs=[]
    for old in evidence['jobs']:
        if a.window is not None and old['segment_id']!=a.window:continue
        start=round(old['start']*16000);pcm=np.ascontiguousarray(audio[start:start+old['samples']],dtype=np.float32)
        digest=hashlib.sha256(pcm.tobytes()).hexdigest()
        if digest!=old['pcm_sha256']:raise RuntimeError('saved PCM mismatch for window '+str(old['segment_id']))
        path=out/f"window-{old['segment_id']}.npy";np.save(path,pcm,allow_pickle=False)
        jobs.append(dict(old,path=str(path),context=''))
    policy=dict(evidence['policy'],generation_evidence=True,checkpoint=True,cancel_file=str(out/'cancel'))
    if a.limit is not None:policy['max_new_tokens']=a.limit
    manifest=out/'manifest.json';manifest.write_text(json.dumps(dict(jobs=jobs,policy=policy)),'utf8')
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1',HF_HOME=str(out/'hf'))
    command=[str(a.runtime),'-I','-u',str(ROOT/'qwen_asr_worker.py'),'--manifest',str(manifest),
        '--output',str(out/'result.json'),'--model-dir',str(a.model)]
    with (out/'worker.log').open('w',encoding='utf8') as log:
        code=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,timeout=600).returncode
    if code:raise RuntimeError('worker failed; see '+str(out/'worker.log'))
    result=json.loads((out/'result.json').read_text('utf8'));rows=result['results']
    summary=dict(windows=len(rows),exact_pcm_fingerprints=True,
        initial_limit_hits=sum(bool((r.get('generation') or {}).get('initial',{}).get('token_limit_reached'))
            or bool((r.get('generation') or {}).get('token_limit_reached')) for r in rows),
        retried=sum((r.get('generation') or {}).get('retry_count',0) for r in rows),
        unresolved=sum(bool((r.get('generation') or {}).get('token_limit_reached')) for r in rows),
        eos=sum(bool((r.get('generation') or {}).get('eos_observed')) for r in rows),
        manual_listening_performed=False,initial_policy=policy,injected_limit=a.limit is not None,
        elapsed_ms=result['inference_ms'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
