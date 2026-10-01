"""Launch workflow GUI checks without switching the user's desktop."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path);p.add_argument('--glossary-result',type=Path)
    p.add_argument('--scenario',default='workflow-glossary-selection')
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Fresh tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    from twobyteasr.processes import run_hidden_subprocess
    media=out/'fixture.mp4'
    run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-f','lavfi','-i','color=navy:s=640x360:r=30:d=8',
        '-c:v','libx264','-preset','ultrafast',str(media)],purpose='isolated GUI fixture',check=True,timeout=30)
    project=SubtitleProject(media=StudioMedia(path=str(media),duration_ms=8000,width=640,height=360),cues=[StudioCue('gui',0,5000,'交互验证')])
    project.validate();path=out/'fixture.2byteproj';save_project(project,path)
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO=args.scenario,
        TWOBYTEASR_STARTUP_PROJECT=str(path),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONIOENCODING='utf8')
    if args.glossary_result:env['TWOBYTEASR_GLOSSARY_RESULT']=str(args.glossary_result.resolve())
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(cmd+[str(path)],cwd=root,env=env,output=out,timeout=420)
    result=json.loads((out/'result.json').read_text('utf8'));print(json.dumps(dict(exit_code=code,completed=result.get('completed'),error=result.get('error')),ensure_ascii=False))
    return 0 if code==0 and result.get('completed') else 1


if __name__=='__main__':raise SystemExit(main())
