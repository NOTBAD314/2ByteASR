"""Run the production UI on an isolated short project using real local media."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('New tmp directory required')
    out.mkdir(parents=True)
    # Fixture construction is separate from the observed interaction trace.
    from twobyteasr.studio_project import SubtitleProject,StudioCue,StudioSpeaker
    from twobyteasr.studio_edit_sequence import EditSequence,VideoSegment,store_sequence
    from twobyteasr.studio_media_pool import sync_primary_video_track_from_sequence
    payload=json.loads(args.project.read_text(encoding='utf-8-sig'))
    p=SubtitleProject.from_dict(payload)
    if not Path(p.media.path).is_file():raise FileNotFoundError(p.media.path)
    p.cues=[StudioCue('before',1000,3100,'切割前：保留完整字幕','A'),
            StudioCue('cross',3000,7000,'同轨重叠\n仍然清晰可读','A'),
            StudioCue('after',7600,11600,'切割后：保留人工编辑','B'),
            StudioCue('tail',13000,17500,'后段字幕与素材保持同步','B')]
    p.speakers=[StudioSpeaker('A',name='主要候选'),StudioSpeaker('B',name='待整理候选')]
    p.style_recipes={};p.render_settings.pop('_cue_domain',None)
    p.studio_state['auto_subtitle_stacking']=True
    p.media_pool=[];p.video_tracks=[];p.audio_tracks=[];p.av_track_groups=[]
    seq=EditSequence(source_path=p.media.path,source_duration_ms=p.media.duration_ms,video_track_locked=False,
        segments=[VideoSegment('original',p.media.path,0,20000,0,20000)])
    store_sequence(p,seq);sync_primary_video_track_from_sequence(p,seq)
    p.generation_metadata={'timeline_recognition':{'sequence':seq.to_dict()},'speaker_recovery':{
        'raw_segments':[{'start':i,'end':i+.5,'text':'原始发言','speaker':'A' if i<11 else 'B'} for i in range(14)],
        'processing':{'mode':'native'}}}
    from twobyteasr.speaker_recovery import candidate_snapshot
    evidence=candidate_snapshot(p.generation_metadata['speaker_recovery']['raw_segments'])
    evidence['processing']={'mode':'native'}
    p.generation_metadata['speaker_recovery']=evidence
    p.validate()
    (out/'fixture.2byteproj').write_text(json.dumps(p.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    env=os.environ.copy();env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(100/175),PYTHONIOENCODING='utf-8',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='cut-range-frame',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    from twobyteasr.processes import run_hidden_subprocess
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    with (out/'application.log').open('wb') as log:
        result=run_hidden_subprocess(cmd,cwd=root,env=env,stdout=log,stderr=log,timeout=480,purpose='cut range frame production UI acceptance')
    report=json.loads((out/'runtime.json').read_text(encoding='utf-8'))
    print(json.dumps(dict(passed=report['passed'],exit_code=result.returncode,error=report.get('error')),ensure_ascii=False))
    return 0 if report['passed'] and result.returncode==0 else 1


if __name__=='__main__':raise SystemExit(main())
