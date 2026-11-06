"""Real FFmpeg regressions: sparse pixels, error propagation and safe publication."""
import json
from pathlib import Path
import sys

import av
import numpy as np
import pytest

from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
from twobyteasr.exports.static_caption_export import render_static_graph
from twobyteasr.exports.export_failure import ExportFailure, ErrorEvidence, ffmpeg_failure
from twobyteasr.system.processes import run_hidden_subprocess

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    instance=QApplication.instance() or QApplication([])
    identity=QFontDatabase.addApplicationFont(str(ROOT/'assets/fonts/SourceHanSansSC-Medium.otf'))
    assert QFontDatabase.applicationFontFamilies(identity)
    return instance


def fixture_project(tmp_path, count=8, duration=3, size=(320, 180), bilingual=False):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
    source = tmp_path / '中文 空格 source.mp4'
    if not source.exists():
        run_hidden_subprocess([str(FFMPEG), '-v','error','-y','-f','lavfi','-i',
            f'color=c=0x202020:s={size[0]}x{size[1]}:r=30:d={duration}',
            '-f','lavfi','-i',f'sine=frequency=440:sample_rate=48000:duration={duration}',
            '-c:v','libx264','-threads','2','-c:a','aac',str(source)],
            purpose='export reliability fixture',check=True,timeout=45)
    style=SubtitleStyle('g','Gradient',font_size=80,font_family='Source Han Sans SC',font_weight=500)
    project=SubtitleProject(media=StudioMedia(str(source),duration_ms=duration*1000,width=size[0],height=size[1]),
        styles=[style],cues=[StudioCue(str(i),round(i*duration*1000/count),round((i+1)*duration*1000/count),
            f'字幕 {i} Ａ😀',style_id='g',speaker_id='a' if i%2 else 'b') for i in range(count)])
    project.style_recipes['g']={'name':'Gradient','engine':'remotion','motion':{'mode':'none'},'colors':{
        'fill':{'type':'linear-gradient','angle':0,'stops':[
            {'position':0,'color':'#FFFF0000'},{'position':1,'color':'#FF00FFFF'}]}}}
    project.validate()
    return project


def job_for(project,tmp_path,encoder='libx264',audio='copy',**kw):
    return RenderJob(project.media.path,str(tmp_path/'sub.ass'),str(tmp_path/'中文 成品.mp4'),
        RenderSettings(encoder=encoder,preset='p4' if encoder.endswith('_nvenc') else 'ultrafast',
            quality_mode='cq',quality=18,width=project.media.width,height=project.media.height,
            fps=30,audio_codec=audio),duration_seconds=project.media.duration_ms/1000,**kw)


@pytest.mark.parametrize('encoder,audio', [('libx264','copy'),('libx264','aac'),('h264_nvenc','copy'),('h264_nvenc','aac')])
def test_static_real_encoder_audio_matrix(tmp_path,app,encoder,audio):
    project=fixture_project(tmp_path)
    job=job_for(project,tmp_path,encoder,audio)
    trace=[]
    render_static_graph(project,FFMPEG,job,trace=lambda k,v:trace.append((k,v)))
    frames=list(av.open(job.output_path).decode(video=0))
    assert len(frames)==90
    assert all(np.count_nonzero(f.to_ndarray(format='rgb24')[:,:,0]>100)>10 for f in frames)
    data=job.completion_metadata
    assert data['actual_encoder']==encoder
    assert abs(float(data['format']['duration'])-3)<.08
    assert any(s['codec_type']=='audio' for s in data['streams'])
    audio_stream=next(s for s in data['streams'] if s['codec_type']=='audio')
    assert abs(float(audio_stream['duration'])-float(data['streams'][0]['duration']))<.04
    with av.open(job.output_path) as media:
        decoded_audio=list(media.decode(audio=0))
    assert abs(sum(frame.samples for frame in decoded_audio)/48000-3)<.04
    if audio=='copy':
        import hashlib
        def packet_hash(path):
            result=hashlib.sha256()
            with av.open(str(path)) as container:
                for packet in container.demux(audio=0):
                    if packet.size:result.update(bytes(packet))
            return result.hexdigest()
        assert packet_hash(project.media.path)==packet_hash(job.output_path)
    assert not list(tmp_path.glob('.static-captions-*'))


