"""Run the confirmed field-project copy in a private desktop and isolated profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--project',type=Path,required=True);ap.add_argument('--exe',type=Path)
    args=ap.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):ap.error('fresh repo tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    raw=args.project.read_bytes();original=hashlib.sha256(raw).hexdigest()
    copy=out/'field-source.2byteproj';copy.write_bytes(raw)
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    entry=save_project(SubtitleProject(media=StudioMedia('',duration_ms=0)),out/'entry.2byteproj')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='export-visibility-stalls',
        TWOBYTEASR_FIELD_PROJECT=str(copy),TWOBYTEASR_STARTUP_PROJECT=str(entry),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_SEEK_CACHE_ROOT=str(root/'tmp/field-seek-cache'),
        QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=1200)
    result=json.loads((out/'result.json').read_text(encoding='utf-8')) if (out/'result.json').exists() else {}
    unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==original
    print(json.dumps(dict(exit_code=code,completed=result.get('completed'),passed=result.get('passed'),
        project_unchanged=unchanged,output=str(out)),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') and unchanged else 1


if __name__=='__main__':raise SystemExit(main())
