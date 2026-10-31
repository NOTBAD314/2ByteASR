"""Normal-entry real-project UI verification on an owned Windows desktop."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--presets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-source',type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--theme',default='warm')
    args=parser.parse_args()
    if args.exe and args.baseline_source:parser.error('frozen verification cannot import an external baseline')
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('Use a fresh source/tmp output')
    out.mkdir(parents=True)
    original=hashlib.sha256(args.project.read_bytes()).hexdigest()
    project=out/'project.2byteproj';shutil.copy2(args.project,project)
    font=root.parent/'input/优设标题黑.ttf'
    if font.is_file():
        target=out/'local/Microsoft/Windows/Fonts';target.mkdir(parents=True)
        shutil.copy2(font,target/font.name)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='review-editor',TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE='1600x950',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',
        INTERACTION_PRESETS=str(args.presets.resolve()),INTERACTION_THEME=args.theme)
    if args.baseline_source:env['INTERACTION_BASELINE_SOURCE']=str(args.baseline_source.resolve())
    if args.exe:env['TWOBYTEASR_ACCEPTANCE_SCENARIO']='studio-interaction'
    from isolated_windows_desktop import run_on_desktop
    command=[args.exe.resolve()] if args.exe else [sys.executable,'-B',root/'scripts/studio_performance_profile_entry.py']
    code=run_on_desktop(command,
        cwd=root,env=env,output=out/'process',timeout=420)
    file=out/'result.json'
    result=json.loads(file.read_text(encoding='utf8')) if file.exists() else {}
    result.update(process_exit=code,source_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==original)
    result['passed']=bool(result.get('passed') and code==0 and result.get('gui_shutdown') and result['source_unchanged'])
    file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','process_exit','error','project','samples')},ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
