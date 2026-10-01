"""Headed source/frozen selection geometry matrix on isolated synthetic media."""
import argparse, copy, json, os
from pathlib import Path
import shutil, subprocess, sys

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dpi',type=float,default=1.75);parser.add_argument('--exe',type=Path)
    parser.add_argument('--media',type=Path,required=True);parser.add_argument('--quick',action='store_true')
    parser.add_argument('--long',action='store_true',help='180px long line and explicit multiline fixtures')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('fresh tmp required')
    out.mkdir(parents=True);shutil.copyfile(args.media,out/'synthetic.mp4')
    (out/'temp').mkdir()
    env=os.environ.copy();env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),
        TEMP=str(out/'temp'),TMP=str(out/'temp'),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(args.dpi/1.75),QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough',
        TWOBYTEASR_SELECTION_DIAGNOSTICS='1',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='selection-geometry',TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    os.environ.update({k:env[k] for k in ('LOCALAPPDATA','APPDATA','TEMP','TMP')})
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,SubtitleStyle,save_project,hydrate_media_contract
    from twobyteasr.studio_helpers import probe_media_identity
    from twobyteasr.style_recipe import StyleRecipe
    from twobyteasr.visual_design_graph import glitch_graph,MotionGraph
    from twobyteasr.web_theme import WebThemeDocument
    texts=['哎这张我要收藏一下啊','好','哎这张我要收藏一下啊回头再给大家分享这份收藏','哎这张我要收藏一下啊\n回头再分享']
    if args.long:texts=['只要打PVP顺手就给他做完了','第一行字幕\n第二行字幕\n第三行字幕']
    font_size=180 if args.long else 94
    config=dict(dpi=args.dpi,cases=[])
    for route in ('native','static','html'):
        for number,text in enumerate(texts[:1] if args.quick and not args.long else texts):
            for family in (['Source Han Sans SC'] if args.quick or args.long else ['Source Han Sans SC','Cubic 11']):
                ident=f'{route}-{number}-'+('heavy' if family.startswith('Source') else 'cubic')
                style=SubtitleStyle(id='sample',name='几何测试',font_family=family,font_size=font_size,font_weight=900 if family.startswith('Source') else 400,
                    outline_width=5,shadow=0,position_x=960,position_y=930)
                project=SubtitleProject(media=StudioMedia(str(out/'synthetic.mp4'),duration_ms=6000,width=1280,height=720),
                    speakers=[StudioSpeaker('AUDIT')],styles=[style],cues=[StudioCue('sample',250,3800,text,'AUDIT',style_id='sample'),StudioCue('second',3900,5900,'继续分享','AUDIT',style_id='sample')])
                if route=='static':
                    graph=glitch_graph();graph.motion_graph=MotionGraph(5250,[]);graph.effect_layers=[];graph.decoration_layers=[]
                    recipe=StyleRecipe('静态几何',engine='remotion',visual_graph=graph.to_dict(),
                        typography={'fontFamily':family,'fontSize':font_size,'fontWeight':style.font_weight},
                        colors={'fill':'#FFFFFFFF'})
                    project.style_recipes['sample']=recipe.to_dict()
                if route=='html':
                    theme=WebThemeDocument.from_dict(dict(name='真实网页几何',id='selection-synthetic-html',
                        palette={'primary':'#FCFCFC','text':'#FFFFFF'},
                        appearance={'fontFamily':family,'fontSize':font_size,'fontWeight':style.font_weight,'color':'#FFFFFF','strokeColor':'#000000','strokeWidth':5},
                        cueHtml='<div class="caption"><span class="body">{{text}}</span><i class="local"></i></div>',
                        cueCss='.caption{position:absolute;left:50%;bottom:8%;transform:translateX(-50%);width:max-content;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);color:var(--wt-color);line-height:1.12;white-space:pre;}.body{display:inline-block;-webkit-text-stroke:var(--wt-stroke-w) var(--wt-stroke);paint-order:stroke fill;}.local{position:absolute;left:0;right:0;height:2px;background:#F2B887;bottom:-4px;}',
                        stageHtml='',stageCss='',motionSpec={'version':1,'runtime':'gsap','tracks':[
                            {'selector':'.body','phase':'build','from':{'opacity':0,'scaleX':.9},'to':{'opacity':1,'scaleX':1}},
                            {'selector':'.body','phase':'resolve','from':{'opacity':1,'scaleX':1},'to':{'opacity':0,'scaleX':.9}}]})).to_dict()
                    theme['cueCss']=theme['cueCss'].replace('font-weight:var(--wt-weight)',f'font-weight:{style.font_weight}')
                    if family.startswith('Source'):theme['appearance']['fontFamily']='Source Han Sans SC Heavy'
                    project.style_recipes['sample']=StyleRecipe('网页',engine='remotion',web_theme=theme).to_dict()
                hydrate_media_contract(project,probe_media_identity(str(out/'synthetic.mp4')))
                save_project(project,out/(ident+'.2byteproj'));config['cases'].append(dict(id=ident,route=route,font=family,text=text))
    shutil.copyfile(out/(config['cases'][0]['id']+'.2byteproj'),out/'fixture.2byteproj')
    (out/'matrix.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf8')
    from twobyteasr.processes import run_hidden_subprocess
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,str(root/'quick_start.py')]
    with (out/'process.log').open('w',encoding='utf8') as log:
        child=run_hidden_subprocess(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200,purpose='headed selection geometry matrix')
    data=json.loads((out/'result.json').read_text('utf8'));print(json.dumps({k:data.get(k) for k in ('passed','error','counts')},ensure_ascii=False))
    return child.returncode or (0 if data.get('passed') else 1)
if __name__=='__main__':raise SystemExit(main())
