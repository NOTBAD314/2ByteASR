"""Own the canonical PCM producer, early MOSI process and local VAD dependencies."""
from __future__ import annotations

import json,os,threading,time
from dataclasses import replace
from pathlib import Path

from .run_context import ContextExecutor,local_runtime_context
from .streaming_audio import StreamingAudio,probe_samples,RATE
from .streaming_recognition import LongMediaPipeline,eligible


class LiveInput:
    def __init__(self,context,legacy,pipeline,media,cache,fps,paths,text_plan,samples,*,use_graph):
        from ..system.task_resources import task_budget
        self.context,self.legacy,self.pipeline=context,legacy,pipeline
        self.media,self.cache,self.paths=media,cache,paths
        self.budget=context.execution_budget or task_budget();context.execution_budget=self.budget
        self.producer=StreamingAudio(media,cache,samples,check=self.check)
        context.streaming_preparation=self.producer
        self.graph=(LongMediaPipeline(context=context,legacy=legacy,pipeline=pipeline,
            media_path=media,cache_context=cache,audio=self.producer.audio,seconds=samples/RATE,
            fps=fps,paths=paths,text_plan=text_plan) if use_graph else None)
        self.vad_pool=ContextExecutor(max_workers=1,thread_name_prefix='ready-vad') if use_graph else None
        self.vad_futures={};self.vad_executions={};self.lock=threading.RLock()
        if self.graph:
            self.graph.piece_vad=True
            context.long_pipeline=self.graph;context.primary_ready_callback=self.graph.accept
        self.asr_pool=ContextExecutor(max_workers=1,thread_name_prefix='early-mosi')
        self.producer.start(self._piece if use_graph else None)
        self.future=self.asr_pool.submit(self._asr)
        context.early_primary=(self.asr_pool,self.future)

    def check(self):
        from .service import CancelledError
        from .run_context import context_is_current
        if bool(getattr(self.context.cancellation_token,'is_cancelled',False)) or not context_is_current(self.context):
            raise CancelledError('流式音频任务已取消。')

    def _asr(self):
        from ..providers.asr_api_process import transcribe
        from .pipeline_activity import work
        parent=self.context;producer=self.producer
        class InputToken:
            @property
            def is_cancelled(self):
                return bool(getattr(parent.cancellation_token,'is_cancelled',False) or producer.error)
        local=replace(parent,root_context=parent,cancellation_token=InputToken())
        with local_runtime_context(local),work(self.legacy,'mosi','MOSS 云端分片转写',total=self.producer.total):
            return transcribe(self.media,[],publish_primary=True,prepared_source=self.producer.spec)

    def _piece(self,index,start,end):
        with self.lock:self.vad_futures[index]=self.vad_pool.submit(self._vad,index,start,end)

    def _vad(self,index,start,end):
        from .pipeline_activity import work
        local=replace(self.context,root_context=self.context,shard_id=f'pcm-r{index+1:03}',
            shard_input_version=self.producer.clock_identity,review_items=[])
        pad=800*16;left=max(0,start-pad)
        self.producer.wait_ready(end+pad)
        right=min(self.producer.valid_samples,end+pad)
        clip=self.producer.audio[left:right]
        path=Path(self.cache['cache_dir'])/'ready-shards'/f'vad-{start}-{end}.json'
        from .vad import ALGORITHM, selected_detection, encode, decode, cacheable, VadRegions
        identity=dict(clock=self.producer.clock_identity,start=start,end=end,
                      model=self.pipeline._path_signature(self.paths['firered_vad']),
                      version=ALGORITHM)
        try:
            cached=json.loads(path.read_text(encoding='utf8'))
            if cached.get('identity')==identity:
                value=decode(cached)
                self.vad_executions[index]=value.execution
                self.graph.set_piece_vad(index,value,execution=value.execution);return value
        except (OSError,ValueError,KeyError,TypeError):pass
        with local_runtime_context(local),self.legacy.capture_review_items() as reviews:
            with work(self.legacy,'vad',f'第 {index+1}/{self.producer.total} 片 · 人声检查') as report:
                value=selected_detection(lambda:self.pipeline.detect_firered_vad(clip,self.legacy,_owned_polling=True),
                    lambda:self.pipeline.detect_lightweight_vad(clip,self.legacy),requested='firered_vad',
                    duration=len(clip)/RATE,check=self.check,event=self.legacy.record_run_event)
                report(state='degraded' if value.execution['degraded'] else 'completed', **value.execution)
                regions=value
        def globalize(rows):
            result = []
            for row in rows:
                original_start = float(row['start'])+left/RATE
                original_end = float(row['end'])+left/RATE
                begin, finish = max(start/RATE, original_start), min(end/RATE, original_end)
                if finish <= begin:
                    continue
                value = dict(row, start=begin, end=finish)
                if row.get('confidence') is not None and (begin != original_start or finish != original_end):
                    value.update(confidence_bounds_verified=False,
                                 confidence_bounds=[original_start, original_end])
                result.append(value)
            return result
        global_regions = globalize(regions)
        execution=dict(value.execution,start=start/RATE,end=end/RATE)
        if 'detected_regions' in execution:
            execution['detected_regions'] = globalize(execution['detected_regions'])
        global_regions=VadRegions(global_regions,execution=execution)
        self.vad_executions[index]=execution
        self.graph.set_piece_vad(index,global_regions,execution=execution)
        from ..storage.atomic_files import write_text_atomic
        path.parent.mkdir(parents=True,exist_ok=True)
        destination=path if cacheable(global_regions) else path.with_suffix('.fallback.json')
        write_text_atomic(destination,json.dumps(dict(identity=identity,**encode(global_regions)),ensure_ascii=False))
        self.legacy.extend_review_items(reviews)
        return global_regions

    def complete_audio(self):return self.producer.complete_audio()

    def vad_regions(self):
        self.producer.complete_audio()
        with self.lock:futures=list(self.vad_futures.values())
        rows=[]
        for future in futures:
            while not future.done():self.check();time.sleep(.05)
            rows.extend(future.result())
        from .vad import VadRegions, receipt, merge_regions
        merged = merge_regions(rows)
        failed=[value for value in self.vad_executions.values() if value.get('degraded')]
        execution=receipt('firered_vad','lightweight_vad' if failed else 'firered_vad',self.producer.valid_samples/RATE,
            reason='; '.join(value.get('failure_reason','') for value in failed),
            shards=[dict(index=index,**value) for index,value in sorted(self.vad_executions.items())])
        return VadRegions(merged,execution=execution)

    def close(self):
        self.asr_pool.shutdown(wait=True,cancel_futures=True)
        if self.vad_pool:self.vad_pool.shutdown(wait=True,cancel_futures=True)


