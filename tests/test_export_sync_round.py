import copy
import os
from pathlib import Path
import math
import wave

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence, projected_cues
from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
from twobyteasr.exports.export_timeline import write_export_ass
from twobyteasr.exports.video_export import capture_video_graph
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
from twobyteasr.exports.export_preferences import output_basename, clean_affix
from twobyteasr.exports.export_progress import ExportProgress


def test_static_gradient_progress_reserves_majority_for_actual_encoding():
    progress=ExportProgress(100,advanced=True,static_advanced=True)
    value,_=progress.update({'stage':'advanced_render','percent':100})
    assert value==5
    value,_=progress.update({'stage':'encode','out_time_us':'1760000'})
    assert 5<value<10
    assert progress.update({'stage':'mux','percent':100})[0]==100
from twobyteasr.recognition.speaker_evidence import needs_moss_speakers, fuse_moss_speakers

FFMPEG = Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'


def test_output_name_and_known_placeholder_only():
    assert clean_affix('_成片@3得43这') == ''
    assert clean_affix('_我的成片') == '_我的成片'
    assert output_basename('直播.mp4.mp4', '[NOTBAD]') == '[NOTBAD]直播'
    assert output_basename('CON') == '_CON'
    assert output_basename('直播:测试', '', '_最终') == '直播_测试_最终'


def test_progress_keeps_work_fraction_across_stages():
    progress = ExportProgress(100, raster=True)
    total, stage = progress.update({'stage':'compose_video','percent':str(721/22133*100)})
    assert stage == pytest.approx(3.2576, abs=.001)
    assert total == pytest.approx(2+.75*stage)
    previous, _ = progress.update({'stage':'compose_video','percent':100})
    current, _ = progress.update({'stage':'encode','out_time_us':1})
    assert current >= previous
    assert progress.update({'stage':'encode','out_time_us':100000000})[0] < 100
    assert progress.update({'stage':'mux','percent':100})[0] == 100


def test_diarization_auto_requires_acoustic_global_identity():
    assert not needs_moss_speakers('auto',[{'speaker':'S00','speaker_evidence':{'local_speaker':None}}])
    assert not needs_moss_speakers('provider',[{'speaker':'S00'}])
    single = [{'speaker':'API_S00','speaker_evidence':{'local_speaker':0,'request_index':0}}]
    assert not needs_moss_speakers('auto',single)
    assert not needs_moss_speakers('auto',single+[{'speaker_evidence':{'local_speaker':0,'request_index':1}}])
    assert needs_moss_speakers('moss', single)


def test_untimed_phrase_split_requires_exact_nonoverlapping_acoustic_text():
    api=[dict(start=0,end=2,text='你好！再见。')]
    moss=[dict(start=0,end=1,text='你好',speaker=0),dict(start=1,end=2,text='再见',speaker='S02')]
    rows=fuse_moss_speakers(api,moss)
    assert [(r['text'],r['speaker']) for r in rows]==[('你好！','0'),('再见。','S02')]
    assert all(r['alignment_evidence']=='exact_transcript_moss_phrase_boundary' for r in rows)
    moss[1]['start']=.8
    rows=fuse_moss_speakers(api,moss)
    assert len(rows)==1 and rows[0]['speaker']=='S00'
    moss[1].update(start=1,text='另一句话')
    rows=fuse_moss_speakers(api,moss)
    assert len(rows)==1 and rows[0]['speaker']=='S00'


