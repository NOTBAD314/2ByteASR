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
        self.vad_pool=ContextExecutor(max_workers=self.budget.cpu_workers,thread_name_prefix='ready-vad') if use_graph else None
        self.vad_futures={};self.lock=threading.RLock()
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
        identity=dict(clock=self.producer.clock_identity,start=start,end=end,model=self.paths['firered_vad'],
                      version='vad-owned-shard-pad800-v1')
        try:
            cached=json.loads(path.read_text(encoding='utf8'))
            if cached.get('identity')==identity:
                self.graph.set_piece_vad(index,cached['regions']);return cached['regions']
        except (OSError,ValueError,KeyError,TypeError):pass
        with local_runtime_context(local),self.legacy.capture_review_items() as reviews:
            with work(self.legacy,'vad',f'第 {index+1}/{self.producer.total} 片 · 人声检查'):
                try:
                    regions=self.pipeline.detect_firered_vad(clip,self.legacy,_owned_polling=True)
                except Exception as exc:
                    if exc.__class__.__name__=='CancelledError':raise
                    self.legacy.record_run_event('vad_backend_selected',backend='lightweight_vad',
                        reason='shard_vad_unavailable',error_type=type(exc).__name__)
                    try:regions=self.pipeline.detect_lightweight_vad(clip,self.legacy)
                    except RuntimeError:regions=[]
        global_regions=[dict(start=max(start/RATE,float(row['start'])+left/RATE),
            end=min(end/RATE,float(row['end'])+left/RATE)) for row in regions]
        global_regions=[row for row in global_regions if row['end']>row['start']]
        self.graph.set_piece_vad(index,global_regions)
        from ..storage.atomic_files import write_text_atomic
        path.parent.mkdir(parents=True,exist_ok=True)
        write_text_atomic(path,json.dumps(dict(identity=identity,regions=global_regions),ensure_ascii=False))
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
        rows.sort(key=lambda row:row['start'])
        merged=[]
        for row in rows:
            if merged and row['start']<=merged[-1]['end']:
                merged[-1]['end']=max(merged[-1]['end'],row['end'])
            else:merged.append(dict(row))
        return merged

    def close(self):
        self.asr_pool.shutdown(wait=True,cancel_futures=True)
        if self.vad_pool:self.vad_pool.shutdown(wait=True,cancel_futures=True)


def create_live_input(context,legacy,pipeline,media,cache,fps,paths,text_plan):
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
