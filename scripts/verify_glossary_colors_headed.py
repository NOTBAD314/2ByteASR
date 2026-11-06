"""Normal Windows processes verify the glossary and effect-paint workflows."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scale',default='1')
    parser.add_argument('--zoom',type=int,default=100)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--eyedrop-only',action='store_true')
    parser.add_argument('--layout-only',action='store_true')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        parser.error('Choose a fresh output under source/tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.app import ui_zoom
    ui_zoom.set_zoom_percent(args.zoom)
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,SubtitleStyle,save_project
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    media=out/'fixture.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-f','lavfi','-i','color=c=0x203047:s=640x360:r=24:d=8',
        '-c:v','libx264','-preset','ultrafast','-threads','2','-pix_fmt','yuv420p',str(media)],check=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
    style=SubtitleStyle('effect-paints','完整外观',font_family='Source Han Sans SC Heavy',font_size=40,font_weight=900,
        primary_color='#FFFFFFFF',outline_color='#FF000000',outline_width=3,outline2_color='#FF224488',outline2_width=7,
        border_style=3,back_color='#99224466',shadow=5,position_x=320,position_y=255,alignment=2)
    recipe=StyleRecipe('完整外观',engine='remotion',colors={'fill':style.primary_color},
        outline={'shadow':{'enabled':True,'color':'#FF000000','opacity':.65,'offset_x':8,'offset_y':8,'blur_radius':4,'spread':1}},
        effects={'glow':{'enabled':True,'color':'#FF22CC66','opacity':.75,'radius':8,'spread':1}},
        background={'enabled':True,'color':style.back_color,'padding':14,'radius':8})
    cues=[StudioCue('paint-'+str(i),i*4000,(i+1)*4000,'字幕样式 Aa 123' if i==0 else '第二句预设保存检查',style_id=style.id) for i in range(2)]
    project=SubtitleProject(StudioMedia(str(media),duration_ms=8000,width=640,height=360),cues=cues,styles=[style],
        style_recipes={style.id:recipe.to_dict()},render_settings={'play_res_x':640,'play_res_y':360},
        generation_metadata={'translations':{cues[0].id:'Gradient effects',cues[1].id:'Preset roundtrip'}},
        studio_state={'bilingual':{'mode':'bilingual','original_scale':1.,'translation_scale':.8}})
    save_project(project,out/'fixture.2byteproj')
    settings=out/'local/2ByteASR/2byteasr_settings.json'
    settings.parent.mkdir(parents=True,exist_ok=True)
    settings.write_text(json.dumps({'schema_version':1,'studio_preferences':{'auto_cover':False,'recovery_policy':'official'}}),'utf8')
    from isolated_windows_desktop import run_on_desktop
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-colors',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_INVOKER_CWD=str(ROOT),QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,
        PYTHONUTF8='1',PYTHONFAULTHANDLER='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',REAL_LONG_BASELINE='1',
        TWOBYTEASR_MPV=str(ROOT/'tools/mpv/mpv.exe'),TWOBYTEASR_STARTUP_SIZE='1440x900',GLOSSARY_COLORS_EYEDROP_ONLY='1' if args.eyedrop_only else '0',GLOSSARY_COLORS_LAYOUT_ONLY='1' if args.layout_only else '0')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    final=[]
    phases=(False,) if (args.eyedrop_only or args.layout_only) else (False,True)
    for restoring in phases:
        path=out/('colors-saved.2byteproj' if restoring else 'fixture.2byteproj')
        if restoring:
            restart=out/'restart.2byteproj';shutil.copy2(path,restart);path=restart
        env.update(TWOBYTEASR_STARTUP_PROJECT=str(path),REAL_LONG_PROJECT=str(path),GLOSSARY_COLORS_RESTORE='1' if restoring else '0')
        code=run_on_desktop(command,cwd=ROOT,env=env,output=out/('process-restart' if restoring else 'process-first'),timeout=660,
            desktop_name='Default' if args.visible else None)
        result_path=out/'result.json'
        result=json.loads(result_path.read_text('utf8')) if result_path.exists() else dict(passed=False,error='No GUI result')
        result['exit_code']=code
        result['passed']=bool(result.get('passed') and code==0 and all(result.get('checks',{}).values()))
        (out/('restart-result.json' if restoring else 'first-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        final.append(dict(phase='restart' if restoring else 'first',passed=result['passed'],exit_code=code,dpr=result.get('dpr'),checks=len(result.get('checks',{})),error=result.get('error')))
        print(json.dumps(final[-1],ensure_ascii=False),flush=True)
        if not result['passed']:break
    summary=dict(passed=len(final)==len(phases) and all(r['passed'] for r in final),phases=final)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf8')
    return 0 if summary['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
