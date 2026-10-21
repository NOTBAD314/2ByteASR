"""Distinct-source V1/V2 audio workflow on an isolated normal application entry."""
import argparse
import json
import os
from pathlib import Path
import sys


def prepare_fixture(root, out, *, gap=True, background=False):
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,AudioTrack,AudioClip,sync_linked_av_contract,save_project
    from twobyteasr.timeline.studio_media_pool import add_media_asset,create_video_track,add_video_clip
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    sources=[]
    for name,freq,color in [('v1',440,'navy'),('v2',880,'maroon')]:
        source=out/(name+'.mp4')
        run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i',f'color={color}:s=640x360:r=30:d=12',
            '-f','lavfi','-i',f'sine=frequency={freq}:sample_rate=48000:duration=12',
            '-c:v','libx264','-preset','ultrafast','-c:a','pcm_s16le','-f','matroska',str(source)],
            purpose='isolated distinct-frequency routing fixture',check=True,timeout=30)
        sources.append(source)
    p=SubtitleProject(media=StudioMedia(str(sources[0]),duration_ms=12000,width=640,height=360));p.validate()
    p.video_tracks[0].enabled=False;p.video_tracks[0].locked=False;sequence_of(p).video_track_locked=False
    p.media_pool[0].audio_metadata['has_audio']=True
    asset=add_media_asset(p,sources[1],duration_ms=12000,video_metadata={'has_video':True,'width':640,'height':360,'fps':30},audio_metadata={'has_audio':True})
    t=create_video_track(p)
    intervals=[(0,4000),(6000,12000)] if gap else [(0,12000)]
    for start,end in intervals:add_video_clip(p,t.id,asset.asset_id,source_in_ms=start,source_out_ms=end,timeline_in_ms=start)
    sync_linked_av_contract(p)
    if background:
        music=add_media_asset(p,sources[0],duration_ms=12000)
        p.audio_tracks.append(AudioTrack('BGM','Independent same-source music',clips=[AudioClip('bgm-instance',music.asset_id,source_out_ms=12000,timeline_out_ms=12000)]))
    p.studio_state.update(playhead_ms=0,selected_video_track_id='V2',audio_master_mode='mix_all')
    path=out/'fixture.2byteproj';save_project(p,path)
    return path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--before',action='store_true')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('use a fresh tmp directory')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    project=prepare_fixture(root,out,gap=args.before)
    import shutil
    shutil.copy2(project,out/'pristine.2byteproj')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='workflow-sustained-audio' if args.before else 'audio-output-workflow',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_AUDIO_TRACE='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',QT_QPA_PLATFORM='windows',
        TWOBYTEASR_AUDIO_CASES='[["V2-visible",1,10]]',PYTHONUTF8='1',PYTHONIOENCODING='utf8')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code=run_audit_on_desktop(command+[str(project)],cwd=root,env=env,output=out,timeout=190,
        receipt=out/('result.json' if args.before else 'audio-workflow-result.json'),
        passed_field='completed' if args.before else 'passed')
    receipt = json.loads((out/('result.json' if args.before else 'audio-workflow-result.json')).read_text('utf8'))
    passed = code == 0 and (receipt.get('completed') if args.before else receipt.get('passed'))
    print(json.dumps(dict(exit_code=code,passed=bool(passed),output=str(out),before=args.before,error=receipt.get('error'))))
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
