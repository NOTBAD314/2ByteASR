"""Source/frozen fixed Studio UI gates; never writes user projects/settings."""
from pathlib import Path
import argparse,json,os,shutil,sys,time


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path)
    p.add_argument('--mode',choices=['playback','endurance','theme'],default='playback')
    p.add_argument('--project',type=Path)
    p.add_argument('--unmute-owned-session',action='store_true')
    p.add_argument('--ablation',choices=['none','audio-off','web-off','waveform-off','basic'],default='none')
    args=p.parse_args()
    out=root/'tmp/dual-track-provider-recovery/runs'/f'{args.mode}-{"frozen" if args.exe else "source"}-{time.strftime("%Y%m%d-%H%M%S")}'
    out.mkdir(parents=True);project=out/'fixture.2byteproj'
    media_root=root/'tmp/dual-track-provider-recovery/media'
    if args.project:shutil.copyfile(args.project,project)
    elif args.mode=='theme':shutil.copyfile(media_root/'v1-only.2byteproj',project)
    else:
        from twobyteasr.studio_project import SubtitleProject,StudioMedia,save_project
        save_project(SubtitleProject(media=StudioMedia(path='',display_name='诊断工程')),project)
    shutil.copyfile(root/'tests/fixtures/polar_bear_f38c393_concepts.json',out/'concepts.json')
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',
        DASHSCOPE_API_KEY='sk-local-test-dummy',TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='dual-track-recovery',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_RECOVERY_MODE=args.mode,
        TWOBYTEASR_RECOVERY_MEDIA_ROOT=str(media_root),TWOBYTEASR_RECOVERY_UNMUTE='1' if args.unmute_owned_session else '0',
        TWOBYTEASR_RECOVERY_ABLATION=args.ablation)
    from twobyteasr.processes import run_hidden_subprocess
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    print('EVIDENCE',out,flush=True)
    with (out/'application.log').open('wb') as log:
        result=run_hidden_subprocess(command,cwd=root,purpose='Studio dual-track recovery UI audit',
            stdout=log,stderr=log,timeout=930 if args.mode=='endurance' else 240)
    (out/'exit.json').write_text(json.dumps({'returncode':result.returncode,'command':command}),encoding='utf8')
    name='ai-ui-acceptance.json' if args.mode=='theme' else 'ui-operations.json'
    report=json.loads((out/name).read_text('utf8'))
    print(json.dumps({k:report.get(k) for k in ('checks','error','elapsed','elapsed_seconds','export')},ensure_ascii=False),flush=True)
    if result.returncode or report.get('error') or not all(report.get('checks',{}).values()):raise SystemExit(1)
if __name__=='__main__':main()
