"""Actual bundled-FFmpeg files; timeline edits, silence, formats and publication."""
import copy
from pathlib import Path
import subprocess

import numpy as np
import pytest

from twobyteasr.exports.audio_delivery import FORMATS, format_capabilities, run_audio_job, probe_audio
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job

ROOT=Path(__file__).resolve().parents[1]
FFMPEG=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'


@pytest.fixture
def tones(tmp_path):
    result=[]
    for frequency in (440,880,220):
        path=tmp_path/f'中文 音源 {frequency}.wav'
        subprocess.run([str(FFMPEG),'-v','error','-f','lavfi','-i',
            f'sine=frequency={frequency}:sample_rate=44100:duration=4','-c:a','pcm_s16le',str(path)],
            check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        result.append(str(path))
    return result


def edited_job(tmp_path,tones,name='wav'):
    def layer(source,start,end,source_start=0,rate=1,gain=0):
        return dict(source_path=source,timeline_in_ms=start,timeline_out_ms=end,
            source_in_ms=source_start,source_out_ms=source_start+(end-start)*rate,
            playback_rate=rate,gain_db=gain,stream_index=0)
    return RenderJob(tones[0],'',str(tmp_path/('剪輯後 聲音.'+name)),
        settings=RenderSettings(output_kind='audio',container=name,audio_bit_depth=24),
        start_seconds=0,duration_seconds=3,
        audio_graph={'segments':[layer(tones[0],0,1000,1000),
            layer(tones[1],1500,3000,500,2,-6),layer(tones[2],2000,2700,0,1,-12)]})


def pcm(path):
    raw=subprocess.run([str(FFMPEG),'-v','error','-i',str(path),'-ac','1','-ar','44100',
        '-f','f32le','pipe:1'],capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return np.frombuffer(raw,dtype='<f4')


@pytest.mark.parametrize('name',list(FORMATS))
def test_real_edited_audio_formats(tmp_path,tones,name):
    cap=format_capabilities(FFMPEG)[name]
    assert cap['available'], cap['reason']
    job=edited_job(tmp_path,tones,name)
    output=run_render_job(FFMPEG,job)
    metadata=probe_audio(FFMPEG,output)
    assert len(metadata['streams'])==1
    stream=metadata['streams'][0]
    assert stream['codec_type']=='audio'
    assert stream['codec_name']=={'mp3':'mp3','wav':'pcm_s24le','m4a':'aac','flac':'flac','ogg':'vorbis','opus':'opus'}[name]
    assert int(stream['sample_rate'])==(48000 if name=='opus' else 44100)
    assert abs(float(metadata['format']['duration'])-3)<.1
    sound=pcm(output)
    assert np.sqrt(np.mean(sound[52000:61000]**2))<.002  # timeline gap, not original audio
    def dominant(start,end):
        samples=sound[round(start*44100):round(end*44100)]
        return np.fft.rfftfreq(len(samples),1/44100)[np.argmax(abs(np.fft.rfft(samples)))]
    assert abs(dominant(.15,.85)-440)<3
    assert abs(dominant(1.65,1.95)-880)<4  # 2x duration, pitch preserved
    assert job.completion_metadata['output_path']==str(output.resolve())
    assert not list(tmp_path.glob('.2byteasr-audio-*'))


def test_range_silence_and_volume_match(tmp_path,tones):
    job=edited_job(tmp_path,tones)
    job.start_seconds=.5;job.duration_seconds=2
    output=run_audio_job(FFMPEG,job)
    sound=pcm(output)
    assert abs(len(sound)-88200)<=2
    assert max(abs(sound[25000:41000]))<1e-5
    rms=lambda a,b:np.sqrt(np.mean(sound[round(a*44100):round(b*44100)]**2))
    assert .45<rms(1.15,1.4)/rms(.1,.4)<.56


def test_cancel_and_no_tracks_never_publish(tmp_path,tones):
    job=edited_job(tmp_path,tones)
    with pytest.raises(InterruptedError):
        run_audio_job(FFMPEG,job,cancelled=lambda:True)
    assert not Path(job.output_path).exists()
    job.audio_graph={'segments':[]}
    with pytest.raises(ValueError,match='音轨'):
        run_audio_job(FFMPEG,job)
    assert not Path(job.output_path).exists()
    assert not list(tmp_path.glob('.2byteasr-audio-*'))


def test_cancel_running_preserves_existing_file(tmp_path,tones):
    job=edited_job(tmp_path,tones)
    target=Path(job.output_path);target.write_bytes(b'previous output')
    with pytest.raises(FileExistsError):run_audio_job(FFMPEG,job)
    job.overwrite_existing=True
    calls=[0]
    def cancel():
        calls[0]+=1
        return calls[0]>=4
    with pytest.raises(InterruptedError):run_audio_job(FFMPEG,job,cancelled=cancel)
    assert target.read_bytes()==b'previous output'
    assert not list(tmp_path.glob('.2byteasr-audio-*'))


def test_failure_and_empty_range(tmp_path,tones):
    job=edited_job(tmp_path,tones)
    job.audio_graph['segments'][0]['source_path']=str(tmp_path/'missing 中文.wav')
    with pytest.raises((RuntimeError,subprocess.CalledProcessError,FileNotFoundError)):run_audio_job(FFMPEG,job)
    assert not Path(job.output_path).exists()
    job.duration_seconds=0
    with pytest.raises(ValueError):run_audio_job(FFMPEG,job)


def test_audio_route_does_not_touch_video_or_subtitles(tmp_path,tones,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('audio entered video route')
    monkeypatch.setattr('twobyteasr.exports.studio_render.build_render_command',forbidden)
    monkeypatch.setattr('twobyteasr.exports.timeline_media.resolve_video_graph',forbidden)
    monkeypatch.setattr('twobyteasr.exports.export_validation.validate_output',forbidden)
    job=edited_job(tmp_path,tones)
    job.video_graph={'must_not_be_read':True}
    assert run_render_job(FFMPEG,job).is_file()


def test_fade_preserves_mono_and_applies_per_sample(tmp_path,tones):
    job=edited_job(tmp_path,tones)
    job.audio_graph['segments']=job.audio_graph['segments'][:1]
    job.duration_seconds=1
    job.audio_graph['segments'][0]['audio_envelopes']=[
        dict(start_ms=0,end_ms=500,role='in',curve='linear'),
        dict(start_ms=500,end_ms=1000,role='out',curve='linear')]
    output=run_audio_job(FFMPEG,job)
    assert probe_audio(FFMPEG,output)['streams'][0]['channels']==1
    sound=pcm(output)
    rms=lambda a,b:np.sqrt(np.mean(sound[round(a*44100):round(b*44100)]**2))
    assert rms(.01,.06)<rms(.35,.45)*.2
    assert rms(.94,.99)<rms(.55,.65)*.2


@pytest.mark.parametrize('depth',[16,24,32])
def test_pcm_options_are_real_stream_properties(tmp_path,tones,depth):
    job=edited_job(tmp_path,tones)
    job.settings.audio_bit_depth=depth
    job.settings.audio_sample_rate=48000
    job.settings.audio_channels=2
    output=run_audio_job(FFMPEG,job)
    stream=probe_audio(FFMPEG,output)['streams'][0]
    assert stream['codec_name']==f'pcm_s{depth}le'
    assert stream['sample_rate']=='48000' and stream['channels']==2


def test_typed_audio_extension_is_not_duplicated():
    from twobyteasr.exports.export_preferences import output_basename
    for name in FORMATS:
        assert output_basename('中文 声音.'+name.upper())=='中文 声音'


def test_gappy_flv_trims_content_audio_without_video_proxy(tmp_path,monkeypatch):
    source=tmp_path/'有空洞 的錄播.flv'
    subprocess.run([str(FFMPEG),'-v','error','-f','lavfi','-i','color=c=red:s=160x90:r=10:d=4',
        '-f','lavfi','-i','sine=frequency=880:sample_rate=44100:duration=4',
        '-filter_complex','[0:v]setpts=PTS+gte(T\\,2)*3/TB[v];[1:a]asetpts=PTS+gte(T\\,2)*3/TB[a]',
        '-map','[v]','-map','[a]','-c:v','flv','-c:a','libmp3lame',str(source)],
        check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    def forbidden(*args,**kwargs):raise AssertionError('audio export must not build a video proxy')
    monkeypatch.setattr('twobyteasr.exports.timeline_media.resolve_audio_layers',forbidden)
    job=edited_job(tmp_path,[str(source)]*3)
    job.audio_graph['segments']=job.audio_graph['segments'][:1]
    job.audio_graph['segments'][0].update(source_in_ms=2500,source_out_ms=3500)
    job.duration_seconds=1
    output=run_audio_job(FFMPEG,job)
    sound=pcm(output)
    assert len(sound)==44100
    assert np.sqrt(np.mean(sound[4410:39690]**2))>.04
