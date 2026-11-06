"""Normal Windows app, owned data/desktop, readable and binary numbered frames."""
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fps',default='25')
    parser.add_argument('--trim-head',action='store_true')
    parser.add_argument('--cut-middle',action='store_true')
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--tools-root',type=Path)
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        parser.error('fresh output under checkout/tmp required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    sys.path.insert(0,str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from PIL import Image,ImageDraw,ImageFont
    frames=out/'frames';frames.mkdir()
    fps=Fraction(args.fps);count=round(float(fps)*6)
    font=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',64)
    for number in range(count):
        picture=Image.new('RGB',(640,360),(20,44,64));draw=ImageDraw.Draw(picture)
        for bit in range(10):
            draw.rectangle((16+bit*40,16,47+bit*40,47),fill='white' if number&(1<<bit) else 'black')
        draw.text((40,110),f'FRAME {number:04d}',font=font,fill='white')
        draw.text((40,200),f'{args.fps} fps',font=font,fill=(116,211,187))
        picture.save(frames/f'{number:04d}.png')
    media=out/'frames.mp4'
    subprocess.run(['ffmpeg','-v','error','-framerate',args.fps,'-i',str(frames/'%04d.png'),
        '-f','lavfi','-i','anullsrc=r=48000:cl=mono','-c:v','libx264','-threads','2',
        '-crf','10','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(media)],check=True,timeout=60,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    import subtitle_core as core
    from twobyteasr.projects.studio_project import project_from_runtime_cues,save_project
    project=project_from_runtime_cues(str(media),[core.SubtitleCue(i+1,i*.2,(i+1)*.2,f'Caption {i+1:02}') for i in range(30)])
    if project.media.duration_ms<5900 or project.media.width!=640:
        raise RuntimeError('Fixture must have a real probed media contract: '+str(project.generation_metadata.get('media_contract_probe_error')))
    if args.trim_head or args.cut_middle:
        from twobyteasr.timeline.studio_edit_sequence import sequence_of
        from twobyteasr.timeline.studio_clip_edit import ripple_ranges_command
        sequence_of(project).video_track_locked=False
        for track in project.video_tracks:track.locked=False
        command=ripple_ranges_command(project,[(2000,4000)] if args.cut_middle else [(0,1000)]);command.redo()
    fixture=out/'fixture.2byteproj';save_project(project,fixture)
    tools_root=(args.tools_root.resolve() if args.tools_root else next(
        (base for base in (ROOT,*ROOT.parents) if (base/'tools/mpv/mpv.exe').is_file()),ROOT))
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='issue-frame-step',TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_STARTUP_SIZE='1440x900',
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        TWOBYTEASR_MPV=str(tools_root/'tools/mpv/mpv.exe'),
        ISSUE_FRAME_FPS=args.fps,ISSUE_FRAME_TRIM_MS='1000' if args.trim_head else '0',
        ISSUE_FRAME_CUT_MIDDLE='1' if args.cut_middle else '0')
    for name in list(env):
        if name.endswith(('_API_KEY','_ACCESS_TOKEN','_REFRESH_TOKEN')):env.pop(name)
    command=[sys.executable,'-B',str(ROOT/'quick_start.py')]
    if args.baseline:
        names=['studio/studio_ui.py','studio/studio_shortcuts.py','studio/studio_playback_flow.py',
            'studio/studio_video_canvas.py','studio/shortcut_registry.py','playback/studio_mpv.py']
        modules={'.'.join(('twobyteasr/'+name).removesuffix('.py').split('/')):
            str(args.baseline.resolve()/'twobyteasr'/name) for name in names}
        entry=out/'baseline_entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy\n'
            +'sys.path.insert(0,'+repr(str(ROOT))+')\nmodules='+repr(modules)+'\n'
            +'class Before(importlib.abc.MetaPathFinder):\n'
            +' def find_spec(self,name,path=None,target=None):\n'
            +'  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'
            +'sys.meta_path.insert(0,Before())\nrunpy.run_path('+repr(str(ROOT/'quick_start.py'))+',run_name="__main__")\n','utf8')
        command=[sys.executable,'-B',str(entry)]
        (out/'baseline-modules.json').write_text(json.dumps(modules,indent=2),'utf8')
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=150)
    result_path=out/'result.json'
    result=json.loads(result_path.read_text('utf8')) if result_path.exists() else {'passed':False,'error':'no audit result'}
    result['exit_code']=code
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'exit_code':code,'passed':result.get('passed'),'error':result.get('error'),
        'failed':[x['name'] for x in result.get('checks',[]) if not x['passed']],'output':str(out)},ensure_ascii=False))
    return 0 if result.get('passed') and code==0 else 1


if __name__=='__main__':raise SystemExit(main())
