# SPDX-License-Identifier: GPL-3.0-only
"""Actual export frame bounds: short ranges, AV tails, rates and seam handles."""
import copy
from dataclasses import replace
from fractions import Fraction
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from twobyteasr.exports.export_media import MediaIndex, ExportMediaError, probe_media, SequentialExportDecoder
from twobyteasr.exports import video_export


def make_job(tmp_path, *, start=0,duration=2.117,full_ms=223296,fps=60):
    source=tmp_path/'source.mp4'
    clip=dict(id='primary',asset_id='A1',source_in_ms=0,source_out_ms=full_ms,
        timeline_in_ms=0,timeline_out_ms=full_ms,playback_rate=1)
    graph=dict(media_pool=[dict(asset_id='A1',canonical_source=str(source),
        video_metadata=dict(has_video=True))],video_tracks=[dict(id='V1',clips=[clip])],
        duration_ms=full_ms,fps=fps)
    return SimpleNamespace(settings=SimpleNamespace(fps=fps),start_seconds=start,
        duration_seconds=duration,video_graph=graph,media_path=str(source),output_path=str(tmp_path/'output.mp4'))


def index_for(path, *, last_frame=13396,fps=60):
    return MediaIndex(str(path),Fraction(0),Fraction(1,fps),tuple(range(last_frame+1)),Fraction(fps),'{}',0)


def install_index(monkeypatch,job,index):
    calls=[]
    def probe(ffmpeg,path,**kwargs):calls.append(path);return index
    monkeypatch.setattr(video_export,'probe_media',probe)
    return calls


def receipt(job):return json.loads(Path(job.output_path).with_suffix('.preflight.json').read_text('utf8'))


def test_short_range_does_not_request_unsampled_whole_clip_out(tmp_path,monkeypatch):
    job=make_job(tmp_path);before=copy.deepcopy(job.video_graph);media=index_for(job.media_path)
    # Reproduce the old exclusive-end failure exactly; frame indexing is real.
    with pytest.raises(ValueError):media.target(Fraction(223296,1000))
    calls=install_index(monkeypatch,job,media)
    video_export.preflight_video_job(Path('ffmpeg.exe'),job)
    rows=receipt(job)
    assert max(row['timeline_frame_index'] for row in rows)==127
    assert max(Fraction(row['source_pts']) for row in rows)==Fraction(127,60)
    assert not any(row['boundary_clamped'] for row in rows)
    assert calls==[str(Path(job.media_path).resolve())]
    assert job.video_graph==before and job.duration_seconds==2.117


def test_complete_av_tail_uses_last_actual_frame_and_explicit_existing_hold(tmp_path,monkeypatch):
    job=make_job(tmp_path,duration=223.296);media=index_for(job.media_path)
    install_index(monkeypatch,job,media);video_export.preflight_video_job(Path('ffmpeg.exe'),job)
    last=receipt(job)[-1]
    assert last['timeline_frame_index']==13397
    assert Fraction(last['source_pts'])==Fraction(13397,60)
    assert Fraction(last['resolved_pts'])==Fraction(13396,60)
    assert last['boundary_clamped'] and last['export_duration_seconds']==223.296
    assert last['source_frame_interval']=='1/60'


def test_complete_tail_beyond_existing_single_frame_bound_still_fails(tmp_path,monkeypatch):
    job=make_job(tmp_path,duration=223.334,full_ms=223334)
    install_index(monkeypatch,job,index_for(job.media_path))
    with pytest.raises(ExportMediaError,match='CLIP_MAPPING') as error:
        video_export.preflight_video_job(Path('ffmpeg.exe'),job)
    assert error.value.receipt['timeline_frame_index']>=13398
    assert job.video_graph['video_tracks'][0]['clips'][0]['source_out_ms']==223334


def test_half_open_boundaries_nonzero_export_start_and_exact_rate(tmp_path,monkeypatch):
    job=make_job(tmp_path,start=1.0,duration=.1)
    clip=job.video_graph['video_tracks'][0]['clips'][0]
    clip.update(timeline_in_ms=1010,timeline_out_ms=1070,source_in_ms=2000,source_out_ms=2120,playback_rate=2.)
    install_index(monkeypatch,job,index_for(job.media_path))
    video_export.preflight_video_job(Path('ffmpeg.exe'),job)
    rows=receipt(job);assert [r['timeline_frame_index'] for r in rows]==[1,2,3,4]
    assert Fraction(rows[0]['timeline_pts'])==Fraction(61,60)
    assert Fraction(rows[0]['source_pts'])==Fraction(151,75)
    assert Fraction(rows[-1]['timeline_pts'])<Fraction(1070,1000)


