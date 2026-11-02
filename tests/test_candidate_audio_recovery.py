"""Lossless candidate input and real single-clock audio-only transport guards."""
import copy,hashlib
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.recognition.transcript_acceptance import digest
from twobyteasr.recognition.alignment_audio import pcm_digest

APP=QApplication.instance() or QApplication([])


def snapshot_for(tmp_path):
    source=tmp_path/'source.bin';source.write_bytes(b'original source identity')
    pcm=(np.sin(np.arange(48000,dtype=np.float64)*.13)*.17123).astype('float32')
    path=tmp_path/'original.npy';np.save(path,pcm,allow_pickle=False)
    identities={str(source):{'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}}
    policy=dict(confirmed_after_listening=True,input_pcm={'path':str(path),'samples':len(pcm),'range_origin_ms':0},
        candidate_scope=[1.,2.],audio_graph_digest=digest({'segments':[]}),pcm_sha256=pcm_digest(pcm[16000:32000]),
        source_identities=copy.deepcopy(identities))
    return dict(language_recovery_policy=policy,audio_graph={'segments':[]},sources=identities,
        duration_ms=1000,range_ms=[1000,2000],fingerprint='same-immutable-input'),pcm,path


def test_exact_float_pcm_crop_survives_production_decode_and_cache_hit(tmp_path):
    import subtitle_core
    from twobyteasr.recognition.candidate_audio import prepare_candidate_input
    from twobyteasr.recognition.cache import decode_audio_to_array
    snapshot,pcm,path=snapshot_for(tmp_path)
    before=path.read_bytes()
    target=Path(prepare_candidate_input(snapshot,tmp_path/'cache'))
    decoded=decode_audio_to_array(str(target))
    assert np.array_equal(decoded,pcm[16000:32000])
    first=target.stat().st_mtime_ns
    assert prepare_candidate_input(snapshot,tmp_path/'cache')==str(target)
    assert target.stat().st_mtime_ns==first and path.read_bytes()==before


@pytest.mark.parametrize('change',['graph','source','range','pcm'])
def test_changed_input_never_reuses_old_candidate_pcm(tmp_path,change):
    from twobyteasr.recognition.candidate_audio import prepare_candidate_input
    snapshot,pcm,path=snapshot_for(tmp_path)
    if change=='graph':snapshot['audio_graph']={'changed':True}
    if change=='source':next(iter(snapshot['sources'].values()))['sha256']='different'
    if change=='range':snapshot['range_ms']=[0,1000]
    if change=='pcm':pcm[20000]+=.01;np.save(path,pcm,allow_pickle=False)
    with pytest.raises(ValueError):prepare_candidate_input(snapshot,tmp_path/'cache')
    assert not (tmp_path/'cache/candidate-inputs').exists()


def test_audio_only_startup_waits_for_current_pcm_and_maps_source_time():
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=MpvCanvas()
    sample={}
    try:
        canvas._navigation_visible=True
        canvas.set_project_time_mapping(enabled=True,timeline_in_ms=2000,source_in_ms=60000,playback_rate=1.5)
        canvas.set_external_clock_provider(lambda:sample,enabled=True)
        canvas.enter_audio_only_source(2000,10000)
        generation=canvas._playback_clock.generation
        assert canvas._startup_state=='MEDIA_OPENING'
        sample.update(source_path='current.wav',state='PAUSED',transport_generation=[generation-1,0],
            source_generation=7,clock_sequence=1,estimated_source_ms=61500.,effective_rate=1.5,paused=True,decoded_bytes=64000)
        canvas._reconcile_position()
        assert canvas._startup_state=='MEDIA_OPENING'
        sample['transport_generation']=[generation,0]
        canvas._reconcile_position()
        assert canvas._startup_state=='READY'
        current=canvas._playback_clock.snapshot()
        assert current.observed_media_ms==pytest.approx(3000.)
        assert current.playback_rate==pytest.approx(1.)
    finally:
        canvas._timer.stop();canvas._sync_timer.stop();canvas.deleteLater()


def test_audio_only_play_and_seek_keep_preroll_and_user_pause():
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=MpvCanvas();ready=[False]
    try:
        canvas.controller=SimpleNamespace(running=True)
        canvas.suspend_media_async=lambda **kw:True
        canvas.set_external_clock_provider(lambda:{},enabled=True)
        canvas.enter_audio_only_source(0,10000)
        canvas._startup_state='READY'
        canvas.playback_ready=lambda:ready[0];canvas.playback_prepare=lambda:None
        canvas.set_paused(False)
        assert canvas._paused and canvas._buffered_play_pending
        ready[0]=True;canvas.set_paused(False)
        assert not canvas._paused
        ready[0]=False;canvas.seek(2.,project_ms=2000)
        assert canvas._paused and canvas._seek_hold_active
        canvas.set_paused(True)
        assert not canvas._seek_hold_active and not canvas.playback_intended
        ready[0]=True
        canvas._resume_after_seek_hold(canvas._seek_hold_token)
        assert canvas._paused
    finally:
        canvas._timer.stop();canvas._sync_timer.stop();canvas._buffered_play_timer.stop()
        canvas.controller=None;canvas.deleteLater()



def test_video_frame_tail_reuses_only_verified_real_pcm_without_padding(tmp_path):
    from twobyteasr.recognition.candidate_audio import prepare_candidate_input
    from twobyteasr.recognition.cache import decode_audio_to_array
    snapshot,pcm,path=snapshot_for(tmp_path)
    policy=snapshot['language_recovery_policy']
    policy.update(candidate_scope=[0.,3.04],pcm_scope=[0.,3.],frame_tail_tolerance_seconds=.04,pcm_sha256=None,full_pcm_sha256=pcm_digest(pcm))
    snapshot.update(range_ms=[0,3040],duration_ms=3040)
    target=prepare_candidate_input(snapshot,tmp_path/'cache')
    assert np.array_equal(decode_audio_to_array(target),pcm)
    assert len(decode_audio_to_array(target))==48000
    assert policy['pcm_sha256']==pcm_digest(pcm)
