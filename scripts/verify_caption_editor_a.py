"""Run approved-caption-editor acceptance through normal source, EXE or launcher."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--font',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--baseline-source',type=Path)
    parser.add_argument('--theme',default='warm')
    parser.add_argument('--size',default='1600x950')
    parser.add_argument('--scale',default='1')
    args=parser.parse_args()
    out=args.output.resolve();original=args.project.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('Use a fresh directory under this source/tmp')
    out.mkdir(parents=True)
    checksum=hashlib.sha256(original.read_bytes()).hexdigest()
    copied=out/'project.2byteproj';shutil.copy2(original,copied)
    fontdir=out/'local/Microsoft/Windows/Fonts';fontdir.mkdir(parents=True)
    shutil.copy2(args.font,fontdir/args.font.name)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-editor-a',TWOBYTEASR_STARTUP_PROJECT=str(copied),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE=args.size,TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,
        PYTHONUTF8='1',HF_HUB_OFFLINE='1',CAPTION_EDITOR_A_THEME=args.theme)
    if args.baseline_source:
        env.update(REVIEW_EDITOR_BASELINE_SOURCE=str(args.baseline_source.resolve()),CAPTION_EDITOR_A_BASELINE='1')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'scripts/review_editor_entry.py')]
    sys.path.insert(0,str(root/'scripts'))
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=420)
    receipt=out/'result.json'
    result=json.loads(receipt.read_text(encoding='utf8')) if receipt.exists() else {}
    result.update(process_exit=code,input_unchanged=hashlib.sha256(original.read_bytes()).hexdigest()==checksum)
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result['input_unchanged'])
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({key:result.get(key) for key in ['passed','process_exit','gui_shutdown','error','input_unchanged']},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
