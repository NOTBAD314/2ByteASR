"""Reuse verified static caption pixels across their full cue lifetime.

Only time-independent text graphs qualify. HTML, animation, decorations and
effect layers retain the full authored production renderer.
"""
from pathlib import Path
import re
import tempfile
import time
from .export_validation import record_completion, publish_output, notify_after_publication
from .export_failure import ExportFailure, ffmpeg_failure
from .static_caption_timeline import build_caption_timeline, caption_input, caption_filter
from ..rendering.caption_asset_identity import renderer_identity_scope


def _run_static_command(command, folder, runner, **kwargs):
    """Keep filters and all caption inputs out of the Windows command line.

    Called after the preview transport appends its output branch. All external
    file inputs remain absolute when the child's working directory changes.
    """
    folder = Path(folder).resolve()
    command = [str(value) for value in command]
    command[0] = str(Path(command[0]).resolve())
    from .ffmpeg_paths import filter_value
    sources, labels, removed = [], {}, set()
    input_count = 0
    kept_count = 0
    for index, option in enumerate(command[:-1]):
        if option == '-i':
            path = Path(command[index + 1]).resolve()
            if path.parent == folder and path.suffix.lower() == '.png':
                label = f'staticinput{input_count}'
                sources.append(f'movie=filename={filter_value(path.name)}:dec_threads=1[{label}]')
                labels[input_count] = label
                removed.update((index, index + 1))
            else:
                # concat resolves child URLs; an absolute list path containing
                # '#' can change its base URL. Owned inputs use a safe basename.
                command[index + 1] = path.name if path.parent == folder else str(path)
                labels[input_count] = str(kept_count)
                kept_count += 1
            input_count += 1
    command = [value for index, value in enumerate(command) if index not in removed]
    graph_at = command.index('-filter_complex')
    graph = folder / 'captions.ffgraph'
    def relabel(match):
        original = int(match[1])
        if original not in labels:
            return match[0]
        label = labels[original]
        return f'[{label}{match[2] or ""}]' if label.isdigit() else f'[{label}]'
    filters = re.sub(r'\[(\d+)(:[^\[\]]+)?\]', relabel, command[graph_at + 1])
    graph.write_text(';'.join([*sources, filters]), encoding='utf-8')
    command[graph_at:graph_at + 2] = ['-/filter_complex', graph.name]
    for index, option in enumerate(command[:-1]):
        if option == '-map':
            value = command[index + 1]
            match = re.fullmatch(r'(\d+)(:[^\[\]]+)?', value)
            if match and int(match[1]) in labels:
                mapped = relabel(match)
                command[index + 1] = mapped[1:-1] if labels[int(match[1])].isdigit() else mapped
    return runner(command, cwd=folder, **kwargs)


def static_graph_project(project, *, start_ms=None, end_ms=None):
    from ..rendering.advanced_renderer import split_renderer_cues
    from .static_caption_contract import shared_static_cue
    _, advanced=split_renderer_cues(project)
    hidden=project.hidden_speaker_ids()
    advanced=[c for c in advanced if c.speaker_id not in hidden
              and (start_ms is None or c.end_ms>start_ms) and (end_ms is None or c.start_ms<end_ms)]
    if not advanced: return False
    for cue in advanced:
        if not shared_static_cue(project,cue):return False
    return True


