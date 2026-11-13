"""Normal application proofread acceptance with owned projects and profile."""
from pathlib import Path
import argparse,hashlib,json,os,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--scale',default='1');p.add_argument('--exe',type=Path)
    args=p.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('fresh source/tmp output required')
    out.mkdir(parents=True);original=args.project.read_bytes();(out/'real.2byteproj').write_bytes(original)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out/'profile'),LOCALAPPDATA=str(out/'profile/local'),
        APPDATA=str(out/'profile/roaming'),TWOBYTEASR_ACCEPTANCE_SCENARIO='proofread-integrity',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_STARTUP_PROJECT=str(out/'real.2byteproj'),
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR=args.scale,QT_FONT_DPI='96',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    env.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=str(ROOT))
    if args.scale == 'native':
        for name in ('QT_SCALE_FACTOR','QT_FONT_DPI','QT_SCREEN_SCALE_FACTORS','QT_AUTO_SCREEN_SCALE_FACTOR'):
            env.pop(name,None)
        env['QT_ENABLE_HIGHDPI_SCALING']='1'
        env['TWOBYTEASR_ACCEPTANCE_NATIVE_DPI']='1'
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=420,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    result.update(process_exit=code,original_unchanged=args.project.read_bytes()==original,source_sha256=hashlib.sha256(original).hexdigest())
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result.get('passed'),checks=len(result.get('checks',[])),error=result.get('error'),
        exit=code,output=str(out)),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') and result['original_unchanged'] else 1


if __name__=='__main__':raise SystemExit(main())
