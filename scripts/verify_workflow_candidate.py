"""Build isolated media/projects then exercise the normal source or EXE entry."""
import argparse,json,os,sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--offscreen',action='store_true')
    parser.add_argument('--isolated-desktop',action='store_true')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('output must be in workspace tmp')
    out.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    from twobyteasr.studio_edit_sequence import sequence_of,projected_cues
    from twobyteasr.studio_media_pool import add_media_asset,create_video_track,add_video_clip
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    for name,color,hz in [('A','blue',440),('B','green',880)]:
        media=out/(name+'.mp4')
        run_hidden_subprocess([ffmpeg,'-v','error','-y','-f','lavfi','-i',f'color={color}:s=640x360:r=30:d=20',
            '-f','lavfi','-i',f'sine=frequency={hz}:sample_rate=48000:duration=20','-c:v','libx264','-c:a','aac','-shortest',media],
            purpose='isolated workflow fixture',check=True,timeout=30)
        p=SubtitleProject(media=StudioMedia(path=str(media),duration_ms=20000,width=640,height=360),
            cues=[StudioCue(name,6000,15000,'WORKFLOW '+name)])
        p.validate();p.styles[0].font_size=72
        if name=='B':
            seg=sequence_of(p).segments[0];seg.source_in_ms=2000;seg.timeline_out_ms=18000
        p.studio_state.update(playhead_ms=7000,last_selected_cue=projected_cues(p)[0].id)
        (out/'projects'/name).mkdir(parents=True,exist_ok=True)
        save_project(p,out/'projects'/name/(name+'.2byteproj'))
    # Use the user's actual two PV sources read-only if still available.
    desktop=Path.home()/'Desktop'
    v1=desktop/'未眠野PV_版本1.mp4';v2=desktop/'未眠野PV_版本1_1.mp4'
    if not (v1.is_file() and v2.is_file()):v1,v2=out/'A.mp4',out/'B.mp4'
    p=SubtitleProject(media=StudioMedia(path=str(v1),duration_ms=20000,width=1920,height=1080),
        cues=[StudioCue('dual',1000,19000,'WORKFLOW DUAL')])
    p.validate();asset=add_media_asset(p,v2,fingerprint='workflow-v2',duration_ms=20000)
    track=create_video_track(p);add_video_clip(p,track.id,asset.asset_id,timeline_in_ms=0)
    p.validate();p.studio_state.update(playhead_ms=3000,last_selected_cue='dual')
    save_project(p,out/'dual.2byteproj')
    env=os.environ.copy();env.update(USERPROFILE=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='workflow-fixes',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_STARTUP_PROJECT=str(out/'projects/A/A.2byteproj'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',PYTHONDONTWRITEBYTECODE='1')
    if args.offscreen:env['QT_QPA_PLATFORM']='offscreen'
    else:env.pop('QT_QPA_PLATFORM',None)
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    if args.isolated_desktop:
        from isolated_windows_desktop import run_on_desktop
        from types import SimpleNamespace
        result=SimpleNamespace(returncode=run_on_desktop(command+[str(out/'projects/A/A.2byteproj')],
            cwd=root,env=env,output=out/'process',timeout=280),stdout=b'',stderr=b'')
    else:
        result=run_hidden_subprocess(command+[str(out/'projects/A/A.2byteproj')],purpose='workflow candidate verification',
            cwd=root,env=env,capture_output=True,timeout=280)
    (out/'stdout.log').write_bytes(result.stdout);(out/'stderr.log').write_bytes(result.stderr)
    receipt=json.loads((out/'result.json').read_text(encoding='utf8'))
    receipt['process_exit_code']=result.returncode
    (out/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(passed=receipt['passed'],exit_code=result.returncode,error=receipt.get('error'),checks=len(receipt['checks'])),ensure_ascii=True))
    return 0 if receipt['passed'] and result.returncode==0 else 1
if __name__=='__main__':raise SystemExit(main())