@record_completion
@renderer_identity_scope
def render_static_graph(project, ffmpeg, job, *, progress=None, cancelled=None, trace=None):
    from ..caption_style.bilingual_layout import materialize_display_project
    project = materialize_display_project(project)
    from ..rendering.advanced_renderer import split_renderer_cues, _run_streaming_process, _ffmpeg_filter_path, _native_segment_project
    from ..rendering.ass_compiler import compile_ass
    from .studio_render import select_encoder, _quality_arguments, encoder_preset, export_progress, STAGE_ADVANCED_RENDER, STAGE_ENCODE, STAGE_MUX, STAGE_VALIDATE
    from .export_validation import validate_output, output_validation_options
    output=Path(job.output_path).resolve()
    if output.exists() and not job.overwrite_existing:raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter();timings={};start=float(job.start_seconds or 0)
    duration=float(job.duration_seconds or project.media.duration_ms/1000-start)
    canvas=(job.export_context or {}).get('caption_canvas') or getattr(project,'_output_canvas',{})
    output_size=canvas.get('output') or (0,0)
    width=int(job.settings.width or output_size[0] or project.media.width or project.render_settings.get('play_res_x') or 1920)
    height=int(job.settings.height or output_size[1] or project.media.height or project.render_settings.get('play_res_y') or 1080)
    fps=job.settings.fps or getattr(project.media,'fps',0) or 30
    with tempfile.TemporaryDirectory(prefix='.static-captions-',dir=output.parent) as folder:
        temp=Path(folder);partial=temp/('output'+output.suffix)
        # The Qt still path needs one canonical snapshot per cue, not the
        # normalized browser payload followed by a second identical snapshot.
        _, advanced = split_renderer_cues(project)
        hidden = project.hidden_speaker_ids()
        origin_ms, end_ms = round(start*1000), round((start+duration)*1000)
        props = dict(cues=[dict(id=c.id, startMs=max(0, c.start_ms-origin_ms),
                               endMs=min(round(duration*1000), c.end_ms-origin_ms))
                           for c in advanced if c.speaker_id not in hidden
                           and c.end_ms>origin_ms and c.start_ms<end_ms])
        from ..caption_style.visual_snapshot import build_visual_cue_snapshot
        from ..rendering.advanced_live_renderer import render_live_snapshot
        layers=[]; raster_cache={}
        by_id={cue.id:cue for cue in project.cues}
        from .static_caption_preparation import StaticCaptionPreparation, retain_static_failure
        from .static_caption_contract import intentional_empty_reason
        from ..rendering.alpha_geometry import alpha_metrics
        from ..subtitle_rules.current_issues import digest
        from PySide6.QtCore import QRect
        invisible_count=0;persistent_hits=0;rasterized=0
        def raster_progress(payload):
            data=dict(payload)
            if data.get('percent') is not None:data['percent']=float(data['percent'])*.7
            if progress:progress(data)
        with StaticCaptionPreparation(len(props['cues']),raster_progress if progress else None,trace,identity=dict(
                job_id=(job.export_context or {}).get('job_id'),project_id=project.project_id,
                project_revision=(job.export_context or {}).get('project_revision'))) as preparation:
            for i,cue in enumerate(props['cues']):
                if cancelled and cancelled():raise InterruptedError('render cancelled')
                preparation.task(i,cue['id'])
                snapshot=None
                detail=dict(task_index=i,cue_id=cue['id'],output=[width,height],dpr=1,
                            stable_cue_id=cue['id'].removesuffix('#tr'),
                            layer='translation' if cue['id'].endswith('#tr') else 'original',
                            start_ms=cue['startMs'],end_ms=cue['endMs'],renderer='render_static_graph/qt-static',
                            requested_size=[job.settings.width,job.settings.height],
                            media_size=[project.media.width,project.media.height])
                try:
                    snapshot=build_visual_cue_snapshot(project,cue['id'],width=width,height=height,fps=fps,resolved_cue=by_id[cue['id']])
                    from ..rendering.static_export_cache import cache_key,restore,store
                    persistent_key=cache_key(snapshot,width,height)
                    key=persistent_key or snapshot.pixel_hash(renderer_version='qt-static-v1',resolution=(width,height),device_pixel_ratio=1.)
                    detail.update(snapshot_hash=snapshot.stable_hash(),cache_identity=key,
                        text_length=len(snapshot.text),text_digest=digest(snapshot.text),
                        display_summary=dict(length=len(snapshot.text),digest=digest(snapshot.text)),
                        font_family=snapshot.font_family,font_size=snapshot.font_size,
                        font_weight=snapshot.font_weight,italic=snapshot.italic,
                        resolved_style_hash=getattr(snapshot.resolved_caption,'style_hash',None),
                        playres=[snapshot.playres_x,snapshot.playres_y],position=[snapshot.position_x,snapshot.position_y],
                        scale=[snapshot.scale_x,snapshot.scale_y],rotation=snapshot.rotation,
                        sample='time_independent',appearance_generation=snapshot.appearance_generation)
                    import json
                    detail['resolved_font']=json.loads(getattr(snapshot.resolved_caption,'font_face_json','{}'))
                    layout=json.loads(getattr(snapshot.resolved_caption,'layout_json','{}'))
                    detail['layout']={name:value for name,value in layout.items() if name in
                                      {'line_widths','line_heights','line_ascents','ink_bounds','max_width'}}
                    cached=raster_cache.get(key)
                    reused=cached is not None
                    if cached is None:
                        cached=restore(persistent_key,temp/f'caption-{i}.png',width,height)
                        reused=cached is not None
                        if reused:persistent_hits+=1
                        if reused and trace:trace('static_caption_asset_cache',dict(cue_id=cue['id'],hit=True))
                    if cached is None:
                        preparation.step('raster')
                        rasterized+=1
                        geometry={}
                        image=render_live_snapshot(snapshot,width=width,height=height,diagnostics=geometry)
                        detail['raster_geometry']=geometry
                        preparation.step('alpha')
                        bounds,nonzero=alpha_metrics(image)
                        detail.update(image_mode=str(image.format()),image_size=[image.width(),image.height()],
                                      alpha_nonzero=nonzero,alpha_bounds=bounds)
                        empty_reason=intentional_empty_reason(snapshot) if bounds is None else None
                        if bounds is None:
                            detail['reason_code']=empty_reason or 'unexpected_empty_raster'
                            if trace:trace('static_caption_empty',detail)
                            from ..diagnostics.event_log import emit
                            emit('video.export.caption_pixels',level='INFO' if empty_reason else 'ERROR',
                                 result='intentionally_invisible' if empty_reason else 'failed',**detail)
                            if not empty_reason:
                                detail['first_empty_stage']=('glyph_layout' if geometry.get('glyph_path_empty') else
                                    'transform_or_clip' if geometry.get('glyph_intersects_canvas') is False else 'paint_or_composite')
                                raise RuntimeError(f"静态字幕 {i}（ID {cue['id']}）的生产像素为空；"
                                                   f"原因 unexpected_empty_raster，画布 {width}×{height}。")
                            cached=(None,None,empty_reason)
                        else:
                            preparation.step('save')
                            path=temp/f'caption-{i}.png'
                            # Crop once in memory, preserving canonical full-canvas
                            # coordinates. Avoid writing and decoding a full PNG
                            # for every cue before discovering the first failure.
                            if not image.copy(QRect(*bounds)).save(str(path)):
                                raise OSError('Cannot write static caption raster')
                            x,y,w,h=bounds
                            cached=(path,(x,y,x+w,y+h),None)
                            store(persistent_key,path,cached[1],width,height)
                        raster_cache[key]=cached
                    if cancelled and cancelled():raise InterruptedError('render cancelled')
                    path,box,empty_reason=cached
                    if empty_reason:
                        invisible_count+=1
                        if reused and trace:trace('static_caption_empty',dict(detail,reason_code=empty_reason))
                    else:
                        layers.append(dict(path=path,bounds=box,start=max(0,cue['startMs']/1000),
                                           end=min(duration,cue['endMs']/1000),raster_detail=detail))
                    preparation.done(reused=reused)
                except InterruptedError:
                    raise
                except Exception as exc:
                    preparation.failed+=1
                    detail.update(failed_step=preparation.stage,task_elapsed_ms=(time.perf_counter()-preparation.task_started)*1000)
                    preparation.step('failed');preparation.report(force=True)
                    try:
                        folder=retain_static_failure(project,props,job,i,snapshot,detail,exc)
                        if trace:trace('static_caption_failure_artifact',dict(detail,local_artifact=str(folder)))
                    except Exception as artifact_error:
                        if trace:trace('static_caption_evidence_failed',dict(task_index=i,error_type=type(artifact_error).__name__))
                    raise ExportFailure(str(exc),stage=STAGE_ADVANCED_RENDER,
                        category='output_io' if isinstance(exc,OSError) else 'subtitle_render',
                        cue_id=cue['id'],cue_index=i,cue_time_ms=cue['startMs']) from exc
        timings['subtitle_stills']=time.perf_counter()-started
        from ..rendering.advanced_renderer import _trim_overlay_cache
        _trim_overlay_cache()
        job.completion_metadata['caption_assets']=dict(static=dict(total=len(props['cues']),
            rendered=rasterized,hits=persistent_hits))
        filters=[];inputs=[];native_filter=None
        native=_native_segment_project(project,round(start*1000),round((start+duration)*1000))
        base='[staticfps]'
        filters.append(f'[0:v]fps={fps:.12g}:round=near:start_time=0[staticfps]')
        # The source was proved identical by prepared_video_job; non-identity
        # graphs arrive as the existing composition at the requested range.
        filters.append(f'{base}scale={width}:{height}[scaled]');base='[scaled]'
        if native.cues:
            ass=temp/'native.ass';ass.write_text(compile_ass(native),encoding='utf-8-sig')
            fonts = Path(__file__).resolve().parents[2]/'assets/fonts'
            native_filter=f'ass=filename={_ffmpeg_filter_path(ass)}:fontsdir={_ffmpeg_filter_path(fonts)}'
            filters.append(f'{base}{native_filter}[native]');base='[native]'
        total_png=sum(path.stat().st_size for path in {layer['path'] for layer in layers})
        schedule_start=time.perf_counter()
        if progress:progress(export_progress(STAGE_ADVANCED_RENDER,message='合成静态字幕变化场景…',percent=70))
        def scheduled(done,total):
            if progress:progress(export_progress(STAGE_ADVANCED_RENDER,
                message=f'合成字幕场景 {done}/{total}…',percent=70+30*done/total))
        sparse=build_caption_timeline(layers,temp,fps=fps,duration=duration,cancelled=cancelled,progress=scheduled)
        if progress:progress(export_progress(STAGE_ADVANCED_RENDER,message='静态字幕准备完成',percent=100))
        timings.update(caption_schedule=time.perf_counter()-schedule_start,
                       sparse_scenes=sparse['scenes'],caption_cache_peak_bytes=sparse['cache_peak_bytes'],
                       source_captions=len(layers))
        layers=[sparse]
        box=sparse['bounds']
        inputs=caption_input(sparse)
        pre,label=caption_filter(sparse,'[1:v]',fps)
        if pre:filters.append(pre.rstrip(';'))
        from .caption_composite_region import append_region_overlay
        base=append_region_overlay(filters,base,label,bounds=box,width=width,height=height,
            pixel_format=job.settings.pixel_format,tag='captioned')
        encoder=select_encoder(ffmpeg,job.settings)
        command=[str(ffmpeg),'-hide_banner','-loglevel','level+info','-xerror','-y','-benchmark','-filter_complex_threads','2']
        if job.direct_video_graph:
            from dataclasses import replace
            from .export_filtergraph import compile_video_filtergraph
            effective=replace(job,settings=replace(job.settings,width=width,height=height))
            command+=compile_video_filtergraph(ffmpeg,effective,'null',caption_overlays=layers,caption_filter=native_filter)
        else:
            if start>0 and not job.composition_resolved:command+=['-ss',f'{start:.9f}']
            from .studio_render import video_input_acceleration
            command += [*video_input_acceleration(job), '-i',job.media_path,*inputs,'-t',f'{duration:.9f}','-filter_complex',';'.join(filters),'-map',base,'-map','0:a?']
        command+=['-c:v',encoder,*_quality_arguments(encoder,job.settings),'-pix_fmt',job.settings.pixel_format,'-r',f'{fps:.12g}']
        preset=encoder_preset(encoder,job.settings.preset)
        if preset:command+=['-preset',preset]
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
        if job.composition_resolved:
            from .video_export import composed_video_frame_count
            frames=composed_video_frame_count(job)
            if frames is not None:command+=['-frames:v',str(frames)]
        if job.settings.container in {'mp4','mov'}:command+=['-movflags','+faststart']
        command+=['-progress','pipe:1','-nostats',str(partial)]
        if trace:trace('static_caption_command',command)
        if progress:progress(export_progress(STAGE_ENCODE,message='连续合成字幕与视频并编码…',duration_seconds=duration))
        current={}
        def line(value):
            key,separator,val=value.partition('=')
            if separator:current[key]=val
            if key=='progress':
                if progress:
                    progress(export_progress(STAGE_ENCODE,message='连续合成字幕与视频并编码…',
                        out_time_us=current.get('out_time_us'),frame=current.get('frame',''),
                        fps=current.get('fps',''),speed=current.get('speed',''),
                        video_time_seconds=int(current.get('frame') or 0)/fps,duration_seconds=duration))
                current.clear()
        from .export_preview import run_streaming_with_preview
        encode_start=time.perf_counter()
        def run_static(command, **kwargs):
            return _run_static_command(command, temp, _run_streaming_process, **kwargs)
        code,log=run_streaming_with_preview(command,job,run_static,on_line=line,cancelled=cancelled,
            warning=(lambda text:progress({'notice':text})) if progress else None)
        timings['encode']=time.perf_counter()-encode_start
        if code:raise ffmpeg_failure(code,log,encoder=encoder,fps=fps)
        if progress:progress(export_progress('validate',message='检查成片…'))
        validate_start=time.perf_counter();metadata=validate_output(ffmpeg,partial,duration=duration,fps=fps,cancelled=cancelled,preview_path=job.completion_preview_path, **output_validation_options(job))
        timings['validate']=time.perf_counter()-validate_start
        publish_output(partial, output, job, metadata, cancelled=cancelled)
        timings.update(wall=time.perf_counter()-started,static_images=len(layers),intentionally_invisible=invisible_count,temporary_png_bytes=total_png,encoder=encoder)
        from .export_run_log import note_export
        note_export('static_caption_timings', timings)
        notify_after_publication(job, trace, 'static_caption_timings', timings)
        notify_after_publication(job, trace, 'validated_output', metadata)
        notify_after_publication(job, progress, export_progress(STAGE_VALIDATE,message='导出完成',percent=100))
    return output