def test_first_error_survives_many_progress_lines():
    evidence=ErrorEvidence()
    evidence.feed('stderr','[h264_nvenc] OpenEncodeSessionEx failed: out of memory')
    for i in range(1000):
        evidence.feed('stdout',f'frame={i}')
        evidence.feed('stderr','informational encoder line')
    evidence.feed('stderr','Conversion failed!')
    error=ffmpeg_failure(17,evidence.result(),encoder='h264_nvenc')
    assert 'OpenEncodeSessionEx' in str(error) and 'frame=' not in str(error)
    assert error.evidence['returncode']==17 and error.evidence['retry_cpu']


def test_real_ffmpeg_stderr_and_exit_are_retained(tmp_path):
    from twobyteasr.rendering.advanced_renderer import _run_streaming_process
    code,evidence=_run_streaming_process([str(FFMPEG),'-hide_banner','-i',str(tmp_path/'missing.mp4'),
        '-progress','pipe:1','-f','null','-'])
    error=ffmpeg_failure(code,evidence,encoder='libx264')
    assert code!=0 and error.evidence['first_errors']
    assert 'No such file' in str(evidence) or 'Error opening' in str(evidence)


def test_render_error_retains_original_traceback_and_output(tmp_path,app,monkeypatch):
    import twobyteasr.rendering.advanced_live_renderer as live
    project=fixture_project(tmp_path)
    job=job_for(project,tmp_path,overwrite_existing=True)
    Path(job.output_path).write_bytes(b'previous finished video')
    def broken(*args,**kwargs):
        raise ValueError('fixture glyph failure')
    monkeypatch.setattr(live,'render_live_snapshot',broken)
    # A verified persistent hit intentionally does not invoke the renderer.
    # Force this fault-injection case to exercise a cache miss.
    from twobyteasr.rendering import static_export_cache
    monkeypatch.setattr(static_export_cache,'restore',lambda *args:None)
    with pytest.raises(ExportFailure) as caught:
        render_static_graph(project,FFMPEG,job)
    assert caught.value.evidence['cue_id']=='0'
    manifest=json.loads((Path(job.export_context['diagnostics_path'])/'manifest.json').read_text('utf8'))
    assert 'fixture glyph failure' in manifest['failure']['traceback']
    assert manifest['failure']['category']=='subtitle_render'
    assert Path(job.output_path).read_bytes()==b'previous finished video'
    assert not list(tmp_path.glob('.static-captions-*'))


def test_sparse_rgba_matches_original_overlays_at_all_boundaries(tmp_path):
    from PIL import Image
    from twobyteasr.exports.static_caption_timeline import build_caption_timeline,caption_input,caption_filter
    layers=[]
    for index,(color,start,end,box) in enumerate([
            ((255,20,40,128),.033,.7,(10,12,34,30)),
            ((10,40,255,64),.05,.5,(20,16,42,38)),
            ((50,255,80,200),.8,1.,(10,12,34,30))]):
        path=tmp_path/f'layer{index}.png'
        Image.new('RGBA',(box[2]-box[0],box[3]-box[1]),color).save(path)
        layers.append(dict(path=path,bounds=box,start=start,end=end))
    sparse=build_caption_timeline(layers,tmp_path,fps=30,duration=1)
    results=[]
    for use_sparse in (False,True):
        command=[str(FFMPEG),'-v','error','-y','-filter_complex_threads','2','-f','lavfi','-i','color=c=0x202020:s=64x64:r=30:d=1']
        if use_sparse:
            command+=caption_input(sparse)
            pre,label=caption_filter(sparse,'[1:v]',30)
            graph=pre+f'[0:v]{label}overlay=x=10:y=12:format=auto[out]'
        else:
            graph='';base='[0:v]'
            for i,layer in enumerate(layers):
                command+=['-i',str(layer['path'])]
                x,y,*_=layer['bounds']
                graph+=f"{base}[{i+1}:v]overlay=x={x}:y={y}:format=auto:enable='gte(t,{layer['start']})*lt(t,{layer['end']})'[s{i}];"
                base=f'[s{i}]'
            graph=graph[:-1];label=base
        output=tmp_path/f'{use_sparse}.nut'
        command+=['-filter_complex',graph,'-map','[out]' if use_sparse else label,
            '-t','1','-c:v','rawvideo','-pix_fmt','rgb24','-threads','1',str(output)]
        run_hidden_subprocess(command,purpose='sparse overlay pixel comparison',check=True,timeout=20)
        results.append([f.to_ndarray(format='rgb24').astype(int) for f in av.open(str(output)).decode(video=0)])
    assert len(results[0])==len(results[1])==30
    differences=[np.abs(a-b).max() for a,b in zip(*results)]
    assert max(differences)<=2, differences


