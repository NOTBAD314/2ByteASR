"""Bounded PCM/RMS and backend provenance, independent of model weights."""
import contextlib
import json
import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from firered_vad_worker import detect_chunks
from twobyteasr.recognition import vad
from twobyteasr.recognition.speech_coverage import union


def wav(path, seconds):
    with wave.open(str(path), 'wb') as output:
        output.setparams((1,2,16000,0,'NONE','not compressed'))
        output.writeframes(np.ones(round(seconds*16000), dtype='<i2').tobytes())
    return path


def test_pcm_chunks_boundaries_tail_progress_and_zero_argument(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(inference_mode=contextlib.nullcontext))
    sizes, progress = [], []
    class Model:
        def detect(self, audio):
            sizes.append(len(audio))
            return {'timestamps':[(0,len(audio)/16000)]}, None
    result, execution = detect_chunks(Model(), wav(tmp_path/'audio.wav',65.123), chunk_seconds=0,
                                      progress=lambda **value:progress.append(value))
    assert union(result) == [(0.,65.123)]
    assert max(sizes) <= 31*16000 and len(sizes) == 3
    assert [row['processed_seconds'] for row in progress] == [30,60,65.123]
    assert execution['samples'] == round(65.123*16000)


def test_single_memory_failure_shrinks_then_continues(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(inference_mode=contextlib.nullcontext))
    sizes=[]
    class Model:
        def detect(self,audio):
            sizes.append(len(audio))
            if len(sizes)==2:raise MemoryError('bad allocation')
            return {'timestamps':[(0,len(audio)/16000)]},None
    result, execution=detect_chunks(Model(),wav(tmp_path/'audio.wav',65.123))
    assert union(result) == [(0.,65.123)]
    assert execution['memory_retries']==1 and execution['chunk_seconds']==15
    assert max(sizes[2:]) <= 16*16000


def test_fatal_chunk_failure_does_not_become_success(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(inference_mode=contextlib.nullcontext))
    class Model:
        def detect(self,audio):raise MemoryError('bad allocation')
    with pytest.raises(MemoryError):detect_chunks(Model(),wav(tmp_path/'audio.wav',65))


def test_rms_equal_to_full_window_grid_with_bounded_square(monkeypatch):
    samples=np.random.default_rng(10).normal(size=16000*73+13).astype(np.float32)
    frame,hop=480,160
    windows=np.lib.stride_tricks.sliding_window_view(samples,frame)[::hop]
    expected=np.sqrt(np.mean(np.square(windows,dtype=np.float32),axis=1)+1e-10)
    square=np.square
    shapes=[]
    def bounded(array,**options):
        shapes.append(array.shape)
        return square(array,**options)
    monkeypatch.setattr(np,'square',bounded)
    actual=vad.bounded_rms(samples,frame,hop,block_frames=73)
    np.testing.assert_array_equal(actual,expected)
    assert max(shape[0] for shape in shapes)<=73


def test_fallback_identity_rejected_cache_and_conservative_coverage():
    calls=[]
    def fail():
        calls.append('firered')
        error=RuntimeError('bad allocation')
        error.vad_execution={'status':'partial_failed','processed_seconds':30}
        raise error
    result=vad.selected_detection(fail,lambda:[dict(start=2,end=3)],requested='firered_vad',duration=80)
    assert union(result)==[(0.,80)]
    assert result.execution['actual_backend']=='lightweight_vad' and result.execution['degraded']
    assert result.execution['failed_backend_execution']['status']=='partial_failed'
    assert not vad.cacheable(result)
    assert vad.completion_label(result)=='FireRedVAD 失败，已使用轻量检测'
    with pytest.raises(ValueError):vad.decode(vad.encode(result))
    good=vad.selected_detection(lambda:calls.append('firered') or [dict(start=1,end=4)],lambda:[],requested='firered_vad',duration=80)
    assert calls==['firered','firered'] and vad.cacheable(good)
    assert vad.decode(vad.encode(good))==good
    with pytest.raises(KeyError):vad.decode({'regions':[]})


