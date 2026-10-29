"""Real-window check: follow-playhead, dropdown windows, the app after an export (2026-10-27).

Starts the real app (source, or ``--exe`` for a frozen candidate) on a private
desktop with an isolated data folder and runs the ``export-follow`` acceptance
scenario (``twobyteasr/acceptance/export_follow_audit.py``) on the sample
project. Offline; no AI. Nothing is read from or written to the real user data.

    python -X utf8 scripts/verify_export_follow_headed.py --output tmp/<new folder> [--exe dist/2ByteASR/2ByteASR.exe]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def _advanced(path: Path) -> None:
    """Give every caption an animated style, so the export takes the browser renderer."""
    from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
    from twobyteasr.projects.studio_project import SubtitleStyle, load_project, save_project
    from twobyteasr.rendering.advanced_renderer import project_requires_advanced
    project = load_project(path)
    recipe = style_recipe_for_prompt('Cyberpunk HUD')
    project.styles.append(SubtitleStyle(id='advanced', name='Cyberpunk HUD',
                                        font_family=str(recipe.typography.get('fontFamily')),
                                        font_size=float(recipe.typography.get('fontSize', 58))))
    project.style_recipes['advanced'] = recipe.to_dict()
    for cue in project.cues:
        cue.style_id = 'advanced'
    assert project_requires_advanced(project)
    save_project(project, path)


def _long_fixture(out: Path, seconds: int, source: Path | None = None) -> Path:
    """A 1080p clip with audio and a caption (plus a translation) every 3 s:
    generated, or ``seconds`` of a real video (stream copy from 60 s in)."""
    from types import SimpleNamespace
    from twobyteasr.projects.studio_project import project_from_runtime_cues, save_project
    from twobyteasr.system.processes import run_hidden_subprocess
    media = out / 'media' / f'long-{seconds}s.mp4'
    media.parent.mkdir(parents=True)
    ffmpeg = ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
    if source is not None:
        command = [str(ffmpeg), '-v', 'error', '-ss', '60', '-t', str(seconds), '-i', str(source), '-c', 'copy', str(media)]
    else:
        command = [str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', f'testsrc2=s=1920x1080:r=30:d={seconds}',
                   '-f', 'lavfi', '-i', f'sine=f=440:r=48000:d={seconds}', '-c:v', 'libx264', '-preset',
                   'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(media)]
    run_hidden_subprocess(command, check=True, timeout=1800, purpose='long export fixture')
    cues = [SimpleNamespace(cue_id=f'c{i}', start=i * 3.0, end=i * 3.0 + 2.6, text=f'第 {i} 句测试字幕，导出完成后应用应保持响应',
                            speaker='S00') for i in range(seconds // 3)]
    project = project_from_runtime_cues(media, cues, generation_metadata={'language': {'code': 'zh', 'requested': 'zh'}})
    project.generation_metadata['translations'] = {cue.id: f'Line {n}: the app must stay responsive after export'
                                                   for n, cue in enumerate(project.cues)}
    path = out / 'projects' / 'long-fixture' / 'long-fixture.2byteproj'
    path.parent.mkdir(parents=True)
    return save_project(project, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--media-seconds', type=int, default=0,
                        help='export a generated 1080p clip this long instead of the 24 s sample')
    parser.add_argument('--media', type=Path, help='with --media-seconds: cut the clip from this real video (read only)')
    parser.add_argument('--encoder', default='', help='choose this encoder on the export page instead of 自动')
    parser.add_argument('--skip-follow', action='store_true')
    parser.add_argument('--minimize', action='store_true', help='minimize during the export, restore after it')
    parser.add_argument('--details', action='store_true', help='open the running log during the export')
    parser.add_argument('--advanced', action='store_true', help='animated caption style (browser renderer)')
    parser.add_argument('--real-desktop', action='store_true',
                        help='run on the visible desktop (real taskbar notification, composited video window)')
    parser.add_argument('--quiet', action='store_true', help='no completion beep')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    profile = out / 'profile'
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(profile)
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from verify_ui_polish_headed import _fixture
    # The acceptance runner requires its own copied project.
    fixture = _long_fixture(out, args.media_seconds, args.media) if args.media_seconds else _fixture(out)
    if args.advanced:
        _advanced(fixture)
    local, roaming = out / 'local', out / 'roaming'
    local.mkdir()
    roaming.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_TEST_ROOT=str(profile), PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONFAULTHANDLER='1',
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='export-follow',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
               NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
               TWOBYTEASR_EXPORT_FOLLOW_OPTIONS=','.join(
                   name for name, on in (('skip-follow', args.skip_follow), ('minimize', args.minimize),
                                         ('details', args.details), ('quiet', args.quiet),
                                         (f'encoder={args.encoder}', bool(args.encoder))) if on))
    if args.advanced:
        # Isolated runs make system Chrome refuse remote debugging; real users are unaffected.
        env['TWOBYTEASR_RENDERER_CHROME'] = str(ROOT / 'renderer' / 'node_modules' / '.remotion' / 'chrome-headless-shell'
                                                / 'win64' / 'chrome-headless-shell-win64' / 'chrome-headless-shell.exe')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    if args.real_desktop:
        import subprocess
        (out / 'process').mkdir()
        with (out / 'process' / 'stdout.log').open('wb') as log:
            code = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=args.timeout).returncode
    else:
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    path = out / 'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=bool(result.get('passed')) and code == 0 and bool(result.get('gui_shutdown')), exit=code,
                   shutdown=result.get('gui_shutdown'), executable=result.get('executable'),
                   checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                   failed=[c for c in result.get('checks', []) if not c['passed']],
                   metrics=result.get('metrics'), errors=[e[-1500:] for e in result.get('errors', [])])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
