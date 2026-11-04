"""Explicit source/frozen real-encoding audit; no account/model calls."""
import json,os,sys,time,traceback
from pathlib import Path


def main(spec_path):
    spec=json.loads(Path(spec_path).read_text('utf8'));out=Path(spec['output']).resolve()
    if not out.is_relative_to((Path.cwd()/'tmp').resolve()):raise ValueError('Audit output must be in cwd/tmp')
    out.mkdir(parents=True,exist_ok=True)
    from ..test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    import av,numpy as np
    from ..projects.studio_project import SubtitleProject,StudioMedia,StudioCue,SubtitleStyle,StudioSpeaker
    from ..exports.studio_render import RenderJob,RenderSettings,run_render_job
    from ..exports.static_caption_export import render_static_graph
    from ..rendering.advanced_renderer import AdvancedRendererBackend
    from ..rendering.ass_compiler import compile_ass
    from ..system.processes import run_hidden_subprocess
    from ..exports import static_caption_export,export_preview,export_run_log
    root=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
    app=QApplication.instance() or QApplication([])
    face=QFontDatabase.addApplicationFont(str(root/'assets/fonts/SourceHanSansSC-Medium.otf'))
    families=QFontDatabase.applicationFontFamilies(face)
    if not families:raise ValueError('Bundled source font missing')
    emoji=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/seguiemj.ttf'
    if emoji.exists():QFontDatabase.addApplicationFont(str(emoji))
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    chrome=root/'renderer/node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'
    if chrome.exists():os.environ['TWOBYTEASR_RENDERER_CHROME']=str(chrome)
    report=dict(passed=False,frozen=bool(getattr(sys,'frozen',False)),executable=sys.executable,
        module_paths={m.__name__:m.__file__ for m in [static_caption_export,export_preview,export_run_log]},cases=[])
    if report['frozen']:
        report['build']=json.loads((root/'2byteasr_build.json').read_text('utf8'))
        assert all(Path(p).resolve().is_relative_to(root) for p in report['module_paths'].values())
    def write():(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    write()
    for case in spec['cases']:
        label=case['label'];folder=out/label;folder.mkdir(exist_ok=True)
        result=dict(label=label,passed=False);began=time.perf_counter()
        try:
            duration=case.get('duration',32);width=case.get('width',640);height=case.get('height',360);count=case.get('count',64)
            source=folder/'中文 空格源.mp4'
            run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i',f'color=c=0x202020:s={width}x{height}:r=30:d={duration}',
                '-f','lavfi','-i',f'sine=frequency=440:sample_rate=48000:duration={duration}',
                '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac',str(source)],purpose='frozen export fixture',check=True,timeout=90)
            project=SubtitleProject(media=StudioMedia(str(source),duration_ms=round(duration*1000),width=width,height=height),
                styles=[SubtitleStyle('g','Gradient',font_family=families[0],font_weight=500,font_size=68)],
                cues=[StudioCue(str(i),round(i*duration*1000/max(1,count)),round((i+1)*duration*1000/max(1,count)),f'字幕 {i:04d} 中文 😀',style_id='g') for i in range(count)])
            if count:project.style_recipes['g']={'name':'Gradient','engine':'remotion','motion':{'mode':'none'},'colors':{'fill':{'type':'linear-gradient','angle':0,'stops':[{'position':0,'color':'#FFFF0000'},{'position':1,'color':'#FF00FFFF'}]}}}
            if case.get('complex'):
                import math
                from ..caption_design.studio_ai import style_recipe_for_prompt
                project.style_recipes['g']=style_recipe_for_prompt('赛博朋克 Cyberpunk HUD 多层描边 glow glitch').to_dict()
                recipe=project.style_recipes['g'];recipe.setdefault('effects',{}).update(glow={'enabled':True,'color':'#FF00D8FF','blur':38,'opacity':.9},shadow={'enabled':True,'blur':16,'opacity':.8,'offset_x':9,'offset_y':12})
                authored=next(st for st in project.styles if st.id=='g');authored.outline_width=8;authored.outline2_width=16;authored.outline2_color='#FFFF00FF'
                project.speakers=[StudioSpeaker(f'S{i+1:02d}',f'Track {i+1}',style_id='g') for i in range(4)]
                step=duration*1000/max(1,math.ceil(count/4))
                for i,cue in enumerate(project.cues):
                    lane=i%4;cue.speaker_id=f'S{lane+1:02d}';cue.start_ms=round((i//4)*step);cue.end_ms=min(round(duration*1000),round((i//4+1.25)*step))
                    cue.transform={'position_x':480 if lane%2==0 else 1440,'position_y':600 if lane<2 else 920}
            if case.get('bilingual'):
                project.generation_metadata['translations']={cue.id:f'Translation {i}' for i,cue in enumerate(project.cues)}
                project.studio_state['bilingual']={'mode':'bilingual','layout':'ink_v1'}
            project.validate();ass=folder/'captions.ass';ass.write_text(compile_ass(project),encoding='utf8')
            encoder=case.get('encoder','h264_nvenc');settings=RenderSettings(encoder=encoder,preset='p4' if encoder.endswith('_nvenc') else 'ultrafast',quality_mode='cq',quality=18,width=width,height=height,fps=30,audio_codec=case.get('audio','copy'))
            previews=[];deadline=[None]
            def preview(image,ms,phase):
                previews.append(ms)
                if case.get('preview_fault') and ms>=26500:
                    deadline[0]=time.monotonic()+12
                    raise RuntimeError('in-process preview observer failed after 26.5 seconds')
            job=RenderJob(str(source),str(ass),str(folder/'中文 成品.mp4'),settings,duration_seconds=duration,
                export_project_data=project.to_dict(),preview_callback=preview if case.get('preview') or case.get('preview_fault') else None)
            fn=AdvancedRendererBackend().render if case.get('complex') else render_static_graph if count else None
            kwargs=dict(cancelled=lambda:deadline[0] is not None and time.monotonic()>deadline[0])
            if fn:fn(project,ffmpeg,job,**kwargs)
            else:run_render_job(ffmpeg,job,**kwargs)
            frames=painted=0
            with av.open(job.output_path) as media:
                for frame in media.decode(video=0):
                    if count:
                        pixels=frame.to_ndarray(format='rgb24')
                        r,g,b=(pixels[:,:,i].astype(np.int16) for i in range(3))
                        painted+=int(np.count_nonzero((np.abs(r-g)>8)|(np.abs(r-b)>8)|(np.abs(g-b)>8))>10)
                    if frames in {0,795,round(duration*30)-1}:frame.to_image().save(folder/f'frame-{frames}.png')
                    frames+=1
            receipt=job.completion_metadata;video=next(st for st in receipt['streams'] if st['codec_type']=='video');audio=next((st for st in receipt['streams'] if st['codec_type']=='audio'),None)
            checks=dict(frame_count=frames==round(duration*30),dimensions=video['width']==width and video['height']==height,
                duration=abs(float(video['duration'])-duration)<.05,pixel_format=video['pix_fmt']=='yuv420p',encoder=receipt['actual_encoder']==encoder,
                audio=audio is not None and abs(float(audio['duration'])-duration)<.05,caption_pixels=not count or painted>frames*.5,
                preview=not (case.get('preview') or case.get('preview_fault')) or max(previews,default=0)>=26500,
                fault_warning=not case.get('preview_fault') or bool(job.export_context.get('preview_warning')))
            result.update(checks=checks,frames=frames,painted=painted,preview_frames=len(previews),receipt=receipt,diagnostics=job.export_context.get('diagnostics_path'),passed=all(checks.values()))
        except Exception as error:result.update(error=str(error),traceback=traceback.format_exc())
        result['wall_seconds']=time.perf_counter()-began;report['cases'].append(result);write()
    report['passed']=all(case['passed'] for case in report['cases']);write()
    return 0 if report['passed'] else 1
