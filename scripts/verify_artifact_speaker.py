"""Real local workers; isolated data and Windows desktop; no installer."""
import argparse
import json
import os
import shutil
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path)
    p.add_argument('--sample',type=Path);p.add_argument('--sample-start',type=float,default=0)
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Fresh tmp directory required')
    out.mkdir(parents=True)
    runtime=Path(os.environ['LOCALAPPDATA'])/'2ByteASR/runtimes/nemotron/py31213-torch211-cu128-tf4b28d51-v6/Scripts/python.exe'
    if not runtime.is_file():raise ValueError('Verified Nemotron v6 runtime missing; no automatic installation')
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    # Fresh copies, including model metadata, keep even loader writes away
    # from the installed models. No download/install occurs in this audit.
    for name in ('FireRedASR2-AED','FireRedVAD','Nemotron-3-Diarization'):
        shutil.copytree(root/'models'/name,out/'models'/name,dirs_exist_ok=True)
    from twobyteasr.processes import run_hidden_subprocess
    interpreters={}
    for role, interpreter in (('main',Path(sys.executable)),('nemotron',runtime)):
        target=out/'local/2ByteASR/runtimes'/role
        run_hidden_subprocess([str(interpreter),'-m','venv','--without-pip',str(target)],
            purpose='isolated verification interpreter',check=True,timeout=60)
        (target/'Lib/site-packages/qa-dependencies.pth').write_text(str(interpreter.parent.parent/'Lib/site-packages'),'utf8')
        interpreters[role]=target/'Scripts/python.exe'
    shutil.copy2(runtime.parent.parent/'nemotron-readiness.json',interpreters['nemotron'].parent.parent/'nemotron-readiness.json')
    media=out/'speech.mp4';sample=args.sample or root/'tmp/implementation-20260924/nemotron-human-sample.wav'
    run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-f','lavfi','-i','color=navy:s=640x360:r=30:d=18',
        '-ss',str(args.sample_start),'-i',str(sample),'-t','18','-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(media)],purpose='isolated real speech sample',check=True,timeout=30)
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    project=SubtitleProject(media=StudioMedia(path=str(media),duration_ms=18000,width=640,height=360),cues=[StudioCue('fixture',0,5000,'本地识别验收')])
    project.validate();path=out/'fixture.2byteproj';save_project(project,path)
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='artifact-speaker',
        TWOBYTEASR_STARTUP_PROJECT=str(path),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_NEMOTRON_PYTHON=str(interpreters['nemotron']),TWOBYTEASR_MAIN_PYTHON=str(interpreters['main']),PYTHONDONTWRITEBYTECODE='1',
        QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONIOENCODING='utf8',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(cmd+[str(path)],cwd=root,env=env,output=out,timeout=900)
    result=json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps(dict(exit_code=code,completed=result.get('completed'),error=result.get('error')),ensure_ascii=False))
    return 0 if code==0 and result.get('completed') else 1


if __name__=='__main__':raise SystemExit(main())
