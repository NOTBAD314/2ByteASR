"""Read-only copy of the requested template; two ordinary app processes."""
import argparse,json,os,sys,time,hashlib,shutil
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Use new workspace/tmp output')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,save_project,hydrate_media_contract
    from twobyteasr.studio_helpers import probe_media_identity
    source=Path(os.environ['USERPROFILE'])/'AppData/Local/2ByteASR/cover-workspace/templates'
    key='bdda449597484a968cc6c3f800ce1bfd';entry=json.loads((source/(key+'.json')).read_text('utf8'))
    target=out/'config/cover-workspace/templates';target.mkdir(parents=True)
    originals={}
    for name in (key+'.json',entry['cover'],entry['thumbnail']):
        originals[name]=hashlib.sha256((source/name).read_bytes()).hexdigest();shutil.copy2(source/name,target/name)
    media=out/'fixture.mp4'
    run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
        'testsrc2=size=1280x720:rate=30','-t','7','-c:v','libx264','-preset','ultrafast','-an',media],
        timeout=30,check=True,purpose='isolated changing video fixture')
    project=SubtitleProject(media=StudioMedia(str(media),duration_ms=7000,width=1280,height=720))
    hydrate_media_contract(project,probe_media_identity(str(media)));fixture=out/'fixture.2byteproj';save_project(project,fixture)
    env=os.environ.copy();env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='windows',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='cover-frame',TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',PYTHONIOENCODING='utf8')
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,str(root/'quick_start.py')]
    reports=[]
    for phase in ('create','reopen'):
        env['TWOBYTEASR_COVER_FRAME_PHASE']=phase
        with (out/(phase+'-process.log')).open('wb') as log:
            child=run_hidden_subprocess(cmd,cwd=root,env=env,stdout=log,stderr=log,timeout=240,purpose='normal Studio frozen template audit')
        result=out/(phase+'-cover-frame.json');until=time.monotonic()+200
        while not result.exists() and time.monotonic()<until:time.sleep(.2)
        reports.append(json.loads(result.read_text('utf8')))
        if not reports[-1]['passed']:break
    unchanged=all(hashlib.sha256((source/name).read_bytes()).hexdigest()==digest for name,digest in originals.items())
    value=dict(passed=len(reports)==2 and all(x['passed'] for x in reports) and unchanged,source_template_unchanged=unchanged,phases=reports)
    (out/'result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=value['passed'],output=str(out),errors=[r.get('error') for r in reports]),ensure_ascii=False))
    return 0 if value['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
