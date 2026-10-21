"""Run the ordinary app on a private Windows desktop with copied inputs."""
import argparse, hashlib, json, os, shutil, sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--media',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--usage',type=Path)
    parser.add_argument('--autosave',type=Path)
    parser.add_argument('--route',choices=('direct','home','recent','switch'),default='direct')
    parser.add_argument('--full',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('Use a new output folder under this source tmp')
    out.mkdir(parents=True)
    raw=json.loads(args.project.read_text('utf-8-sig')); old=raw['media']['path']
    def relink(value):
        if isinstance(value,dict):return {k:relink(v) for k,v in value.items()}
        if isinstance(value,list):return [relink(v) for v in value]
        return str(args.media.resolve()) if value==old else value
    raw=relink(raw);raw['report_path']=''
    raw.setdefault('studio_state',{})['playhead_ms']=12909
    project=out/'problem-copy.2byteproj';project.write_text(json.dumps(raw,ensure_ascii=False),'utf8')
    if args.autosave:
        recovery=relink(json.loads(args.autosave.read_text('utf-8-sig')))
        recovery['report_path']=''
        from twobyteasr.projects.media_graph_integrity import graph_integrity
        # Relinking the owned copy changes its graph hash. Keep its original
        # project/caption data, and sign the relocated graph as normal save does.
        recovery.setdefault('autosave',{})['project_path']=str(project)
        recovery['autosave']['media_graph_integrity']=graph_integrity(recovery)
        # The original snapshot's data is preserved. Only its lookup filename
        # follows the new, owned project path, as production autosave does.
        directory=out/'autosave';directory.mkdir()
        key=hashlib.sha256(str(project.resolve()).encode('utf8')).hexdigest()[:24]
        candidate=directory/(key+'.2byteproj')
        candidate.write_text(json.dumps(recovery,ensure_ascii=False),'utf8')
        os.utime(candidate,(project.stat().st_mtime+2,project.stat().st_mtime+2))
    if args.settings:
        dest=out/'config';dest.mkdir(parents=True)
        shutil.copy2(args.settings,dest/'2byteasr_settings.json')
    if args.usage:
        # A read-only SQLite backup also includes committed WAL rows.
        import sqlite3
        dest=out/'local/2ByteASR';dest.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(args.usage.resolve().as_uri()+'?mode=ro',uri=True) as src:
            with sqlite3.connect(dest/'api-usage.sqlite3') as dst:src.backup(dst)
    env=os.environ.copy()
    for key in ('QT_QPA_PLATFORM','TWOBYTEASR_TEST_ROOT','TWOBYTEASR_ACCEPTANCE_PROFILE_DIR',
                'TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_DIAGNOSTIC_NO_PLAYER'):
        env.pop(key,None)
    env.update(TWOBYTEASR_TEST_ROOT=str(out),QT_QPA_PLATFORM='windows',PYTHONUTF8='1',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='open-followup',
        TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
        TWOBYTEASR_FOLLOWUP_ROUTE=args.route,TWOBYTEASR_FOLLOWUP_FULL=str(int(args.full)))
    if args.autosave:env['TWOBYTEASR_FOLLOWUP_RECOVERY']='1'
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    if args.route=='direct':command.append(str(project))
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=480)
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').is_file() else {}
    receipt=dict(exit_code=code,passed=code==0 and result.get('passed') and result.get('gui_shutdown'),
        checks=len(result.get('checks',[])),settings='copied' if args.settings else 'fresh',route=args.route,
        input_sha256=hashlib.sha256(args.project.read_bytes()).hexdigest(),output=str(out),error=result.get('error'))
    (out/'process-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(receipt,ensure_ascii=True))
    return 0 if receipt['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
