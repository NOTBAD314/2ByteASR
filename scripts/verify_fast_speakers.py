"""ASR-free acoustic audit of an existing frozen task and its saved API words."""
import argparse
import json
from pathlib import Path
import sys
import wave
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'): raise ValueError('tmp output required')
    out.mkdir(parents=True,exist_ok=True)
    vad=json.loads((args.cache/'firered_vad.json').read_text(encoding='utf-8'))
    source=json.loads((args.cache/'speaker-evidence/api-before-diarization.json').read_text(encoding='utf-8'))
    import numpy as np
    with wave.open(vad['identity']['path']) as wav:
        assert wav.getnchannels()==1
        rate=wav.getframerate()
        audio=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
    from twobyteasr.speaker_diarization import diarize
    records=[]
    for _ in range(2):
        rows,receipt=diarize(source['references'],audio,vad['data'],sample_rate=rate,
            model_dir=ROOT/'models/spkrec-ecapa-voxceleb',cache_dir=out,
            worker_path=ROOT/'speaker_embed_worker.py',python=sys.executable)
        assert ''.join(r['text'] for r in rows)==''.join(r['text'] for r in source['references'])
        records.append(dict(rows=rows,**receipt))
    (out/'comparison.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([dict(cache_hit=r['cache_hit'],seconds=r['elapsed_seconds'],
        windows=len(r['windows']),labels=sorted({w['speaker'] for w in r['windows']}),
        assigned_rows=sum(x['speaker']!='S00' for x in r['rows']),rows=len(r['rows'])) for r in records]))

if __name__=='__main__': main()
