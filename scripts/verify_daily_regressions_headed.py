"""Normal-entry Windows audit of the reported daily regressions; isolated writes."""
from pathlib import Path
import argparse, json, os, shutil, subprocess, sys

def main():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--theme',default='grape')
    p.add_argument('--scale',default='1')
    p.add_argument('--size',default='1600x980')
    p.add_argument('--exe',type=Path)
    p.add_argument('--gui',type=Path)
    p.add_argument('--entry-bridge',type=Path)
    p.add_argument('--visible',action='store_true')
    p.add_argument('--restart',action='store_true')
    p.add_argument('--manual',action='store_true')
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        p.error('Choose a new directory under this source/tmp')
    out.mkdir(parents=True)
    shutil.copyfile(a.project.resolve(),out/'project.2byteproj')
    shutil.copyfile(a.report.resolve(),out/'report.json')
    report=json.loads((out/'report.json').read_text('utf8'))
    report['result']['outputs']['project']=str(out/'project.2byteproj')
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False),'utf8')
    project=json.loads((out/'project.2byteproj').read_text('utf8'))
    project['report_path']=str(out/'report.json')
    (out/'project.2byteproj').write_text(json.dumps(project,ensure_ascii=False),'utf8')
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    sys.path.insert(0,str(root))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import studio_settings_path
    recent=[]
    for i in range(14):
        path=out/f'工程{i+1}.2byteproj';shutil.copyfile(out/'project.2byteproj',path)
        recent.append(dict(path=str(path),name=f'工程{i+1} · 验收副本',cue_count=207,last_opened=f'2026-10-30T{23-i:02d}:00:00+08:00'))
    settings=studio_settings_path();settings.parent.mkdir(parents=True,exist_ok=True)
    settings.write_text(json.dumps(dict(recent_projects=recent),ensure_ascii=False),'utf8')
    (out/'input.json').write_text(json.dumps(dict(theme=a.theme,visible=a.visible,manual=a.manual),ensure_ascii=False),'utf8')
    env=dict(os.environ,TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='daily-regressions',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE=a.size,
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=a.scale,
        PYTHONUTF8='1',HF_HUB_OFFLINE='1')
    cmd=[sys.executable,'-X','utf8','-B',str(root/'scripts/review_editor_entry.py')]
    if a.exe:cmd=[str(a.exe.resolve())]
    if a.gui:
        cmd=[sys.executable,'-B',str(a.entry_bridge.resolve()),'--launcher',str(a.exe.resolve()),
             '--gui',str(a.gui.resolve()),'--output',str(out),'--timeout','480']
    if a.visible:
        with (out/'process.log').open('wb') as log:
            code=subprocess.run(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,
                                timeout=480,creationflags=0x08000000).returncode
    else:
        sys.path.insert(0,str(root/'scripts'))
        from isolated_windows_desktop import run_on_desktop
        code=run_on_desktop(cmd,cwd=root,env=env,output=out/'process',timeout=480)
    file=out/'result.json';r=json.loads(file.read_text('utf8')) if file.exists() else {}
    r['process_exit']=code;r['passed']=bool(r.get('passed') and r.get('gui_shutdown') and code==0)
    if a.restart and r['passed']:
        file.with_name('first-result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),'utf8')
        spec=json.loads((out/'input.json').read_text('utf8'));spec['phase']='restart'
        (out/'input.json').write_text(json.dumps(spec,ensure_ascii=False),'utf8')
        restart_env=dict(env);restart_env.pop('TWOBYTEASR_STARTUP_SIZE',None)
        restart_env['TWOBYTEASR_ACCEPTANCE_PRESERVE_WINDOW_STATE']='1'
        if a.visible:
            with (out/'restart-process.log').open('wb') as log:
                restart_code=subprocess.run(cmd,cwd=root,env=restart_env,stdout=log,stderr=subprocess.STDOUT,
                    timeout=180,creationflags=0x08000000).returncode
        else:
            restart_code=run_on_desktop(cmd,cwd=root,env=restart_env,output=out/'restart-process',timeout=180)
        restart=json.loads(file.read_text('utf8')) if file.exists() else {}
        restart['process_exit']=restart_code
        r['restart']=restart
        r['passed']=bool(r['passed'] and restart.get('passed') and restart.get('gui_shutdown') and restart_code==0)
        if not r['passed']:r['error']=restart.get('error','restart failed')
    file.write_text(json.dumps(r,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:r.get(k) for k in ['passed','process_exit','gui_shutdown','error']},ensure_ascii=False))
    return 0 if r['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