def create_live_input(context,legacy,pipeline,media,cache,fps,paths,text_plan):
    # The Chinese AED process consumes its full shared PCM in order. Keep
    # decoding atomic here; remote/AED/text stages still overlap by receipts.
    if str(getattr(legacy,'FIRERED_ASR_BACKEND',''))=='local':return None
    if (context.recognition_snapshot.get('language_recovery_policy') or {}).get('reuse_candidates'):
        return None
    from ..providers.mosi_asr import MODEL
    if ((context.asr_endpoint_snapshot or {}).get('model')!=MODEL
            or context.audio_stream or os.environ.get('TWOBYTEASR_STREAM_AUDIO')=='0'):
        return None
    marker=Path(cache['cache_dir'])/'streaming-audio.json'
    # Older native task IDs are keyed by full PCM. Keep their original route
    # when it already has audio/receipts; never migrate them into fresh uploads.
    if not marker.is_file() and (Path(cache['cache_dir'])/'audio_meta.json').is_file():return None
    samples=probe_samples(media)
    if samples is None or samples<=25*60*RATE:return None
    admitted,_reason=eligible(context,legacy,samples/RATE)
    if not admitted and not marker.is_file():return None
    use_graph=admitted and not bool((context.asr_settings_snapshot.get('models') or {}).get('mosi_resplit_blocked'))
    return LiveInput(context,legacy,pipeline,media,cache,fps,paths,text_plan,samples,use_graph=use_graph)