def test_mid_encode_exit_preserves_existing_output_and_logs(tmp_path,app,monkeypatch):
    import twobyteasr.rendering.advanced_renderer as renderer
    project=fixture_project(tmp_path,duration=32)
    job=job_for(project,tmp_path,overwrite_existing=True)
    Path(job.output_path).write_bytes(b'previous finished video')
    original=renderer.popen_hidden_subprocess
    children=[]
    def launch(command,**kw):
        # Pace a real FFmpeg child so the test can terminate it after it has
        # encoded frames, rather than simulating a return value.
        command=list(command);command[command.index('-i'):command.index('-i')]=['-re']
        child=original(command,**kw);children.append(child)
        return child
    monkeypatch.setattr(renderer,'popen_hidden_subprocess',launch)
    def progress(payload):
        if int(payload.get('out_time_us') or payload.get('out_time_ms') or 0)>1000000 and children:
            children[-1].terminate()
    with pytest.raises(ExportFailure) as caught:
        render_static_graph(project,FFMPEG,job,progress=progress)
    failure=caught.value.evidence
    assert failure['returncode']!=0 and int(failure['progress']['frame'])>0
    assert Path(job.output_path).read_bytes()==b'previous finished video'
    logs=Path(job.export_context['diagnostics_path'])
    assert list(logs.glob('*.stderr.log')) and list(logs.glob('*.stdout.log'))
    assert all(child.poll() is not None for child in children)
    assert not list(tmp_path.glob('.static-captions-*'))


def test_cancel_real_encoder_cleans_partial_and_can_retry(tmp_path,app):
    project=fixture_project(tmp_path,duration=4)
    job=job_for(project,tmp_path)
    cancel=[False]
    def progress(payload):
        if int(payload.get('out_time_us') or payload.get('out_time_ms') or 0)>0:cancel[0]=True
    with pytest.raises(InterruptedError):
        render_static_graph(project,FFMPEG,job,progress=progress,cancelled=lambda:cancel[0])
    assert not Path(job.output_path).exists() and not list(tmp_path.glob('.static-captions-*'))
    render_static_graph(project,FFMPEG,job)
    assert Path(job.output_path).is_file() and 'failure' not in job.export_context


def test_publication_disk_error_preserves_existing_video(tmp_path,app,monkeypatch):
    from twobyteasr.exports import export_validation
    project=fixture_project(tmp_path)
    job=job_for(project,tmp_path,overwrite_existing=True)
    Path(job.output_path).write_bytes(b'previous finished video')
    replace=export_validation.os.replace
    def disk_error(source,destination):
        if Path(destination)==Path(job.output_path):
            raise OSError(28,'No space left on device (injected publication failure)')
        return replace(source,destination)
    monkeypatch.setattr(export_validation.os,'replace',disk_error)
    with pytest.raises(OSError,match='No space left'):
        render_static_graph(project,FFMPEG,job)
    assert Path(job.output_path).read_bytes()==b'previous finished video'
    assert job.export_context['failure']['stage']=='publish'
    assert job.export_context['failure']['progress'].get('out_time_ms')
    assert not list(tmp_path.glob('.static-captions-*'))


def test_real_ffmpeg_write_failure_is_not_successful_mux(tmp_path):
    import socket
    import threading
    from twobyteasr.rendering.advanced_renderer import _run_streaming_process
    server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(15)
    received=[]
    def disconnect():
        with server:
            connection,_=server.accept()
            with connection:
                size=0
                while size<16384:
                    data=connection.recv(4096)
                    if not data:break
                    size+=len(data)
                received.append(size)
                connection.shutdown(socket.SHUT_RDWR)
    thread=threading.Thread(target=disconnect,daemon=True);thread.start()
    code,evidence=_run_streaming_process([str(FFMPEG),'-v','error','-f','lavfi','-i',
        'testsrc2=s=320x180:r=30:d=32','-c:v','libx264','-preset','ultrafast','-threads','2','-g','15',
        '-movflags','frag_keyframe+empty_moov','-progress','pipe:1','-f','mp4',
        f'tcp://127.0.0.1:{server.getsockname()[1]}'])
    thread.join(3)
    assert received[0]>=16384 and code!=0
    assert int(evidence.progress['frame'])>0
    assert evidence.progress['progress']=='end'  # A failed FFmpeg run can still emit end.
    failure=ffmpeg_failure(code,evidence,encoder='libx264')
    assert failure.evidence['stage']=='encode'
    assert failure.evidence['first_errors'] and 'frame=' not in failure.evidence['reason']


