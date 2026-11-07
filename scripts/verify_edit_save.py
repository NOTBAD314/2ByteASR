"""Owned fixed-path Studio editing fixture, source/frozen/root entry support."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--media', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--launcher', type=Path)
    parser.add_argument('--part', choices=['edits','saves','reliability','crash-recovery'], default='edits')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        parser.error('fresh source/tmp output required')
    out.mkdir(parents=True)
    original_hash = hashlib.sha256(args.project.read_bytes()).hexdigest()
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project,save_project,SubtitleProject,StudioMedia
    from twobyteasr.media.media_service import MediaService
    from twobyteasr.timeline.studio_edit_sequence import sequence_of,persist_sequence
    project = load_project(args.project)
    metadata = MediaService().metadata(args.media)
    old_path = project.media.path
    source = str(args.media.resolve())
    project.media.path = source
    project.media.fingerprint = metadata.fingerprint
    project.media.width,project.media.height = metadata.width,metadata.height
    for asset in project.media_pool:
        if asset.canonical_source == old_path:
            asset.canonical_source = source
            asset.fingerprint = metadata.fingerprint
            asset.video_metadata = asdict(metadata)
            asset.offline = False
    sequence = sequence_of(project)
    sequence.source_path = source
    for segment in sequence.segments:
        if segment.source_path == old_path:
            segment.source_path = source
    persist_sequence(project)
    target = args.target.resolve()
    if not target.is_relative_to(ROOT.parents[1]):
        parser.error('owned workspace target required')
    target.parent.mkdir(parents=True, exist_ok=True)
    save_project(project, target, compact=True)
    entry = save_project(SubtitleProject(StudioMedia('')),out/'entry.2byteproj')
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='edit-save',
        TWOBYTEASR_STARTUP_PROJECT=str(entry),EDIT_SAVE_PROJECT=str(target),
        EDIT_SAVE_PART='reliability' if args.part=='crash-recovery' else args.part,
        EDIT_SAVE_CRASH_AFTER_RECOVERY='1' if args.part=='crash-recovery' else '',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_MAIN_PYTHON=sys.executable,
        TWOBYTEASR_INVOKER_CWD=str(ROOT),QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',
        PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    if args.baseline:
        baseline = args.baseline.resolve()
        modules = {'.'.join(p.relative_to(baseline).with_suffix('').parts):str(p)
            for p in (baseline/'twobyteasr').rglob('*.py') if 'acceptance' not in p.parts
            and (ROOT/p.relative_to(baseline)).is_file() and p.read_bytes()!=(ROOT/p.relative_to(baseline)).read_bytes()}
        driver = out/'before_entry.py'
        driver.write_text('import sys,runpy,importlib.abc,importlib.util\n'
            +'sys.path.insert(0,'+repr(str(ROOT))+')\nmodules='+repr(modules)+'\n'
            +'class Before(importlib.abc.MetaPathFinder):\n'
            +' def find_spec(self,name,path=None,target=None):\n'
            +'  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'
            +'sys.meta_path.insert(0,Before())\nrunpy.run_path('+repr(str(ROOT/'quick_start.py'))+',run_name="__main__")\n','utf8')
        command=[sys.executable,'-B',str(driver)]
        env['EDIT_SAVE_BASELINE']='1'
    if args.launcher:
        from audit_launch_bridge import run_audit_on_desktop
        code = run_audit_on_desktop([str(args.launcher.resolve())],cwd=ROOT,env=env,
                                   output=out,timeout=450,receipt=out/'result.json')
    else:
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=450)
    p = out/'result.json'
    result = json.loads(p.read_text('utf8')) if p.exists() else dict(passed=False,error='missing receipt')
    result.update(process_exit=code, original_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==original_hash)
    if args.part == 'crash-recovery' and code == 91:
        reader = out/'reopen_recovery.py'
        reader.write_text(
            'import json,sys\nfrom pathlib import Path\n'
            +'sys.path.insert(0,'+repr(str(ROOT))+')\n'
            +"if __name__=='__main__':\n"
            +' from twobyteasr.projects.studio_project import recoverable_autosave,load_project\n'
            +' r=json.loads(Path(sys.argv[1]).read_text("utf8"))\n'
            +' recovered=recoverable_autosave(r["crash_target"])\n'
            +' assert recovered is not None\n'
            +' p=load_project(recovered)\n'
            +' assert p.cues[0].text==r["crash_expected_text"]\n'
            +' print("FRESH_PROCESS_RECOVERY_OK")\n','utf8')
        recovered = subprocess.run([sys.executable,'-B',str(reader),str(p)],env=env,capture_output=True,text=True)
        result['fresh_process_recovery'] = dict(exit_code=recovered.returncode,stdout=recovered.stdout,stderr=recovered.stderr)
        result['passed'] = bool(result.get('crash_ready') and recovered.returncode==0 and result['original_unchanged'])
    else:
        result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result['original_unchanged'])
    p.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','error','process_exit','original_unchanged')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
