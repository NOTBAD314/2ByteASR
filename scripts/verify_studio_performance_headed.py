"""Whole-project controlled input, frame, commit, save and event-loop timing."""
import argparse,hashlib,json,os,shutil,sys
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','presets','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--glossary',type=Path)
    parser.add_argument('--baseline-source',type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--phase',choices=('batch','single','save','all'),default='batch')
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):parser.error('Use a fresh source/tmp output')
    out.mkdir(parents=True);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    font=args.presets.resolve().parent/'优设标题黑.ttf'
    inputs={str(p.resolve()):sha(p) for p in (args.project,args.presets,args.glossary,font if font.exists() else None) if p}
    project=out/'性能验收副本.2byteproj';shutil.copy2(args.project,project)
    store=out/'local/2ByteASR/SubtitleStudioPreview';store.mkdir(parents=True)
    shutil.copy2(args.presets,store/'style-presets.json')
    if args.glossary:shutil.copy2(args.glossary,out/'local/2ByteASR/learned_game_terms.json')
    if font.exists():
        folder=out/'local/Microsoft/Windows/Fonts';folder.mkdir(parents=True);shutil.copy2(font,folder/font.name)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-performance' if args.exe else 'review-editor',
        TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE='1600x950',
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',
        PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',STUDIO_PERF_VISIBLE='1' if args.visible else '0',
        STUDIO_PERF_PHASE=args.phase,STUDIO_PERF_ROUNDS=str(args.rounds))
    if args.baseline_source:env['INTERACTION_BASELINE_SOURCE']=str(args.baseline_source.resolve())
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'scripts/studio_performance_entry.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=600,
                        **({'desktop_name':'Default'} if args.visible else {}))
    file=out/'result.json';r=json.loads(file.read_text(encoding='utf8')) if file.exists() else {}
    r.update(process_exit=code,inputs_unchanged=all(sha(Path(p))==value for p,value in inputs.items()))
    r['inputs_sha256']=inputs
    if args.exe:
        r['exe_sha256']=sha(args.exe)
        r['build_identity']=json.loads((args.exe.parent/'2byteasr_build.json').read_text(encoding='utf8'))
    r['passed']=bool(r.get('passed') and r.get('gui_shutdown') and code==0 and r['inputs_unchanged'])
    file.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:r.get(k) for k in ('passed','error','project','operations','cold_interactive_ms','hot_reopen_ms')},ensure_ascii=False))
    return 0 if r['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