def test_clip_outside_requested_samples_not_probed(tmp_path,monkeypatch):
    job=make_job(tmp_path);extra=copy.deepcopy(job.video_graph['video_tracks'][0]['clips'][0])
    extra.update(id='later',asset_id='missing',timeline_in_ms=5000,timeline_out_ms=6000)
    job.video_graph['media_pool'].append(dict(asset_id='missing',canonical_source=str(tmp_path/'missing.mp4')))
    job.video_graph['video_tracks'][0]['clips'].append(extra)
    calls=install_index(monkeypatch,job,index_for(job.media_path))
    video_export.preflight_video_job(Path('ffmpeg.exe'),job)
    assert len(calls)==1
    assert next(r for r in receipt(job) if r['clip_id']=='later')['status']=='not_sampled'


def test_range_without_active_video_keeps_empty_index_and_raster_route(tmp_path,monkeypatch):
    from twobyteasr.exports.studio_render import RenderJob,RenderSettings
    original=make_job(tmp_path,full_ms=1000)
    job=RenderJob(original.media_path,str(tmp_path/'unused.ass'),original.output_path,
        RenderSettings(fps=60,audio_codec='none'),start_seconds=2.,duration_seconds=.2,
        video_graph=original.video_graph)
    monkeypatch.setattr(video_export,'probe_media',lambda *a,**k:pytest.fail('inactive source was probed'))
    received=[]
    def compose(ffmpeg,actual,output,**kwargs):
        received.append(kwargs['indexes']);return dict(fps=60,duration_seconds=.2)
    monkeypatch.setattr(video_export,'compose_video',compose)
    with video_export.prepared_video_job(Path('ffmpeg.exe'),job) as prepared:
        assert prepared.composition_resolved and prepared.duration_seconds==.2
    assert received==[{}]


def test_transition_expanded_handle_is_checked_on_same_raster_clock(tmp_path,monkeypatch):
    job=make_job(tmp_path,start=.9,duration=.1)
    clip=job.video_graph['video_tracks'][0]['clips'][0]
    clip.update(timeline_in_ms=1000,timeline_out_ms=2000,source_in_ms=500,source_out_ms=1500)
    # Drive the actual shared production transition-window seam contract.
    from twobyteasr.timeline import studio_transitions
    window=dict(clip,timeline_in_ms=900,source_in_ms=400)
    monkeypatch.setattr(studio_transitions,'transition_windows',lambda *args:{('V1','primary'):window})
    install_index(monkeypatch,job,index_for(job.media_path))
    video_export.preflight_video_job(Path('ffmpeg.exe'),job)
    assert receipt(job)[0]['timeline_frame_index']==0 and Fraction(receipt(job)[0]['source_pts'])==Fraction(2,5)


def test_real_media_audio_tail_short_and_full_decoder_requests(tmp_path):
    from twobyteasr.system.processes import run_hidden_subprocess
    root=Path(__file__).resolve().parents[1]
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    if not ffmpeg.is_file():ffmpeg=root/'prototype/runtime/ffmpeg/ffmpeg.exe'
    if not ffmpeg.is_file():pytest.skip('Explicit audited FFmpeg required')
    source=tmp_path/'actual-av-tail.mp4'
    run_hidden_subprocess([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=s=160x90:r=60:d=0.5',
        '-f','lavfi','-i','sine=frequency=440:duration=0.512','-c:v','libx264','-threads','2','-c:a','aac',str(source)],
        purpose='actual AV-tail preflight regression',check=True,timeout=15)
    media=probe_media(ffmpeg,source)
    assert media.last==Fraction(29,60) and media.interval==Fraction(1,60)
    job=make_job(tmp_path,duration=.512,full_ms=512);job.media_path=str(source)
    job.video_graph['media_pool'][0]['canonical_source']=str(source)
    before=copy.deepcopy(job.video_graph)
    indexes=video_export.preflight_video_job(ffmpeg,job);rows=receipt(job)
    assert rows[-1]['timeline_frame_index']==30 and rows[-1]['boundary_clamped']
    decoder=SequentialExportDecoder(indexes[str(source.resolve())])
    try:
        _,last=decoder.read(Fraction(rows[-1]['source_pts']))
        assert last['boundary_clamped'] and last['frame_pts']==media.pts[-1]
    finally:decoder.close()
    job.duration_seconds=.2;video_export.preflight_video_job(ffmpeg,job)
    assert not any(r['boundary_clamped'] for r in receipt(job))
    assert job.video_graph==before
