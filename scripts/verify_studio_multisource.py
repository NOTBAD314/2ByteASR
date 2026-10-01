"""Normal source/frozen entry, isolated projects and private Windows desktop."""
import argparse,copy,json,os,sys,shutil
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--user-project',type=Path)
    parser.add_argument('--analysis',type=Path)
    parser.add_argument('--long-play',action='store_true')
    parser.add_argument('--detect',action='store_true')
    parser.add_argument('--real-only',action='store_true')
    parser.add_argument('--held-preview',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('New tmp output required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    if args.detect:
        import venv
        shutil.copytree(root/'models/FireRedVAD/VAD',out/'models/FireRedVAD/VAD')
        runtime=out/'local/2ByteASR/runtimes/main'
        venv.EnvBuilder(with_pip=False).create(runtime)
        (runtime/'Lib/site-packages/qa-dependencies.pth').write_text(str(root/'.venv-main/Lib/site-packages'),'utf8')
        os.environ['TWOBYTEASR_MAIN_PYTHON']=str(runtime/'Scripts/python.exe')
        os.environ['PYTHONDONTWRITEBYTECODE']='1'
    from twobyteasr.processes import run_hidden_subprocess
    assets=root/'tmp/studio-multisource-20260928/assets';assets.mkdir(parents=True,exist_ok=True)
    for name,color,freq,duration in [('first','red',440,10),('second','blue',880,15),('third','green',660,7)]:
        path=assets/(name+'.mp4')
        if not path.exists():
            run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
                f'color=c={color}:s=1280x720:r=30:d={duration}','-f','lavfi','-i',
                f'sine=frequency={freq}:sample_rate=48000:duration={duration}',
                '-c:v','libx264','-preset','ultrafast','-g','30','-c:a','aac','-shortest',path],
                check=True,timeout=90,purpose='multi-source acceptance fixtures')
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,save_project
    from twobyteasr.studio_edit_sequence import sequence_of
    from twobyteasr.studio_media_pool import add_media_asset,create_video_track,add_video_clip
    p=SubtitleProject(media=StudioMedia(path=str(assets/'first.mp4'),duration_ms=10000,width=1280,height=720))
    p.validate();p.video_tracks[0].locked=sequence_of(p).video_track_locked=False
    a=add_media_asset(p,assets/'second.mp4',duration_ms=15000)
    t=create_video_track(p,'V2');add_video_clip(p,t.id,a.asset_id,timeline_in_ms=10000)
    save_project(p,out/'two.2byteproj')
    overlap=copy.deepcopy(p);c=overlap.video_tracks[1].clips[0];c.timeline_in_ms=5000;c.timeline_out_ms=20000
    save_project(overlap,out/'overlap.2byteproj')
    gap=copy.deepcopy(p);c=gap.video_tracks[1].clips[0];c.timeline_in_ms=12000;c.timeline_out_ms=27000
    save_project(gap,out/'gap.2byteproj')
    from twobyteasr.studio_clip_edit import reassign_clips_command
    three=copy.deepcopy(p)
    reassign_clips_command(three,'V2','V1',[three.video_tracks[1].clips[0].id],append=True).redo()
    a=add_media_asset(three,assets/'third.mp4',duration_ms=7000)
    add_video_clip(three,'V2',a.asset_id,timeline_in_ms=25000)
    reassign_clips_command(three,'V2','V1',[three.video_tracks[1].clips[0].id],append=True).redo()
    save_project(three,out/'three.2byteproj')
    if args.held_preview:
        from twobyteasr.studio_clip_edit import clip_edit_command
        for name,duration,cut,frequency,color in [('deep-a',42,30,440,'green'),('deep-b',108,100,880,'blue')]:
            path=assets/(name+'.mp4')
            if not path.exists():
                run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
                    f'color=c=red:s=320x180:r=10:d={duration},drawbox=c={color}:t=fill:enable=gte(t\\,{cut})',
                    '-f','lavfi','-i',f'aevalsrc=0.15*sin(2*PI*if(lt(t\\,{cut})\\,220\\,{frequency})*t):s=48000:d={duration}',
                    '-c:v','libx264','-preset','ultrafast','-g','10','-c:a','aac','-shortest',path],
                    check=True,timeout=90,purpose='deep source mapping fixtures')
        p=SubtitleProject(media=StudioMedia(path=str(assets/'deep-a.mp4'),duration_ms=42000,width=320,height=180))
        p.validate();p.video_tracks[0].locked=sequence_of(p).video_track_locked=False
        a=p.video_tracks[0].clips[0]
        clip_edit_command(p,'V1','trim',clip_id=a.id,start=30000,end=40000).redo()
        clip_edit_command(p,'V1','move',clip_id=a.id,start=0).redo()
        b=add_media_asset(p,assets/'deep-b.mp4',duration_ms=108000)
        create_video_track(p,'V2');add_video_clip(p,'V2',b.asset_id,timeline_in_ms=15000,source_in_ms=100000,source_out_ms=105000)
        save_project(p,out/'deep.2byteproj')
    if args.user_project:shutil.copy2(args.user_project,out/'user.2byteproj')
    if args.analysis:shutil.copy2(args.analysis,out/'analysis.json')
    (out/'config.json').write_text(json.dumps({'long_play':args.long_play,'detect':args.detect,'real_only':args.real_only,'held_preview':args.held_preview}),'utf8')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='multisource',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'two.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONIOENCODING='utf8')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command+[str(out/'two.2byteproj')],cwd=root,env=env,output=out/'process',timeout=1400)
    result=json.loads((out/'result.json').read_text('utf8'))
    result['process_exit_code']=code
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'error':result.get('error'),'code':code},ensure_ascii=False))
    return 0 if result['passed'] and code==0 else 1


if __name__=='__main__':raise SystemExit(main())
