"""Prepare isolated full-duration media, then use the normal production entry."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--synthetic',action='store_true')
    parser.add_argument('--transitions',action='store_true')
    parser.add_argument('--cases',default='[["V1",4,52],["V2",4,52]]')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('output must be under tmp')
    if out.exists():raise ValueError('use a fresh directory')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    from twobyteasr.studio_media_pool import add_media_asset,create_video_track,add_video_clip
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe';ffprobe=ffmpeg.with_name('ffprobe.exe')
    if args.synthetic:
        media=out/'wideband.mp4'
        signal='0.09*sin(2*PI*440*t)+0.06*sin(2*PI*3500*t)+0.04*sin(2*PI*9000*t)+0.025*sin(2*PI*14000*t)+0.06*random(0)*lt(mod(t,1),0.02)'
        run_hidden_subprocess([str(ffmpeg),'-v','error','-f','lavfi','-i','color=navy:s=640x360:r=30:d=300',
            '-f','lavfi','-i',f'aevalsrc={signal}|{signal.replace("440","880")}:s=48000:d=300',
            '-c:v','libx264','-preset','ultrafast','-c:a','aac','-b:a','256k','-shortest',str(media)],purpose='isolated wideband fixture',check=True,timeout=90)
        v1=v2=media
    else:
        v1=Path.home()/'Desktop/未眠野PV_版本1.mp4';v2=Path.home()/'Desktop/未眠野PV_版本1_1.mp4'
    def probe(path):
        result=run_hidden_subprocess([str(ffprobe),'-v','error','-show_format','-show_streams','-of','json',str(path)],purpose='read-only media duration',capture_output=True,check=True,timeout=20)
        data=json.loads(result.stdout);v=next(s for s in data['streams'] if s['codec_type']=='video')
        return round(float(data['format']['duration'])*1000),v['width'],v['height']
    duration,width,height=probe(v1);duration2,_,_=probe(v2)
    project=SubtitleProject(media=StudioMedia(path=str(v1),duration_ms=duration,width=width,height=height),
        cues=[StudioCue('audio-probe',0,min(duration,duration2),'持续音频验证')])
    project.validate();asset=add_media_asset(project,v2,fingerprint='audio-probe-v2',duration_ms=duration2)
    track=create_video_track(project);add_video_clip(project,track.id,asset.asset_id,timeline_in_ms=0)
    project.validate();project.studio_state.update(playhead_ms=0,last_selected_cue='audio-probe')
    path=out/'fixture.2byteproj';save_project(project,path)
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='workflow-sustained-audio',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_STARTUP_PROJECT=str(path),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        QT_QPA_PLATFORM='windows',TWOBYTEASR_AUDIO_CASES=args.cases,PYTHONIOENCODING='utf-8',PYTHONUTF8='1',
        TWOBYTEASR_AUDIO_TRACE='1')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    if args.transitions:env['TWOBYTEASR_AUDIO_TRANSITIONS']='1'
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command+[str(path)],cwd=root,env=env,output=out,timeout=sum(c[2] for c in json.loads(args.cases))+260)
    receipt=json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps(dict(exit_code=code,completed=receipt['completed'],error=receipt.get('error'),cases=len(receipt['cases']))))
    return 0 if code==0 and receipt['completed'] else 1

if __name__=='__main__':raise SystemExit(main())
