"""Run the normal Windows MainWindow and its owned worker in an isolated desktop."""
from __future__ import annotations
import argparse,json,os,sys,wave,shutil
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--real-task',type=Path,help='Read-only original journal; copy its available project for real history/open checks')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):raise ValueError('Use a fresh source/tmp output')
    out.mkdir(parents=True)
    with wave.open(str(out/'fixture.wav'),'wb') as f:
        f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*48000)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    sys.path.insert(0,str(root))
    if args.real_task:
        from twobyteasr.recognition.task_journal import report_payload
        payload=report_payload(args.real_task)
        project_source=Path(payload['result']['outputs']['project'])
        project_copy=out/'retained-real-project.2byteproj'
        shutil.copy2(project_source,project_copy)
        payload['result']['outputs']['project']=str(project_copy)
        payload['task']['reports']=[]
        payload['task'].pop('optional_report',None)
        target=out/'retained-real-task'/payload['job_id']/'task.json'
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(payload,ensure_ascii=False),'utf-8')
        (out/'real-history-input.json').write_text(json.dumps({'record':str(target),
            'source':str(args.real_task.resolve()),'project':str(project_copy)},ensure_ascii=False),'utf-8')
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    project=save_project(SubtitleProject(media=StudioMedia(path=str(out/'fixture.wav'),duration_ms=3000),
        cues=[StudioCue('fixture',200,1200,'隔离验证')]),out/'fixture.2byteproj')
    env=dict(os.environ,TWOBYTEASR_ACCEPTANCE_SCENARIO='recognition-recovery',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',
        TWOBYTEASR_STARTUP_SIZE='1500x900',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=110)
    result=json.loads((out/'result.json').read_text(encoding='utf-8')) if (out/'result.json').is_file() else {'error':'No result'}
    result['exit_code']=code
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    expected_exit=code==0 or code==2 and result.get('checks',{}).get('cancelled_durable')
    return 0 if expected_exit and result.get('finished') and not result.get('error') and all(result['checks'].values()) else 1

if __name__=='__main__':raise SystemExit(main())
