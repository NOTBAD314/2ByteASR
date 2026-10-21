"""Content-addressed edited FLV input: real decode plus instance/cache guards."""
import copy
import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from twobyteasr.media.indexed_media import IndexedMediaCache
from twobyteasr.exports.timeline_media import resolve_audio_layers, resolve_video_graph, TIME_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'


def run(*args):
    return subprocess.run([str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                           *map(str, args)], check=True, capture_output=True).stdout


@pytest.fixture(scope='module')
def gappy(tmp_path_factory):
    root = tmp_path_factory.mktemp('content-flv')
    rng = np.random.default_rng(319)
    # Nonperiodic audio is an independent content marker, unlike one tone
    # whose correlation would also pass after a many-second offset.
    original = (rng.normal(0, .07, 16000*12)*32767).astype('<i2')
    wav = root/'marker.wav'
    with wave.open(str(wav), 'wb') as f:
        f.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        f.writeframes(original.tobytes())
    files=[]
    for index,gap in enumerate((2,4)):
        if index:
            original=(rng.normal(0,.07,16000*12)*32767).astype('<i2')
            with wave.open(str(wav),'wb') as f:
                f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(original.tobytes())
        source=root/f'source-{index}.flv'
        run('-f','lavfi','-i','testsrc2=size=96x64:rate=25:duration=12','-i',wav,
            '-filter_complex',f"[0:v]setpts='PTS+{gap}*gte(T,5)/TB'[v];[1:a]asetpts='PTS+{gap}*gte(T,5)/TB'[a]",
            '-map','[v]','-map','[a]','-c:v','libx264','-preset','ultrafast','-c:a','aac','-f','flv',source)
        files.append(source)
    return root,files


def pcm(path, start, duration):
    # Decode from the head and sample-trim: independent of production -ss.
    raw=run('-i',path,'-map','0:a:0','-af',f'asetpts=N/SR/TB,atrim=start={start}:duration={duration}',
            '-ac','1','-ar','16000','-f','s16le','pipe:1')
    return np.frombuffer(raw,dtype='<i2').astype(np.float64)


def test_two_different_gap_sources_resolve_once_and_keep_clip_instances(gappy, tmp_path):
    _,sources=gappy;cache=IndexedMediaCache(tmp_path/'seek')
    layers=[dict(source_path=str(sources[i%2]),clip_id=f'clip-{i}',audio_clip_id=f'a-{i}',
        timeline_in_ms=i*2000,timeline_out_ms=(i+1)*2000,source_in_ms=7500,source_out_ms=9500,
        playback_rate=1.,gain_db=0.,stream_index=0) for i in range(3)]
    before=copy.deepcopy(layers)
    resolved,receipts=resolve_audio_layers(layers,FFMPEG,cache=cache)
    assert layers==before and len(receipts)==2
    assert [l['clip_id'] for l in resolved]==['clip-0','clip-1','clip-2']
    assert resolved[0]['source_path']==resolved[2]['source_path']!=resolved[1]['source_path']
    assert all(r['kind']=='continuous_proxy' for r in receipts.values())
    # Existing proxy clock differs from PCM sample clock by codec/container
    # frame rounding. Bound and measure it, never allow the 2s/4s discontinuity.
    from scipy.signal import correlate
    for src,r in zip(sources,resolved):
        expected=pcm(src,7,3)
        actual=pcm(r['source_path'],7.5,1)
        c=correlate(expected,actual,mode='valid',method='fft')
        lag=int(c.argmax())/16000-.5
        assert abs(lag)<.15,lag
    warm,again=resolve_audio_layers(layers,FFMPEG,cache=cache)
    assert warm==resolved and again==receipts
    assert resolve_audio_layers(resolved,FFMPEG,cache=cache)==(resolved,{})


def test_export_binds_video_and_audio_to_same_per_source_artifact(gappy,tmp_path):
    _,sources=gappy; cache=IndexedMediaCache(tmp_path/'seek')
    graph=dict(media_pool=[dict(asset_id=f's{i}',canonical_source=str(p)) for i,p in enumerate(sources)],
        video_tracks=[dict(id='V1',clips=[dict(id=f'c{i}',asset_id=f's{i}') for i in range(2)])],
        audio_mix=[dict(source_path=str(p),clip_id=f'c{i}') for i,p in enumerate(sources)])
    before=copy.deepcopy(graph)
    result=resolve_video_graph(graph,FFMPEG,cache=cache)
    assert graph==before and result['media_time_contract']==TIME_CONTRACT
    assert [a['canonical_source'] for a in result['media_pool']]==[a['source_path'] for a in result['audio_mix']]
    assert resolve_video_graph(result,FFMPEG,cache=cache) is result


