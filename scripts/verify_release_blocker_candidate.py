"""Launch the fixed smoke scenario through the normal entry, fully isolated."""
import argparse,json,os,sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    output=args.output.resolve()
    if not output.is_relative_to(root/'tmp'):raise ValueError('output must be in workspace tmp')
    output.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    from twobyteasr.processes import run_hidden_subprocess
    fixture=output/'synthetic.mp4'
    run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-y','-f','lavfi','-i','color=blue:s=320x180:r=12:d=2','-c:v','libx264',fixture],purpose='release fixture',check=True,timeout=30)
    p=SubtitleProject(media=StudioMedia(path=str(fixture),duration_ms=2000,width=320,height=180),cues=[StudioCue('cue',100,1600,'合成验收')])
    project=save_project(p,output/'startup.2byteproj')
    env=os.environ.copy()
    env.update(USERPROFILE=str(output),QT_QPA_PLATFORM='offscreen',TWOBYTEASR_ACCEPTANCE_SCENARIO='release-blockers',
        TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',PYTHONDONTWRITEBYTECODE='1')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    command.append(str(project))
    result=run_hidden_subprocess(command,purpose='isolated release candidate smoke',cwd=root,env=env,capture_output=True,timeout=100)
    (output/'stdout.log').write_bytes(result.stdout);(output/'stderr.log').write_bytes(result.stderr)
    receipt=json.loads((output/'result.json').read_text(encoding='utf8'))
    receipt['process_exit_code']=result.returncode
    (output/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')
    if result.returncode or not receipt.get('passed') or not all(receipt['checks'].values()):raise RuntimeError(receipt)
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
