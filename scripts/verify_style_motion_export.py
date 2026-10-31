"""Export and decode a representative real bilingual styled/moving segment."""
import argparse,copy,json,os,shutil,subprocess,sys,time
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--renderer',type=Path)
    args=ap.parse_args();root=Path(__file__).resolve().parents[1];out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    fonts=Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts'
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'),QT_QPA_PLATFORM='offscreen')
    sys.path.insert(0,str(root));from twobyteasr.test_isolation import install
    install()
    copies=Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts';copies.mkdir(parents=True,exist_ok=True)
    for name in ('猫啃什锦黑.ttf','SourceHanSansSC-VF.otf'):shutil.copy2(fonts/name,copies/name)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    app=QApplication([])
    for font in copies.iterdir():QFontDatabase.addApplicationFont(str(font))
    from twobyteasr.projects.studio_project import load_project,save_project
    from twobyteasr.caption_style.motion_application import motion_command
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.caption_style.style_recipe import route_recipe
    from twobyteasr.rendering.caption_playback_cache import PreparedCaption
    from twobyteasr.rendering.caption_scene import SceneRasterizer
    from twobyteasr.rendering.ass_compiler import compile_ass
    from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend,project_requires_advanced,compile_composition_data
    from twobyteasr.exports.studio_render import RenderJob,RenderSettings,run_render_job
    p=load_project(args.project);cue=next(c for c in p.cues if c.id=='137')
    start=cue.start_ms/1000-.2;duration=12.
    p.cues=[c for c in p.cues if c.end_ms>start*1000 and c.start_ms<(start+duration)*1000]
    loop={'entry':{'type':'fade','duration':180},'exit':{'type':'fade','duration':140},
          'loop':{'type':'loop_breathe','duration':1200,'strength':'medium'}}
    cmd=motion_command(p,[c.id for c in p.cues],motion=loop,language='linked');cmd.redo()
    save_project(p,out/'export-input.2byteproj')
    ass=out/'captions.ass';ass.write_text(compile_ass(p,frame_rate=30.),'utf-8-sig')
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe';ffprobe=ffmpeg.with_name('ffprobe.exe')
    job=RenderJob(p.media.path,str(ass),str(out/'styled-bilingual-motion.mp4'),
        settings=RenderSettings(encoder='h264_nvenc',preset='p4',quality=18,width=1920,height=1080,
            fps=30.,audio_codec='aac',font_directory=str(copies)),
        start_seconds=start,duration_seconds=duration,overwrite_existing=True)
    result=dict(passed=False,start_seconds=start,duration_seconds=duration,cues=[c.id for c in p.cues],
        full_input_cues=len(load_project(args.project).cues),route='advanced' if project_requires_advanced(p) else 'native',events=[])
    if result['route']=='advanced':
        props=compile_composition_data(p,width=1920,height=1080,fps=30.,start_seconds=start,duration_seconds=duration)
        result['font_assets']=[{k:v for k,v in f.items() if k!='source'}for f in props.get('fontFaces',[])]
        result['compiled_cues']=[dict(id=c['id'],text=c['text'],layout=c['visual']['layout'],
            typography=c['visual']['typography'],fill=c['visual']['fill'],strokes=c['visual']['strokes'],
            shadow=c['visual']['shadow'],line_count=c['lineCount'])for c in props['cues']]
        del props
    def trace(event,data):
        result['events'].append(dict(event=event,data=data))
        (out/'events.json').write_text(json.dumps(result['events'],ensure_ascii=False,indent=2,default=str),'utf8')
    t=time.perf_counter()
    if result['route']=='advanced':AdvancedRendererBackend(args.renderer).render(p,ffmpeg,job,trace=trace)
    else:run_render_job(ffmpeg,job,trace=trace)
    result['render_seconds']=time.perf_counter()-t
    result['probe']=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries',
        'stream=codec_type,width,height,avg_frame_rate,nb_frames,duration:format=duration','-of','json',job.output_path],text=True,encoding='utf8'))
    result['frames']=[];raster=SceneRasterizer()
    for offset in (.8,1.,2.8,6.,9.4,11.4):
        at=start*1000+offset*1000
        decoded=out/f'export-{offset:.1f}.png'
        subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-ss',str(offset),'-i',job.output_path,
            '-frames:v','1','-y',str(decoded)],check=True)
        shown=project_display_cues(p,[c for c in p.cues if c.start_ms<=at<c.end_ms]);rows=[]
        for c in shown:
            snapshot=build_visual_cue_snapshot(p,c.id,width=1920,height=1080,resolved_cue=c)
            rows.append((c.id,PreparedCaption(snapshot,snapshot.stable_hash(),route_recipe(snapshot.style_recipe))))
        pixels,evidence=raster.frame(rows,at,1920,1080);pixels.save(str(out/f'preview-overlay-{offset:.1f}.png'))
        result['frames'].append(dict(offset=offset,active=[c.id for c in shown],evidence=evidence,
            layout=[dict(id=c.id,position=[s.snapshot.position_x,s.snapshot.position_y],
                font_size=s.snapshot.font_size,text=s.snapshot.text,fill=s.snapshot.fill)for c_id,s in rows for c in shown if c.id==c_id]))
    raster.close()
    video=next(x for x in result['probe']['streams'] if x['codec_type']=='video')
    result['passed']=abs(float(video.get('duration',duration))-duration)<.1 and int(video.get('nb_frames',0))==360
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    print(json.dumps(dict(passed=result['passed'],route=result['route'],seconds=result['render_seconds'],probe=result['probe']),ensure_ascii=False))
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
