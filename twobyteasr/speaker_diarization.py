"""Conservative, ASR-free ECAPA clustering on the frozen task waveform.

This estimates anonymous acoustic identities, never the real host's identity.
Uncertain/short/mixed windows stay unassigned and retain their original text.
"""
import copy
import hashlib
import json
import time
from pathlib import Path

VERSION = 'ecapa-window-v3'
COSINE_THRESHOLD = .45


def has_native_speakers(rows):
    evidence = [r.get('speaker_evidence', {}) for r in rows]
    return bool(evidence) and all(e.get('local_speaker') is not None for e in evidence) and len(
        {e.get('request_index') for e in evidence}) == 1


def speech_windows(regions, duration):
    """Use VAD turns, never concatenate unrelated short captions as a voice."""
    windows = []
    for region in regions:
        a, b = (region['start'], region['end']) if isinstance(region, dict) else region[:2]
        a, b = max(0., float(a)), min(duration, float(b))
        if b-a < .8:
            continue
        start = a
        while start < b-.79:
            end = min(b, start+2.4)
            windows.append({'start':round(start,4), 'end':round(end,4), 'speaker':f'W{len(windows):05d}'})
            if end == b: break
            start += 1.2
    return windows


def cluster_windows(windows, embeddings, threshold=COSINE_THRESHOLD):
    import numpy as np
    groups = []
    assignments = {}
    # Longer observations establish references before short observations.
    for row in sorted(windows, key=lambda r: (-(r['end']-r['start']),r['start'])):
        raw = embeddings.get('0|'+row['speaker'])
        if raw is None: continue
        vector = np.asarray(raw, dtype=float)
        vector /= max(1e-9, np.linalg.norm(vector))
        scores = [float(vector @ g['centroid']) for g in groups]
        best = max(range(len(scores)), key=scores.__getitem__) if scores else None
        if best is None or scores[best] < threshold:
            best = len(groups)
            groups.append({'centroid':vector, 'vectors':[], 'rows':[]})
        group = groups[best]
        group['vectors'].append(vector); group['rows'].append(row)
        centroid = np.mean(group['vectors'],axis=0)
        group['centroid'] = centroid/max(1e-9,np.linalg.norm(centroid))
        assignments[row['speaker']] = best
    for index, group in enumerate(groups):
        # Overlapping windows do not count the same speech twice.
        intervals = sorted((r['start'],r['end']) for r in group['rows'])
        seconds = 0.; right = -1.
        for a,b in intervals:
            seconds += max(0.,b-max(a,right)); right=max(right,b)
        group['seconds'] = seconds
        group['reliable'] = seconds >= 4 and len(group['rows']) >= 2
    output = []
    for row in windows:
        index = assignments.get(row['speaker'])
        item = dict(row, speaker='S00', confidence=0.)
        if index is not None and groups[index]['reliable']:
            vector=np.asarray(embeddings['0|'+row['speaker']],dtype=float)
            vector/=max(1e-9,np.linalg.norm(vector))
            scores=sorted((float(vector@g['centroid']), i) for i,g in enumerate(groups) if g['reliable'])
            best, target=scores[-1]
            margin=best-scores[-2][0] if len(scores)>1 else best
            if best >= threshold and margin >= .08:
                item.update(speaker=f'S{target+1:02d}',confidence=best,
                    support_seconds=groups[target]['seconds'])
        output.append(item)
    return output


