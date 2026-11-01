import contextlib
import json
import threading
import time
from types import MethodType,SimpleNamespace

import pytest

from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context,get_runtime_context,ContextExecutor
from twobyteasr.recognition.streaming_recognition import LongMediaPipeline,ShardResult,STRIDE


class Legacy:
    FIRERED_ASR_BACKEND='off'
    def __init__(self):self.events=[]
    def record_run_event(self,kind,**data):self.events.append((kind,time.perf_counter(),data))
    @contextlib.contextmanager
    def capture_review_items(self):yield []
    def extend_review_items(self,rows):pass
    def serialize_cues(self,rows):return [vars(row).copy() for row in rows]
    deserialize_cues=staticmethod(lambda rows:[SimpleNamespace(**row) for row in rows])
    serialize_segments=serialize_cues
    deserialize_segments=deserialize_cues


def create(tmp_path,context,legacy,process):
    context.execution_budget=SimpleNamespace(shard_workers=2)
    pipeline=LongMediaPipeline(context=context,legacy=legacy,pipeline=None,media_path='media.mp4',
        cache_context={'cache_dir':str(tmp_path),'identity':{'audio':'immutable-fixture'}},audio=[],
        seconds=2400,fps=30,paths={},text_plan=SimpleNamespace(group=False,polish=False))
    pipeline._process=MethodType(process,pipeline)
    pipeline.set_vad([])
    return pipeline


def payload(index,text='はい'):
    return dict(request_index=index,request_total=2,rows=[dict(start=index*10.,end=index*10.+1,
        text=text,speaker=f'R{index+1:03}_S01')])


def result(index,version,primary):
    number=(index+1)*STRIDE+1
    cue=SimpleNamespace(cue_id=number,start=index*10.,end=index*10.+1,text=primary[0]['text'],speaker=primary[0]['speaker'])
    metadata={'translation_records':{'version':1,'target':'zh-Hans','records':{str(number):{'text':'好的'}},'history':[]},
              'translations':{str(number):'好的'}}
    return ShardResult(index,version,primary,[],[cue],metadata,[])


def test_fast_shard_finishes_before_slow_cloud_input_and_stable_ids_merge(tmp_path):
    legacy=Legacy();context=RuntimeContext(requested_language='ja',subtitle_output='bilingual')
    seen=[];fast=threading.Event()
    def process(self,index,version,primary,local):
        assert get_runtime_context() is local
        with ContextExecutor(max_workers=1) as nested:
            assert nested.submit(lambda:get_runtime_context().shard_id).result()==f'r{index+1:03}'
        seen.append(index);fast.set()
        return result(index,version,primary)
    with activate_runtime_context(context):
        pipeline=create(tmp_path,context,legacy,process)
        pipeline.accept(payload(1))
        assert fast.wait(1) # The first cloud request has not returned at all.
        pipeline.accept(payload(0))
        assert len(pipeline.ensure_primary({'references':payload(0)['rows']+payload(1)['rows']} )['references'])==2
        cues,segments=pipeline.collect();pipeline.close()
    assert [cue.cue_id for cue in cues]==[STRIDE+1,2*STRIDE+1]
    assert seen[0]==1
    assert set(context.translation_ready['metadata']['translations'])=={str(STRIDE+1),str(2*STRIDE+1)}


def test_one_failed_node_keeps_other_checkpoint_and_restart_reuses_it(tmp_path):
    legacy=Legacy();calls=[]
    def process(self,index,version,primary,local):
        calls.append(index)
        if index==0:raise RuntimeError('one node failed')
        return result(index,version,primary)
    with activate_runtime_context(RuntimeContext(requested_language='ja')) as context:
        pipeline=create(tmp_path,context,legacy,process)
        pipeline.accept(payload(0));pipeline.accept(payload(1))
        for future in pipeline.futures.values():future.result()
        with pytest.raises(RuntimeError,match='one node failed'):pipeline.collect()
        pipeline.close()
    assert len(list((tmp_path/'ready-shards').glob('r002-*.json')))>=2
    calls.clear()
    def repaired(self,index,version,primary,local):calls.append(index);return result(index,version,primary)
    with activate_runtime_context(RuntimeContext(requested_language='ja')) as context:
        pipeline=create(tmp_path,context,legacy,repaired)
        pipeline.accept(payload(0));pipeline.accept(payload(1));pipeline.collect();pipeline.close()
    assert calls==[0]


@pytest.mark.parametrize('nested_bounds',[False,True])
def test_blocked_native_callback_preserves_gap_range(tmp_path,monkeypatch,nested_bounds):
    from twobyteasr.recognition import cloud_gap_fill
    legacy=Legacy();seen=[]
    def fill(_legacy,payload,**kwargs):
        seen.extend(payload['cloud_gaps'])
        payload['references']=[dict(start=1200.2,end=1201.8,text='原文',speaker='S01')]
    monkeypatch.setattr(cloud_gap_fill,'fill_cloud_gaps',fill)
    with activate_runtime_context(RuntimeContext(requested_language='ja')) as context:
        pipeline=create(tmp_path,context,legacy,lambda *a:None)
        pipeline.total=2
        gap=dict(reason='content_blocked',segment=[2,2])
        if nested_bounds:gap.update(start=1200.,end=2400.)
        rows=pipeline._prepare_primary(1,[dict(start=1200.,end=2400.,cloud_gap=gap)],context)
        pipeline.close()
    assert seen[0]['start']==1200. and seen[0]['end']==2400.
    assert rows[0]['start']==1200.2 and rows[0]['speaker']=='G002_S01'


def test_production_collection_waits_for_unaffected_checkpoint_before_raising(tmp_path):
    legacy=Legacy();release=threading.Event();slow_started=threading.Event();error_seen=threading.Event()
    def process(self,index,version,primary,local):
        if index==0:raise RuntimeError('failed local node')
        slow_started.set();release.wait(3)
        return result(index,version,primary)
    with activate_runtime_context(RuntimeContext(requested_language='ja')) as context:
        pipeline=create(tmp_path,context,legacy,process)
        pipeline.accept(payload(0));pipeline.accept(payload(1))
        def collect():
            try:
                pipeline.ensure_primary({'references':payload(0)['rows']+payload(1)['rows']})
                pipeline.collect()
            except RuntimeError:
                error_seen.set();raise
        try:
            with ContextExecutor(max_workers=1) as caller:
                future=caller.submit(collect)
                assert slow_started.wait(1)
                assert not error_seen.wait(.2)
                release.set()
                with pytest.raises(RuntimeError,match='failed local node'):future.result(3)
            assert any(not path.name.endswith('-input.json') for path in (tmp_path/'ready-shards').glob('r002-*.json'))
        finally:
            release.set();pipeline.close()
