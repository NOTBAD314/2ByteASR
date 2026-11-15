"""Fixed-transcript, common-boundary alignment benchmark; never invents truth."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import statistics
import time
import wave
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
import numpy as np

VARIANTS={'A':'qwen_aligner','B':'qwen_aligner','C':'qwen_ultra_aligner','D':'qwen_ultra_head'}


def read_pcm(path, output):
    """16k mono PCM16 WAV is converted in blocks; NPY is mapped read-only."""
    path=Path(path)
    if path.suffix.lower()=='.npy':
        audio=np.load(path,mmap_mode='r',allow_pickle=False)
        if audio.dtype!=np.float32 or audio.ndim!=1:
            raise ValueError('Expected mono float32 NPY')
        return audio
    with wave.open(str(path),'rb') as stream:
        if (stream.getframerate(),stream.getnchannels(),stream.getsampwidth())!=(16000,1,2):
            raise ValueError('Use mono 16k PCM16 WAV or predecoded float32 NPY')
        mapped=np.lib.format.open_memmap(output,mode='w+',dtype=np.float32,shape=(stream.getnframes(),))
        cursor=0
        while True:
            block=stream.readframes(65536)
            if not block: break
            values=np.frombuffer(block,dtype='<i2')
            mapped[cursor:cursor+len(values)]=values.astype(np.float32)/32768
            cursor+=len(values)
        mapped.flush();mapped._mmap.close()
    return np.load(output,mmap_mode='r',allow_pickle=False)


def endpoint_stats(rows, side):
    """Missing runs stay in the denominator; observed and all-case tails differ."""
    expected=[row for row in rows if row.get('reference') is not None]
    errors=[float(row[side+'_error_ms']) for row in expected if row.get(side+'_error_ms') is not None]
    missing=len(expected)-len(errors)
    absolute=sorted(abs(x) for x in errors)
    def all_percentile(q):
        if not expected:return None
        rank=max(0,math.ceil(len(expected)*q)-1)
        return absolute[rank] if rank<len(absolute) else 'unbounded_due_to_missing'
    return dict(expected=len(expected),measured=len(errors),missing_or_failed=missing,
        annotation_missing=len(rows)-len(expected),
        median_abs_ms=float(np.median(absolute)) if absolute else None,
        mae_ms=float(np.mean(absolute)) if absolute else None,
        p95_observed_ms=float(np.percentile(absolute,95)) if absolute else None,
        p99_observed_ms=float(np.percentile(absolute,99)) if absolute else None,
        p95_all_cases_ms=all_percentile(.95),p99_all_cases_ms=all_percentile(.99),
        **{f'over_{cut}_pct':100*sum(x>cut for x in absolute)/len(expected) if expected else None for cut in (250,500,1000)},
        **{f'over_{cut}_or_missing_pct':100*(sum(x>cut for x in absolute)+missing)/len(expected) if expected else None for cut in (250,500,1000)})


def common_boundary(sample, row):
    """Match original-character spans, not natural-token array positions."""
    text=sample['text']
    span=sample.get('span') or [0,len(text)]
    candidates=(row.get('word_units') or [])+(row.get('char_units') or [])
    def find(side,index):
        matches=[unit for unit in candidates if unit.get('char_'+side)==index
                 and unit.get(side+'_basis')=='model' and unit.get(side+'_ms') is not None]
        # Prefer word-pass outer boundaries; char slots only supply internal cuts.
        return float(matches[0][side+'_ms']) if matches else None
    start,end=find('start',span[0]),find('end',span[1])
    # Leading/trailing punctuation has no timestamp; common speech envelope
    # uses the first/last kept original character, not a fabricated punctuation time.
    from ..forced_alignment import content_char_map
    content=content_char_map(text[span[0]:span[1]])
    if content:
        if start is None:start=find('start',span[0]+content[0][1])
        if end is None:end=find('end',span[0]+content[-1][2])
    return start,end


def score_rows(samples,payload,ctc_times=None):
    rows={str(row['id']):row for row in payload.get('results') or []}
    scored=[]
    for sample in samples:
        row=rows.get(str(sample['id']))
        result=dict(id=sample['id'],language=sample['language'],scenario=sample.get('scenario','unspecified'),
            speaker=sample.get('speaker','S00'),reference=sample.get('reference'),status='missing',
            start_error_ms=None,end_error_ms=None,text_preserved=False)
        if row is not None:
            start,end=common_boundary(sample,row)
            if ctc_times and str(sample['id']) in ctc_times:
                start,end=ctc_times[str(sample['id'])]
            result.update(status=row.get('status'),text_preserved=row.get('text')==sample['text'],
                          start_ms=start,end_ms=end)
            if start is None or end is None:result['status']='unmeasured_common_boundary'
            if sample.get('reference') is not None:
                truth=sample['reference']
                if start is not None:result['start_error_ms']=start-float(truth['start_ms'])
                if end is not None:result['end_error_ms']=end-float(truth['end_ms'])
            units=row.get('char_units') or row.get('word_units') or []
            result['units_total']=len(units)
            result['units_unmeasured']=sum(u.get('start_basis')!='model' or u.get('end_basis')!='model' for u in units)
            result['zero_duration']=sum(u['end_ms']<=u['start_ms'] for u in units)
            result['outside_window']=sum(u['start_ms']<row['window_start_ms'] or u['end_ms']>row['window_end_ms'] for u in units)
            result['abnormal_overlap']=sum(left['end_ms']>right['start_ms'] for name in ('word_units','char_units')
                for left,right in zip(row.get(name) or [],(row.get(name) or [])[1:]))
            result['nonfinite']=sum(not math.isfinite(float(u[key])) for u in units for key in ('start_ms','end_ms'))
            result['tail_cut_over_250ms']=result['end_error_ms'] is not None and result['end_error_ms'] < -250
        scored.append(result)
    return scored


def summarize(rows):
    groups=defaultdict(list)
    for row in rows:
        for key in ('all', 'language:'+row['language'], 'scenario:'+row['language']+'/'+row['scenario']):
            groups[key].append(row)
    result={}
    for key,items in groups.items():
        result[key]=dict(samples=len(items),statuses=dict(Counter(row['status'] for row in items)),
            start=endpoint_stats(items,'start'),end=endpoint_stats(items,'end'),
            text_preserved=sum(row['text_preserved'] for row in items),
            **{name:sum(row.get(name,0) for row in items) for name in
               ('zero_duration','outside_window','nonfinite','abnormal_overlap','units_total','units_unmeasured','tail_cut_over_250ms')})
    return result


def apply_production_ctc(*args,**kwargs):
    raise RuntimeError('日语CTC已退出生产包。离线B对照须使用明确指定的旧源码：scripts/offline_ctc_reference.py --legacy-source <完整前驱源码>')


def source_identity():
    root=Path(__file__).resolve().parents[2]
    names=['qwen_aligner_worker.py','twobyteasr/forced_alignment.py',
        'twobyteasr/recognition/asr.py','twobyteasr/recognition/alignment_backend.py',
        'twobyteasr/recognition/alignment_audio.py','twobyteasr/recognition/alignment_checkpoints.py',
        'twobyteasr/recognition/ultra_local_head.py',
        'twobyteasr/acceptance/alignment_comparison.py']
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}


class ProcessTreeMemory:
    """Observed RSS of this benchmark and its owned children; 50ms samples."""
    def __init__(self):
        import threading
        self.stop_event=threading.Event()
        self.peak_tree_mb=None;self.peak_children_mb=None;self.pids=set();self.error=None
        self.thread=threading.Thread(target=self._run,daemon=True)
    def _run(self):
        try:
            import psutil
            parent=psutil.Process()
            while not self.stop_event.is_set():
                children=[]
                try:children=parent.children(recursive=True)
                except psutil.Error:pass
                own=parent.memory_info().rss;rss=0
                for child in children:
                    try:
                        rss+=child.memory_info().rss;self.pids.add(child.pid)
                    except psutil.Error:pass
                self.peak_tree_mb=max(self.peak_tree_mb or 0,(own+rss)/1024**2)
                self.peak_children_mb=max(self.peak_children_mb or 0,rss/1024**2)
                self.stop_event.wait(.05)
        except Exception as exc:self.error=type(exc).__name__+': '+str(exc)
    def start(self):self.thread.start()
    def stop(self):
        self.stop_event.set();self.thread.join(2)


def run_suite(suite_path,out,*,device='auto',repeats=3,variants='AC',batch_size=8):
    from ..recognition import asr
    from ..recognition.run_context import RuntimeContext,activate_runtime_context
    suite_path=Path(suite_path).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    suite=json.loads(suite_path.read_text('utf8'))
    if suite.get('schema')!='alignment-boundaries-v1':raise ValueError('Unknown benchmark suite schema')
    samples=suite['samples']
    if len({str(row['id']) for row in samples})!=len(samples):raise ValueError('Duplicate sample identity')
    if repeats<3:raise ValueError('Use at least three runs; cold and two warm runs are separate')
    audio=read_pcm(suite_path.parent/suite['audio'],out/'input.npy')
    jobs=[{key:sample[key] for key in ('id','text','language','window_start_ms','window_end_ms')} for sample in samples]
    os.environ['TWOBYTEASR_ALIGNER_DEVICE']=device
    input_source_identity=source_identity()
    report=dict(source_identity=input_source_identity, policy='no-qwen-or-ctc-acoustic-cache-v2', schema='alignment-comparison-v1',suite=str(suite_path),reference_kind=suite.get('reference_kind','unannotated'),
        note='Fixed transcript; no ASR/translation requests. Concatenated clips are not real long-video precision evidence.',
        runs=[],groups={},replacement_gate=dict(accepted=False,reason='requires human Japanese boundaries, scenario coverage and repeated B comparison'))
    try:
        for variant in variants:
            if variant not in VARIANTS:raise ValueError('GGUF must be an independent adapter, not a relabelled Python run')
            backend=VARIANTS[variant]
            context=RuntimeContext(alignment_checkpoint_dir=str(out/'checkpoints'/variant),
                                  asr_settings_snapshot={'models':{'firered_asr_backend':backend}})
            try:
                with activate_runtime_context(context):
                    for iteration in range(repeats):
                        record=dict(variant=variant,backend=backend,iteration=iteration,
                                    temperature='cold' if iteration==0 else 'warm',cache='disabled')
                        memory=ProcessTreeMemory();memory.start()
                        started=time.perf_counter()
                        try:
                            payload=asr._run_qwen_aligner_worker_once(audio,jobs,batch_size=batch_size)
                            ctc_times,events=apply_production_ctc(samples,payload,audio) if variant=='B' else (None,[])
                            scored=score_rows(samples,payload,ctc_times)
                            raw_name=f'{variant}-{iteration}.json'
                            (out/raw_name).write_text(json.dumps(dict(payload=payload,ctc=events,scored=scored),ensure_ascii=False,indent=2),'utf8')
                            record.update(status='completed',elapsed_s=time.perf_counter()-started,load_ms=payload.get('load_ms'),
                                inference_ms=payload.get('inference_ms'),peak_ram_mb=payload.get('peak_ram_mb'),
                                peak_qwen_vram_mb=payload.get('peak_vram_mb'),identity=payload.get('alignment_identity'),
                                execution=payload.get('execution_identity'),raw=raw_name,groups=summarize(scored))
                        except Exception as exc:
                            record.update(status='failed',elapsed_s=time.perf_counter()-started,error=f'{type(exc).__name__}: {exc}',
                                          failed_samples=len(samples),annotation_missing=sum(not row.get('reference') for row in samples),
                                          groups=summarize([dict(id=s['id'],language=s['language'],scenario=s.get('scenario','unspecified'),
                                              reference=s.get('reference'),status='failed',text_preserved=False,start_error_ms=None,end_error_ms=None)
                                              for s in samples]))
                        finally:
                            memory.stop()
                            record.update(peak_process_tree_rss_mb=memory.peak_tree_mb,
                                peak_children_rss_mb=memory.peak_children_mb,
                                memory_sample_seconds=.05,memory_error=memory.error,
                                memory_scope='parent+owned child RSS; shared/file-backed pages may be counted in more than one process',
                                full_chain_vram_mb=None,
                                vram_scope='Qwen CUDA allocator counter only; complete process-tree driver VRAM is not collected; see hardware evidence')
                        report['runs'].append(record)
                        (out/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),'utf8')
                        print(json.dumps({key:record.get(key) for key in ('variant','iteration','status','elapsed_s','inference_ms','error')},ensure_ascii=False),flush=True)
                    if report['runs'][-1]['status']=='completed':
                        started=time.perf_counter()
                        asr.run_qwen_aligner_worker(audio,jobs,batch_size=batch_size)
                        cached=asr.run_qwen_aligner_worker(audio,jobs,batch_size=batch_size)
                        report['runs'].append(dict(variant=variant,temperature='cache',status='completed',
                            checkpoint_hits=cached.get('checkpoint_hits'),windows=len(jobs),
                            cache_probe_pair_s=time.perf_counter()-started))
            finally:context.close_resources()
    finally:
        audio._mmap.close()
        report['source_stable']=source_identity()==input_source_identity
        report['replacement_gate']=replacement_gate(suite,report)
        (out/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),'utf8')
    return report


REQUIRED_JAPANESE_SCENARIOS={'dialogue','game_bgm','anime','fast','long_pause','repetition',
                             'names','mixed_language','quiet','particles','long_vowel','sokuon','overlap'}


def replacement_gate(suite, report):
    """A conservative project gate, never a claim about upstream benchmarks."""
    japanese=[row for row in suite['samples'] if row['language']=='Japanese']
    reasons=[]
    if not report.get('source_stable',False):reasons.append('benchmark_source_changed_or_not_recorded')
    if suite.get('reference_kind')!='human' or any(row.get('reference') is None for row in japanese) or not japanese:
        reasons.append('no_complete_human_japanese_boundaries')
    if len(japanese)<int(suite.get('minimum_japanese_samples',50)):
        reasons.append('insufficient_japanese_sample_count')
    tags={tag for row in japanese for tag in row.get('scenario_tags',[row.get('scenario','')])}
    missing=sorted(REQUIRED_JAPANESE_SCENARIOS-tags)
    if missing:reasons.append('missing_key_scenarios:'+','.join(missing))
    warm={variant:[row for row in report['runs'] if row['variant']==variant and row.get('temperature')=='warm']
          for variant in VARIANTS}
    if len(warm['B'])<2 or any(row['status']!='completed' for row in warm['B']):
        reasons.append('production_B_comparison_missing_or_failed')
    if reasons:return dict(accepted=False,selected=None,reasons=reasons)
    decisions={}
    for variant in ('C','D'):
        failures=[]
        candidates=warm[variant]
        if len(candidates)<2 or any(row['status']!='completed' for row in candidates):
            decisions[variant]=['candidate_repeated_runs_missing_or_failed'];continue
        for candidate in candidates:
            group=candidate.get('groups',{}).get('language:Japanese',{})
            if group.get('text_preserved')!=len(japanese):failures.append('original_text_not_preserved')
            if any(group.get(key,0) for key in ('nonfinite','outside_window','zero_duration')):
                failures.append('invalid_intervals')
            for side in ('start','end'):
                value=group.get(side,{}).get('p95_all_cases_ms')
                bases=[row.get('groups',{}).get('language:Japanese',{}).get(side,{}) for row in warm['B']]
                if not isinstance(value,(int,float)) or any(not isinstance(b.get('p95_all_cases_ms'),(int,float)) or value>b['p95_all_cases_ms'] for b in bases):
                    failures.append(side+'_p95_regression_or_missing')
                if any(group.get(side,{}).get('over_1000_or_missing_pct',100)>b.get('over_1000_or_missing_pct',0) for b in bases):
                    failures.append(side+'_severe_regression')
            if any(group.get('tail_cut_over_250ms',0)>row.get('groups',{}).get('language:Japanese',{}).get('tail_cut_over_250ms',0) for row in warm['B']):
                failures.append('tail_cut_increased')
            for key,scene in candidate.get('groups',{}).items():
                if not key.startswith('scenario:Japanese/'):continue
                for base in warm['B']:
                    previous=base.get('groups',{}).get(key)
                    if previous is None:failures.append('scenario_baseline_missing');continue
                    for side in ('start','end'):
                        a,b=scene[side]['p95_all_cases_ms'],previous[side]['p95_all_cases_ms']
                        if not isinstance(a,(int,float)) or not isinstance(b,(int,float)) or a>b:
                            failures.append('key_scenario_regression')
        median_candidate=statistics.median(row['elapsed_s'] for row in candidates)
        median_base=statistics.median(row['elapsed_s'] for row in warm['B'])
        if median_candidate>1.1*median_base:failures.append('warm_full_chain_over_1_1x')
        decisions[variant]=sorted(set(failures))
    selected=next((variant for variant in ('C','D') if decisions.get(variant)==[]),None)
    return dict(accepted=selected is not None,selected=selected,decisions=decisions,reasons=[] if selected else ['no_candidate_passed'])
