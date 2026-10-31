"""Real problem-project copy, normal MainWindow entry, isolated Windows desktop."""
import argparse,hashlib,json,os,shutil,sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--glossary',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-source',type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--phase',choices=['functional','stability','idle','export'],default='functional')
    parser.add_argument('--idle-seconds',type=int,default=600)
    parser.add_argument('--profile',action='store_true')
    parser.add_argument('--library',help='Explicit local-library stress scope on the copied project only')
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('use a fresh source/tmp directory')
    out.mkdir(parents=True)
    inputs={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.project,args.glossary)}
    shutil.copy2(args.project,out/'project.2byteproj')
    if args.library:
        payload=json.loads((out/'project.2byteproj').read_text(encoding='utf-8-sig'))
        payload['glossary_ids']=[args.library]
        (out/'project.2byteproj').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    data=out/'local/2ByteASR';data.mkdir(parents=True)
    shutil.copy2(args.glossary,data/'learned_game_terms.json')
    # A private copy of the authored font, never a system font install.
    font=root.parent/'input/优设标题黑.ttf'
    if font.exists():
        target=out/'local/Microsoft/Windows/Fonts';target.mkdir(parents=True)
        shutil.copy2(font,target/font.name)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-followup',TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE='1600x950',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONFAULTHANDLER='1',
        STUDIO_FOLLOWUP_PHASE=args.phase,STUDIO_FOLLOWUP_IDLE_SECONDS=str(args.idle_seconds))
    env.update(GIT_CONFIG_COUNT='2',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=str(root),
        GIT_CONFIG_KEY_1='safe.directory',GIT_CONFIG_VALUE_1=str(args.baseline_source.resolve() if args.baseline_source else root))
    if args.profile:env['STUDIO_FOLLOWUP_PROFILE']='1'
    if args.baseline_source:env['STUDIO_FOLLOWUP_BASELINE_SOURCE']=str(args.baseline_source.resolve())
    from isolated_windows_desktop import run_on_desktop
    command=[args.exe.resolve()] if args.exe else [sys.executable,'-B',root/'scripts/studio_followup_entry.py']
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=args.idle_seconds+300 if args.phase=='idle' else 900)
    file=out/'result.json';result=json.loads(file.read_text('utf-8')) if file.exists() else {}
    result.update(process_exit=code,inputs_unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in inputs.items()))
    result['passed']=bool(code==0 and result.get('passed') and result.get('gui_shutdown') and result['inputs_unchanged'])
    file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result.get(k) for k in ('passed','process_exit','error','project','timings','checks')},ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
