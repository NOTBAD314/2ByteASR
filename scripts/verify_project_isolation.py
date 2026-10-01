"""Create private projects and run the normal source/frozen Studio entry."""
import argparse,copy,json,os,sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--baseline',type=Path)
    parser.add_argument('--user-copies',type=Path)
    parser.add_argument('--clean-machine',action='store_true')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('New tmp output required')
    if args.clean_machine and (not args.exe or not out.is_relative_to(args.exe.resolve().parent/'tmp')):
        parser.error('--clean-machine requires --exe and a new output under the installed directory/tmp')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    folder=out/'projects';folder.mkdir()
    for name,color in [('A','navy'),('B','green')]:
        run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',f'color={color}:s=640x360:r=30:d=8',
            '-c:v','libx264','-preset','ultrafast',out/(name+'.mp4')],purpose='project isolation fixture',check=True,timeout=30)
    for name,text,media in [('A','PROJECT A OWN','A'),('B','PROJECT B OWN','B'),('empty','','B'),('same-id','COPIED PROJECT OWN','A')]:
        p=SubtitleProject(media=StudioMedia(path=str(out/(media+'.mp4')),duration_ms=8000,width=640,height=360),
            cues=[StudioCue('same-cue',0,6000,text)] if text else [])
        if name in {'A','same-id'}:p.project_id='copied-project-id'
        p.validate();save_project(p,folder/(name+'.2byteproj'))
    if args.user_copies:
        for path in args.user_copies.glob('*.2byteproj'):
            r=json.loads(path.read_text('utf-8-sig'))
            name='user-B' if '大饭包' in path.name else 'user-A'
            # Original data and media remain read-only; archive paths belong
            # to the private copy, not the user's project store.
            r['studio_state']={**r.get('studio_state',{}),'playhead_ms':0}
            (folder/(name+'.2byteproj')).write_text(json.dumps(r,ensure_ascii=False),'utf8')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='project-isolation',
        TWOBYTEASR_STARTUP_PROJECT=str(folder/'A.2byteproj'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',QT_QPA_PLATFORM='windows',PYTHONIOENCODING='utf8')
    if args.baseline:env['TWOBYTEASR_ISOLATION_BASELINE']=str(args.baseline.resolve())
    if args.clean_machine:
        if not args.exe:parser.error('--clean-machine requires --exe')
        profile=out/'profile';profile.mkdir()
        env.update(USERPROFILE=str(profile), PYTHONPATH='', PYTHONHOME='',
            PATH=os.pathsep.join([os.environ['SystemRoot'],str(Path(os.environ['SystemRoot'])/'System32')]),
            **{'2BYTEASR_MODEL_ROOT':str(profile/'models')})
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command+[str(folder/'A.2byteproj')],cwd=args.exe.resolve().parent if args.clean_machine else root,env=env,output=out/'process',timeout=300)
    result=json.loads((out/'result.json').read_text('utf8'));result['process_exit_code']=code
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'exit_code':code,'error':result.get('error')},ensure_ascii=False))
    return 0 if result['passed'] and code==0 else 1

if __name__=='__main__':raise SystemExit(main())
