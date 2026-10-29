"""Isolated normal-entry clip-assistant acceptance with real read-only media."""
from __future__ import annotations
import argparse,json,os,re,sys,shutil
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--transcript-project',type=Path)
    parser.add_argument('--media',type=Path)
    parser.add_argument('--xml',type=Path)
    parser.add_argument('--srt',type=Path)
    parser.add_argument('--error-project',type=Path)
    parser.add_argument('--lang',default='zh')
    parser.add_argument('--timeout',type=int,default=480)
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('fresh directory under tmp required')
    out.mkdir(parents=True)
    profile=out/'profile';os.environ['TWOBYTEASR_TEST_ROOT']=str(profile)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import project_from_runtime_cues,save_project,parse_subtitle_timecode_ms,load_project
    from twobyteasr.media.danmaku_binding import bind_manual,inspect_xml
    project=load_project(args.transcript_project) if args.transcript_project else None
    if project is None and args.media is None:raise ValueError('--transcript-project or --media is required')
    media=Path(project.media.path) if project else args.media.resolve()
    xml=args.xml or media.with_suffix('.xml');srt=args.srt
    for p in (media,xml):
        if not p.is_file():raise FileNotFoundError(p)
    cues=[]
    blocks=re.split(r'\n\s*\n',srt.read_text('utf-8-sig').strip()) if srt else []
    for i,block in enumerate(blocks):
        lines=block.splitlines()
        time_line=next((j for j,line in enumerate(lines) if '-->' in line),None)
        if time_line is None:continue
        a,b=lines[time_line].split('-->')
        start,end=parse_subtitle_timecode_ms(a),parse_subtitle_timecode_ms(b)
        if start is not None and end is not None:
            cues.append(SimpleNamespace(cue_id=f'real-srt-{i}',start=start/1000,end=end/1000,
                                        text=' '.join(lines[time_line+1:]),speaker='S00'))
    project=project or project_from_runtime_cues(media,cues)
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    sequence_of(project).video_track_locked=False
    for track in project.video_tracks:track.locked=False
    count,duration,error=inspect_xml(xml)
    bind_manual(project,str(xml),count,duration,error)
    fixture=out/'projects'/'real.2byteproj';fixture.parent.mkdir()
    save_project(project,fixture)
    # Saved user error project is copied only; all following opens/saves use it.
    error_source=args.error_project
    if error_source and error_source.is_file():shutil.copy2(error_source,out/'projects'/'save-error-copy.2byteproj')
    (out/'sources.json').write_text(json.dumps(dict(media=str(media),xml=str(xml),srt=str(srt or ''),
        cue_count=len(project.cues),danmaku_count=count,
        subtitle_alignment=('source-anchored one-minute local ASR excerpt; no human listening' if args.transcript_project else
                            'same-stem SRT is NOT verified as source-aligned; UI-only fixture'),
        transcript_project=str(args.transcript_project or '')),ensure_ascii=False,indent=2),'utf-8')
    local,roaming=out/'local',out/'roaming';local.mkdir();roaming.mkdir()
    settings=profile/'local'/'2ByteASR'/'2byteasr_settings.json';settings.parent.mkdir(parents=True,exist_ok=True)
    settings.write_text(json.dumps({'schema_version':1,'models':{'polish_api_key':'','polish_llm_service':'custom'}}),'utf-8')
    env={k:v for k,v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local),APPDATA=str(roaming),TWOBYTEASR_TEST_ROOT=str(profile),
        TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='clip-suggestions',TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',
        TWOBYTEASR_CLIP_AUDIT_LANG=args.lang,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HTTP_PROXY='http://127.0.0.1:9',
        HTTPS_PROXY='http://127.0.0.1:9',NO_PROXY='127.0.0.1,localhost')
    env['2BYTEASR_USER_DATA_ROOT']=str(local)
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=args.timeout)
    receipt=out/'result.json'
    result=json.loads(receipt.read_text('utf-8')) if receipt.exists() else {'errors':['no result']}
    print(json.dumps({'exit':code,'passed':result.get('passed'),'checks':result.get('checks'),
                      'errors':result.get('errors')},ensure_ascii=False,indent=2))
    return 0 if code==0 and result.get('passed') else 1

if __name__=='__main__':raise SystemExit(main())
