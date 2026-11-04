import copy

import numpy as np
import pytest

from twobyteasr.recognition.alignment_checkpoints import run_cached,save_worker_checkpoint
from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context


def job(number,text='今日は'):
    return dict(id=str(number),text=text,language='Japanese',window_start_ms=number*100,window_end_ms=number*100+100)


def output(jobs):
    return dict(protocol='test',model='test-model',results=[dict(row,status='aligned') for row in jobs])


def test_renumbering_reuses_audio_windows_and_text_changes_only_one_node(tmp_path):
    calls=[];audio=np.arange(16000,dtype=np.float32)
    def runner(rows):calls.append([row['id'] for row in rows]);return output(rows)
    context=RuntimeContext(alignment_checkpoint_dir=str(tmp_path))
    with activate_runtime_context(context):
        first=run_cached(audio,[job(1),job(2)],identity={'engine':'test','revision':'v1'},runner=runner)
        again=run_cached(audio,[dict(job(2),id='renamed-b'),dict(job(1),id='renamed-a')],
                         identity={'engine':'test','revision':'v1'},runner=runner)
        assert len(calls)==1 and again['checkpoint_hits']==2 and again['model_load_count']==0
        assert [row['id'] for row in again['results']]==['renamed-b','renamed-a']
        changed=run_cached(audio,[job(1),job(2,'明日は')],identity={'engine':'test','revision':'v1'},runner=runner)
        assert calls[-1]==['2'] and changed['checkpoint_hits']==1
        shifted=audio.copy();shifted[1600:3200]+=1
        run_cached(shifted,[job(1),job(2,'明日は')],identity={'engine':'test','revision':'v1'},runner=runner)
        assert calls[-1]==['1']


def test_partial_worker_crash_retains_completed_batch_and_corruption_is_rejected(tmp_path):
    audio=np.zeros(16000,dtype=np.float32);context=RuntimeContext(alignment_checkpoint_dir=str(tmp_path))
    def crash(rows):
        row=dict(rows[0],status='aligned');save_worker_checkpoint(rows[0]['_checkpoint'],row,{'model':'test'})
        raise RuntimeError('interrupted batch')
    calls=[]
    def resume(rows):calls.extend(row['id'] for row in rows);return output(rows)
    with activate_runtime_context(context):
        with pytest.raises(RuntimeError,match='interrupted'):
            run_cached(audio,[job(1),job(2)],identity={'engine':'test'},runner=crash)
        result=run_cached(audio,[job(1),job(2)],identity={'engine':'test'},runner=resume)
        assert calls==['2'] and result['checkpoint_hits']==1
        for path in tmp_path.glob('*.json.gz'):path.write_bytes(b'broken')
        calls.clear()
        run_cached(audio,[job(1),job(2)],identity={'engine':'test'},runner=resume)
        assert calls==['1','2']


def test_cancelled_result_is_never_published(tmp_path):
    from types import SimpleNamespace
    from twobyteasr.recognition.service import CancelledError
    token=SimpleNamespace(is_cancelled=False)
    context=RuntimeContext(alignment_checkpoint_dir=str(tmp_path),cancellation_token=token)
    def late(rows):token.is_cancelled=True;return output(rows)
    with activate_runtime_context(context):
        with pytest.raises(CancelledError):
            run_cached(np.zeros(16000,dtype=np.float32),[job(1)],identity={'engine':'test'},runner=late)
    assert not list(tmp_path.glob('*.json.gz'))


def test_mfa_tuple_parameters_round_trip_without_invalidating_acoustic_cache(tmp_path):
    audio=np.zeros(16000,dtype=np.float32);calls=[]
    identity=dict(engine='mfa',models=[('Japanese','japanese_mfa'),('Chinese','mandarin_mfa')],revision='3.4.3')
    def runner(rows):calls.append(len(rows));return output(rows)
    with activate_runtime_context(RuntimeContext(alignment_checkpoint_dir=str(tmp_path))):
        run_cached(audio,[job(1)],identity=identity,runner=runner)
        reused=run_cached(audio,[dict(job(1),id='renumbered')],identity=identity,runner=runner)
    assert calls==[1] and reused['checkpoint_hits']==1 and reused['model_load_count']==0