def test_cancellation_propagates_and_never_runs_fallback():
    class CancelledError(RuntimeError):pass
    def fail():raise CancelledError()
    def energy():raise AssertionError('cancellation was swallowed')
    with pytest.raises(CancelledError):
        vad.selected_detection(fail,energy,requested='firered_vad',duration=80)


def test_real_silence_is_distinct_from_backend_failure():
    result=vad.selected_detection(lambda:[],lambda:[],requested='firered_vad',duration=80)
    assert not result and result.execution['status']=='no_speech'
    assert not result.execution['degraded'] and vad.cacheable(result)


def test_normal_cache_retry_runs_firered_and_stage_label_matches(tmp_path,monkeypatch):
    import subtitle_core as core
    from twobyteasr.recognition.cache import run_cached_stage
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    calls,events=[],[]
    def detect():
        calls.append(1)
        if len(calls)==1:
            def fail():raise MemoryError('bad allocation')
            return vad.selected_detection(fail,lambda:[],requested='firered_vad',duration=65)
        return vad.VadRegions([dict(start=0,end=60)],execution=vad.receipt('firered_vad','firered_vad',65))
    cache=dict(cache_dir=str(tmp_path),identity={'sha256':'test'})
    signature=dict(algorithm_version=vad.ALGORITHM)
    def run():
        return run_cached_stage('firered_vad',cache,detect,encoder=vad.encode,decoder=vad.decode,
                                should_cache=vad.cacheable,extra_signature=signature)
    monkeypatch.setattr(core,'record_run_event',lambda event,**fields:events.append(dict(event=event,**fields)))
    with activate_runtime_context(RuntimeContext()):
        first=core.run_timed_stage(1,1,'人声检测','CPU',run)
        assert first.execution['degraded'] and not (tmp_path/'firered_vad.json').exists()
        second=run()
        assert (tmp_path/'firered_vad.json').exists()
        third=run()
    assert len(calls)==2 and third==second
    assert json.loads((tmp_path/'firered_vad.json').read_text('utf8'))['data']['execution']['actual_backend']=='firered_vad'
    assert any(row.get('label')=='FireRedVAD 失败，已使用轻量检测' for row in events)


def test_pcm_writer_preserves_exact_amplitude_and_is_bounded(tmp_path,monkeypatch):
    from twobyteasr.recognition.asr import write_pcm16_wav
    samples=np.linspace(-1.5,1.5,16000*65+1,dtype=np.float32)
    expected=np.rint(np.clip(samples,-1.,1.)*32767).astype('<i2')
    clip=np.clip;sizes=[]
    def bounded(value,*args,**options):
        sizes.append(len(value));return clip(value,*args,**options)
    monkeypatch.setattr(np,'clip',bounded)
    path=tmp_path/'audio.wav';write_pcm16_wav(path,samples)
    with wave.open(str(path),'rb') as stream:
        actual=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2')
    np.testing.assert_array_equal(expected,actual)
    assert max(sizes)<=30*16000


