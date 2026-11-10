"""The caught CTC failure must not become a reusable, measured window."""
import copy
import json
from types import SimpleNamespace

import pytest

from firered_aed_worker import _install_timestamp_receipts
from twobyteasr.recognition.firered_checkpoints import VERSION,save_row,read_row,fingerprint
from twobyteasr.recognition.asr_schema import normalize_firered_worker_result,flatten_segment_tokens


def row(estimated=False):
    return dict(segment_id=4,text='啊'*238+'哈'*688+'测试'*12,
        timestamp=[dict(text='啊',start=i*.04,end=(i+1)*.04) for i in range(950)],
        evidence_version=VERSION,transcription_status='success',
        alignment_status='failed_or_unavailable' if estimated else 'aligned',
        timestamp_source='uniform_window_estimate' if estimated else 'ctc_forced_alignment',
        timestamp_reliability='estimated' if estimated else 'measured')


def test_observer_sees_missing_hypothesis_before_uniform_fallback():
    model=SimpleNamespace(_get_and_fix_timestamp=lambda hyp,ids,dur:[[str(ids[0]),0,dur]])
    receipts=_install_timestamp_receipts(model)
    failed=model._get_and_fix_timestamp({'timestamp':None},[1],38)
    good=model._get_and_fix_timestamp({'timestamp':([0],[1])},[2],38)
    assert receipts[id(failed)]['timestamp_reliability']=='estimated'
    assert receipts[id(good)]['timestamp_reliability']=='measured'


def test_write_and_read_both_reject_failed_or_unversioned_checkpoints(tmp_path):
    job=dict(audio_sha256='pcm',segment_id=4,duration=38.)
    identity={'model':'fixture'}
    assert save_row(tmp_path,job,identity,row(True)) is None
    key=fingerprint({'input':'pcm','model':identity,'duration':38.})
    for value in [row(True),{k:v for k,v in row().items() if k not in
            {'evidence_version','transcription_status','alignment_status','timestamp_source','timestamp_reliability'}}]:
        (tmp_path/(key+'.json')).write_text(json.dumps(dict(version=VERSION,key=key,row=value,sha256=fingerprint(value))),encoding='utf-8')
        assert read_row(tmp_path,job,identity) is None


def test_quantization_and_laughter_alone_do_not_invalidate_measured_alignment(tmp_path):
    job=dict(audio_sha256='pcm',segment_id=4,duration=38.)
    value=row()
    assert save_row(tmp_path,job,'model',value)
    assert read_row(tmp_path,job,'model')==value


def test_failed_window_retains_transcript_but_contributes_no_word_evidence():
    good=dict(row(),segment_id=1,text='正常',timestamp=[dict(text='正常',start=1,end=2)])
    bad=row(True)
    jobs=[dict(segment_id=1,offset=0,duration=38),dict(segment_id=4,offset=108,duration=38)]
    canonical=normalize_firered_worker_result({'results':[good,bad]},jobs)
    assert canonical['segments'][1]['text']==bad['text']
    assert canonical['segments'][1]['alignment_status']=='failed_or_unavailable'
    assert [t['text'] for t in flatten_segment_tokens(canonical)]==['正常']


def test_only_untrusted_windows_require_retry(tmp_path):
    jobs=[dict(audio_sha256=str(i),segment_id=i,duration=38.) for i in range(10)]
    for i,job in enumerate(jobs):
        save_row(tmp_path,job,'model',dict(row(i==3),segment_id=i))
    missing=[j['segment_id'] for j in jobs if read_row(tmp_path,j,'model') is None]
    assert missing==[3]


@pytest.mark.parametrize('field,value',[('evidence_version','old'),('timestamp_reliability','unknown'),
    ('alignment_status','failed'),('transcription_status','failed')])
def test_status_is_revalidated_even_when_digest_is_valid(tmp_path,field,value):
    job=dict(audio_sha256='pcm',segment_id=4,duration=38.)
    assert save_row(tmp_path,job,'model',dict(row(),**{field:value})) is None


def test_aed_receipt_upgrade_does_not_invalidate_other_aligners(monkeypatch):
    import subtitle_core
    from twobyteasr.recognition import cache,firered_checkpoints
    monkeypatch.setattr(cache,'FIRERED_ASR_BACKEND','qwen_aligner')
    before=cache.cache_stage_signature('firered')
    monkeypatch.setattr(firered_checkpoints,'VERSION','future-version')
    assert cache.cache_stage_signature('firered')==before
    monkeypatch.setattr(cache,'FIRERED_ASR_BACKEND','local')
    before=cache.cache_stage_signature('firered')
    monkeypatch.setattr(firered_checkpoints,'VERSION','another-version')
    assert cache.cache_stage_signature('firered')!=before
