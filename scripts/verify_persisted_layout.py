"""Prepare and run the normal GUI layout audit on copied GE captions.

The generated layout fixture reuses real text/media, with synthetic times. It
does not claim new ASR. Original project/media are protected by before/after SHA.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--video',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Fresh repository tmp output required')
    original=args.project.resolve()
    raw=json.loads(original.read_text('utf-8-sig'))
    media=Path(raw['media']['path'])
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    protected={str(original):sha(original),str(media):sha(media)}
    out.mkdir(parents=True);(out/'real-ge.2byteproj').write_bytes(original.read_bytes())
    # PROCESS_START is emitted during imports, before app-level isolation.
    os.environ['TWOBYTEASR_STARTUP_TRACE']=str(out/'startup-trace.jsonl')
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import (load_project,save_project,SubtitleProject,StudioCue,StudioSpeaker)
    from twobyteasr.timeline.studio_edit_sequence import projected_cues
    from twobyteasr.caption_style.style_resolution import resolve_cue_visual
    from twobyteasr.caption_style.subtitle_stacking import initialize_project_layout
    source=load_project(out/'real-ge.2byteproj');cues=list(projected_cues(source))
    pairs=[(a,b) for i,a in enumerate(cues) for b in cues[i+1:] if a.speaker_id!=b.speaker_id
           and min(a.end_ms,b.end_ms)-max(a.start_ms,b.start_ms)>150]
    if not pairs:raise ValueError('Source copy contains no verified cross-speaker overlap')
    pair=next((x for x in pairs if any('一幕' in c.text for c in x)),pairs[0])
    pair=tuple(sorted(pair,key=lambda c:(c.start_ms,c.id)))
    styles=[]
    for index,cue in enumerate(pair):
        style=resolve_cue_visual(source,cue).style
        style.id='default' if index==0 else 'second';style.name='布局验收 '+str(index+1)
        style.position_x=style.position_y=None;style.alignment=2;style.margin_v=43
        styles.append(style)
    speakers=[copy.deepcopy(s) for s in source.speakers if s.id in {c.speaker_id for c in pair}]
    generated=SubtitleProject(media=copy.deepcopy(source.media),styles=styles,speakers=speakers,
        cues=[StudioCue('initial-earlier',1000,4000,pair[0].text,speaker_id=pair[0].speaker_id),
              StudioCue('initial-later',1700,4500,pair[1].text,speaker_id=pair[1].speaker_id,style_id='second')])
    generated.render_settings=dict(source.render_settings);generated.render_settings['_cue_domain']='timeline'
    initialize_project_layout(generated);save_project(generated,out/'initial.2byteproj')
    real_point=round((max(c.start_ms for c in pair)+min(c.end_ms for c in pair))/2)
    plan=dict(kind='persisted_layout_real_copy_and_generated_fixture',protected=protected,
        generated_fixture='real media/text; synthetic 1.0/1.7-second cue starts; no new ASR',
        real_cue_count=len(source.cues),real_ids=[c.id for c in pair],real_point_ms=real_point,
        real_expected=[dict(id=c.id,text=c.text,start_ms=c.start_ms,end_ms=c.end_ms,speaker_id=c.speaker_id)
                       for c in source.cues],media_path=str(media),video=args.video)
    (out/'layout-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf8')
    if args.prepare_only:print(str(out/'layout-plan.json'));return 0
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='persisted-layout',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'initial.2byteproj'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONIOENCODING='utf8')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command+[str(out/'initial.2byteproj')],cwd=root,env=env,output=out,timeout=420)
    result=json.loads((out/'layout-result.json').read_text('utf8'))
    unchanged=all(sha(path)==value for path,value in protected.items())
    result['protected_originals_unchanged']=unchanged;result['exit_code']=code
    if result.get('videos'):
        from twobyteasr.system.processes import run_hidden_subprocess
        result['video_fully_decoded']=True
        for row in result['videos']:
            video=Path(row['path']);decode=run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),
                '-v','error','-i',str(video),'-map','0:v:0','-f','null','-'],capture_output=True,timeout=90,
                purpose='independent full layout video decode')
            row['fully_decoded']=decode.returncode==0
            result['video_fully_decoded'] &= row['fully_decoded']
            point=2.8 if row['kind']=='generated-manual-swap' else plan['real_point_ms']/1000
            target=out/f'export-frame-{row["kind"]}-{point:g}.png'
            captured=run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-ss',str(point),
                '-i',str(video),'-frames:v','1',str(target)],capture_output=True,timeout=30,purpose='layout output frame')
            result.setdefault('export_frames',[]).append(dict(path=str(target),point_seconds=point,decoded=captured.returncode==0))
    (out/'layout-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],exit_code=code,protected=unchanged,error=result.get('error')),ensure_ascii=False))
    return 0 if code==0 and result['passed'] and unchanged and result.get('video_fully_decoded',True) else 1


if __name__=='__main__':raise SystemExit(main())
