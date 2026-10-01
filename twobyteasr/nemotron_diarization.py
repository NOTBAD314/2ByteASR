"""One continuous diarization job and conservative word/span activity fusion."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from .nemotron_stream import MODEL_REVISION,RUNTIME_REVISION,MODE

PARAMETERS=dict(active_threshold=.5,min_coverage=.55,min_mean_activity=.45,margin=.15)
UNKNOWN_SPEAKER='UNASSIGNED'


def activity_assignment(values,start,end,step,parameters=PARAMETERS):
    import numpy as np
    start=max(0.,float(start));end=float(end)
    lo=max(0,int(start/step));hi=min(len(values),int(np.ceil(end/step)))
    if hi<=lo or end<=start:return UNKNOWN_SPEAKER,dict(needs_confirmation=True,candidates=[],overlap=False)
    weights=np.maximum(0,np.minimum(end,(np.arange(lo,hi)+1)*step)-np.maximum(start,np.arange(lo,hi)*step))
    block=np.asarray(values[lo:hi],dtype=np.float64)
    means=(block*weights[:,None]).sum(axis=0)/max(end-start,1e-9)
    coverage=((block>=parameters['active_threshold'])*weights[:,None]).sum(axis=0)/max(end-start,1e-9)
    order=np.argsort(means)[::-1];first,second=map(int,order[:2])
    candidates=[f'NEMO_{i+1:02d}' for i in range(8) if coverage[i]>=.15]
    overlap=bool(np.any(np.sum(block>=parameters['active_threshold'],axis=1)>1))
    certain=coverage[first]>=parameters['min_coverage'] and means[first]>=parameters['min_mean_activity'] and means[first]-means[second]>=parameters['margin']
    label=f'NEMO_{first+1:02d}' if certain else UNKNOWN_SPEAKER
    return label,dict(needs_confirmation=not certain,candidates=candidates,overlap=overlap,
        mean_activity=means.round(4).tolist(),active_coverage=coverage.round(4).tolist(),
        source='nemotron',meaning='speaker activity, not transcript attribution confidence')


def merge(references,values,step,parameters=PARAMETERS):
    """Only trusted complete token spans can split text. No synthetic timings."""
    output=[]
    for row in references:
        tokens=row.get('tokens') or []
        # Punctuation, decimal signs and spaces are transcript content too.
        # A mismatched alignment remains coarse; it must never rewrite text.
        if ''.join(t.get('text',t.get('word','')) for t in tokens)!=row.get('text',''):
            tokens=[]
        if any(not float(row['start'])<=float(t['start'])<float(t['end'])<=float(row['end'])+.01 for t in tokens):tokens=[]
        groups=[]
        for unit in tokens or [row]:
            label,evidence=activity_assignment(values,unit['start'],unit['end'],step,parameters)
            if not tokens and len(evidence['candidates'])>1:
                label=UNKNOWN_SPEAKER;evidence['needs_confirmation']=True
            key=(label,evidence['overlap'],tuple(evidence['candidates']) if label==UNKNOWN_SPEAKER else ())
            if not groups or groups[-1][0]!=key:groups.append((key,[],[]))
            groups[-1][1].append(unit);groups[-1][2].append(evidence)
        for (label,overlap,_),units,evidence in groups:
            item=copy.deepcopy(row)
            if tokens:
                item.update(start=units[0]['start'],end=units[-1]['end'],tokens=copy.deepcopy(units),
                    text=''.join(t.get('text',t.get('word','')) for t in units))
            item.update(speaker=label,speaker_evidence=dict(source='nemotron',overlap=overlap,
                needs_confirmation=label==UNKNOWN_SPEAKER,granularity='word' if tokens else 'coarse_sentence',units=evidence))
            output.append(item)
    return output


def ensure_ready():
    from .environment import preflight
    from .model_registry import scan_model_registry,_sha256_matches
    from .runtime_paths import detect_install_root
    record=scan_model_registry().record('nemotron')
    if not record or record.health.value!='INSTALLED':raise RuntimeError('Nemotron 模型未安装或校验未通过，请在模型工坊下载。')
    spec=json.loads((detect_install_root()/'dependencies.lock.json').read_text('utf8'))['models']['nemotron']
    if any(not _sha256_matches(record.installation_path/name,digest) for name,digest in spec['sha256'].items()):
        raise RuntimeError('Nemotron 权重内容与固定版本校验不一致')
    runtime=preflight('nemotron')
    if not runtime.ok:raise RuntimeError('Nemotron 独立运行环境未就绪：'+'；'.join(runtime.problems))
    return record


def diarize(references,audio,cache_dir,*,mapping_version='timeline_recognition_v1'):
    from .cache import record_run_event
    fields = dict(model_id='NEMOTRON_DIARIZATION',role='speaker_diarization',backend='local')
    record_run_event('MODEL_SELECTED', **fields)
    try:
        result, receipt = _diarize(references,audio,cache_dir,mapping_version=mapping_version)
    except Exception as exc:
        record_run_event('MODEL_FAILED', **fields, failure_reason=str(exc))
        raise
    record_run_event('MODEL_RESULT_AVAILABLE' if receipt['cache_hit'] else 'MODEL_COMPLETED',
                     **fields, segment_count=len(result),cache_hit=receipt['cache_hit'])
    return result,receipt


def _diarize(references,audio,cache_dir,*,mapping_version='timeline_recognition_v1'):
    import numpy as np
    from . import asr
    from .runtime_paths import detect_install_root
    from .runtime_registry import resolve_runtime_python
    from .cloud_asr_jobs import save
    asr._raise_if_queue_cancelled()
    from .cache import record_run_event
    try:
        record=ensure_ready()
    except Exception:
        record_run_event('MODEL_ENVIRONMENT_READY',model_id='NEMOTRON_DIARIZATION',environment_ready=False)
        raise
    record_run_event('MODEL_ENVIRONMENT_READY',model_id='NEMOTRON_DIARIZATION',environment_ready=True)
    wave=np.asarray(audio,dtype='<f4')
    if wave.ndim!=1 or not np.isfinite(wave).all():raise ValueError('Nemotron requires finite mono 16kHz task PCM')
    identity=dict(version=2,audio_sha256=hashlib.sha256(wave.tobytes()).hexdigest(),samples=len(wave),sample_rate=16000,
        mapping_version=mapping_version,model_revision=MODEL_REVISION,runtime_revision=RUNTIME_REVISION,
        mode=MODE,parameters=PARAMETERS)
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    root=Path(cache_dir)/'nemotron'/key;root.mkdir(parents=True,exist_ok=True)
    output=root/'receipt.json';prob=root/'activity.npy'
    valid=False
    if output.is_file() and prob.is_file():
        receipt=json.loads(output.read_text('utf8'))
        valid=receipt.get('identity')==identity and receipt.get('artifact_sha256')==hashlib.sha256(prob.read_bytes()).hexdigest()
    if not valid:
        array=root/'input.npy';np.save(array,wave)
        worker=detect_install_root()/'nemotron_worker.py'
        if (worker.parent/'workers'/worker.name).is_file():worker=worker.parent/'workers'/worker.name
        worker_output=root/'worker-result.json'
        try:
            payload=asr._run_isolated_asr_worker([resolve_runtime_python('nemotron'),'-u',str(worker)],str(worker_output),
                model_id='NEMOTRON_DIARIZATION',audio_input=str(array),model_path=str(record.installation_path),entrypoint=str(worker),
                timeout_seconds=max(3600,len(wave)/16000*8+300),
                input_text=json.dumps(dict(audio_array=str(array),model_path=str(record.installation_path),
                    output=str(worker_output),probabilities=str(prob))))
            asr._raise_if_queue_cancelled()
            receipt=dict(identity=identity,**payload,artifact_sha256=hashlib.sha256(prob.read_bytes()).hexdigest(),
                limitation='最多8个匿名通道；不是干净音轨；超过容量或重叠文字缺失需人工复核')
            save(output,receipt)
        finally:
            array.unlink(missing_ok=True)
    values=np.load(prob,mmap_mode='r')[:receipt['frame_count']]
    if values.shape[1:]!=(8,) or not np.isfinite(values).all():raise RuntimeError('Nemotron 概率产物非法')
    record_run_event('speaker_progress',backend='nemotron',state='merging',cache_hit=valid)
    result=merge(references,values,receipt['frame_step_seconds'])
    receipt['assignments']=[dict(start=r['start'],end=r['end'],speaker=r['speaker'],evidence=r['speaker_evidence']) for r in result]
    receipt['cache_hit']=valid
    # Preserve the exact frozen text/time input and the attribution stage apart
    # from reusable model probabilities. No ASR, regrouping or text rewrite.
    assignment_key=hashlib.sha256(json.dumps(references,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    save(root/f'assignments-{assignment_key}.json',dict(input=references,output=result,
        audio_identity=identity,frame_step_seconds=receipt['frame_step_seconds']))
    record_run_event('speaker_progress',backend='nemotron',state='completed',cache_hit=valid,
                     frame_count=receipt['frame_count'],labels=sorted({r['speaker'] for r in result}),
                     audio_sha256=identity['audio_sha256'])
    return result,receipt
