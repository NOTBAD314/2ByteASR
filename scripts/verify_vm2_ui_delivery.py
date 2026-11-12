"""Verify the delivered interfaces through the normal Windows app entry."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--scale',default='1')
    args=parser.parse_args();output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):raise ValueError('Use a fresh source/tmp output')
    output.mkdir(parents=True)
    protected={}
    for name,p in [('project',args.project.resolve()),('report',args.report.resolve())]:
        protected[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        shutil.copy2(p,output/('retained'+p.suffix))
    (output/'input.json').write_text(json.dumps(dict(project=str(output/('retained'+args.project.suffix)),
        report=str(output/('retained'+args.report.suffix)),protected=protected,scale=args.scale,
        scope='Normal MainWindow, retained real terminal result, synthetic history failures and update offers; no new provider request; process Qt scaling, Windows DPI unchanged'),ensure_ascii=False,indent=2),'utf8')
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    startup=output/'startup.2byteproj';save_project(SubtitleProject(media=StudioMedia(path='')),startup)
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,QT_ENABLE_HIGHDPI_SCALING='0',
        QT_FONT_DPI='96',QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough',TWOBYTEASR_ACCEPTANCE_SCENARIO='vm2-ui-delivery',
        TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_STARTUP_PROJECT=str(startup),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_TEST_ROOT=str(output/'profile'),LOCALAPPDATA=str(output/'profile/local'),APPDATA=str(output/'profile/roaming'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=output,timeout=300,receipt=output/'result.json')
    for path,digest in protected.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise RuntimeError('Original task changed: '+path)
    (output/'process-exit.json').write_text(json.dumps(dict(exit_code=code,originals_preserved=True)),'utf8')
    return code

if __name__=='__main__':raise SystemExit(main())
