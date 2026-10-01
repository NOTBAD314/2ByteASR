"""Reuse verified static caption pixels across their full cue lifetime.

Only time-independent text graphs qualify. HTML, animation, decorations and
effect layers retain the full authored production renderer.
"""
from pathlib import Path
import tempfile
import time
from .export_validation import record_completion, publish_output, notify_after_publication


def static_graph_project(project):
    from .advanced_renderer import split_renderer_cues
    from .static_caption_contract import shared_static_cue
    _, advanced=split_renderer_cues(project)
    if not advanced: return False
    for cue in advanced:
        if not shared_static_cue(project,cue):return False
    return True


@record_completion
def render_static_graph(project, ffmpeg, job, *, progress=None, cancelled=None, trace=None):
    from PIL import Image
    from .advanced_renderer import compile_composition_data, _run_streaming_process, _ffmpeg_filter_path, _native_segment_project
    from .ass_compiler import compile_ass
    from .studio_render import select_encoder, _quality_arguments, export_progress, STAGE_ADVANCED_RENDER, STAGE_ENCODE, STAGE_MUX
    from .export_validation import validate_output
    output=Path(job.output_path).resolve()
    if output.exists() and not job.overwrite_existing:raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter();timings={};start=float(job.start_seconds or 0)
    duration=float(job.duration_seconds or project.media.duration_ms/1000-start)
    width=job.settings.width or project.media.width;height=job.settings.height or project.media.height
    fps=job.settings.fps or 30
    with tempfile.TemporaryDirectory(prefix='.static-captions-',dir=output.parent) as folder:
        temp=Path(folder);partial=temp/('output'+output.suffix)
        props=compile_composition_data(project,width=width,height=height,fps=fps,start_seconds=start,duration_seconds=duration)
        from .visual_snapshot import build_visual_cue_snapshot
        from .advanced_live_renderer import render_live_snapshot
        layers=[]; raster_cache={}
        if progress:progress(export_progress(STAGE_ADVANCED_RENDER,message=f'绘制 {len(props["cues"])} 张静态字幕并复用完整时段…'))
        for i,cue in enumerate(props['cues']):
            if cancelled and cancelled():raise InterruptedError('render cancelled')
            snapshot=build_visual_cue_snapshot(project,cue['id'],width=width,height=height,fps=fps)
            # This is the same canonical glyph-ink anchor as first-frame LIVE.
            # Browser line-box metrics and effect padding cannot move it later.
            key=snapshot.pixel_hash(renderer_version='qt-static-v1',resolution=(width,height),device_pixel_ratio=1.)
            path=raster_cache.get(key)
            if path is None:
                path=temp/f'caption-{i}.png'
                image=render_live_snapshot(snapshot,width=width,height=height)
                if not image.save(str(path)):raise RuntimeError('Cannot write static caption raster')
                raster_cache[key]=path
            layers.append(dict(path=path,start=max(0,cue['startMs']/1000),end=min(duration,cue['endMs']/1000)))
        timings['subtitle_stills']=time.perf_counter()-started
        filters=[];inputs=[];native_filter=None
        native=_native_segment_project(project,round(start*1000),round((start+duration)*1000))
        base='[0:v]'
        # The source was proved identical by prepared_video_job; non-identity
        # graphs arrive as the existing composition at the requested range.
        if job.settings.width and job.settings.height:filters.append(f'{base}scale={width}:{height}[scaled]');base='[scaled]'
        if native.cues:
            ass=temp/'native.ass';ass.write_text(compile_ass(native),encoding='utf-8-sig')
            fonts = Path(__file__).resolve().parents[1]/'assets/fonts'
            native_filter=f'ass=filename={_ffmpeg_filter_path(ass)}:fontsdir={_ffmpeg_filter_path(fonts)}'
            filters.append(f'{base}{native_filter}[native]');base='[native]'
        total_png=0; cropped_bounds={}
        for i,layer in enumerate(layers):
            box=cropped_bounds.get(layer['path'])
            if box is None:
                with Image.open(layer['path']) as im:
                    box=im.getchannel('A').getbbox()
                    if box is None:raise RuntimeError(f'静态字幕 {i} 的生产像素为空')
                    im.crop(box).save(layer['path'])
                cropped_bounds[layer['path']]=box
            total_png+=layer['path'].stat().st_size
            layer['bounds']=box
            inputs.extend(['-i',str(layer['path'])])
            filters.append(f"{base}[{i+1}:v]overlay=x={box[0]}:y={box[1]}:eof_action=repeat:format=auto:enable='gte(t,{layer['start']:.9f})*lt(t,{layer['end']:.9f})'[s{i}]")
            base=f'[s{i}]'
        encoder=select_encoder(ffmpeg,job.settings)
        command=[str(ffmpeg),'-hide_banner','-loglevel','warning','-y','-benchmark','-filter_complex_threads','2']
        if job.direct_video_graph:
            from .export_filtergraph import compile_video_filtergraph
            command+=compile_video_filtergraph(ffmpeg,job,'null',caption_overlays=layers,caption_filter=native_filter)
        else:
            if start>0 and not job.composition_resolved:command+=['-ss',f'{start:.9f}']
            command+=['-i',job.media_path,*inputs,'-t',f'{duration:.9f}','-filter_complex',';'.join(filters),'-map',base,'-map','0:a?']
        command+=['-c:v',encoder,*_quality_arguments(encoder,job.settings),'-pix_fmt',job.settings.pixel_format,'-r',f'{fps:.12g}']
        if job.settings.preset:command+=['-preset',job.settings.preset]
        if job.settings.profile:command+=['-profile:v',job.settings.profile]
        if job.settings.level:command+=['-level:v',job.settings.level]
        if job.settings.gop>0:command+=['-g',str(job.settings.gop)]
        if job.settings.b_frames>=0:command+=['-bf',str(job.settings.b_frames)]
        if job.settings.audio_codec=='none':command+=['-an']
        elif job.settings.audio_codec=='copy' and not job.direct_video_graph:command+=['-c:a','copy']
        else:
            command+=['-c:a','libopus' if job.settings.audio_codec=='opus' else 'aac','-b:a',f'{job.settings.audio_bitrate_kbps}k']
            if job.settings.audio_sample_rate:command+=['-ar',str(job.settings.audio_sample_rate)]
            if job.settings.audio_channels:command+=['-ac',str(job.settings.audio_channels)]
        if job.settings.container in {'mp4','mov'}:command+=['-movflags','+faststart']
        command+=['-progress','pipe:1','-nostats',str(partial)]
        if trace:trace('static_caption_command',command)
        if progress:progress(export_progress(STAGE_ENCODE,message='连续合成字幕与视频并编码…',duration_seconds=duration))
        def line(value):
            if progress and value.startswith('out_time_us='):
                progress(export_progress(STAGE_ENCODE,message='连续合成字幕与视频并编码…',out_time_us=value.split('=',1)[1],duration_seconds=duration))
        from .export_preview import run_streaming_with_preview
        encode_start=time.perf_counter()
        code,log=run_streaming_with_preview(command,job,_run_streaming_process,on_line=line,cancelled=cancelled)
        timings['encode']=time.perf_counter()-encode_start
        if code:raise RuntimeError('静态字幕编码失败：'+log[-3000:])
        if progress:progress(export_progress(STAGE_MUX,message='完整解码校验后发布成片…'))
        validate_start=time.perf_counter();metadata=validate_output(ffmpeg,partial,duration=duration,fps=fps,cancelled=cancelled,preview_path=job.completion_preview_path)
        timings['validate']=time.perf_counter()-validate_start
        publish_output(partial, output, job, metadata, cancelled=cancelled)
        timings.update(wall=time.perf_counter()-started,static_images=len(layers),temporary_png_bytes=total_png,encoder=encoder)
        notify_after_publication(job, trace, 'static_caption_timings', timings)
        notify_after_publication(job, trace, 'validated_output', metadata)
        notify_after_publication(job, progress, export_progress(STAGE_MUX,message='导出完成',percent=100))
    return output
