"""Offline style/geometry and raster evidence on a copy of the real project."""
from pathlib import Path
import argparse, copy, hashlib, json, os, shutil, statistics, sys, time

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--presets',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--product-source',type=Path)
    ap.add_argument('--frames',type=int,default=24);args=ap.parse_args()
    root=Path(__file__).resolve().parents[1];out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    user_fonts=Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts'
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile');os.environ['QT_QPA_PLATFORM']='offscreen'
    sys.path.insert(0,str(args.product_source.resolve() if args.product_source else root))
    from twobyteasr.test_isolation import install
    install()
    fonts=out/'profile/local/Microsoft/Windows/Fonts';fonts.mkdir(parents=True,exist_ok=True)
    for name in ('猫啃什锦黑.ttf','优设标题黑.ttf','SourceHanSansSC-VF.otf'):
        shutil.copy2(user_fonts/name,fonts/name)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    app=QApplication([])
    for font in fonts.iterdir():QFontDatabase.addApplicationFont(str(font))
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.caption_style.style_presets import StylePresetStore
    from twobyteasr.caption_style.scoped_preset import preset_command
    from twobyteasr.caption_style.scoped_style import style_patch_command,effective_layer_style
    from twobyteasr.caption_style.bilingual_layout import project_display_cues,ink_block
    from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.caption_style.motion_application import motion_command
    from twobyteasr.caption_style.style_recipe import route_recipe
    from twobyteasr.rendering.caption_playback_cache import PreparedCaption
    from twobyteasr.rendering.caption_scene import SceneRasterizer
    import psutil
    store=StylePresetStore();store.path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(args.presets,store.path)
    p=load_project(args.project);cue=p.cues[136]
    result={'cues':len(p.cues),'translations':len(p.generation_metadata.get('translations',{})),
        'cue_id':cue.id,'text':cue.text,'speaker':cue.speaker_id,
        'speaker_count':sum(c.speaker_id==cue.speaker_id for c in p.cues),
        'source_sha256':hashlib.sha256(args.project.read_bytes()).hexdigest(),'geometry':[],'render':[]}
    def geometry(label):
        rows=[]
        for c in project_display_cues(p,[cue]):
            r=resolve_caption_style(p.styles,p.speakers,c,p.style_recipes,1920,1080);s=r.style
            block=ink_block(r);row=(s.alignment-1)//3;f=(1.,.5,0.)[row]
            y=s.position_y if s.position_y is not None else 1080-s.margin_v
            rows.append({'id':c.id,'font_size':s.font_size,'position':[s.position_x,y],
                'ink':[y-f*block[0]-block[2],y+(1-f)*block[0]+block[2]+block[3]],
                'fill':s.primary_color,'outline':s.outline_color,'recipe_fill':json.loads(r.recipe_json).get('colors',{}).get('fill'),
                'line_count':r.line_count})
        gap=abs(rows[0]['position'][1]-rows[1]['position'][1]) if len(rows)>1 else None
        overlap=len(rows)>1 and min(r['ink'][1] for r in rows)>max(r['ink'][0] for r in rows)
        result['geometry'].append({'step':label,'rows':rows,'overlap':overlap,'anchor_distance':gap,
                                  'transform':copy.deepcopy(cue.transform)})
    geometry('input')
    patch=store.load_patch('user-ca40c9cf62d9')
    result['preset']=patch
    for include in (False,True):
        cmd=preset_command(p,[cue.id],patch,layer='group',apply_geometry=include)
        if cmd:cmd.redo()
        geometry('preset_geometry_'+str(include))
        cmd=style_patch_command(p,[cue.id],{'font_size':61},layer='group');cmd.redo()
        geometry('size_61_geometry_'+str(include))
    loop={'entry':{'type':'fade','duration':180},'exit':{'type':'fade','duration':140},
          'loop':{'type':'loop_breathe','duration':1200,'strength':'medium'}}
    for name,styled,animated in [('A',False,False),('B',True,False),('C',False,True),('D',True,True)]:
        cmd=preset_command(p,[cue.id],patch if styled else store.load_patch('default'),layer='group',apply_geometry=False)
        if cmd:cmd.redo()
        cmd=motion_command(p,[cue.id],motion=loop if animated else {'entry':{'type':'none'},'exit':{'type':'none'}},language='linked')
        if cmd:cmd.redo()
        shown=project_display_cues(p,[cue]);prepared=[]
        for c in shown:
            snap=build_visual_cue_snapshot(p,c.id,width=1280,height=720,resolved_cue=c)
            digest=hashlib.sha256(repr(snap).encode()).hexdigest()
            prepared.append((c.id,PreparedCaption(snap,digest,route_recipe(snap.style_recipe))))
        raster=SceneRasterizer();samples=[];proc=psutil.Process();cpu0=proc.cpu_times();start=time.perf_counter()
        for i in range(args.frames):
            t=time.perf_counter();image,rows=raster.frame(prepared,cue.start_ms+100+i*100,1280,720)
            samples.append((time.perf_counter()-t)*1000)
            if i in (0,args.frames//2,args.frames-1):image.save(str(out/(name+f'-{i}.png')))
        elapsed=time.perf_counter()-start;cpu1=proc.cpu_times();ordered=sorted(samples)
        result['render'].append({'scenario':name,'p50_ms':statistics.median(samples),
            'p95_ms':ordered[min(len(ordered)-1,int(len(ordered)*.95))],'max_ms':max(samples),
            'over_33ms':sum(x>33.333 for x in samples),'samples_ms':samples,'raster_entries':len(raster.rasters),
            'rss_mb':proc.memory_info().rss/1048576,'cpu_s':cpu1.user+cpu1.system-cpu0.user-cpu0.system,
            'elapsed_s':elapsed,'units':[len(x.snapshot.word_animation.get('units',[]))for _,x in prepared]})
        raster.close()
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'geometry':[(x['step'],x['overlap'],x['anchor_distance'])for x in result['geometry']],
        'render':[{k:v for k,v in r.items() if k!='samples_ms'}for r in result['render']]},ensure_ascii=False))

if __name__=='__main__':main()
