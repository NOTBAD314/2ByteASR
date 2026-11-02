"""Real-window check of the loading faces (library fan → picked project, poster, failure).

Usage: python -X utf8 scripts/verify_loading_faces_headed.py --output tmp/<new dir> [--theme sand] [--private] [--exe <EXE>]

Isolated profile (TWOBYTEASR_TEST_ROOT) under the output directory, offline
guards, generated media and projects only; no user data is read or written.
Six recent projects with real cover frames are seeded into the isolated
Studio settings so the library face shows its fan.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ['testsrc2', 'smptehdbars', 'mandelbrot', 'rgbtestsrc', 'cellauto=rule=110', 'life=s=320x200:mold=10:r=25']
NAMES = ['寂静岭 f · 第 3 期实况', '双人成行 · 第 7 期', '空洞骑士 速通复盘', '动物森友会 · 岛屿改造',
         '生化危机 4 重制 · 第 1 期', '星露谷 · 第二年春']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--theme', default='sand')
    parser.add_argument('--pick', type=int, default=1)
    parser.add_argument('--private', action='store_true')
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        parser.error('Use a new repository tmp output')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import (SubtitleProject, StudioMedia, StudioCue, save_project,
                                                   studio_settings_path)
    base = Path(args.exe).resolve().parent if args.exe else ROOT
    for font in (base / 'assets/fonts').glob('SourceHan*'):
        target = out / 'local/Microsoft/Windows/Fonts' / font.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(font, target)
    ffmpeg = base / 'tools/ffmpeg/bin/ffmpeg.exe'
    video = out / 'source.mp4'
    hidden = dict(check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=12',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=12', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-c:a', 'aac', '-shortest', str(video)], **hidden)
    records = []
    for index, (source, name) in enumerate(zip(SOURCES, NAMES)):
        folder = out / 'projects' / f'p{index}'
        (folder / 'preview').mkdir(parents=True)
        project = folder / 'project.2byteproj'
        cues = [StudioCue(f'c{i}', i * 1000, i * 1000 + 900, f'{name} 字幕 {i}') for i in range(12)]
        save_project(SubtitleProject(media=StudioMedia(path=str(video), duration_ms=12000, width=1280, height=720),
                                     cues=cues), project)
        size = '' if 'life' in source else (':' if '=' in source else '=') + 'size=640x400'
        subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', f'{source}{size}', '-frames:v', '1',
                        '-vf', 'scale=640:400', str(folder / 'preview' / 'project-cover.jpg')], **hidden)
        records.append(dict(path=str(project), name=name, cue_count=148 + index * 37,
                            duration_ms=2538000 + index * 611000, cover_path='preview/project-cover.jpg',
                            last_opened=f'2026-11-0{2 - index // 3}T2{3 - index}:41:00'))
    settings = studio_settings_path()
    settings.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(settings.read_text('utf-8')) if settings.is_file() else {}
    payload['recent_projects'] = records
    settings.write_text(json.dumps(payload, ensure_ascii=False, indent=2), 'utf-8')
    entry = out / 'entry.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), entry)
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_SCENARIO='loading-faces', TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_LOADING_FACES_THEME=args.theme,
               TWOBYTEASR_LOADING_FACES_PICK=str(args.pick), QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):
        env.pop(key, None)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    code = -1
    try:
        if args.private:
            from isolated_windows_desktop import run_on_desktop
            code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=300)
        else:
            with (out / 'application.log').open('wb') as log:
                code = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=log, timeout=300,
                                      creationflags=subprocess.CREATE_NO_WINDOW).returncode
    except subprocess.TimeoutExpired:
        (out / 'runner-timeout.json').write_text(json.dumps({'reason': 'exceeded 300 seconds'}), 'utf8')
    report = out / f'loading-faces-{args.theme}.json'
    data = json.loads(report.read_text('utf-8')) if report.exists() else {}
    passed = bool(code == 0 and data.get('passed') and data.get('normal_shutdown') and not data.get('errors'))
    print(json.dumps(dict(passed=passed, exit_code=code, checks=len(data.get('checks', [])),
                          failed=[c['name'] for c in data.get('checks', []) if not c['passed']],
                          errors=data.get('errors'), captures=len(data.get('captures', [])), output=str(out)),
                     ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
