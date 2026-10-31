import json
from pathlib import Path
import numpy as np
import subtitle_core
from twobyteasr.recognition import cache
from twobyteasr.playback.cue_audio_preview import CuePreviewPlan
from twobyteasr.playback.recognition_audio_preview import cached_recognition_pcm


def cached(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path/'cache'))
    source = tmp_path/'original.flv'
    source.write_bytes(b'source identity')
    stat = source.stat()
    identity = dict(path=str(source),size=stat.st_size,mtime_ns=stat.st_mtime_ns,sha256='verified',fingerprint='file',selection={})
    folder = Path(cache.CACHE_ROOT)/cache.stable_digest(identity)[:24]
    folder.mkdir(parents=True)
    signal = (np.sin(np.arange(32000)*2*np.pi*440/16000)*.4).astype(np.float32)
    np.save(folder/'audio_16k.npy',signal)
    (folder/'audio_meta.json').write_text(json.dumps(dict(schema=cache.CACHE_SCHEMA_VERSION,
        identity=identity,signature=cache.cache_stage_signature('audio'),sample_rate=16000,samples=len(signal))))
    layer = dict(source_path=str(source),timeline_in_ms=0,timeline_out_ms=2000,source_in_ms=0,
                 stream_index=0,playback_rate=1.,gain_db=0.,audio_envelopes=[])
    plan = CuePreviewPlan('request','project','revision','cue','speech','timeline',(500,1000),(500,1000),[layer],
                          recognition_identity=identity)
    return plan, signal, folder


def test_reads_only_requested_range_with_exact_source_offset(tmp_path,monkeypatch):
    plan, signal, _ = cached(tmp_path,monkeypatch)
    payload = cached_recognition_pcm(plan)
    assert len(payload) == 48000*.5*2*2
    values = np.frombuffer(payload,dtype='<i2').reshape(-1,2)
    assert np.array_equal(values[:,0],values[:,1])
    assert np.max(np.abs(values[::3,0]/32767.-signal[8000:16000])) < .00004


def test_replaced_media_wrong_stream_gain_and_corrupt_cache_fall_back(tmp_path,monkeypatch):
    plan, _, folder = cached(tmp_path,monkeypatch)
    for field,value in [('stream_index',1),('gain_db',-2),('playback_rate',2),('audio_envelopes',[{'fade':1}])]:
        old = plan.layers[0][field]
        plan.layers[0][field] = value
        assert cached_recognition_pcm(plan) is None
        plan.layers[0][field] = old
    np.save(folder/'audio_16k.npy',np.zeros(32000,dtype=np.int16))
    assert cached_recognition_pcm(plan) is None
    Path(plan.layers[0]['source_path']).write_bytes(b'replaced media with another size')
    assert cached_recognition_pcm(plan) is None
