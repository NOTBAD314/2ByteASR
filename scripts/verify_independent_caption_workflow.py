"""Normal-entry independent-caption workflow on a private Windows desktop."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--user-project',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a fresh repository tmp directory')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,load_project
    from twobyteasr.timeline.studio_media_pool import create_video_track,add_media_asset,add_video_clip
    from twobyteasr.timeline.studio_edit_sequence import sequence_of,projected_cues
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    for name,color,tone in [('base','red',440),('edit','blue',880)]:
        run_hidden_subprocess([str(ffmpeg),'-v','error','-f','lavfi','-i',f'color={color}:s=640x360:r=30:d=20',
            '-f','lavfi','-i',f'sine=frequency={tone}:duration=20:sample_rate=48000',
            '-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(out/(name+'.mp4'))],
            purpose='isolated caption workflow fixture',check=True,timeout=45)
    p=SubtitleProject(media=StudioMedia(str(out/'base.mp4'),duration_ms=20000,width=640,height=360),cues=[
        StudioCue('before',8000,9000,'区间前 / BEFORE','S1'),
        StudioCue('left',9500,10500,'左跨界 / LEFT','S1'),
        StudioCue('inside',10200,11400,'区间内删除 / REMOVE','S1'),
        StudioCue('right',11500,12500,'右跨界 / RIGHT','S1'),
        StudioCue('cross',9000,13000,'11223344','S2',evidence_refs=['exact']),
        StudioCue('after',12500,14000,'区间后 / AFTER','S2')])
    p.asr_evidence={'exact':{'words':[{'text':text,'start_ms':a,'end_ms':b} for text,a,b in
        [('11',9000,9900),('22',10200,10900),('33',11100,11900),('44',12200,12900)]]}}
    p.validate();p.video_tracks[0].locked=True;p.video_tracks[0].enabled=False
    sequence_of(p).video_track_locked=True
    asset=add_media_asset(p,str(out/'edit.mp4'),duration_ms=20000,video_metadata={'width':640,'height':360})
    lane=create_video_track(p,'V2');lane.locked=False
    clip=add_video_clip(p,lane.id,asset.asset_id,timeline_in_ms=0)
    clip_edit_command(p,lane.id,'split',clip_id=clip.id,time_ms=10000).redo()
    path=save_project(p,out/'fixture.2byteproj')
    plan={'kind':'independent-caption-workflow','project':str(path),'raw_cues':p.to_dict()['cues'],
          'raw_asr':copy.deepcopy(p.asr_evidence),'protected_project':None}
    if args.user_project:
        source=args.user_project.resolve();copy_path=out/'protected-actual-copy.2byteproj'
        shutil.copy2(source,copy_path);actual=load_project(copy_path)
        plan['protected_project']={'source':str(source),'copy':str(copy_path),
            'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'raw_cues':actual.to_dict()['cues'],'displayed_cues':[__import__('dataclasses').asdict(c) for c in projected_cues(actual)],
            'asr_evidence':actual.asr_evidence,'speakers':actual.to_dict()['speakers']}
    (out/'caption-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf8')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='independent-caption-workflow',
        TWOBYTEASR_STARTUP_PROJECT=str(path),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_TRACE=str(out/'startup-trace.jsonl'),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',PYTHONUTF8='1',PYTHONIOENCODING='utf8',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from audit_launch_bridge import run_audit_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(cmd+[str(path)],cwd=ROOT,env=env,output=out,timeout=420,receipt=out/'caption-workflow-result.json')
    target=out/'caption-workflow-result.json'
    result=json.loads(target.read_text('utf8')) if target.is_file() else {'passed':False,'error':'Missing GUI receipt'}
    result['process_exit']=code
    if args.user_project:
        result['protected_source_unchanged']=hashlib.sha256(args.user_project.read_bytes()).hexdigest()==plan['protected_project']['sha256']
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result.get('protected_source_unchanged',True))
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':result['passed'],'exit_code':code,'checks':len(result.get('checks',[])),'error':result.get('error')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
