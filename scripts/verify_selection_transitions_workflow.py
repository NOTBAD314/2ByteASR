"""Normal-entry real selection gestures, transitions and final export pixels."""
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path);p.add_argument('--scale',default='1')
    args=p.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('Fresh repository tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,VideoTrack,VideoClip,save_project
    from twobyteasr.timeline.studio_media_pool import add_media_asset,sync_linked_av_contract
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    for name,color,tone in [('red','red',440),('blue','blue',880)]:
        run_hidden_subprocess([str(ffmpeg),'-v','error','-f','lavfi','-i',f'color={color}:s=480x270:r=30:d=8',
            '-f','lavfi','-i',f'sine=frequency={tone}:sample_rate=48000:duration=8',
            '-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(out/(name+'.mp4'))],
            purpose='isolated transition color/tone fixture',check=True,timeout=30)
    project=SubtitleProject(media=StudioMedia(path=str(out/'red.mp4'),duration_ms=8000,width=480,height=270),cues=[
        StudioCue('sel-1',1200,2000,'选中字幕一','S1'),StudioCue('sel-2',6200,6800,'选中字幕二','S1'),StudioCue('sel-narrow',12000,12040,'窄','S1'),StudioCue('sel-off',18000,18500,'离屏字幕','S1')])
    project.validate();project.video_tracks[0].locked=True;project.video_tracks[0].enabled=False;sequence_of(project).video_track_locked=True
    blue=add_media_asset(project,str(out/'blue.mp4'),duration_ms=8000,video_metadata={'width':480,'height':270,'fps':30,'has_video':True},audio_metadata={'has_audio':True})
    red=project.media_pool[0]
    project.video_tracks.append(VideoTrack('V2','实际剪辑',clips=[VideoClip('sel-red',red.asset_id,1000,4000,1000,4000),
        VideoClip('sel-blue',blue.asset_id,1000,4000,4000,7000),VideoClip('sel-offvideo',red.asset_id,5000,7000,17000,19000)],z_index=1))
    sync_linked_av_contract(project);project.studio_state.update(playhead_ms=1500,project_name='框选与转场验收')
    path=save_project(project,out/'fixture.2byteproj')
    (out/'selection-plan.json').write_text(json.dumps(dict(project=str(path),ffmpeg=str(ffmpeg),scale=args.scale),ensure_ascii=False,indent=2),'utf8')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='selection-transitions-workflow',
        TWOBYTEASR_STARTUP_PROJECT=str(path),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,PYTHONUTF8='1',PYTHONIOENCODING='utf8',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from audit_launch_bridge import run_audit_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(cmd+[str(path)],cwd=ROOT,env=env,output=out,receipt=out/'selection-workflow-result.json',timeout=420)
    target=out/'selection-workflow-result.json';result=json.loads(target.read_text('utf8')) if target.is_file() else dict(passed=False,error='Missing GUI receipt')
    result['process_exit']=code;result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],exit_code=code,checks=len(result.get('checks',[])),error=result.get('error')),ensure_ascii=False))
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
