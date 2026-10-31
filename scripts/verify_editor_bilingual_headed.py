"""Copied real Austin project and recovery checkpoints; normal Home click."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys


def main():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--autosaves',type=Path);p.add_argument('--baseline-source',type=Path)
    p.add_argument('--exe',type=Path);p.add_argument('--gui',type=Path);p.add_argument('--entry-bridge',type=Path)
    p.add_argument('--cycles',type=int,default=3);p.add_argument('--theme',default='grape')
    p.add_argument('--open-only',action='store_true');p.add_argument('--recovery-policy',default='ask')
    p.add_argument('--restart',action='store_true')
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):p.error('Use a fresh source/tmp output')
    out.mkdir(parents=True);shutil.copy2(a.project,out/'project.2byteproj')
    original_hash=hashlib.sha256(a.project.read_bytes()).hexdigest()
    key=hashlib.sha256(str((out/'project.2byteproj').resolve()).encode('utf8')).hexdigest()[:24]
    archive=out/'autosave';archive.mkdir()
    copied=[]
    if a.autosaves:
        for file in a.autosaves.iterdir():
            if not file.is_file():continue
            name=key+file.name[file.name.index('.'):]
            target=archive/name;shutil.copy2(file,target)
            copied.append(dict(source=str(file),copied=str(target),sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    sys.path.insert(0,str(root))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import studio_settings_path
    settings=studio_settings_path();settings.parent.mkdir(parents=True,exist_ok=True)
    payload=dict(studio_preferences=dict(autosave_enabled=False,recovery_policy=a.recovery_policy),
        recent_projects=[dict(path=str(out/'project.2byteproj'),name='Austin GP · 完整工程验收副本',cue_count=1392,
            last_opened='2026-10-31T04:12:05+00:00')])
    settings.write_text(json.dumps(payload,ensure_ascii=False),'utf8')
    (out/'input.json').write_text(json.dumps(dict(cycles=a.cycles,theme=a.theme,open_only=a.open_only,
        source_sha256=original_hash,autosaves=copied),ensure_ascii=False,indent=2),'utf8')
    env=dict(os.environ,TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='editor-bilingual',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='0',
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE='1600x980',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',PYTHONUTF8='1',HF_HUB_OFFLINE='1')
    if a.baseline_source:env['REVIEW_EDITOR_BASELINE_SOURCE']=str(a.baseline_source.resolve())
    cmd=[sys.executable,'-B','-X','utf8',str(root/'scripts/review_editor_entry.py')]
    if a.exe:cmd=[str(a.exe.resolve())]
    if a.gui:
        cmd=[sys.executable,'-B',str(a.entry_bridge.resolve()),'--launcher',str(a.exe.resolve()),
            '--gui',str(a.gui.resolve()),'--output',str(out),'--timeout','600']
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(cmd,cwd=root,env=env,output=out/'process',timeout=620)
    file=out/'result.json';result=json.loads(file.read_text('utf8')) if file.exists() else {}
    result.update(process_exit=code,input_unchanged=hashlib.sha256(a.project.read_bytes()).hexdigest()==original_hash)
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result['input_unchanged'])
    if a.restart and result['passed']:
        (out/'first-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        spec=json.loads((out/'input.json').read_text('utf8'));spec['phase']='restart'
        (out/'input.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),'utf8')
        restart_code=run_on_desktop(cmd,cwd=root,env=env,output=out/'restart-process',timeout=200)
        restarted=json.loads(file.read_text('utf8'));restarted['process_exit']=restart_code
        result['restart']=restarted
        result['passed']=bool(result['passed'] and restarted.get('passed') and restarted.get('gui_shutdown') and restart_code==0)
    file.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({key:result.get(key) for key in ('passed','process_exit','error','opens','gap_state')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