def test_cancel_cannot_fall_back_to_unmapped_original(gappy,tmp_path):
    _,sources=gappy
    with pytest.raises(InterruptedError):
        IndexedMediaCache(tmp_path).prepare_timeline_source(str(sources[0]),ffmpeg=FFMPEG,cancelled=lambda:True)


def test_corrupt_proxy_fails_without_deleting_evidence(gappy,tmp_path):
    _,sources=gappy; cache=IndexedMediaCache(tmp_path/'seek')
    receipt=cache.prepare_timeline_source(str(sources[0]),ffmpeg=FFMPEG)
    proxy=Path(receipt['path']);proxy.write_bytes(b'broken evidence')
    with pytest.raises(RuntimeError,match='连续时间轴媒体不可用'):
        cache.prepare_timeline_source(str(sources[0]),ffmpeg=FFMPEG)
    assert proxy.read_bytes()==b'broken evidence'


@pytest.mark.parametrize('suffix',['mp4','flv'])
def test_healthy_containers_preserve_content_and_identity(gappy,tmp_path,suffix):
    _,sources=gappy
    source=tmp_path/('healthy.'+suffix)
    # Re-encode from sequential samples/frames, intentionally discarding the
    # faulty source timestamps. This is an independent healthy control.
    run('-i',sources[0],'-vf','setpts=N/(25*TB)','-af','asetpts=N/SR/TB',
        '-c:v','libx264','-preset','ultrafast','-c:a','aac',source)
    receipt=IndexedMediaCache(tmp_path/'seek').prepare_timeline_source(str(source),ffmpeg=FFMPEG)
    assert receipt['kind']=='identity' and Path(receipt['path'])==source.resolve()
    assert np.array_equal(pcm(source,7,1),pcm(receipt['path'],7,1))


@pytest.mark.parametrize('pieces',[
    [(0,0,3000,0)],  # no edit at the origin
    [(0,7500,9500,0)],
    [(0,7500,9500,0),(1,8000,10000,2000)],
    [(1,8000,10000,0),(0,7500,9500,2000)],
    [(0,6000,7500,0),(0,9000,10000,1500),(0,6000,7500,2500)],
    [(0,7500,9500,0),(1,8000,10000,4000)],  # ordinary delete: retain gap
])
def test_task_pcm_content_order_gap_and_warm_cache(gappy,tmp_path,monkeypatch,pieces):
    from twobyteasr.media import indexed_media
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot,prepare_recognition_input
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.timeline.studio_edit_sequence import EditSequence,VideoSegment,store_sequence
    from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
    from scipy.signal import correlate
    _,sources=gappy
    monkeypatch.setattr(indexed_media,'GLOBAL_INDEXED_MEDIA',IndexedMediaCache(tmp_path/'seek'))
    project=SubtitleProject(media=StudioMedia(path=str(sources[0]),duration_ms=14000,width=96,height=64));project.validate()
    seq=EditSequence(source_path=str(sources[0]),source_duration_ms=14000,video_track_locked=False,
        segments=[VideoSegment(f'instance{i}',str(sources[s]),a,b,t,t+b-a) for i,(s,a,b,t) in enumerate(pieces)])
    store_sequence(project,seq);sync_primary_video_track_from_sequence(project,seq)
    snap=capture_recognition_snapshot(project);path=prepare_recognition_input(snap,tmp_path,FFMPEG)
    raw=Path(path).read_bytes()
    assert prepare_recognition_input(snap,tmp_path,FFMPEG)==path and Path(path).read_bytes()==raw
    with wave.open(path,'rb') as f:
        assert f.getnframes()==16*snap['duration_ms']
        actual=np.frombuffer(f.readframes(f.getnframes()),'<i2').astype(np.float64)
    for s,a,b,t in pieces:
        # Compare a nonperiodic interior to an independent full-head decode.
        expected=pcm(sources[s],max(0,a/1000),min(1.5,(b-a)/1000))
        window=actual[(t+300)*16:(t+800)*16]
        c=correlate(expected,window,mode='valid',method='fft');at=int(c.argmax())
        assert abs(at/16000-.3)<.15
        assert np.corrcoef(expected[at:at+len(window)],window)[0,1]>.9
    for left,right in zip(pieces,pieces[1:]):
        end=left[3]+left[2]-left[1];start=right[3]
        if start-end>300:assert np.max(np.abs(actual[(end+150)*16:(start-100)*16]))==0
    meta=json.loads(Path(path).with_name('input.json').read_text('utf-8'))
    assert meta['media_time_contract']==TIME_CONTRACT and meta['audio_sha256']
    assert [x['clip_id'] for x in meta['rendered_audio_segments']]==[f'instance{i}' for i in range(len(pieces))]
