"""Open the fixed replay in normal Studio on an isolated Windows desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--comparison',type=Path,required=True)
    p.add_argument('--project',type=Path,help='Open a private copy of the evidence-preserving candidate with its real media.')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path)
    p.add_argument('--preview-term',action='append',help='Capture the first matching cue for each requested term.')
    p.add_argument('--viewport-audit',action='store_true')
    args=p.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a fresh source/tmp output')
    output.mkdir(parents=True)
    comparison=json.loads(args.comparison.read_text(encoding='utf-8'))
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import project_from_runtime_cues,save_project,load_project
    import subtitle_core as core
    if args.project:
        project=load_project(args.project)
    else:
        media=output/'fixture.mp4'
        subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-y','-v','error','-f','lavfi',
            '-i','color=c=0x17243b:size=1280x720:rate=10:duration=336','-c:v','libx264',
            '-preset','ultrafast','-threads','2','-pix_fmt','yuv420p',str(media)],check=True)
        project=project_from_runtime_cues(str(media),core.deserialize_cues(comparison['final_cues']),
            generation_metadata={'language':{'code':'zh'}},initialize_layout=False)
        project.media.duration_ms=336000
        project.media.width=1280;project.media.height=720
    target=save_project(project,output/'replay.2byteproj')
    env=dict(os.environ,TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='qwen-grouping-quality',
        TWOBYTEASR_STARTUP_PROJECT=str(target),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_GROUPING_PREVIEW_TERMS=json.dumps(args.preview_term or ['相信他','选这个东西','足够信任','来一把','他要兜27个','可以刷']),
        TWOBYTEASR_GROUPING_FIRST_PER_TERM='1' if args.preview_term else '0',
        TWOBYTEASR_GROUPING_VIEWPORT_AUDIT='1' if args.viewport_audit else '0',
        TWOBYTEASR_GROUPING_TASK_PHASE_AUDIT='1',
        QT_QPA_PLATFORM='windows',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',PYTHONUTF8='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9',NO_PROXY='127.0.0.1,localhost')
    sys.path.insert(0,str(ROOT/'scripts'))
    env.update(LOCALAPPDATA=str(output/'local'), APPDATA=str(output/'roaming'))
    from audit_launch_bridge import run_audit_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=output,
                             timeout=240,receipt=output/'result.json')
    result=json.loads((output/'result.json').read_text(encoding='utf-8'))
    result.update(process_exit=code,passed=bool(result.get('passed') and code==0))
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result.get(k) for k in ('passed','process_exit','error')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
