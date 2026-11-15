"""Normal Studio entry with owned media, mouse gestures and real export metering."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--scale',default='1');parser.add_argument('--theme',default='sand')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():parser.error('fresh output under tmp required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,save_project
    from twobyteasr.timeline.studio_media_pool import add_media_asset,create_video_track,add_video_clip,set_audio_master_mode
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe';media=out/'fixture.mp4'
    subprocess.run([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=c=0x26343d:s=960x540:r=12:d=327',
        '-f','lavfi','-i','sine=frequency=997:sample_rate=48000:duration=327','-af','volume=0.4',
        '-c:v','libx264','-preset','ultrafast','-c:a','aac','-ac','2','-shortest',str(media)],
        check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    text="And uh but I just also say you what I'm going to do here does require studio."
    import re
    tokens=list(re.finditer(r'\S+',text));words=[];cursor=0;weights=[1+i%4 for i in range(len(tokens))]
    for token,weight in zip(tokens,weights):
        a=321039+round(cursor/sum(weights)*5681);cursor+=weight
        words.append(dict(text=token.group(),start_ms=a,end_ms=321039+round(cursor/sum(weights)*5681)))
    p=SubtitleProject(media=StudioMedia(str(media),duration_ms=327000,width=960,height=540),
        cues=[StudioCue('c132',321039,326720,text,evidence_refs=['fixture'])],asr_evidence={'fixture':{'words':words}})
    p.generation_metadata['language']={'code':'en','requested':'en'};p.validate()
    for track in (*p.video_tracks,*p.audio_tracks):track.locked=False
    asset=add_media_asset(p,media,duration_ms=327000,video_metadata={'has_video':True},audio_metadata={'has_audio':True})
    track=create_video_track(p);add_video_clip(p,track.id,asset.asset_id,source_out_ms=12000)
    set_audio_master_mode(p,'mix_all')
    for track in (*p.video_tracks,*p.audio_tracks):track.locked=False
    fixture=out/'fixture.2byteproj';save_project(p,fixture)
    env=os.environ.copy();env.update(QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,TWOBYTEASR_VOLUME_THEME=args.theme,
        TWOBYTEASR_ACCEPTANCE_SCENARIO='english-track-loudness',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):env.pop(key,None)
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-X','utf8',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=360,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').is_file() else {}
    print(json.dumps(dict(output=str(out),exit=code,passed=result.get('passed'),checks=len(result.get('checks',[])),error=result.get('error')),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') else 1


if __name__=='__main__':raise SystemExit(main())
