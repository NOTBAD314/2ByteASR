
"""Measure the production editor on a private Windows desktop, source or frozen."""
import argparse,json,os,sys
from pathlib import Path
def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--fixtures",type=Path,required=True)
    parser.add_argument("--size",type=int,choices=(100,500,511,2000,10000),default=100)
    parser.add_argument("--profile",action="store_true",help="Diagnostic cProfile run; not comparable latency data")
    parser.add_argument("--calls",action="store_true",help="Bounded per-method timings, GUI separated from workers")
    parser.add_argument("--control", choices=("none", "no-lexicon", "no-draft"), default="none")
    parser.add_argument("--mode",choices=("no-player","paused","playing","no-preview","hwdec-no","vo-gpu"),default="paused")
    parser.add_argument("--exe",type=Path)
    parser.add_argument("--baseline",type=Path)
    parser.add_argument('--core-baseline', type=Path,
                        help='Saved pre-fix studio_project.py; restore only pretty autosave and unconditional dictionary warmup')
    parser.add_argument("--cycles",type=int,default=3)
    parser.add_argument('--soak-seconds', type=int, default=0)
    parser.add_argument('--reopens', type=int, default=20)
    parser.add_argument('--diagnostics', choices=('on','off'), default='on')
    parser.add_argument('--edit-soak', type=int, default=0,
                        help='2026-10-21: N typed edits + Enter on different cues, no reopen; GUI blocked time per Enter')
    parser.add_argument('--batch-style', action='store_true',
                        help='with --edit-soak: first select all, click the 已选 scope and move Y twice')
    # 2026-10-22 (report-eb10): what the reporting user did between edits.
    parser.add_argument('--soak-seek', action='store_true',
                        help='with --edit-soak: move the playhead onto each edited cue so its caption is shown')
    parser.add_argument('--soak-pause-every', type=int, default=0,
                        help='with --edit-soak: after every N-th edit stay idle --soak-pause-s seconds (autosave runs)')
    parser.add_argument('--soak-pause-s', type=float, default=4.0)
    parser.add_argument('--soak-click-every', type=int, default=0,
                        help='with --edit-soak: commit every N-th edit by clicking the timeline instead of Enter')
    parser.add_argument('--soak-search', default='',
                        help='with --edit-soak: afterwards type this text into find/replace, one character at a time')
    parser.add_argument('--open-timing', action='append', default=[], metavar='LABEL=PROJECT',
                        help='2026-10-21: open these projects (fresh copies) and record readiness stages')
    parser.add_argument('--open-repeats', type=int, default=2)
    parser.add_argument('--freeze-audit', type=Path, metavar='PROJECT',
                        help='time filter clicks, save, seek+play and page switches on a copy of PROJECT')
    parser.add_argument('--freeze-repeats', type=int, default=2)
    parser.add_argument('--freeze-ballast', type=int, default=0,
                        help='with --freeze-audit: keep this many small dicts alive (post-recognition heap)')
    parser.add_argument('--freeze-switch', default='',
                        help='with --freeze-audit: sys.setswitchinterval value in seconds')
    parser.add_argument('--recovery-waits', default='',
                        help='with --open-timing: seconds the autosave recovery prompt stays up, e.g. 2,40')
    args=parser.parse_args();out=args.output.resolve();fixture=args.fixtures.resolve()
    if not out.is_relative_to(root/"tmp") or not fixture.is_relative_to(root/"tmp"):
        parser.error("Evidence and fixtures must be inside repository tmp")
    if out.exists():parser.error("Use a fresh evidence directory")
    out.mkdir(parents=True)
    os.environ["TWOBYTEASR_TEST_ROOT"]=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.acceptance.editor_diagnostics_audit import prepare_fixtures
    prepare_fixtures(root,fixture)
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    entry=out/"entry.2byteproj";save_project(SubtitleProject(media=StudioMedia(path="")),entry)
    env=os.environ.copy()
    env.update(TWOBYTEASR_STARTUP_TRACE=str(out/"startup.jsonl"),QT_QPA_PLATFORM="windows",PYTHONUTF8="1",
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO="editor-diagnostics",TWOBYTEASR_STARTUP_PROJECT=str(entry),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_EDITOR_FIXTURES=str(fixture),
        TWOBYTEASR_EDITOR_SIZE=str(args.size),TWOBYTEASR_EDITOR_MODE=args.mode,
        TWOBYTEASR_EDITOR_CYCLES=str(args.cycles))
    env["TWOBYTEASR_EDITOR_CONTROL"] = args.control
    env['TWOBYTEASR_EDITOR_SOAK_SECONDS'] = str(args.soak_seconds)
    env['TWOBYTEASR_EDITOR_REOPENS'] = str(args.reopens)
    env['TWOBYTEASR_EDITOR_DIAGNOSTICS'] = '1' if args.diagnostics == 'on' else '0'
    if args.edit_soak:
        env.update(TWOBYTEASR_EDIT_SOAK='1', TWOBYTEASR_SOAK_ITERATIONS=str(args.edit_soak),
                   TWOBYTEASR_SOAK_BATCH='1' if args.batch_style else '0',
                   TWOBYTEASR_SOAK_SEEK='1' if args.soak_seek else '0',
                   TWOBYTEASR_SOAK_PAUSE_EVERY=str(args.soak_pause_every),
                   TWOBYTEASR_SOAK_PAUSE_S=str(args.soak_pause_s),
                   TWOBYTEASR_SOAK_CLICK_EVERY=str(args.soak_click_every),
                   TWOBYTEASR_SOAK_SEARCH=args.soak_search)
    if args.open_timing:
        projects=[f"{label}={Path(path).resolve()}" for label,path in (item.split('=',1) for item in args.open_timing)]
        env.update(TWOBYTEASR_OPEN_TIMING='1',TWOBYTEASR_OPEN_PROJECTS=';'.join(projects),
                   TWOBYTEASR_OPEN_REPEATS=str(args.open_repeats),TWOBYTEASR_OPEN_RECOVERY_WAITS=args.recovery_waits)
    if args.freeze_audit:
        env.update(TWOBYTEASR_FREEZE_AUDIT='1',TWOBYTEASR_FREEZE_PROJECT=str(args.freeze_audit.resolve()),
                   TWOBYTEASR_FREEZE_REPEATS=str(args.freeze_repeats),
                   TWOBYTEASR_FREEZE_BALLAST=str(args.freeze_ballast),
                   TWOBYTEASR_FREEZE_SWITCH=args.freeze_switch)
    if args.profile: env["TWOBYTEASR_EDITOR_PROFILE"]="1"
    if args.calls: env["TWOBYTEASR_EDITOR_CALLS"]="1"
    for key in ("NO_PLAYER","NO_EDIT_PREVIEW","HWDEC","VO"):env.pop("TWOBYTEASR_DIAGNOSTIC_"+key,None)
    if args.mode=="no-player":env["TWOBYTEASR_DIAGNOSTIC_NO_PLAYER"]="1"
    if args.mode=="no-preview":env["TWOBYTEASR_DIAGNOSTIC_NO_EDIT_PREVIEW"]="1"
    if args.mode=="hwdec-no":env["TWOBYTEASR_DIAGNOSTIC_HWDEC"]="no"
    if args.mode=="vo-gpu":env["TWOBYTEASR_DIAGNOSTIC_VO"]="gpu"
    if args.baseline:env["TWOBYTEASR_EDITOR_BASELINE"]=str(args.baseline.resolve())
    if args.core_baseline:env['TWOBYTEASR_EDITOR_CORE_BASELINE']=str(args.core_baseline.resolve())
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,"-B",str(root/"quick_start.py")]
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=root,env=env,output=out/"process",timeout=300+args.soak_seconds)
    result=json.loads((out/"result.json").read_text("utf8")) if (out/"result.json").exists() else {}
    print(json.dumps(dict(exit_code=code,output=str(out),passed=result.get("passed"),error=result.get("error"),
        cases=[dict(name=r["name"],stats=r["stats"]) for r in result.get("cases",[])]),ensure_ascii=False))
    return 0 if code==0 and result.get("passed") and result.get("gui_shutdown") else 1
if __name__=="__main__":raise SystemExit(main())

