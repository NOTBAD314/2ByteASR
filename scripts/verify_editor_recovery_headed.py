
"""Isolated abnormal termination/native fault followed by GUI recovery."""
import argparse,json,os,sys,threading,time,subprocess
from pathlib import Path
def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--exe",type=Path)
    parser.add_argument("--native",action="store_true")
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/"tmp"):parser.error("Use a fresh tmp output directory")
    out.mkdir(parents=True);profile=out
    os.environ["TWOBYTEASR_TEST_ROOT"]=str(profile)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,save_project
    fixture=out/"recovery.2byteproj";entry=out/"entry.2byteproj"
    save_project(SubtitleProject(StudioMedia(""),cues=[StudioCue("c0",0,2000,"原句"),StudioCue("c1",2000,4000,"下一句")]),fixture)
    save_project(SubtitleProject(StudioMedia("")),entry)
    env=os.environ.copy()
    env.update(QT_QPA_PLATFORM="windows",PYTHONUTF8="1",TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",
        TWOBYTEASR_DIAGNOSTIC_NO_PLAYER="1",TWOBYTEASR_ACCEPTANCE_SCENARIO="editor-recovery",
        TWOBYTEASR_RECOVERY_FIXTURE=str(fixture),TWOBYTEASR_ACCEPTANCE_PROFILE_DIR=str(profile),TWOBYTEASR_INVOKER_CWD=str(root))
    from isolated_windows_desktop import run_on_desktop
    results=[]
    for phase in (("native" if args.native else "terminate"),"restore"):
        evidence=out/phase;evidence.mkdir()
        phase_entry=evidence/"entry.2byteproj"
        phase_entry.write_bytes(entry.read_bytes())
        env.update(TWOBYTEASR_STARTUP_PROJECT=str(phase_entry),TWOBYTEASR_ACCEPTANCE_DIR=str(evidence),TWOBYTEASR_RECOVERY_PHASE=phase,
            TWOBYTEASR_STARTUP_TRACE=str(evidence/"startup.jsonl"))
        command=[str(args.exe.resolve())] if args.exe else [sys.executable,"-B",str(root/"quick_start.py")]
        stop=threading.Event()
        fault_cleanup={}
        def close_faulted_test():
            # Some CRT/Windows handlers remain in post-fault processing on a
            # private desktop. Preserve evidence, then stop only this owned tree.
            while not stop.wait(.25):
                info=evidence/"process/desktop.json"
                result_path=evidence/"result.json"
                faults=list(profile.glob("local/2ByteASR/logs/diagnostic-sessions/*/native-fault.txt"))
                if not info.exists() or not result_path.exists():continue
                has_fault=any(p.stat().st_size>100 for p in faults)
                if not has_fault and "pre_fault_snapshot" not in fault_cleanup:
                    owned=json.loads(info.read_text("utf8"))
                    pid=json.loads(result_path.read_text("utf8"))["pid"]
                    import psutil
                    parent=psutil.Process(owned["pid"])
                    if pid!=parent.pid and pid not in {p.pid for p in parent.children(recursive=True)}:
                        raise RuntimeError("Unexpected pre-fault test owner")
                    from capture_test_process_dump import capture
                    dump=profile/"local/2ByteASR/logs/crash-dumps/pre-fault-context.dmp"
                    fault_cleanup["pre_fault_snapshot"]=capture(pid,dump,phase="pre-fault")
                if not has_fault:continue
                time.sleep(3)
                owned=json.loads(info.read_text("utf8"))
                pid=json.loads(result_path.read_text("utf8"))["pid"]
                import psutil
                try:
                    parent=psutil.Process(owned["pid"])
                    require_owned=pid==parent.pid or pid in {p.pid for p in parent.children(recursive=True)}
                    if not require_owned:raise RuntimeError("Unexpected fault test owner")
                    from capture_test_process_dump import capture
                    dump=profile/"local/2ByteASR/logs/crash-dumps/controlled-fault.dmp"
                    fault_cleanup["dump"]=capture(pid,dump)
                    fault_cleanup["termination"]="owned test terminated after native stack and post-fault process snapshot; not proof of automatic fault termination"
                    subprocess.run(["taskkill","/PID",str(parent.pid),"/T","/F"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                except psutil.NoSuchProcess: fault_cleanup["termination"]="native exit before cleanup"
                except Exception as exc: fault_cleanup["dump_error"]=type(exc).__name__+": "+str(exc)
                return
        if phase=="native":threading.Thread(target=close_faulted_test,daemon=True).start()
        try:code=run_on_desktop(command,cwd=root,env=env,output=evidence/"process",timeout=100)
        finally:stop.set()
        result=json.loads((evidence/"result.json").read_text("utf8")) if (evidence/"result.json").exists() else {}
        result["exit_code"]=code;result["fault_cleanup"]=fault_cleanup;results.append(result)
        print(json.dumps(dict(phase=phase,code=code,passed=result.get("passed"),error=result.get("error")),ensure_ascii=False),flush=True)
        if not result.get("passed"):break
    faults=list(profile.glob("local/2ByteASR/logs/diagnostic-sessions/*/native-fault.txt"))
    fault_bytes=sum(p.stat().st_size for p in faults)
    passed=len(results)==2 and all(r.get("passed") for r in results) and results[-1]["exit_code"]==0
    if args.native:passed=passed and fault_bytes>100
    summary=dict(passed=passed,native=args.native,native_fault_bytes=fault_bytes,phases=results)
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),"utf8")
    return 0 if passed else 1
if __name__=="__main__":raise SystemExit(main())