def assign_identities(references, windows):
    """Split only at existing exact word boundaries; never regenerate text."""
    output=[]
    for original in references:
        words=original.get('tokens') or []
        exact_words=bool(words) and ''.join(str(w.get('text','')) for w in words)==original['text']
        units=words if exact_words else [original]
        labelled=[]
        for unit in units:
            winner,share,ordered = _identity_for_interval(unit, windows)
            if labelled and labelled[-1][0]==winner:
                labelled[-1][1].append(unit)
            else:
                labelled.append((winner,[unit]))
        for winner,group in labelled:
            row=copy.deepcopy(original)
            if exact_words:
                row.update(start=group[0]['start'],end=group[-1]['end'],
                    text=''.join(w['text'] for w in group),tokens=copy.deepcopy(group))
            row['speaker']=winner
            row['speaker_evidence']={'source':VERSION,'needs_confirmation':True,
                'identity_confirmed':False,'unassigned':winner=='S00',
                'acoustic_support_seconds':max((w.get('support_seconds',0) for w in windows if w['speaker']==winner),default=0)}
            output.append(row)
    return output


def _identity_for_interval(row, windows):
    scores={}
    for window in windows:
        overlap=max(0.,min(row['end'],window['end'])-max(row['start'],window['start']))
        if overlap:
            key=window['speaker']; scores[key]=scores.get(key,0.)+overlap
    ordered=sorted(scores,key=scores.get,reverse=True)
    winner=ordered[0] if ordered else 'S00'
    share=scores.get(winner,0)/max(1e-9,sum(scores.values()))
    if share < .85: winner='S00'
    return winner,share,ordered


def diarize(references, audio, regions, *, sample_rate, model_dir, cache_dir, worker_path, python):
    import numpy as np
    from .processes import run_speaker_embed_worker
    started=time.perf_counter()
    audio=np.asarray(audio,dtype=np.float32)
    if audio.ndim != 1:
        raise ValueError('快速分离需要本次任务的单声道冻结音频')
    model_dir=Path(model_dir)
    checkpoint=model_dir/'embedding_model.ckpt'
    if not checkpoint.is_file():
        raise RuntimeError('缺少 ECAPA 声纹模型；请选择 Filetrans 原生分轨或安装现有声纹模型，不会自动运行 MOSS')
    windows=speech_windows(regions,len(audio)/sample_rate)
    if not windows:
        raise RuntimeError('有效语音太短，无法建立可靠声纹；文字已保留，身份待确认')
    key=hashlib.sha256(VERSION.encode())
    key.update(audio.tobytes()); key.update(json.dumps(windows,sort_keys=True).encode())
    for name in ('embedding_model.ckpt','hyperparams.yaml','mean_var_norm_emb.ckpt'):
        key.update((model_dir/name).read_bytes())
    key.update(Path(worker_path).read_bytes()); key.update(str(sample_rate).encode())
    key.update(str(COSINE_THRESHOLD).encode())
    folder=Path(cache_dir)/'speaker-fast'; folder.mkdir(parents=True,exist_ok=True)
    cached=folder/(key.hexdigest()+'.json')
    if cached.is_file():
        evidence=json.loads(cached.read_text(encoding='utf-8')); hit=True
    else:
        audio_path=folder/(key.hexdigest()+'.npy')
        np.save(audio_path,audio)
        load_start=time.perf_counter()
        embeddings=run_speaker_embed_worker(worker_path=str(worker_path),main_python=python,manifest={
            'audio_npy':str(audio_path),'sample_rate':sample_rate,'model_dir':str(model_dir),
            'max_audio_seconds':2.4,'chunk_overlap_seconds':0,'audio_seconds':len(audio)/sample_rate,
            'threads':4,'batch_size':12,
            'chunks':[{'offset':0,'duration':len(audio)/sample_rate,'segments':windows}]})
        evidence={'windows':cluster_windows(windows,embeddings),'version':VERSION,
                  'cosine_threshold':COSINE_THRESHOLD, 'embeddings':embeddings,
                  'embedding_seconds':time.perf_counter()-load_start,'audio_sha256':hashlib.sha256(audio.tobytes()).hexdigest()}
        cached.write_text(json.dumps(evidence,ensure_ascii=False),encoding='utf-8'); hit=False
    result=assign_identities(references,evidence['windows'])
    return result, {**evidence,'cache_hit':hit,'elapsed_seconds':time.perf_counter()-started,
                    'text_transcription_repeated':False,'moss_called':False}
