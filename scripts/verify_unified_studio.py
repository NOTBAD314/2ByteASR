# SPDX-License-Identifier: GPL-3.0-only
"""Run a guarded normal candidate MainWindow on owned project/MOV copies."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--project',required=True,type=Path)
    parser.add_argument('--source',type=Path,help='Explicit actual source; defaults to project primary media')
    parser.add_argument('--copy-source',action='store_true')
    parser.add_argument('--mov',type=Path)
    parser.add_argument('--mode',choices=('studio','completion','workshop'),default='studio')
    parser.add_argument('--completion-report',type=Path)
    parser.add_argument('--profile-root',type=Path,help='Explicit owned formal QA profile for prepared models/runtimes')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--export-ms',type=int,default=2117)
    parser.add_argument('--cancel-ms',type=int,default=12000)
    parser.add_argument('--skip-cancel',action='store_true')
    parser.add_argument('--skip-export',action='store_true')
    parser.add_argument('--scale',choices=('1','1.25','1.5'),default='1')
    parser.add_argument('--timeout',type=int,default=1500)
    parser.add_argument('--job-timeout',type=int,default=600)
    args=parser.parse_args()
    output=args.output.resolve()
    profile=(args.profile_root or output).resolve()
    if 'tmp' not in (part.lower() for part in profile.parts):
        parser.error('Explicit owned tmp profile required')
    if output.exists() or not (output.is_relative_to((ROOT/'tmp').resolve()) or (args.profile_root and output.is_relative_to(profile))):
        parser.error('Use a fresh output under repository tmp or explicit owned tmp profile')
    if not args.project.is_file():parser.error('A retained real project is required')
    if args.mode=='studio' and (not args.mov or not args.mov.is_file()):parser.error('Actual preserved transparent MOV is required')
    if args.mode=='completion' and (not args.completion_report or not args.completion_report.is_file()):parser.error('Retained actual completion report is required')
    payload=json.loads(args.project.read_text('utf-8-sig'))
    source=(args.source or Path(payload['media']['path'])).resolve()
    if not source.is_file():parser.error('Actual primary source must exist')
    originals={str(args.project.resolve()):sha(args.project),str(source):sha(source)}
    if args.mov:originals[str(args.mov.resolve())]=sha(args.mov)
    if args.completion_report:originals[str(args.completion_report.resolve())]=sha(args.completion_report)
    output.mkdir(parents=True);fixture=output/'inputs';fixture.mkdir()
    shutil.copy2(args.project,fixture/'original.2byteproj')
    profile=(args.profile_root or output).resolve()
    if not profile.is_absolute() or 'tmp' not in (p.lower() for p in profile.parts):
        parser.error('Owned tmp profile required')
    os.environ['TWOBYTEASR_TEST_ROOT']=str(profile)
    os.environ['TWOBYTEASR_STARTUP_TRACE']=str(output/'startup-trace.jsonl')
    from verify_export_target_real import relocate_project_media,project_timeline_extent
    extent=project_timeline_extent(payload)
    if args.mode=='studio' and not args.skip_export:
        ranges=[args.export_ms]+([] if args.skip_cancel else [args.cancel_ms])
        if any(value<=0 or value>extent['timeline_ms'] for value in ranges):
            parser.error('Real export/cancellation range must fit the actual project timeline')
    if args.copy_source:
        copied=fixture/('primary'+source.suffix);shutil.copy2(source,copied);source=copied
    payload,relocation=relocate_project_media(payload,payload['media']['path'],str(source))
    project_path=fixture/'audit.2byteproj'
    project_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf8')
    mov=None
    if args.mov:
        mov=fixture/'preserved-overlay.mov';shutil.copy2(args.mov,mov)
    report=None
    if args.completion_report:
        report=fixture/'retained-completion-report.json';shutil.copy2(args.completion_report,report)
    inputs=dict(mode=args.mode,project=str(project_path),overlay_mov=str(mov) if mov else None,
        completion_report=str(report) if report else None,original_files=originals,
        source_relocation=relocation,timeline_extent=extent,export_ms=args.export_ms,
        cancel_ms=args.cancel_ms,cancel=not args.skip_cancel,export=not args.skip_export,
        job_timeout=args.job_timeout,timeline_window_ms=max(3000,min(12000,extent['timeline_ms'])),
        source_copy=bool(args.copy_source),design_scope='Original cue/speaker/manual/styles unchanged; actual MOV added through normal media pool')
    (output/'input.json').write_text(json.dumps(inputs,ensure_ascii=False,indent=2),'utf8')
    from twobyteasr.test_isolation import install
    install();env=os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE','TWOBYTEASR_STARTUP_LEAVE_STUDIO','TWOBYTEASR_READINESS_VISUAL'):
        env.pop(key,None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='unified-studio',
        TWOBYTEASR_STARTUP_PROJECT=str(project_path),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_EXPORT_LOG_ROOT=str(output/'diagnostics'),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,QT_ENABLE_HIGHDPI_SCALING='0',
        QT_FONT_DPI='96',QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough',PYTHONUTF8='1',
        PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    if args.profile_root:
        if profile.parent.name.lower()!='tmp' or not output.is_relative_to(profile):
            parser.error('Formal profile output must be inside its direct owned tmp profile')
        env['TWOBYTEASR_ACCEPTANCE_PROFILE_DIR']=str(profile)
        env['TWOBYTEASR_INVOKER_CWD']=str(profile.parent.parent)
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(command,cwd=ROOT,env=env,output=output/'process',timeout=args.timeout)
    target=output/'result.json'
    result=json.loads(target.read_text('utf8')) if target.is_file() else dict(passed=False,error='No normal GUI receipt')
    result.update(process_exit=code,normal_entry_command=command)
    result['original_file_hashes_unchanged']=all(Path(path).is_file() and sha(path)==digest for path,digest in originals.items())
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result['original_file_hashes_unchanged'] and result.get('provider_calls')==0)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],output=str(output),mode=args.mode,checks=len(result.get('checks',[])),exports=len(result.get('exports',[])),process_exit=code,error=result.get('error')),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
