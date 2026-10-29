"""Finite raster frames survive intermediate and final export time cutoffs."""
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from twobyteasr.exports.studio_render import RenderJob,RenderSettings
from twobyteasr.exports import video_export


class Sink:
    def __init__(self):self.frames=[]
    def write(self,data):self.frames.append(bytes(data));return len(data)
    def close(self):pass


class Encoder:
    def __init__(self,argv):self.argv=argv;self.stdin=Sink();self.returncode=None;Path(argv[-1]).write_bytes(b'fake-encoder-output')
    def poll(self):return self.returncode
    def wait(self,timeout=None):self.returncode=0;return 0
    def kill(self):self.returncode=-9


def job_at(tmp_path,duration=2.117,fps=60,start=0,audio='none'):
    media=tmp_path/'source.mkv';media.touch();ass=tmp_path/'source.ass';ass.touch()
    graph=dict(width=4,height=2,fps=fps,duration_ms=10000,media_pool=[],video_tracks=[dict(id='V1',clips=[])])
    return RenderJob(str(media),str(ass),str(tmp_path/'out.mp4'),
        RenderSettings(fps=fps,width=4,height=2,audio_codec=audio,encoder='libx264'),
        start_seconds=start,duration_seconds=duration,video_graph=graph,export_context={'owner':'unchanged'})


@pytest.mark.parametrize('duration,fps,count',[(2.117,60,128),(2.1,60,126),(.001,60,1),(2.117,59.94,127)])
def test_actual_raster_loop_and_final_command_share_exact_finite_frames(tmp_path,monkeypatch,duration,fps,count):
    from twobyteasr.exports import studio_render
    job=job_at(tmp_path,duration,fps,start=4.25);commands=[]
    def encoder(argv,**kwargs):
        process=Encoder(argv);commands.append(process);return process
    monkeypatch.setattr(video_export,'popen_hidden_subprocess',encoder)
    monkeypatch.setattr(studio_render,'select_encoder',lambda *a:'libx264')
    with video_export.prepared_video_job(Path('ffmpeg.exe'),job) as prepared:
        process=commands[0]
        assert len(process.stdin.frames)==count
        assert all(len(frame)==4*2*4 for frame in process.stdin.frames)
        assert process.argv[process.argv.index('-frames:v')+1]==str(count)
        assert '-t' not in process.argv
        assert prepared.duration_seconds==float(Fraction(count)/Fraction(str(fps)))
        assert prepared.start_seconds==4.25 and prepared.composition_resolved
        assert prepared.export_context['owner']=='unchanged'
        clock=prepared.export_context['composed_video_frame_clock']
        assert clock['requested_duration_seconds']==duration
        assert clock['frame_range']==[0,count]
        assert Fraction(clock['last_sample_pts'])==Fraction(17,4)+Fraction(count-1)/Fraction(str(fps))
        command=studio_render.build_render_command(Path('ffmpeg.exe'),prepared)
        assert command[command.index('-frames:v')+1]==str(count)
        assert float(command[command.index('-t')+1])>float(Fraction(count-1)/Fraction(str(fps)))
        # Original ASS remains at project time; resolved media is not seeked twice.
        assert '-ss' not in command
    receipt=json.loads(Path(job.output_path).with_suffix('.composition-frame-clock.json').read_text('utf8'))
    assert receipt['status']=='raster_encoded' and receipt['written_frames']==count
    assert job.duration_seconds==duration and job.export_context=={'owner':'unchanged'}


def test_noncomposed_command_keeps_original_request_and_no_frame_cap(tmp_path,monkeypatch):
    from twobyteasr.exports import studio_render
    job=replace(job_at(tmp_path),video_graph=None,export_context={'composed_video_frame_clock':{'frame_count':9}})
    monkeypatch.setattr(studio_render,'select_encoder',lambda *a:'libx264')
    with video_export.prepared_video_job(Path('ffmpeg.exe'),job) as prepared:
        command=studio_render.build_render_command(Path('ffmpeg.exe'),prepared)
    assert command[command.index('-t')+1]=='2.117' and '-frames:v' not in command
    assert not prepared.composition_resolved and prepared.duration_seconds==2.117


def test_resolved_clock_mismatch_is_rejected_not_silently_recapped(tmp_path):
    job=replace(job_at(tmp_path),composition_resolved=True,
        export_context={'composed_video_frame_clock':{'frame_count':127}})
    with pytest.raises(ValueError,match='frame count does not match'):
        video_export.composed_video_frame_count(job)


@pytest.mark.parametrize('slices',[(),((0.,1.),(2.,4.))])
def test_compatibility_audio_is_trimmed_to_request_not_quantized_video_end(tmp_path,monkeypatch,slices):
    from twobyteasr.exports import studio_render
    job=replace(job_at(tmp_path,audio='aac'),edit_segments=slices)
    monkeypatch.setattr(studio_render,'media_has_audio',lambda *a:True)
    args=video_export._audio_arguments(Path('ffmpeg.exe'),job)
    if slices:
        filters=args[args.index('-filter_complex')+1]
        assert '[joined]atrim=duration=2.117000[audio]' in filters
        assert 'atempo' not in filters and '2.133333' not in filters
    else:
        assert args.index('-t')<args.index('-i')
        assert args[args.index('-t')+1]=='2.117000'


def test_formal_audio_mix_keeps_requested_clock_before_preparing_video(tmp_path,monkeypatch):
    from twobyteasr.exports import studio_render, audio_export
    job=job_at(tmp_path,audio='aac');job.video_graph['audio_mix']=[dict(source_path=job.media_path,timeline_in_ms=0,
        timeline_out_ms=10000,source_in_ms=0,playback_rate=1.,stream_index=0,gain_db=0.,audio_envelopes=[])]
    monkeypatch.setattr(studio_render,'media_has_audio',lambda *a:True)
    args=video_export._audio_arguments(Path('ffmpeg.exe'),job)
    filters=args[args.index('-filter_complex')+1]
    assert filters.endswith('atrim=duration=2.117000[audio]') and '2.133333' not in filters


def test_static_graph_final_route_keeps_composed_frame_cap(tmp_path,monkeypatch):
    from twobyteasr.exports import studio_render, static_caption_export, export_validation, export_preview
    from twobyteasr.rendering import advanced_renderer
    job=replace(job_at(tmp_path),video_graph=None,composition_resolved=True,duration_seconds=128/60,
        export_context={'composed_video_frame_clock':{'frame_count':128}})
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    project=SubtitleProject(media=StudioMedia(path=job.media_path,width=4,height=2,duration_ms=2117))
    monkeypatch.setattr(advanced_renderer,'compile_composition_data',lambda *a,**k:{'cues':[]})
    monkeypatch.setattr(advanced_renderer,'_native_segment_project',lambda *a:SimpleNamespace(cues=[]))
    monkeypatch.setattr(studio_render,'select_encoder',lambda *a:'libx264')
    monkeypatch.setattr(export_validation,'validate_output',lambda *a,**k:{})
    monkeypatch.setattr(static_caption_export,'publish_output',lambda *a,**k:None)
    monkeypatch.setattr(static_caption_export,'notify_after_publication',lambda *a,**k:None)
    commands=[]
    def run(command,*args,**kwargs):commands.append(command);return 0,''
    monkeypatch.setattr(export_preview,'run_streaming_with_preview',run)
    static_caption_export.render_static_graph.__wrapped__(project,Path('ffmpeg.exe'),job)
    assert commands[0][commands[0].index('-frames:v')+1]=='128'
    assert float(commands[0][commands[0].index('-t')+1])>127/60
