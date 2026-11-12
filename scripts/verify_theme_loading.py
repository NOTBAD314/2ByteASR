"""Measure the normal GUI on a private Windows desktop, with isolated fixtures."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scale', default='1')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--real-project', type=Path)
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--mode', default='all', choices=['all', 'cold-project', 'stress', 'flows'])
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use a new directory under this source/tmp.')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out / 'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, StudioCue, save_project, studio_settings_path
    media = out / 'sample.mp4'
    subprocess.run([str(ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=size=960x540:rate=30:duration=8', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=8',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'aac', '-shortest', str(media)],
        check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    records = []
    for count in (12, 2000, 10000):
        folder = out / f'p{count}'
        folder.mkdir()
        cues = [StudioCue(f'cue-{i}', i * 1800, i * 1800 + 1600, f'这是第{i}条字幕，正在检查加载响应。') for i in range(count)]
        project = SubtitleProject(media=StudioMedia(str(media), duration_ms=max(8000, count * 1800), width=960, height=540), cues=cues)
        from twobyteasr.subtitle_rules import subtitle_translation as st
        project.generation_metadata.update(
            translations={cue.id: f'This is caption {cue.id}.' for cue in cues},
            translation_records=dict(version=1, target='en', records={cue.id: st._record(
                f'This is caption {cue.id}.', cue.text, origin=st.ORIGIN_MANUAL) for cue in cues}, history=[]))
        save_project(project, folder / 'project.2byteproj')
        (folder / 'preview').mkdir()
        subprocess.run([str(ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-i', str(media), '-frames:v', '1',
            str(folder / 'preview/project-cover.jpg')], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        records.append(dict(path=str(folder / 'project.2byteproj'), name=f'{count}条双语工程', cue_count=count,
            duration_ms=project.media.duration_ms, cover_path='preview/project-cover.jpg', last_opened='2026-11-11T12:00:00'))
    entry = out / 'entry.2byteproj'
    save_project(SubtitleProject(StudioMedia('')), entry)
    missing = SubtitleProject(StudioMedia(str(out / 'unavailable.mp4'), duration_ms=8000, width=960, height=540),
        cues=[StudioCue('missing-1', 0, 1500, '素材缺失时仍可编辑字幕。')])
    save_project(missing, out / 'missing-media.2byteproj')
    if args.real_project:
        import hashlib
        from twobyteasr.projects.studio_project import load_project
        real = out / 'real/project.2byteproj'
        real.parent.mkdir()
        shutil.copyfile(args.real_project, real)
        document = load_project(real)
        (out/'real-input.json').write_text(json.dumps(dict(
            source_sha256=hashlib.sha256(args.real_project.read_bytes()).hexdigest(),
            copied_sha256=hashlib.sha256(real.read_bytes()).hexdigest(),
            count=len(document.cues), source_media=str(document.media.path)), ensure_ascii=False), encoding='utf8')
        if Path(document.media.path).is_file():
            (real.parent/'preview').mkdir()
            subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-v','error','-ss','1','-i',document.media.path,
                '-frames:v','1','-vf','scale=640:-2',str(real.parent/'preview/project-cover.jpg')],
                check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    settings = studio_settings_path()
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({'recent_projects': records}, ensure_ascii=False), encoding='utf8')
    # A controlled font directory: the target font is deliberately not installed here.
    for font in (ROOT / 'assets/fonts').glob('SourceHan*otf'):
        target = out / 'profile/local/Microsoft/Windows/Fonts' / font.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(font, target)
    import ctypes
    user = ctypes.windll.user32
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    native_scale = user.GetDpiForSystem() / 96
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
    env = dict(os.environ, QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=str(float(args.scale)/native_scale), PYTHONUTF8='1',
        TWOBYTEASR_ACCEPTANCE_SCENARIO='theme-loading', TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_THEME_TRACE='1',
        TWOBYTEASR_LOADING_RECORD='1' if args.record else '0', TWOBYTEASR_LOADING_MODE=args.mode,
        TWOBYTEASR_LOADING_PROFILE='1' if args.profile else '0')
    env.pop('TWOBYTEASR_STARTUP_OPEN_STUDIO', None)
    from audit_launch_bridge import run_audit_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    code = run_audit_on_desktop(command, cwd=ROOT, env=env, output=out, timeout=360, receipt=out / 'result.json')
    result = json.loads((out / 'result.json').read_text('utf8')) if (out / 'result.json').exists() else {}
    if args.real_project:
        original = json.loads((out/'real-input.json').read_text('utf8'))
        result['real_original_unchanged'] = original['source_sha256'] == hashlib.sha256(args.real_project.read_bytes()).hexdigest()
        result['passed'] = bool(result.get('passed') and result['real_original_unchanged'])
        (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(passed=bool(result.get('passed') and code == 0), exit=code, output=str(out), error=result.get('error')), ensure_ascii=False))
    return 0 if result.get('passed') and code == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
