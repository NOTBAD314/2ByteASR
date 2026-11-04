"""Ready MOSI shards advance locally; only final collection waits for all.

The existing transcript, grouping, timing and translation implementations own
their rules. This coordinator owns bounded admission, stable IDs, immutable
versions, per-shard checkpoints and the final deterministic merge.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, replace, field
from pathlib import Path

from .run_context import ContextExecutor, local_runtime_context

VERSION = 'ready-native-shards-v4-chinese-acoustic-dependencies'
STRIDE = 1_000_000


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode('utf-8')).hexdigest()


def eligible(context, legacy, seconds):
    """Native independent request identities are already protected boundaries.

    Full three-ASR arbitration and explicit language-recovery tasks keep their
    owning dependency graph until those recognizers expose per-shard receipts.
    """
    from ..providers.mosi_asr import MODEL
    from ..subtitle_rules.language_rules import EUROPEAN
    endpoint = context.asr_endpoint_snapshot or {}
    if seconds <= 25*60: return False, 'single_native_request'
    if endpoint.get('model') != MODEL or str(getattr(legacy,'PRIMARY_ASR_BACKEND','')) != 'api':
        return False, 'different_primary_path'
    if context.requested_language not in {'zh','ja','en','ko',*EUROPEAN}:
        return False, 'language_requires_global_resolution_or_arbitration'
    if context.recognition_purpose != 'final' or context.enable_term_search:
        return False, 'selected_global_analysis'
    if context.recognition_snapshot.get('language_recovery_policy'):
        return False, 'explicit_language_recovery'
    if str(getattr(legacy,'QWEN_ASR_BACKEND','off')) != 'off' and getattr(legacy,'USE_QWEN_ASR_REFERENCE',False):
        return False, 'independent_asr_review_not_shard_ready'
    timeline=str(getattr(legacy,'FIRERED_ASR_BACKEND',''))
    if timeline not in {'qwen_aligner','mlx_qwen_aligner','mfa_aligner','off','local'}:
        return False, 'selected_timeline_requires_its_own_acoustic_evidence'
    if context.requested_language=='zh':
        import os
        if (timeline!='local' or context.speaker_source not in {'native','single'}
                or context.dialogue_coverage_mode!='all_dialogue' or context.expected_speakers
                or os.environ.get('FIRERED_LLM_ENDPOINT') or not getattr(legacy,'PARALLEL_GPU_ASR',False)):
            return False, 'chinese_global_selection_or_optional_review'
    elif timeline=='local':
        return False, 'local_firered_requires_chinese'
    return True, 'independent_native_requests_with_explicit_language'


@dataclass
class ShardResult:
    index: int
    version: str
    primary: list
    segments: list
    cues: list
    translation: dict
    reviews: list
    error: BaseException | None = None
    polishing_summary: dict = field(default_factory=dict)


def aggregate_polishing(results):
    """One task summary, not whichever parallel shard happened to finish last."""
    totals={key:0 for key in ('success_batches','fallback_batches','success_cues','fallback_cues')}
    output={'count_scope':'all_shards_processing_records','success_ids':[],'fallback_ids':[],
            'failure_records':{},'failure_categories':{},'term_context':{'accepted_edits':0},'cached_complete_shards':0}
    failed=False
    for result in results:
        summary=result.polishing_summary
        failed=failed or any(r.get('category')=='校对回退' for r in result.reviews)
        if not summary:
            output['cached_complete_shards']+=1
            continue
        for key in totals:totals[key]+=int(summary.get(key) or 0)
        def identity(value):
            try:
                number=int(value)
                return number if number>=STRIDE else (result.index+1)*STRIDE+number
            except (ValueError,TypeError):return f'r{result.index+1:03}:{value}'
        for key in ('success_ids','fallback_ids'):
            output[key].extend(identity(value) for value in summary.get(key,[]))
        for key,value in (summary.get('failure_records') or {}).items():output['failure_records'][str(identity(key))]=value
        for key,value in (summary.get('failure_categories') or {}).items():output['failure_categories'][key]=output['failure_categories'].get(key,0)+int(value)
        output['term_context']['accepted_edits']+=int((summary.get('term_context') or {}).get('accepted_edits') or 0)
    output.update(totals)
    output['status']='partial' if failed or totals['fallback_batches'] or totals['fallback_cues'] else 'completed'
    return output


class LongMediaPipeline:
    def __init__(self, *, context, legacy, pipeline, media_path, cache_context, audio,
                 seconds, fps, paths, text_plan):
        from ..system.task_resources import task_budget
        self.context, self.legacy, self.pipeline = context, legacy, pipeline
        self.media_path, self.cache_context, self.audio = media_path, cache_context, audio
        self.seconds, self.fps, self.paths, self.text_plan = seconds, fps, paths, text_plan
        self.budget = context.execution_budget or task_budget()
        self.last_budget_at=0.
        self.active_shard_limit=self.budget.shard_workers
        context.execution_budget = self.budget
        self.pool = ContextExecutor(max_workers=self.budget.shard_workers,thread_name_prefix='ready-shard')
        self.lock = threading.RLock()
        self.vad_ready = threading.Event()
        self.speech_regions = []
        self.piece_vad=False;self.vad_by_index={};self.vad_events={}
        self.inputs, self.futures, self.coarse, self.results = {}, {}, {}, {}
        self.total = 0
        self.extra_nodes = set()
        self.waiting = deque()
        self.closed = False
        self.phase_stats = {}
        self.completed_nodes = set()
        self.timeline_condition=threading.Condition()
        self.timeline_jobs=[]
        self.timeline_rows={}
        self.timeline_done=False
        self.timeline_final=None
        self.root = Path(cache_context['cache_dir'])/'ready-shards'
        self.root.mkdir(parents=True, exist_ok=True)

    def set_timeline_plan(self,jobs):
        with self.timeline_condition:
            self.timeline_jobs=list(jobs)
            self.timeline_condition.notify_all()

    def add_timeline_rows(self,rows):
        with self.timeline_condition:
            for row in rows:self.timeline_rows[int(row['segment_id'])]=row
            self.timeline_condition.notify_all()

    def finish_timeline(self,result):
        with self.timeline_condition:
            self.timeline_final=result
            self.timeline_done=True
            self.timeline_condition.notify_all()

    def timeline_for(self,bounds):
        from .asr_schema import normalize_firered_worker_result, flatten_segment_tokens
        began=time.perf_counter()
        with self.timeline_condition:
            while True:
                self._check()
                if self.timeline_done:
                    if not self.timeline_final:raise RuntimeError('FireRed 工作进程未交付有效结果；其它分片保留。')
                    tokens=flatten_segment_tokens(self.timeline_final)
                    break
                prefix=[]
                for job in self.timeline_jobs:
                    row=self.timeline_rows.get(int(job['segment_id']))
                    if row is None:break
                    prefix.append(row)
                # Normalize against the full plan: even the last ready window
                # keeps its overlap ownership with the following window.
                covered=(float(self.timeline_jobs[len(prefix)-1]['offset']) if prefix else 0.)
                if prefix and covered >= bounds[1]+2.:
                    tokens=flatten_segment_tokens(normalize_firered_worker_result({'results':prefix},self.timeline_jobs))
                    break
                self.timeline_condition.wait(.1)
        self.legacy.record_run_event('acoustic_dependency_wait', waited_seconds=time.perf_counter()-began,
                                     start=bounds[0],end=bounds[1])
        return [row for row in tokens if float(row['end'])>=bounds[0]-2. and float(row['start'])<=bounds[1]+2.]

    def set_vad(self, regions):
        self.speech_regions = list(regions or [])
        self.vad_ready.set()

    def set_piece_vad(self,index,regions):
        with self.lock:
            self.vad_by_index[index]=list(regions)
            self.speech_regions=[row for values in self.vad_by_index.values() for row in values]
            self.vad_events.setdefault(index,threading.Event()).set()

    def _check(self):
        from .asr import _raise_if_queue_cancelled
        from .run_context import context_is_current
        from .service import CancelledError
        _raise_if_queue_cancelled()
        if self.closed or not context_is_current(self.context):
            raise CancelledError('分片流水线所属的任务已结束。')

    def accept(self, payload):
        """This callback never waits for another cloud request or downstream work."""
        index, total = int(payload['request_index']), int(payload['request_total'])
        if not 0 <= index < total:raise ValueError('分片身份超出清单。')
        revision=int(payload.get('input_revision',0))
        rows = copy.deepcopy(payload.get('rows') or [])
        version = _digest(dict(version=VERSION, media=self.cache_context['identity'], index=index,
            rows=[{key:row.get(key) for key in ('start','end','text','speaker','source','tokens','cloud_gap')}
                  for row in rows], language=self.context.requested_language,
            timeline=str(getattr(self.legacy,'FIRERED_ASR_BACKEND','')),
            fps=self.fps,speaker_source=self.context.speaker_source,
            grouping_prompts=self.context.asr_settings_snapshot.get('grouping_prompts'),
            switches=self.context.asr_settings_snapshot.get('switches'),
            timing_policy=getattr(self.legacy,'TIMING_LOGIC_VERSION',None),
            vad_mode='owned-shard-v1' if self.piece_vad else 'full-stage-v1',
            game_name=self.context.game_name,
            glossary=getattr(self.context.glossary_snapshot,'digest',None),
            providers={key:value.fingerprint for key,value in self.context.provider_snapshots.items()},
            output=self.context.subtitle_output,target=self.context.translation_script,
            grouping=bool(self.text_plan.group),polish=bool(self.text_plan.polish)))
        with self.lock:
            if self.closed:
                return
            self.total = max(total,self.total)
            if self.inputs.get(index,{}).get('version') == version:
                return
            previous=self.inputs.get(index)
            if previous and revision<=previous['revision']:
                self.legacy.record_run_event('ready_shard_late_input_rejected',request_index=index,
                    input_revision=revision,current_revision=previous['revision'])
                return
            if previous:
                self.completed_nodes={node for node in self.completed_nodes if node[0]!=index}
            from ..storage.atomic_files import write_text_atomic
            incoming=self.root/f'r{index+1:03}-{version}-input.json'
            write_text_atomic(incoming,json.dumps(rows,ensure_ascii=False))
            self.inputs[index] = dict(version=version,path=str(incoming),revision=revision)
            if any(row.get('cloud_gap') for row in rows):self.extra_nodes.add(index)
            event = self.coarse[index] = threading.Event()
            self.waiting.append((index,version,str(incoming),event))
            self._dispatch()
        self.legacy.record_run_event('ready_shard_queued',shard_id=f'r{index+1:03}', input_version=version,
                                    request_index=index,request_total=total)

    def _dispatch(self,unused=None):
        with self.lock:
            if self.closed:return
            if time.monotonic()-self.last_budget_at>=2.:
                from ..system.task_resources import live_budget
                current=live_budget()
                self.active_shard_limit=min(self.budget.shard_workers,current.shard_workers)
                self.last_budget_at=time.monotonic()
            active=sum(not future.done() for future in self.futures.values())
            while self.waiting and active < self.active_shard_limit:
                index,version,path,event=self.waiting.popleft()
                if self.inputs[index]['version']!=version:continue
                future=self.pool.submit(self._run,index,version,path,event)
                self.futures[index]=future
                future.add_done_callback(self._dispatch)
                active+=1

    def _context(self,index):
        child = replace(self.context, shard_id=f'r{index+1:03}', root_context=self.context,
            shard_input_version=self.inputs[index]['version'],
            task_language=self.context.task_language or self.context.requested_language,
            language_evidence=copy.deepcopy(self.context.language_evidence),
            language_decision=copy.deepcopy(self.context.language_decision),
            review_items=[], speaker_recovery={}, polishing_summary={}, transcript_acceptance={},
            japanese_phrases=None, segment_alignment_evidence=None, primary_ready_callback=None,
            long_pipeline=None, translation_ready=None)
        # dataclasses.replace runs __post_init__; restore the already bound task
        # decision as an independent snapshot after that initialisation.
        child.language_decision=copy.deepcopy(self.context.language_decision)
        return child

    def _step(self,index,phase,label,runner):
        from .pipeline_activity import work
        self._check()
        started=time.perf_counter()
        succeeded=False
        try:
            with work(self.legacy,phase,f'第 {index+1}/{self.total} 片 · {label}'):
                result=runner()
                succeeded=True
                return result
        finally:
            with self.lock:
                stats=self.phase_stats.setdefault(phase,dict(started=started,finished=started,execution_seconds=0.,nodes=0))
                stats['started']=min(stats['started'],started);stats['finished']=max(stats['finished'],time.perf_counter())
                stats['execution_seconds']+=time.perf_counter()-started;stats['nodes']+=1
                if succeeded:self.completed_nodes.add((index,phase))
                completed=len(self.completed_nodes)
            self.legacy.record_run_event('long_pipeline_progress',completed=completed,total=max(1,self.total)*6+len(self.extra_nodes),
                shards=self.total,phase=phase,request_index=index)

    def _load(self,path,version):
        try:
            saved=json.loads(path.read_text(encoding='utf-8'))
            if saved.get('version') != version or saved.get('checksum') != _digest(saved.get('data')):
                return None
            data=saved['data']
            if data.get('incomplete_roles'):return None
            cues=self.legacy.deserialize_cues(data['cues'])
            for cue,row in zip(cues,data['cues']):
                if row.get('forced_alignment'):cue.forced_alignment=row['forced_alignment']
            result=ShardResult(data['index'],version,data['primary'],self.legacy.deserialize_segments(data['segments']),
                               cues,data['translation'],data['reviews'])
            result.polishing_summary=data.get('polishing_summary') or {}
            return result
        except (OSError,ValueError,KeyError,TypeError):
            return None

    def _save(self,path,result):
        from ..storage.atomic_files import write_text_atomic
        cues=self.legacy.serialize_cues(result.cues)
        for row,cue in zip(cues,result.cues):
            if getattr(cue,'forced_alignment',None):row['forced_alignment']=cue.forced_alignment
        data=dict(index=result.index,primary=result.primary,segments=self.legacy.serialize_segments(result.segments),
                  cues=cues,translation=result.translation,reviews=result.reviews,
                  incomplete_roles=bool(getattr(result,'incomplete_roles',False)),polishing_summary=result.polishing_summary)
        write_text_atomic(path,json.dumps(dict(version=result.version,checksum=_digest(data),data=data),ensure_ascii=False))

    def _run(self,index,version,incoming,coarse_ready):
        local=self._context(index)
        result=ShardResult(index,version,[],[],[],{},[])
        with local_runtime_context(local):
            try:
                raw=json.loads(Path(incoming).read_text(encoding='utf-8'))
                result.primary=raw
                with self.legacy.capture_review_items() as reviews:
                    path=self.root/f'r{index+1:03}-{version}.json'
                    fresh=any((local.force_refresh_api_cache,local.force_refresh_polish_cache,local.force_refresh_group_cache))
                    cached=None if fresh else self._load(path,version)
                    if cached is not None:
                        result=cached
                        with self.lock:
                            if self.inputs[index]['version']!=version:raise ValueError('分片版本已被替换。')
                            self.results[index]=result
                        coarse_ready.set()
                        self.legacy.record_run_event('ready_shard_cache_hit',shard_id=local.shard_id,input_version=version)
                        if str(getattr(self.legacy,'FIRERED_ASR_BACKEND','off'))!='off':
                            self.legacy.record_run_event('MODEL_RESULT_AVAILABLE',
                                model_id=str(self.legacy.FIRERED_ASR_BACKEND),role='timeline_alignment',
                                backend=str(self.legacy.FIRERED_ASR_BACKEND),segment_count=len(result.cues),
                                execution='validated_shard_checkpoint')
                        return result
                    with self.lock:
                        ready=self.vad_events.setdefault(index,threading.Event()) if self.piece_vad else self.vad_ready
                    while not ready.wait(.1):self._check()
                    self._check()
                    primary=self._prepare_primary(index,raw,local)
                    result.primary=primary
                    with self.lock:
                        if self.inputs[index]['version'] != version:raise ValueError('分片版本已被替换。')
                        self.results[index]=result
                    coarse_ready.set()
                    result=self._process(index,version,primary,local)
                result.reviews=list(reviews)
                result.polishing_summary=copy.deepcopy(local.polishing_summary)
                retry_categories={'校对回退','断句回退','翻译未全部完成','翻译未完成','字级对齐失败','缺少对齐模型'}
                records=(result.translation.get('translation_records') or {}).get('records') or {}
                result.incomplete_roles=(any(row.get('category') in retry_categories for row in result.reviews)
                    or any(row.get('status') in {'failed','untranslated','needs_update'} for row in records.values()))
                self._check()
                with self.lock:
                    if self.inputs[index]['version'] != version:
                        from .service import CancelledError
                        raise CancelledError('旧分片版本迟到，不写入新输入。')
                    self.results[index]=result
                    self._save(path,result)
                self.legacy.record_run_event('ready_shard_completed',shard_id=local.shard_id,input_version=version,
                    cues=len(result.cues),source_rows=len(result.primary))
                return result
            except BaseException as exc:
                result.error=exc
                with self.lock:
                    if self.inputs[index]['version']==version:self.results[index]=result
                self.legacy.record_run_event('ready_shard_failed',shard_id=local.shard_id,input_version=version,
                                            error_type=type(exc).__name__,reason=str(exc)[:300])
                return result
            finally:
                coarse_ready.set()

    def _prepare_primary(self,index,rows,context):
        gaps=[]
        for row in rows:
            if not row.get('cloud_gap'):continue
            gap=dict(row['cloud_gap'])
            for key in ('start','end'):
                if key not in gap:gap[key]=row.get(key)
            if gap.get('start') is None or gap.get('end') is None:
                raise ValueError('被拦分片缺少归属区间，保留回执且不重新上传。')
            gaps.append(gap)
        if not gaps:return rows
        from .cloud_gap_fill import fill_cloud_gaps
        from ..system.task_resources import LOCAL_ALIGNMENT_GATE
        payload=dict(segments=[],references=[],cloud_gaps=gaps)
        delegate=self.legacy
        class LocalStageLegacy:
            def __getattr__(self,name):return getattr(delegate,name)
            def run_timed_stage(self,index,total,label,resource,runner):return runner()
        local_legacy=LocalStageLegacy()
        # A blocked request can be filled while unrelated requests stay remote.
        cache=dict(self.cache_context,cache_dir=str(self.root/f'r{index+1:03}-primary'))
        Path(cache['cache_dir']).mkdir(parents=True,exist_ok=True)
        with LOCAL_ALIGNMENT_GATE.lease(self._check):
            # A different heavy acoustic model gets the device as a whole;
            # retire the idle Qwen instance rather than materializing copies.
            with self.context.media_identity_lock:
                sessions=list(self.context.aligner_sessions.values())
                self.context.aligner_sessions.clear()
            for session in sessions:session.close()
            self._step(index,'local-gap-fill','本地补识别',lambda:fill_cloud_gaps(local_legacy,payload,
                media_path=self.media_path,shared_audio=self.audio,speech_regions=self.speech_regions,
                audio_seconds=self.seconds,cache_context=cache,requested_language=context.requested_language,
                stage_total=11,moss_runner=lambda audio:self.pipeline.transcribe_moss_global(
                    self.media_path,audio,local_legacy,cache)))
        for row in payload['references']:
            row['speaker']=f'G{index+1:03}_'+str(row.get('speaker') or 'S00')
        return payload['references']

    def _process(self,index,version,primary,context):
        from .asr import transcribe_qwen_aligner_reference
        from .language_diagnostics import audit_primary_language
        from .transcript_acceptance import gate_primary
        from .cue_forced_alignment import align_final_cues
        from .pipeline_runtime import finalize_cues, finalize_english_cues, normalize_delivered_cue_text
        from .translation_overlap import start as start_translation
        from ..subtitle_rules.language_rules import qwen_language_name
        from ..system.task_resources import LOCAL_ALIGNMENT_GATE
        cache=dict(self.cache_context,cache_dir=str(self.root/f'r{index+1:03}-stages'))
        Path(cache['cache_dir']).mkdir(parents=True,exist_ok=True)
        evidence=Path(cache['cache_dir'])/'timing-evidence'
        audit=audit_primary_language(primary,context,self.legacy)
        accepted=gate_primary(dict(segments=primary,references=primary),self.audio,context,self.legacy,cache,audit)
        primary=accepted['references']
        if not primary:
            raise ValueError('此分片原文未通过语言接受检查；保留原始响应和待核对范围。')
        receipts=[row.get('asr_language_receipt') for row in primary if row.get('asr_language_receipt')]
        if receipts:
            context.shard_bounds=(float(receipts[0]['start']),float(receipts[0]['end']))
        elif primary:
            context.shard_bounds=(max(0.,min(row['start'] for row in primary)-.3),
                                  min(self.seconds,max(row['end'] for row in primary)+.3))
        shard_end=context.shard_bounds[1] if context.shard_bounds else self.seconds
        language=qwen_language_name(context.task_language)
        timeline=str(getattr(self.legacy,'FIRERED_ASR_BACKEND',''))
        def align_initial():
            if timeline=='off':return []
            if timeline=='local':return self.timeline_for(context.shard_bounds)
            return transcribe_qwen_aligner_reference(self.audio,primary,language=language,
                raise_errors=True,evidence_dir=evidence)
        tokens=self._step(index,'initial-alignment','初始字级对齐',align_initial)
        if timeline!='off':
            self.legacy.record_run_event('MODEL_RESULT_AVAILABLE',model_id=timeline,backend=timeline,
                role='timeline_alignment',segment_count=len(tokens),execution='validated_alignment_receipt')
        segments=self.pipeline.build_alternate_primary_segments(primary,tokens,self.legacy,'api')
        if context.task_language=='zh':
            segments=self.pipeline.apply_alternate_dialogue_coverage(segments,primary,tokens,
                self.speech_regions,self.seconds,self.legacy,'api',runtime_context=context)
            segments=self.pipeline.reconcile_firered_moss_qwen(segments,self.legacy)
            for segment in segments:
                segment.caption_arbitration=dict(segment.caption_arbitration or {})
                segment.caption_arbitration['acoustic_words']=[dict(text=str(t.get('text') or ''),
                    start_ms=round(t['start']*1000),end_ms=round(t['end']*1000),model='firered')
                    for t in tokens if t.get('text') and t['end']>segment.start and t['start']<segment.end]
        if len(segments)>=STRIDE:raise ValueError('分片字幕数量超过稳定ID范围。')
        for segment in segments:
            segment.segment_id=(index+1)*STRIDE+segment.segment_id
            segment.final_text=segment.text;segment.final_start=segment.start;segment.final_end=segment.end
            segment.final_text_owner='API'
            window=(segment.caption_arbitration or {}).get('forced_alignment_window') or {}
            segment.final_timing_owner='FireRed' if timeline=='local' and tokens else 'Qwen3-ForcedAligner' if window else 'API coarse sentence bounds'
            if timeline=='local' and segment.firered_text:segment.final_text_owner='API+FireRed'
        # VAD/token dependencies are local and immutable; no other chunk's
        # mutation can invalidate all batches of this shard.
        left=min(row['start'] for row in primary)-2.;right=max(row['end'] for row in primary)+2.
        speech=[row for row in self.speech_regions if float(row['end'])>=left and float(row['start'])<=right]
        if context.task_language=='zh':
            from ..glossary.terminology import apply_to_segments, runtime_snapshot
            segments=apply_to_segments(segments,runtime_snapshot(self.legacy),self.legacy)
        if self.text_plan.polish:
            segments=self._step(index,'polished','校对',lambda:self.legacy.polish_subtitles(segments,
                Path(self.media_path).stem,cache))
        else:
            self._step(index,'polished','保留原文',lambda:None)
        if context.task_language=='zh':
            segments=self.legacy.apply_editorial_segment_rules(segments)
            segments=apply_to_segments(segments,runtime_snapshot(self.legacy),self.legacy)
        cues=self._step(index,'grouped','断句',lambda:self.legacy.group_subtitles(segments,
            firered_tokens=tokens,speech_regions=speech,protect_all_source_boundaries=False,
            cache_context=cache,use_ai=self.text_plan.group,provider_snapshot=context.provider_snapshot))
        if context.task_language in {'zh','ja'}:
            cues=self._step(index,'text-stable','整理最终原文',lambda:finalize_cues(
                cues,segments,tokens,speech,shard_end,self.fps,self.legacy))
        else:
            cues=self._step(index,'text-stable','整理最终原文',lambda:finalize_english_cues(
                cues,segments,speech,shard_end,self.fps,self.legacy))
        for number,cue in enumerate(cues,1):cue.cue_id=(index+1)*STRIDE+number
        if len(cues)>=STRIDE:raise ValueError('分片字幕数量超过稳定ID范围。')
        normalize_delivered_cue_text(cues,self.legacy)
        self._check()
        translation=start_translation(cues,context,self.legacy)
        try:
            def final_alignment():
                if timeline in {'off','local'}:return
                align_final_cues(cues,self.audio,self.legacy,language=language,
                                 speech_regions=speech,evidence_dir=evidence)
                from .cue_boundary_refine import apply_to_runtime_cues
                apply_to_runtime_cues(cues,self.audio,self.legacy,fps=self.fps)
                if context.task_language=='ja':
                    from .ctc_alignment import apply_to_runtime_cues as ctc
                    ctc(cues,self.audio,self.legacy,fps=self.fps)
                self.legacy.relock_display_timing(cues,shard_end,self.fps,stage='ready_shard_word_refinements')
            self._step(index,'final-alignment','最终字级对齐及切点复核',final_alignment)
            meta=self._step(index,'translation','等待本片翻译',lambda:translation.result(cues) if translation else {})
            if meta is None:raise ValueError('稳定原文版本已变化，拒绝旧译文。')
            return ShardResult(index,version,primary,segments,cues,meta,[])
        finally:
            if translation:translation.close()

    def ensure_primary(self,payload):
        """Import cached/native results too; the callback is only an acceleration."""
        refs=payload.get('references') or []
        grouped={}
        for row in refs:
            receipt=row.get('asr_language_receipt') or {}
            speaker=str(row.get('speaker') or '')
            if receipt:
                index=int(receipt['request_index'])
            elif speaker.startswith('R') and speaker[1:4].isdigit():
                index=int(speaker[1:4])-1
            else:
                continue
            grouped.setdefault(index,[]).append(row)
        for gap in payload.get('cloud_gaps') or []:
            grouped[int(gap['segment'][0])-1]=[dict(cloud_gap=gap)]
            self.total=max(self.total,int(gap['segment'][1]))
        self.total=max(self.total,max(grouped,default=-1)+1)
        for index,rows in grouped.items():
            with self.lock:known=index in self.inputs
            if not known:self.accept(dict(request_index=index,request_total=self.total,rows=rows))
        # Wait only for missing primary text, not any shard's correction/grouping.
        for index,event in list(self.coarse.items()):
            while not event.wait(.1):self._check()
            result=self.results[index]
            if result.error and not any(str(row.get('text') or '').strip() for row in result.primary):
                # Complete and checkpoint independent shards before surfacing
                # a missing-primary failure. Downstream failures wait in collect.
                self.collect()
                raise result.error
        all_rows=[row for index in sorted(self.results) for row in self.results[index].primary]
        return dict(payload,references=all_rows,segments=copy.deepcopy(all_rows),cloud_gaps=[])

    def collect(self):
        expected=set(range(self.total))
        if set(self.inputs)!=expected:raise ValueError('分片清单不完整，拒绝无声丢片。')
        while set(self.futures)!=expected:
            self._check();time.sleep(.05)
        failures=[]
        for index in sorted(expected):
            while True:
                result=self.futures[index].result()
                if result.version==self.inputs[index]['version']:break
                self._check();time.sleep(.01)
            if result.error:failures.append((index,result.error))
        if failures:
            self.legacy.record_run_event('ready_shard_failures_retained',
                failed_shards=[f'r{index+1:03}' for index,_error in failures],
                completed_checkpoints=len(expected)-len(failures))
            raise failures[0][1]
        ordered=[self.results[index] for index in sorted(expected)]
        if self.text_plan.polish:
            self.context.polishing_summary=aggregate_polishing(ordered)
            self.legacy.record_run_event('polishing_summary',**self.context.polishing_summary)
        from .shard_identity import namespace_result
        for result in ordered:namespace_result(result)
        cues=sorted([cue for result in ordered for cue in result.cues],key=lambda c:(c.start,c.end,c.cue_id))
        segments=sorted([segment for result in ordered for segment in result.segments],key=lambda s:(s.start,s.end,s.segment_id))
        if len({s.segment_id for s in segments})!=len(segments):raise ValueError('并行来源段出现重复身份。')
        if len({cue.cue_id for cue in cues})!=len(cues):raise ValueError('并行字幕出现重复身份。')
        metadata={}
        for result in ordered:
            self.legacy.extend_review_items(result.reviews)
            for key,value in result.translation.items():
                if not isinstance(value,dict):raise ValueError('翻译元数据不是映射。')
                target=metadata.setdefault(key,{})
                # Translation records have an outer target-language map.
                for name,items in value.items():
                    if isinstance(items,dict):
                        destination=target.setdefault(name,{})
                        if set(destination)&set(items):raise ValueError('原译关联出现重复字幕身份。')
                        destination.update(items)
                    elif isinstance(items,list):
                        target.setdefault(name,[]).extend(items)
                    else:
                        if name in target and target[name] != items:raise ValueError('译文元数据配置冲突。')
                        target[name]=items
        self.context.translation_ready=dict(binding=_digest([(str(c.cue_id),c.text,c.speaker) for c in cues]),
                                           metadata=metadata)
        self.legacy.record_run_event('long_pipeline_completed',shards=self.total,cues=len(cues),
            phases={key:dict(value,wall_seconds=value['finished']-value['started']) for key,value in self.phase_stats.items()},
            note='phase spans overlap; execution seconds must not be summed as total wall time')
        return cues,segments

    def close(self):
        self.context.primary_ready_callback=None
        with self.lock:self.closed=True
        self.vad_ready.set()
        for event in self.vad_events.values():event.set()
        self.pool.shutdown(wait=True,cancel_futures=True)