@pytest.mark.parametrize('rate', ['60','60000/1001'])
def test_real_decoded_cut_repeat_rate_gap_and_subtitle_boundaries(tmp_path, monkeypatch, rate):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'local'))
    app = QApplication.instance() or QApplication([])
    source = tmp_path/'source.mkv'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-y','-f','lavfi','-i',
        f'color=c=0x204080:s=320x180:r={rate}:d=4', '-f','lavfi','-i',
        r"aevalsrc=if(lt(mod(t\,1)\,0.08)\,0.3*sin(2*PI*800*t)\,0):s=48000:d=4",
        '-vf',r'drawbox=x=0:y=0:w=30:h=30:color=white:t=fill:enable=lt(mod(t\,1)\,0.08)',
        '-c:v','ffv1','-c:a','pcm_s16le','-output_ts_offset','2',str(source)],
        purpose='deterministic export sync fixture',check=True,timeout=20)
    project = SubtitleProject(media=StudioMedia(path=str(source),duration_ms=4000,width=320,height=180))
    project.validate()
    sequence = EditSequence(source_path=str(source),source_duration_ms=4000,video_track_locked=False,
        segments=[VideoSegment('late',str(source),2000,3000,200,1200),
                  VideoSegment('early',str(source),400,1400,1200,2200),
                  VideoSegment('repeat',str(source),2000,3000,2400,2900)])
    store_sequence(project,sequence)
    sync_primary_video_track_from_sequence(project,sequence)
    project.video_tracks[0].clips[-1].playback_rate=2.
    project.media_pool[0].video_metadata.update(fps=float(__import__('fractions').Fraction(rate)))
    project.cues=[StudioCue('a',500,700,'SYNC'),StudioCue('b',2500,2700,'SYNC')]
    project.styles[0].primary_color='#FF0000'
    project.styles[0].font_size=110
    project.styles[0].bold=True
    before=copy.deepcopy(project.to_dict())
    ass=tmp_path/'timeline.ass'
    write_export_ass(project,ass,fps=rate)
    assert project.to_dict()==before
    frames=[]
    job=RenderJob(str(source),str(ass),str(tmp_path/'output.mp4'),
        RenderSettings(encoder='libx264',preset='ultrafast',quality=12,width=320,height=180,
                       fps=float(__import__('fractions').Fraction(rate)),audio_codec='aac'),
        start_seconds=.1,duration_seconds=2.8,video_graph=capture_video_graph(project),
        preview_callback=lambda image,t,phase: frames.append((t,image.width(),phase)),
        completion_preview_path=str(tmp_path/'cover.jpg'))
    run_render_job(FFMPEG,job)
    expected=projected_cues(project)
    errors=[]
    flashes=[]
    with av.open(job.output_path) as decoded:
        for frame in decoded.decode(video=0):
            rgb=frame.to_ndarray(format='rgb24')
            visible=np.sum((rgb[:,:,0]>150)&(rgb[:,:,1]<100)&(rgb[:,:,2]<100))>12
            t=.1+float(frame.pts*frame.time_base)
            if rgb[:20,:20].mean()>210:
                flashes.append(t-.1)
            wanted=any(c.start_ms/1000<=t<c.end_ms/1000 for c in expected)
            if visible!=wanted:
                distance=min(abs(t-v/1000) for c in expected for v in (c.start_ms,c.end_ms))
                errors.append(distance)
    assert not errors or max(errors)<=1/float(__import__('fractions').Fraction(rate))+.0001, errors
    assert frames and len({t for t,_,_ in frames})>1
    assert all(width==640 and phase=='已烧录字幕' for _,width,phase in frames)
    assert (tmp_path/'cover.jpg').is_file()
    audio=tmp_path/'decoded.wav'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-y','-i',job.output_path,'-vn','-ac','1','-ar','48000',str(audio)],
        purpose='decode exported pulse evidence',check=True,timeout=10)
    with wave.open(str(audio),'rb') as wav:
        pcm=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')/32768.
    for onset in (.1,1.7,2.3):
        visible=min(t for t in flashes if abs(t-onset)<.15)
        left=max(0,round((onset-.04)*48000))
        offsets=np.flatnonzero(np.abs(pcm[left:round((onset+.10)*48000)])>.1)
        assert len(offsets)
        heard=(left+offsets[0])/48000
        assert abs(heard-visible)<=1/float(__import__('fractions').Fraction(rate))+.008


def test_recognized_project_export_never_reuses_source_ass(tmp_path):
    app=QApplication.instance() or QApplication([])
    project=SubtitleProject(media=StudioMedia(path='video.mp4',duration_ms=5000))
    project.validate()
    seq=EditSequence(source_path='video.mp4',source_duration_ms=4000,
        segments=[VideoSegment('offset','video.mp4',0,4000,1199,5199)])
    store_sequence(project,seq)
    project.generation_metadata['timeline_recognition']={'sequence':seq.to_dict()}
    project.cues=[StudioCue('1',2600,4400,'同步')]
    assert projected_cues(project,domain='source')[0].start_ms==1401
    snapshot=write_export_ass(project,tmp_path/'export.ass',fps=60)
    assert snapshot.cues[0].start_ms==2600
    assert '0:00:02.60' in (tmp_path/'export.ass').read_text(encoding='utf-8-sig')


def test_indexed_flv_offset_keeps_first_gop_motion(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    app=QApplication.instance() or QApplication([])
    source=tmp_path/'indexed.flv'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-y','-f','lavfi','-i','testsrc2=s=320x180:r=60:d=3',
        '-c:v','libx264','-threads','2','-g','120','-bf','2','-flvflags','add_keyframe_index',str(source)],
        purpose='indexed FLV first GOP fixture',check=True,timeout=20)
    project=SubtitleProject(media=StudioMedia(path=str(source),duration_ms=3000,width=320,height=180))
    project.validate()
    seq=EditSequence(source_path=str(source),source_duration_ms=3000,video_track_locked=False,
        segments=[VideoSegment('offset',str(source),0,1500,1199,2699)])
    store_sequence(project,seq);sync_primary_video_track_from_sequence(project,seq)
    ass=tmp_path/'empty.ass';write_export_ass(project,ass,fps=60)
    job=RenderJob(str(source),str(ass),str(tmp_path/'out.mp4'),RenderSettings(encoder='libx264',preset='ultrafast',
        quality=12,width=320,height=180,fps=60,audio_codec='none'),duration_seconds=2.699,video_graph=capture_video_graph(project))
    run_render_job(FFMPEG,job)
    with av.open(str(source)) as c:
        origin=float((c.start_time or 0)/1e6)
        reference=[(float(f.pts*f.time_base)-origin,f.to_ndarray(format='rgb24').astype(float)) for f in c.decode(video=0)]
    with av.open(job.output_path) as c:
        for f in c.decode(video=0):
            t=float(f.pts*f.time_base)
            if 1.2<=t<2.65:
                source_t=t-1.199
                expected=next((p for at,p in reversed(reference) if at<=source_t+.001),reference[0][1])
                assert np.abs(f.to_ndarray(format='rgb24').astype(float)-expected).mean()<5
