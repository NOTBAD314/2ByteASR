"""Opt-in real export/profile. All inputs, diagnostics and results stay in tmp/."""
import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import sys
import threading
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--encoder',default='h264_nvenc')
    parser.add_argument('--audio',default='copy')
    parser.add_argument('--count',type=int,default=1593)
    parser.add_argument('--duration',type=float,default=54)
    parser.add_argument('--width',type=int,default=1920)
    parser.add_argument('--height',type=int,default=1080)
    parser.add_argument('--bilingual',action='store_true')
    parser.add_argument('--no-captions',action='store_true')
    parser.add_argument('--simple',action='store_true')
    parser.add_argument('--animated',action='store_true')
    parser.add_argument('--glow',action='store_true')
    parser.add_argument('--complex',action='store_true')
    parser.add_argument('--overlap',action='store_true')
    parser.add_argument('--render-pages',type=int,default=0)
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    output=args.output.resolve()
    if not output.is_relative_to(root/'tmp'):
        raise ValueError('Evidence output must be under repository tmp/')
    output.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output/'isolated')
    os.environ['TWOBYTEASR_EXPORT_LOG_ROOT']=str(output/'logs')
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    sys.path.insert(0,str(args.source_root.resolve()))
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    import av
    import numpy as np
    import psutil
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,SubtitleStyle
    from twobyteasr.exports.studio_render import RenderJob,RenderSettings,run_render_job
    from twobyteasr.exports.static_caption_export import render_static_graph
    from twobyteasr.rendering.ass_compiler import compile_ass
    from twobyteasr.system.processes import run_hidden_subprocess
    if args.render_pages:
        import twobyteasr.rendering.advanced_renderer as renderer
        original_runner=renderer._run_streaming_process
        def controlled_pages(command,**kwargs):
            command=list(command)
            if 'render' in command and 'SubtitleOverlay' in command:
                command=[value for value in command if not str(value).startswith('--concurrency=')]
                command.append(f'--concurrency={args.render_pages}')
            return original_runner(command,**kwargs)
        renderer._run_streaming_process=controlled_pages
    app=QApplication.instance() or QApplication([])
    font_id=QFontDatabase.addApplicationFont(str(root/'assets/fonts/SourceHanSansSC-Medium.otf'))
    families=QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError('Bundled test font did not load')
    emoji=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/seguiemj.ttf'
    if emoji.exists():QFontDatabase.addApplicationFont(str(emoji))
    binary=root/'tools/ffmpeg/bin/ffmpeg.exe'
    source=output/'中文 空格源.mp4'
    if not source.exists():
        run_hidden_subprocess([binary,'-v','error','-y','-f','lavfi','-i',
            f'color=c=0x202020:s={args.width}x{args.height}:r=30:d={args.duration}',
            '-f','lavfi','-i',f'sine=frequency=440:sample_rate=48000:duration={args.duration}',
            '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac',source],
            purpose='export reliability fixture',check=True,timeout=90)
    project=SubtitleProject(media=StudioMedia(str(source),duration_ms=round(args.duration*1000),width=args.width,height=args.height),
        styles=[SubtitleStyle('g','Gradient',font_size=68,font_family=families[0],font_weight=500)],
        cues=[] if args.no_captions else [StudioCue(str(i),round(i*args.duration*1000/args.count),
            round((i+1)*args.duration*1000/args.count),f'字幕 {i:04d} 中文 Ａ 😀',style_id='g',
            speaker_id='S01' if i%2 else 'S02') for i in range(args.count)])
    if not args.simple:
        project.style_recipes['g']={'name':'Gradient','engine':'remotion','motion':{'mode':'none'},'colors':{
            'fill':{'type':'linear-gradient','angle':0,'stops':[
                {'position':0,'color':'#FFFF0000'},{'position':1,'color':'#FF00FFFF'}]}}}
    if args.bilingual:
        project.generation_metadata['translations']={c.id:f'Translation {i}' for i,c in enumerate(project.cues)}
        project.studio_state['bilingual']={'mode':'bilingual','layout':'ink_v1'}
    if args.animated:
        for cue in project.cues:cue.effect_id='fade-test'
        project.effects['fade-test']={'entry':{'type':'fade','duration':150},'exit':{'type':'fade','duration':150}}
    if args.complex:
        from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
        recipe=style_recipe_for_prompt('赛博朋克 Cyberpunk HUD 多层描边 glow glitch').to_dict()
        recipe.setdefault('typography',{}).update(fontFamily=families[0],fontSize=44)
        project.style_recipes['g']=recipe
    if args.glow:
        recipe=project.style_recipes['g']
        recipe.setdefault('effects',{}).update(glow=dict(enabled=True,color='#FF00D8FF',blur=38,opacity=.9),
            shadow=dict(enabled=True,color='#CC050510',offset_x=9,offset_y=12,blur=16,spread=2))
        recipe['outline']={'layers':[{'width':4,'color':'#FF101028'}, {'width':8,'color':'#FFF438B9'},
            {'width':12,'color':'#FF11DDEC'},{'width':16,'color':'#AA161634'}],
            'shadow':dict(enabled=True,color='#CC050510',offset_x=9,offset_y=12,blur=16,spread=2)}
    if args.overlap:
        import math
        from twobyteasr.projects.studio_project import StudioSpeaker
        project.speakers=[StudioSpeaker(f'S{i+1:02d}',f'压力轨道 {i+1}',style_id='g') for i in range(4)]
        interval=args.duration*1000/max(1,math.ceil(len(project.cues)/4))
        for i,cue in enumerate(project.cues):
            lane=i%4
            cue.speaker_id=f'S{lane+1:02d}'
            cue.start_ms=round((i//4)*interval)
            cue.end_ms=min(round(args.duration*1000),round((i//4+1.25)*interval))
            cue.transform={'position_x':480 if lane%2==0 else 1440,'position_y':600 if lane<2 else 920}
    if args.glow:
        # The application's canonical style owns the two supported strokes.
        # A raw recipe's extra stroke entries are not effective style values.
        authored=next(style for style in project.styles if style.id=='g')
        authored.outline_width=8;authored.outline_color='#FF101028'
        authored.outline2_width=16;authored.outline2_color='#FFFF00FF'
        project.style_recipes['g']['outline']['layers']=[
            {'width':8,'color':'#FF101028'},{'width':16,'color':'#FFFF00FF'}]
    project.validate()
    if args.glow:
        from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
        effective=build_visual_cue_snapshot(project,project.cues[0].id,width=args.width,height=args.height,fps=30)
        audit=dict(strokes=list(effective.strokes),glow=effective.glow,shadow=effective.shadow,
                   motion=effective.style_recipe.get('motion',{}))
        (output/'effective-style.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
        if len(effective.strokes)!=2 or not effective.glow.get('enabled'):
            raise AssertionError('Canonical double stroke/glow did not reach the renderer')
    (output/'fixture-project.json').write_text(json.dumps(project.to_dict(),ensure_ascii=False,indent=2),encoding='utf8')
    ass=output/'captions.ass';ass.write_text(compile_ass(project),encoding='utf8')
    settings=RenderSettings(encoder=args.encoder,preset='p4' if args.encoder.endswith('_nvenc') else 'ultrafast',
        quality_mode='cq',quality=18,width=args.width,height=args.height,fps=30,audio_codec=args.audio)
    job=RenderJob(str(source),str(ass),str(output/'中文 成品.mp4'),settings,duration_seconds=args.duration,
                  export_project_data=project.to_dict())
    preview_stats={'frames':0,'last_ms':None,'size':None}
    if args.preview:
        def receive_preview(image,milliseconds,phase):
            preview_stats.update(frames=preview_stats['frames']+1,last_ms=milliseconds,size=[image.width(),image.height()])
        from dataclasses import replace
        job=replace(job,preview_callback=receive_preview)
    stop=threading.Event();samples=[];seen_cpu={};gpu=[]
    parent=psutil.Process()
    def sample():
        last_gpu=0
        while not stop.wait(.2):
            processes=[parent,*parent.children(recursive=True)]
            row={'elapsed':time.perf_counter()-started,'rss':0,'ffmpeg_rss':0}
            for p in processes:
                try:
                    rss=p.memory_info().rss;row['rss']+=rss
                    cpu=p.cpu_times();seen_cpu[(p.pid,p.create_time())]=cpu.user+cpu.system
                    if p.name().lower().startswith('ffmpeg'):row['ffmpeg_rss']+=rss
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            samples.append(row)
            if time.perf_counter()-last_gpu>=1:
                last_gpu=time.perf_counter()
                try:
                    measured=run_hidden_subprocess(['nvidia-smi',
                        '--query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,memory.used',
                        '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,
                        purpose='isolated export GPU sampling')
                    gpu.append(dict(elapsed=time.perf_counter()-started,device_aggregate=measured.stdout.strip()))
                except (OSError,RuntimeError):pass
    trace=[];progress=[];started=time.perf_counter()
    monitor=threading.Thread(target=sample,daemon=True);monitor.start()
    profiler=cProfile.Profile();error=None
    try:
        profiler.enable()
        if args.simple or args.no_captions:
            run_render_job(binary,job,progress=progress.append,trace=lambda *x:trace.append(x))
        elif args.animated or args.complex:
            from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend
            AdvancedRendererBackend().render(project,binary,job,progress=progress.append,trace=lambda *x:trace.append(x))
        else:
            render_static_graph(project,binary,job,progress=progress.append,trace=lambda *x:trace.append(x))
    except BaseException as exc:
        import traceback
        error={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    finally:
        profiler.disable();wall=time.perf_counter()-started;stop.set();monitor.join(2)
    profiler.dump_stats(str(output/'profile.pstats'))
    with (output/'profile.txt').open('w',encoding='utf8') as stream:
        pstats.Stats(profiler,stream=stream).strip_dirs().sort_stats('cumulative').print_stats(30)
    result={'source_root':str(args.source_root.resolve()),'encoder':args.encoder,'audio':args.audio,
        'count':args.count,'preview':args.preview,'preview_stats':preview_stats,'render_pages':args.render_pages,'glow':args.glow,'complex':args.complex,'overlap':args.overlap,'font_family':families[0],'bilingual':args.bilingual,'duration':args.duration,'size':[args.width,args.height],
        'wall_seconds':wall,'export_fps':args.duration*30/wall,'error':error,
        'peak_tree_rss':max((s['rss'] for s in samples),default=0),
        'peak_ffmpeg_rss':max((s['ffmpeg_rss'] for s in samples),default=0),
        'cpu_seconds_observed':sum(seen_cpu.values()),'cpu_scope':'parent and child lifetimes, sampled; includes setup',
        'gpu_scope':'device aggregate, may include unrelated applications','gpu_samples':gpu,
        'timings':next((v for k,v in trace if k in ('static_caption_timings','advanced_timings')),{}),
        'diagnostics':job.export_context.get('diagnostics_path'),'receipt':job.completion_metadata}
    (output/'resources.json').write_text(json.dumps(samples,indent=2),encoding='utf8')
    (output/'trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf8')
    if error is None:
        container=av.open(job.output_path);count=0;painted=0;selection={0,795,round(args.duration*30)-1}
        for frame in container.decode(video=0):
            pixels=frame.to_ndarray(format='rgb24')
            if args.animated or args.complex:
                r,g,b=(pixels[:,:,i].astype(np.int16) for i in range(3))
                visible=(np.abs(r-g)>8)|(np.abs(r-b)>8)|(np.abs(g-b)>8)
            else:
                visible=pixels[:,:,0]>100
            if np.count_nonzero(visible)>10:painted+=1
            if count in selection:frame.to_image().save(output/f'frame-{count}.png')
            count+=1
        container.close()
        result.update(decoded_frames=count,painted_frames=painted)
        if count!=round(args.duration*30):raise AssertionError(f'Frame mismatch {count}')
        if not args.no_captions and not args.animated and not args.complex and painted<count-1:raise AssertionError(f'Missing caption frames: {painted}/{count}')
        if (args.animated or args.complex) and painted==0:raise AssertionError('No animated subtitle pixels')
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    summary={k:v for k,v in result.items() if k not in ('receipt','gpu_samples')}
    if error:summary['error']=dict(type=error['type'],message=error['message'][:250])
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 1 if error else 0


if __name__=='__main__':
    raise SystemExit(main())
