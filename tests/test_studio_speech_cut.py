import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from twobyteasr.studio.studio_speech_cut import pause_candidates, make_seam_preview
import numpy as np
import wave
import pytest


def test_speech_pauses_preserve_edges_and_pad_once():
    result,stats=pause_candidates([(1000,2000),(4000,5000),(5400,6000)],[(0,10000)],10000)
    assert [(c['start_ms'],c['end_ms']) for c in result]==[(2200,3800)]
    assert stats['short_pauses']==1


def test_no_voice_does_not_recommend_deleting_whole_video():
    result,stats=pause_candidates([],[(0,900000)],900000)
    assert not result and stats['speech_regions']==0


def test_deliberate_video_gaps_and_overlapping_speech_protected():
    result,_=pause_candidates([(0,1000),(900,2000),(7000,8000)],[(0,3000),(6000,9000)],9000)
    assert [(c['start_ms'],c['end_ms']) for c in result]==[(2200,2800),(6200,6800)]


def test_short_overlap_protection_skipped():
    result,stats=pause_candidates([(0,1000),(2100,3000)],[(0,3000)],3000,1000,500)
    assert not result and stats['protected_pauses']==1


def test_audition_join_uses_exact_samples(tmp_path):
    p=tmp_path/'timeline.wav'
    samples=np.arange(16000*6,dtype=np.int32).astype('<i2')
    with wave.open(str(p),'wb') as f:
        f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(samples.tobytes())
    result=make_seam_preview(p,2000,4000)
    with wave.open(str(result),'rb') as f:
        data=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
    assert np.array_equal(data[-38400:],np.concatenate((samples[12800:32000],samples[64000:83200])))


def test_progress_publish_retries_windows_reader_lock(tmp_path,monkeypatch):
    import firered_vad_worker as worker
    import json
    target=tmp_path/'progress.json';target.write_text('{"old":1}','utf8')
    replace=worker.os.replace;calls=[]
    def locked(source,destination):
        calls.append(1)
        if len(calls)<3:
            assert json.loads(target.read_text('utf8'))=={'old':1}
            raise PermissionError('reader temporarily holds destination')
        replace(source,destination)
    monkeypatch.setattr(worker.os,'replace',locked)
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    worker._atomic_write(target,{'processed_seconds':30})
    assert len(calls)==3 and json.loads(target.read_text('utf8'))=={'processed_seconds':30}


def test_progress_publish_permanent_error_is_bounded(tmp_path,monkeypatch):
    import firered_vad_worker as worker
    calls=[]
    def denied(*_):
        calls.append(1);raise PermissionError('permanent denial')
    monkeypatch.setattr(worker.os,'replace',denied)
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    with pytest.raises(PermissionError):worker._atomic_write(tmp_path/'result.json',{})
    assert len(calls)==20