def test_nvenc_and_audio_compatibility_failure_do_not_auto_change_settings(tmp_path,app,monkeypatch):
    from copy import deepcopy
    import twobyteasr.exports.studio_render as render
    from twobyteasr.rendering.ass_compiler import compile_ass
    project=fixture_project(tmp_path)
    job=job_for(project,tmp_path,encoder='h264_nvenc')
    Path(job.ass_path).write_text(compile_ass(project),encoding='utf8')
    before=deepcopy(vars(job.settings));attempts=[]
    # This test checks retry policy only; the tests above exercise real NVENC,
    # libx264, AAC, copy, broken pipes and process termination.
    def fail(*args,**kwargs):
        attempts.append(True)
        raise ExportFailure('NvEncEncodePicture failed',stage='encode',category='nvenc',retry_cpu=True)
    monkeypatch.setattr(render,'_run_render_attempt',fail)
    with pytest.raises(ExportFailure):render.run_render_job(FFMPEG,job)
    assert attempts==[True] and vars(job.settings)==before


def test_real_incompatible_audio_copy_has_explicit_aac_recovery(tmp_path,app):
    from dataclasses import replace
    project=fixture_project(tmp_path)
    source=tmp_path/'WMA source.mkv'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-i',project.media.path,
        '-c:v','copy','-c:a','wmav2',str(source)],purpose='incompatible audio fixture',check=True,timeout=15)
    project.media.path=str(source)
    job=job_for(project,tmp_path)
    with pytest.raises(ExportFailure) as caught:render_static_graph(project,FFMPEG,job)
    assert caught.value.evidence['category']=='audio_mux'
    assert caught.value.evidence['returncode']!=0
    assert job.settings.audio_codec=='copy' and not Path(job.output_path).exists()
    explicitly_changed=replace(job,settings=replace(job.settings,audio_codec='aac'))
    render_static_graph(project,FFMPEG,explicitly_changed)
    assert len(list(av.open(job.output_path).decode(video=0)))==90


def test_source_rate_conversion_samples_caption_on_output_frame_grid(tmp_path,app):
    project=fixture_project(tmp_path,duration=1,count=1)
    source=tmp_path/'24 fps.mp4'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-f','lavfi','-i','color=c=0x202020:s=320x180:r=24:d=1',
        '-c:v','libx264','-threads','2',str(source)],purpose='24 fps timing fixture',check=True,timeout=15)
    project.media.path=str(source)
    project.cues[0].start_ms=40;project.cues[0].end_ms=80
    job=job_for(project,tmp_path,audio='none')
    render_static_graph(project,FFMPEG,job)
    frames=list(av.open(job.output_path).decode(video=0))
    painted=[i for i,f in enumerate(frames) if np.count_nonzero(f.to_ndarray(format='rgb24')[:,:,0]>100)>10]
    assert painted==[2],painted


def test_video_position_does_not_use_processing_fps():
    from twobyteasr.exports.export_failure import ProcessEvidence
    evidence=ProcessEvidence('Error writing output',errors=['Error writing output'],
        progress={'frame':'768','fps':'8.23','out_time_us':'26500000'})
    error=ffmpeg_failure(1,evidence,encoder='h264_nvenc',fps=30)
    assert error.evidence['video_time_seconds']==25.6
    assert error.evidence['progress']['out_time_us']=='26500000'


def test_short_encoded_file_fails_validation_with_last_media_position(tmp_path,app,monkeypatch):
    import twobyteasr.rendering.advanced_renderer as renderer
    project=fixture_project(tmp_path)
    job=job_for(project,tmp_path,overwrite_existing=True)
    Path(job.output_path).write_bytes(b'previous finished video')
    original=renderer._run_streaming_process
    def truncated(command,**kwargs):
        command=list(command)
        command[command.index('-t')+1]='0.5'
        return original(command,**kwargs)
    monkeypatch.setattr(renderer,'_run_streaming_process',truncated)
    with pytest.raises(RuntimeError,match='时长与工程范围不一致'):
        render_static_graph(project,FFMPEG,job)
    failure=job.export_context['failure']
    assert failure['stage']=='validate' and int(failure['progress']['frame'])>0
    assert Path(job.output_path).read_bytes()==b'previous finished video'
    assert not list(tmp_path.glob('.static-captions-*'))


