"""Measure identical real-project playback on an owned Windows desktop."""
import argparse,hashlib,json,os,shutil,sys
from pathlib import Path
def main():
    root=Path(__file__).resolve().parents[1];ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',type=Path,required=True);ap.add_argument('--presets',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--baseline',type=Path)
    ap.add_argument('--seconds',type=float,default=18);ap.add_argument('--ui-only',action='store_true')
    ap.add_argument('--recover-legacy',action='store_true')
    ap.add_argument('--font-picker',action='store_true');ap.add_argument('--font-before',type=Path)
    ap.add_argument('--font-restart',action='store_true')
    ap.add_argument('--font-profile',action='store_true')
    ap.add_argument('--exe',type=Path);ap.add_argument('--gui',type=Path);ap.add_argument('--entry-bridge',type=Path)
    ap.add_argument('--scale',default='1');args=ap.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):ap.error('Use a new source/tmp output')
    out.mkdir(parents=True);original=hashlib.sha256(args.project.read_bytes()).hexdigest()
    project=out/'project.2byteproj';shutil.copy2(args.project,project)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='review-editor',TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE='1800x1040',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,PYTHONUTF8='1',
        STYLE_MOTION_PRESETS=str(args.presets.resolve()),STYLE_MOTION_SECONDS=str(args.seconds),
        STYLE_MOTION_UI_ONLY=str(int(args.ui_only)),
        STYLE_MOTION_RECOVER_LEGACY=str(int(args.recover_legacy)),
        STYLE_FONT_AUDIT=str(int(args.font_picker)),STYLE_FONT_RESTART=str(int(args.font_restart)),
        STYLE_FONT_PROFILE=str(int(args.font_profile)),
        STYLE_MOTION_FONTS=str(Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts'))
    if args.baseline:env['STYLE_MOTION_BASELINE']=str(args.baseline.resolve())
    if args.font_before:env['STYLE_FONT_BEFORE']=str(args.font_before.resolve())
    cmd=[sys.executable,'-B',root/'scripts/style_bilingual_motion_entry.py']
    if args.exe:
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO']='font-picker'if args.font_picker else 'style-bilingual-motion'
        fonts=out/'local/Microsoft/Windows/Fonts';fonts.mkdir(parents=True,exist_ok=True)
        for name in ('猫啃什锦黑.ttf','优设标题黑.ttf','SourceHanSansSC-VF.otf'):
            p=Path(env['STYLE_MOTION_FONTS'])/name
            if p.is_file():shutil.copy2(p,fonts/name)
        preset=out/'local/2ByteASR/SubtitleStudioPreview/style-presets.json';preset.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(args.presets,preset)
        cmd=[str(args.exe.resolve())]
        if args.gui:
            cmd=[sys.executable,'-B',str(args.entry_bridge.resolve()),'--launcher',str(args.exe.resolve()),
                '--gui',str(args.gui.resolve()),'--output',str(out),'--timeout','600']
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(cmd,
        cwd=root,env=env,output=out/'process',timeout=600)
    f=out/'result.json';result=json.loads(f.read_text('utf8')) if f.exists() else {}
    result.update(process_exit=code,source_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==original)
    result['passed']=bool(result.get('passed') and code==0 and result.get('gui_shutdown') and result['source_unchanged'])
    f.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],process_exit=code,error=result.get('error'),
        checks=len(result.get('checks',[])),failed=[x['name']for x in result.get('checks',[]) if not x['passed']],
        performance=[dict(scenario=x['scenario'],p50=x['render_ms']['p50'],p95=x['render_ms']['p95'],
            posts=x['frame_count'])for x in result.get('performance',[])]),ensure_ascii=False))
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
