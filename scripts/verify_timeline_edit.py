"""Normal source/frozen entry on a private Windows desktop, isolated projects."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--user-project',type=Path)
    parser.add_argument('--scale',type=float,default=1.)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--skip-export',action='store_true')
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():
        raise ValueError('Use a new output under tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.processes import run_hidden_subprocess
    assets=root/'tmp/timeline-edit-20260928/assets'
    assets.mkdir(parents=True,exist_ok=True)
    long=assets/'synthetic-60min.mp4'
    overlay=assets/'synthetic-overlay.mp4'
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    if not long.exists():
        run_hidden_subprocess([ffmpeg,'-v','error','-f','lavfi','-i','color=c=red:s=320x180:r=2:d=3600',
            '-f','lavfi','-i',r'aevalsrc=0.2*sin(2*PI*if(lt(t\,1800)\,400\,if(lt(t\,3000)\,700\,1000))*t):s=16000:d=3600',
            '-vf',"drawbox=color=green:t=fill:enable='gte(t,1800)*lt(t,3000)',drawbox=color=blue:t=fill:enable='gte(t,3000)'",
            '-c:v','libx264','-preset','ultrafast','-g','2','-c:a','aac','-b:a','32k','-shortest',long],
            purpose='isolated long timeline source fixture',check=True,timeout=150)
    if not overlay.exists():
        run_hidden_subprocess([ffmpeg,'-v','error','-f','lavfi','-i','color=c=yellow:s=320x180:r=25:d=20',
            '-f','lavfi','-i','sine=frequency=1100:sample_rate=16000:duration=20','-c:v','libx264','-preset','ultrafast',
            '-c:a','aac','-shortest',overlay],purpose='isolated overlay source',check=True,timeout=30)
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    from twobyteasr.studio_edit_sequence import sequence_of
    from twobyteasr.studio_media_pool import add_media_asset,create_video_track,add_video_clip
    p=SubtitleProject(media=StudioMedia(path=str(long),duration_ms=3600000,width=320,height=180),
        cues=[StudioCue('first',1000,3000,'SOURCE START'),StudioCue('cross',1799000,1801500,'SOURCE 30 MIN'),
              StudioCue('retained',2100000,2102000,'AUTHORED CAPTION')])
    p.validate();p.video_tracks[0].locked=False;sequence_of(p).video_track_locked=False
    p.studio_state['timeline_waveform_visible']=False
    save_project(p,out/'long.2byteproj')
    save_project(p,out/'cut-long.2byteproj')
    second=copy.deepcopy(p)
    a=add_media_asset(second,overlay,duration_ms=20000)
    v2=create_video_track(second,'V2')
    add_video_clip(second,v2.id,a.asset_id,timeline_in_ms=10000)
    save_project(second,out/'two-lanes.2byteproj')
    if args.user_project:
        raw=json.loads(args.user_project.read_text('utf-8-sig'))
        raw['studio_state']={**raw.get('studio_state',{}),'playhead_ms':690183}
        (out/'user-copy.2byteproj').write_text(json.dumps(raw,ensure_ascii=False),'utf8')
    (out/'config.json').write_text(json.dumps({'baseline':str(args.baseline.resolve()) if args.baseline else '',
        'skip_export':args.skip_export,'source_fixture':'Synthetic 60 minute red/green/blue, 400/700/1000Hz; original files unchanged'}),'utf8')
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='timeline-edit',TWOBYTEASR_STARTUP_PROJECT=str(out/'two-lanes.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR=str(args.scale),PYTHONIOENCODING='utf8')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command+[str(out/'two-lanes.2byteproj')],cwd=root,env=env,output=out/'process',timeout=1500)
    result=json.loads((out/'result.json').read_text('utf8'))
    result['process_exit_code']=code
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'error':result.get('error'),'code':code},ensure_ascii=False))
    return 0 if result['passed'] and code==0 else 1


if __name__=='__main__':raise SystemExit(main())