def test_informational_filename_cannot_become_fatal_error():
    evidence=ErrorEvidence()
    evidence.feed('stderr',"[info] Input #0 from 'error-invalid-file.mp4':")
    evidence.feed('stderr','[warning] decoder recovered invalid timestamp')
    evidence.feed('stderr','[error] Error writing output: No space left on device')
    evidence.feed('stderr','[error] Conversion failed!')
    error=ffmpeg_failure(1,evidence.result(),encoder='h264_nvenc')
    assert error.evidence['category']=='output_io'
    assert error.evidence['reason']=='[error] Error writing output: No space left on device'


def test_preview_callback_failure_after_26_seconds_does_not_abort_export(tmp_path,app):
    from dataclasses import replace
    import time
    project=fixture_project(tmp_path,duration=40)
    deadline=[None];received=[];progress=[]
    def preview(image,milliseconds,phase):
        received.append(milliseconds)
        if milliseconds>=26500:
            deadline[0]=time.monotonic()+8
            raise RuntimeError('fixture preview callback failed after 26.5s')
    job=replace(job_for(project,tmp_path,encoder='h264_nvenc'),preview_callback=preview)
    render_static_graph(project,FFMPEG,job,progress=progress.append,
        cancelled=lambda:deadline[0] is not None and time.monotonic()>deadline[0])
    frames=list(av.open(job.output_path).decode(video=0))
    assert len(frames)==1200 and max(received)>=26500
    assert any('预览' in str(p.get('notice','')) for p in progress)
    assert any(w['observer']=='export_preview' for w in job.completion_metadata['completion_warnings'])


def test_preview_decoder_failure_after_26_seconds_drains_stream(tmp_path,app,monkeypatch):
    from dataclasses import replace
    import time
    project=fixture_project(tmp_path,duration=40)
    deadline=[None];progress=[];received=[]
    original_open=av.open
    class DecoderFailure:
        def __init__(self,inner):self.inner=inner
        def __enter__(self):self.inner.__enter__();return self
        def __exit__(self,*args):return self.inner.__exit__(*args)
        def decode(self,*args,**kwargs):
            for frame in self.inner.decode(*args,**kwargs):
                if float(frame.pts*frame.time_base)>=26.5:
                    deadline[0]=time.monotonic()+8
                    raise ValueError('fixture preview decoder failed after 26.5s')
                yield frame
    def preview_open(*args,**kwargs):
        result=original_open(*args,**kwargs)
        return DecoderFailure(result) if kwargs.get('format')=='nut' else result
    monkeypatch.setattr(av,'open',preview_open)
    job=replace(job_for(project,tmp_path,encoder='h264_nvenc'),preview_callback=lambda image,ms,phase:received.append(ms))
    render_static_graph(project,FFMPEG,job,progress=progress.append,
        cancelled=lambda:deadline[0] is not None and time.monotonic()>deadline[0])
    assert len(list(original_open(job.output_path).decode(video=0)))==1200
    assert received and any('预览' in str(p.get('notice','')) for p in progress)
    assert 'preview decoder failed' in job.export_context['preview_warning']['reason']


def test_native_export_preview_failure_is_nonfatal(tmp_path,app):
    from dataclasses import replace
    import time
    from twobyteasr.rendering.ass_compiler import compile_ass
    project=fixture_project(tmp_path,duration=40)
    project.style_recipes.clear()
    deadline=[None];progress=[]
    def preview(image,ms,phase):
        if ms>=26500:
            deadline[0]=time.monotonic()+8
            raise ValueError('native preview observer failed')
    job=replace(job_for(project,tmp_path,encoder='h264_nvenc'),preview_callback=preview)
    Path(job.ass_path).write_text(compile_ass(project),encoding='utf8')
    run_render_job(FFMPEG,job,progress=progress.append,
        cancelled=lambda:deadline[0] is not None and time.monotonic()>deadline[0])
    assert len(list(av.open(job.output_path).decode(video=0)))==1200
    assert job.export_context['preview_warning']['last_delivered_ms']>=26000
    assert any('预览' in str(p.get('notice','')) for p in progress)