def test_ready_pcm_cache_rejects_fallback_and_retries_model(tmp_path):
    import contextlib
    from twobyteasr.recognition.streaming_input import LiveInput
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    events=[];calls=[];graph=[]
    def detect(*a,**k):
        calls.append(1)
        if len(calls)==1:raise MemoryError('bad allocation')
        return vad.VadRegions([dict(start=0,end=30)],execution=vad.receipt('firered_vad','firered_vad',30.8))
    item=object.__new__(LiveInput);item.context=RuntimeContext();item.vad_executions={}
    item.legacy=SimpleNamespace(capture_review_items=lambda:contextlib.nullcontext([]),extend_review_items=lambda rows:None,
        record_run_event=lambda event,**fields:events.append((event,fields)))
    item.pipeline=SimpleNamespace(detect_firered_vad=detect,detect_lightweight_vad=lambda *a:[],_path_signature=lambda path:dict(path=path,mtime=1))
    item.paths={'firered_vad':'test-model'};item.cache={'cache_dir':str(tmp_path)}
    item.producer=SimpleNamespace(clock_identity='clock',total=1,valid_samples=31*16000,
        audio=np.zeros(31*16000,dtype=np.float32),wait_ready=lambda value:None)
    item.graph=SimpleNamespace(set_piece_vad=lambda index,regions,**values:graph.append(values))
    item.check=lambda:None
    with activate_runtime_context(item.context):
        first=item._vad(0,0,30*16000)
        assert first.execution['degraded']
        root=tmp_path/'ready-shards'
        assert list(root.glob('*.fallback.json'))
        assert not (root/'vad-0-480000.json').exists()
        second=item._vad(0,0,30*16000)
        third=item._vad(0,0,30*16000)
    assert len(calls)==2 and third==second
    assert graph[-1]['execution']['actual_backend']=='firered_vad'


def test_processed_ready_cache_never_saves_degraded_vad(tmp_path):
    from twobyteasr.recognition.streaming_recognition import LongMediaPipeline,ShardResult
    graph=object.__new__(LongMediaPipeline)
    graph.vad_execution_by_index={0:vad.receipt('firered_vad','lightweight_vad',65,reason='bad allocation')}
    graph.vad_execution={}
    graph.legacy=SimpleNamespace(serialize_cues=lambda value:value,serialize_segments=lambda value:value,record_run_event=lambda *a,**k:None,
        deserialize_cues=lambda value:value,deserialize_segments=lambda value:value)
    path=tmp_path/'ready.json';result=ShardResult(0,'version',[],[],[],{},[])
    graph._save(path,result)
    assert not path.exists()
    graph.vad_execution_by_index[0]=vad.receipt('firered_vad','firered_vad',65)
    graph._save(path,result)
    assert graph._load(path,'version') is not None
    graph.vad_execution_by_index[0]=vad.receipt('lightweight_vad','lightweight_vad',65)
    assert graph._load(path,'version') is None
    graph.vad_execution_by_index[0]=vad.receipt('firered_vad','firered_vad',65)
    saved=json.loads(path.read_text('utf8'));saved['data'].pop('vad_execution')
    from twobyteasr.recognition.streaming_recognition import _digest
    saved['checksum']=_digest(saved['data']);path.write_text(json.dumps(saved),'utf8')
    assert graph._load(path,'version') is None


def test_selected_energy_is_not_negative_asr_evidence():
    result=vad.selected_detection(lambda:None,lambda:[dict(start=2,end=3)],requested='lightweight_vad',duration=80)
    assert union(result)==[(0.,80)]
    assert result.execution['detected_regions']==[dict(start=2,end=3)]
    assert result.execution['actual_backend']=='lightweight_vad'
    assert result.execution['conservative_coverage']


def test_studio_wav_silence_matches_array_without_full_read(tmp_path):
    from twobyteasr.studio.studio_autocut import compute_silence_ranges_ms,compute_silence_ranges_wav
    samples=np.zeros(16000*65+17,dtype='<i2')
    samples[16000*15:16000*22]=5000
    path=tmp_path/'audio.wav'
    with wave.open(str(path),'wb') as stream:
        stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(samples.tobytes())
    values=samples.astype(np.float32)/32768
    assert compute_silence_ranges_wav(path,min_silence_s=1)==compute_silence_ranges_ms(values,16000,min_silence_s=1)


def test_conservative_energy_range_is_not_independent_tail_evidence():
    energy=vad.selected_detection(lambda:None,lambda:[],requested='lightweight_vad',duration=80)
    assert vad.detected_tail(energy) is None
    formal=vad.VadRegions([dict(start=2,end=3)],execution=vad.receipt('firered_vad','firered_vad',80))
    assert vad.detected_tail(formal)==3
    assert vad.detected_tail(vad.VadRegions([],execution=vad.receipt('firered_vad','firered_vad',80)))==0
