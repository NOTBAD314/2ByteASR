# SPDX-License-Identifier: GPL-3.0-only
"""Run the actual shared license UI on an isolated Windows desktop/profile."""
import argparse, hashlib, json, os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--exe',type=Path);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--manifest',type=Path,required=True,help='Independent release-artifacts.json, not an identity read from the running app')
    args=ap.parse_args();out=args.output.resolve()
    manifest=json.loads(args.manifest.read_text('utf-8-sig'))
    if args.exe and hashlib.sha256(args.exe.read_bytes()).hexdigest()!=manifest['application_exe_sha256']:
        raise ValueError('Executable differs from independently selected release')
    if not out.is_relative_to(ROOT/'tmp') or out.exists():raise ValueError('New tmp directory required')
    out.mkdir(parents=True);sys.path.insert(0,str(ROOT))
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install();fixture=out/'guard.2byteproj';fixture.write_text('{}','utf8')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='gpl-migration',TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    env['TWOBYTEASR_ACCEPTANCE_MANIFEST']=str(args.manifest.resolve())
    from isolated_windows_desktop import run_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(cmd,cwd=ROOT,env=env,output=out/'process',timeout=90)
    p=out/'result.json';result=json.loads(p.read_text('utf8')) if p.exists() else {'passed':False,'error':'No receipt'}
    # A sealed older EXE may contain the previous audit. Its UI result cannot
    # establish this new check just because the launcher supplied an environment variable.
    expected_hash=hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if result.get('independent_manifest_sha256')!=expected_hash:
        result['passed']=False
        result['manifest_check_error']='Embedded audit did not attest the independent manifest; external UI verification is required for sealed older builds'
    result['exit_code']=code;p.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':result['passed'],'exit_code':code,'error':result.get('error'),'checks':len(result.get('checks',{}))}))
    return 0 if result['passed'] and code==0 else 1
if __name__=='__main__':raise SystemExit(main())
