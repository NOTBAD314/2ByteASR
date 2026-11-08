"""Scored VAD and conservative fallback preserve R6 recovery policy."""
import contextlib
from types import SimpleNamespace

import numpy as np

from firered_vad_worker import scored_regions
from twobyteasr.recognition import speech_coverage as coverage
from twobyteasr.recognition import vad


def test_scoring_crops_probability_to_owned_interval():
    rows=scored_regions(dict(dur=2,timestamps=[(0,2)]),np.array([.2,.2,.95,.95]),
                        bounds=(1,2),statistics=True)
    assert len(rows)==1 and rows[0]['confidence']==.95
    assert rows[0]['probability_frames']==2
    assert coverage.automatic_speech(rows[0])


def test_merge_preserves_low_probability_transition_and_exact_mean():
    rows=[dict(start=0,end=1,detector='firered_vad',confidence=.95,probability_sum=1.9,probability_frames=2),
          dict(start=1,end=2,detector='firered_vad',confidence=.9,probability_sum=1.8,probability_frames=2),
          dict(start=2,end=3,detector='firered_vad',confidence=.4,probability_sum=.8,probability_frames=2)]
    result=vad.merge_regions(rows)
    assert len(result)==2 and result[0]['end']==2
    assert abs(result[0]['confidence']-.925)<1e-12
    assert not coverage.automatic_speech(result[1],anomalous=True)
    state=coverage.make_state(result,[dict(start=2,end=3,text='已有文本')],duration=3)
    assert state['gaps'][0]['status']=='pending'


def test_energy_processing_range_does_not_become_speech_evidence():
    def fail():raise MemoryError('bad allocation')
    result=vad.selected_detection(fail,lambda:[dict(start=2,end=8,detector='energy')],
                                  requested='firered_vad',duration=80)
    state=coverage.make_state(result,[],duration=80)
    assert state['speech_ranges']==[[2.,8.]]
    assert len(state['gaps'])==1 and state['gaps'][0]['status']=='needs_confirmation'
    assert state['gaps'][0]['end']<9


def test_ready_shard_keeps_score_and_marks_unrescored_clip(tmp_path):
    from twobyteasr.recognition.streaming_input import LiveInput
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    item=object.__new__(LiveInput);item.context=RuntimeContext();item.vad_executions={}
    item.legacy=SimpleNamespace(capture_review_items=lambda:contextlib.nullcontext([]),
        extend_review_items=lambda rows:None,record_run_event=lambda *a,**k:None)
    def detect(*a,**k):
        rows=[dict(start=0,end=2,detector='firered_vad',confidence=.95),
              dict(start=2,end=4,detector='firered_vad',confidence=.95)]
        return vad.VadRegions(rows,execution=vad.receipt('firered_vad','firered_vad',31.6))
    item.pipeline=SimpleNamespace(detect_firered_vad=detect,detect_lightweight_vad=lambda *a:[],
                                  _path_signature=lambda path:dict(path=path))
    item.paths={'firered_vad':'model'};item.cache={'cache_dir':str(tmp_path)}
    item.producer=SimpleNamespace(clock_identity='clock',total=2,valid_samples=61*16000,
        audio=np.zeros(61*16000,dtype=np.float32),wait_ready=lambda value:None)
    item.graph=SimpleNamespace(set_piece_vad=lambda *a,**k:None);item.check=lambda:None
    with activate_runtime_context(item.context):rows=item._vad(1,30*16000,60*16000)
    assert rows[0]['confidence']==.95 and rows[0]['confidence_bounds_verified'] is False
    assert not coverage.automatic_speech(rows[0],anomalous=True)
    assert coverage.automatic_speech(rows[1])
    assert abs(rows[1]['start']-31.2)<1e-10


def test_pipeline_worker_result_keeps_execution_and_scores(tmp_path,monkeypatch):
    import sys
    from pathlib import Path
    import moss_firered_pipeline as pipeline
    from twobyteasr import model_integrity,runtime_paths
    from twobyteasr.system import runtime_registry
    from twobyteasr.recognition import asr
    model=tmp_path/'model';model.mkdir()
    monkeypatch.setattr(pipeline,'_script_paths',lambda legacy:{'firered_vad':str(model)})
    monkeypatch.setattr(model_integrity,'verify_model_files',lambda *a,**k:None)
    monkeypatch.setattr(runtime_registry,'resolve_runtime_python',lambda role:sys.executable)
    monkeypatch.setattr(runtime_paths,'detect_install_root',lambda:Path(pipeline.__file__).parent)
    execution=vad.receipt('firered_vad','firered_vad',65,chunks=3)
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',lambda *a,**k:dict(
        regions=[dict(start=1,end=4,detector='firered_vad',confidence=.95)],execution=execution))
    result=pipeline.detect_firered_vad(np.zeros(16000,dtype=np.float32),
        SimpleNamespace(write_pcm16_wav=lambda *a:None))
    assert isinstance(result,vad.VadRegions)
    assert result.execution['chunks']==3 and result[0]['confidence']==.95
