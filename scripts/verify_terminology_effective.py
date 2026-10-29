"""Normal source/frozen GUI acceptance with isolated data and a generated fixture."""
import argparse, json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--cli-receipt', type=Path, help='Redacted measured CLI receipt for explicit UI replay')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():
        raise ValueError('Choose a new output under repository tmp')
    out.mkdir(parents=True)
    import shutil
    receipt = args.cli_receipt.resolve() if args.cli_receipt else ROOT/'tmp/cli-real-receipt.json'
    if receipt.is_file():shutil.copy2(receipt,out/'cli-real-receipt.json')
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project
    video = out/'fixture.mp4'
    ffmpeg = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
        '-i', 'color=c=0x304044:s=640x360:r=25:d=6', '-f', 'lavfi', '-i',
        'sine=frequency=440:duration=6', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-shortest', str(video)], check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    project = SubtitleProject(media=StudioMedia(path=str(video),duration_ms=6000), cues=[
        StudioCue('term-a',100,1800,'Borlin也没有接住',speaker_id='S01'),
        StudioCue('term-b',1900,3600,'berlin也没有接住',speaker_id='S02'),
        StudioCue('term-c',3700,5600,'s0pp sopp xberlin',speaker_id='S01')],
        speakers=[StudioSpeaker('S01'),StudioSpeaker('S02')])
    fixture=out/'fixture.2byteproj'; save_project(project,fixture)
    env=os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='terminology-effective',
        TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(cmd,cwd=ROOT,env=env,output=out/'process',timeout=170)
    receipt=out/'result.json'
    result=json.loads(receipt.read_text('utf8')) if receipt.exists() else {'passed':False,'error':'GUI produced no receipt'}
    result['process_exit']=code
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0)
    if result['passed']:
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO']='terminology-restore'
        restore_code=run_on_desktop(cmd,cwd=ROOT,env=env,output=out/'restore-process',timeout=110)
        restore_receipt=out/'restore-result.json'
        restored=json.loads(restore_receipt.read_text('utf8')) if restore_receipt.exists() else {'passed':False,'error':'Restart produced no receipt'}
        restored['process_exit']=restore_code
        restored['passed']=bool(restored.get('passed') and restored.get('gui_shutdown') and restore_code==0)
        result['restart']=restored
        result['passed']=bool(result['passed'] and restored['passed'])
        if not restored['passed']:result['error']=restored.get('error','Restart validation failed')
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':result['passed'],'checks':len(result.get('checks',[])),
        'error':result.get('error'),'output':str(out)},ensure_ascii=False),flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
