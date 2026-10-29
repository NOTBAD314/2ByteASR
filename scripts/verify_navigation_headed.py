"""Measure real settings / Studio / home navigation, source or isolated EXE.

python scripts/verify_navigation_headed.py --output tmp/nav-before --cycles 30
    [--project path/to/copied.2byteproj] [--exe path/to/candidate/2ByteASR.exe]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--cycles', type=int, default=30)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--font-root', type=Path, help='Read-only bundled CJK fonts for isolated source profiles')
    parser.add_argument('--profile', action='store_true', help='Separate diagnostic run: cProfile first operations')
    parser.add_argument('--regressions', action='store_true', help='Additional edit, settings and cancellation interactions')
    parser.add_argument('--categories', action='store_true', help='Separate painted settings-category benchmark')
    parser.add_argument('--zoom', type=int, help='Interface zoom percent for the isolated profile, e.g. 150')
    parser.add_argument('--language', help='Interface language for the isolated profile, e.g. en')
    parser.add_argument('--resource-soak', type=int, default=0, help='Extra paused round trips after the measured matrix')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():
        parser.error('Use a fresh directory under repository tmp')
    out.mkdir(parents=True)
    # Preserve the same installed CJK font bytes inside the isolated profile;
    # HKCU can register a filename relative to LOCALAPPDATA. No OS font install.
    font_home=Path(os.environ.get('LOCALAPPDATA',''))/'Microsoft/Windows/Fonts'
    fonts=[]
    for font in font_home.glob('SourceHan*'):
        if font.is_file() and font.suffix.lower() in {'.otf','.ttf','.ttc'}:
            target=out/'local/Microsoft/Windows/Fonts'/font.name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(font,target)
            fonts.append(dict(name=font.name,sha256=hashlib.sha256(font.read_bytes()).hexdigest()))
    font_bundle=args.font_root or ROOT/'dist/2ByteASR/assets/fonts'
    for name in ('SourceHanSansSC-Medium.otf','SourceHanSansSC-Heavy.otf'):
        font=font_bundle/name
        if font.is_file():
            target=out/'local/Microsoft/Windows/Fonts'/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(font,target)
            fonts.append(dict(name=name,sha256=hashlib.sha256(font.read_bytes()).hexdigest()))
    (out/'font-inputs.json').write_text(json.dumps(fonts,indent=2),'utf8')
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    # Both live in the isolated profile the app reads (same test root).
    if args.zoom:
        from twobyteasr.app import ui_zoom
        ui_zoom.set_zoom_percent(args.zoom)
    if args.language:
        from twobyteasr.storage.settings import load_runtime_settings, save_runtime_settings
        runtime, _path, _warnings = load_runtime_settings()
        runtime.setdefault('ui', {})['language'] = args.language
        save_runtime_settings(runtime)
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project
    entry = out/'entry.2byteproj'
    fixture = out/'project.2byteproj'
    if args.project:
        data = args.project.read_bytes()
        fixture.write_bytes(data)
        source_sha = hashlib.sha256(data).hexdigest()
    else:
        shared = ROOT/'tmp/ui-navigation-20261024/fixtures'
        shared.mkdir(parents=True, exist_ok=True)
        media = shared/'small.mp4'
        if not media.exists():
            subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-v','error','-y',
                '-f','lavfi','-i','testsrc2=size=1280x720:rate=30:duration=24',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=24',
                '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(media)],
                check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        save_project(SubtitleProject(media=StudioMedia(path=str(media), duration_ms=24000, width=1280,height=720),
            cues=[StudioCue(f'c{i}',i*600,i*600+500,f'导航性能测试 {i}') for i in range(40)]), fixture)
        source_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
    # The acceptance entry is only an isolation guard (startup stays on Home).
    # Reuse the fixture bytes instead of resolving a default font a second time.
    entry.write_bytes(fixture.read_bytes())
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_RAISE','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):
        env.pop(key,None)
    env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='navigation-performance', TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_NAVIGATION_TRACE='1', TWOBYTEASR_NAVIGATION_CYCLES=str(args.cycles),
        TWOBYTEASR_NAVIGATION_PROFILE='1' if args.profile else '0',
        TWOBYTEASR_NAVIGATION_REGRESSIONS='1' if args.regressions else '0',
        TWOBYTEASR_NAVIGATION_CATEGORIES='1' if args.categories else '0',
        TWOBYTEASR_NAVIGATION_SOAK=str(args.resource_soak),
        QT_QPA_PLATFORM='windows', PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    if args.regressions:
        env.update(TWOBYTEASR_AUDIT_TOP_LEVELS='1',TWOBYTEASR_AUDIT_TOP_LEVEL_PATH=str(out/'top-level-windows.jsonl'))
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=args.timeout)
    result=json.loads((out/'navigation.json').read_text('utf8')) if (out/'navigation.json').exists() else {}
    result['exit_code']=code
    result['input_sha256']=source_sha
    result['source_unchanged']=not args.project or hashlib.sha256(args.project.read_bytes()).hexdigest()==source_sha
    (out/'navigation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(output=str(out),exit_code=code,errors=result.get('errors'),
        entries=len(result.get('entries',[])),summary=result.get('summary')),ensure_ascii=False))
    return 0 if (code==0 and result.get('finished') and result.get('gui_shutdown')
                 and result['source_unchanged'] and not result.get('errors')) else 1


if __name__=='__main__':
    raise SystemExit(main())
