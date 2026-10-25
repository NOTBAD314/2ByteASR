import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--media',type=Path)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--cue-count',type=int,default=24)
    parser.add_argument('--initial-original',action='store_true')
    parser.add_argument('--ui-only',action='store_true')
    parser.add_argument('--open-only',action='store_true')
    parser.add_argument('--langs',default='',help='other interface languages to check the panel in, e.g. en,zh-Hant')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--exe-scenario',choices=('preview-clock','workbench-performance','caption-workbench'),default='preview-clock')
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args()
    if args.langs: os.environ['CAPTION_AUDIT_LANGS']=args.langs
    root=args.source.resolve() if args.source else Path(__file__).resolve().parents[1]
    out=args.output.resolve()
    if args.child:
        sys.path.insert(0,str(root))
        # The auditor is identical in both runs; imports of production code
        # resolve exclusively under the selected baseline/candidate source.
        import importlib.util
        spec=importlib.util.spec_from_file_location('twobyteasr.acceptance.caption_workbench_audit',
            Path(__file__).resolve().parents[1]/'twobyteasr/acceptance/caption_workbench_audit.py')
        audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
        sys.modules[spec.name]=audit
        route='caption-workbench'
        if route not in (root/'twobyteasr/acceptance/studio_acceptance_audit.py').read_text('utf8'):
            route='workbench-performance'
            sys.modules['twobyteasr.acceptance.workbench_performance_audit']=audit
        audit._early_events=[]
        audit._early_hook=audit.window_events(audit._early_events)
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
        fixture=out/'entry.2byteproj'
        save_project(SubtitleProject(media=StudioMedia('')),fixture)
        os.environ.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO=route,
            TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
        if args.media:os.environ['CAPTION_AUDIT_MEDIA']=str(args.media.resolve())
        os.environ['CAPTION_AUDIT_CUE_COUNT']=str(args.cue_count)
        if args.initial_original:os.environ['CAPTION_AUDIT_INITIAL_ORIGINAL']='1'
        if args.ui_only:os.environ['CAPTION_AUDIT_UI_ONLY']='1'
        if args.open_only:os.environ['CAPTION_AUDIT_OPEN_ONLY']='1'
        if args.project:
            import hashlib,shutil
            copied=out/'input-project.2byteproj'
            shutil.copy2(args.project,copied)
            (out/'input-provenance.json').write_text(json.dumps(dict(source=str(args.project.resolve()),
                sha256=hashlib.sha256(copied.read_bytes()).hexdigest()),ensure_ascii=False,indent=2),encoding='utf8')
            os.environ['CAPTION_AUDIT_PROJECT']=str(copied)
        if args.exe:
            import subprocess,time
            os.environ['TWOBYTEASR_ACCEPTANCE_SCENARIO']=args.exe_scenario
            if args.exe_scenario=='workbench-performance':
                if not args.media:raise ValueError('Existing performance scenario requires --media')
                os.environ.update(TWOBYTEASR_PERF_MEDIA=str(args.media.resolve()),
                    TWOBYTEASR_PERF_COUNTS=','.join([str(args.cue_count)]*3))
            from twobyteasr.system.processes import popen_hidden_subprocess, stop_process_tree
            with (out/'exe-stdout.log').open('w',encoding='utf8') as stdout, (out/'exe-stderr.log').open('w',encoding='utf8') as stderr:
                process=popen_hidden_subprocess([str(args.exe.resolve())],cwd=root,env=os.environ.copy(),
                    stdout=stdout,stderr=stderr,purpose='isolated existing daily verification')
                # caption-workbench: the whole MD / selection / bilingual route in the packaged program
                # (2026-10-24 daily port); the other two only measure an existing daily.
                try: code=process.wait(timeout=280 if args.exe_scenario=='caption-workbench' else 180)
                except subprocess.TimeoutExpired:
                    stop_process_tree(process);code=1
            audit._early_hook[0].close()
            (out/'windows.json').write_text(json.dumps(audit._early_events,ensure_ascii=False,indent=2),encoding='utf8')
            return code
        import runpy
        sys.argv=[str(root/'quick_start.py')]
        runpy.run_path(str(root/'quick_start.py'),run_name='__main__')
        return 0
    if out.exists(): raise ValueError('Use a fresh output directory')
    out.mkdir(parents=True)
    env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(out),QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[sys.executable,'-B',str(Path(__file__).resolve()),'--child','--source',str(root),'--output',str(out)]
    if args.media:command+=['--media',str(args.media.resolve())]
    if args.project:command+=['--project',str(args.project.resolve())]
    command+=['--cue-count',str(args.cue_count)]
    if args.initial_original:command+=['--initial-original']
    if args.ui_only:command+=['--ui-only']
    if args.open_only:command+=['--open-only']
    if args.exe:command+=['--exe',str(args.exe.resolve())]
    command+=['--exe-scenario',args.exe_scenario]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=300)
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    print(json.dumps(dict(exit_code=code,passed=result.get('passed'),error=result.get('error'),output=str(out)),ensure_ascii=False))
    return code


if __name__=='__main__':raise SystemExit(main())
