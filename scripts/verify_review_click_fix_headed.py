"""Review click-to-fix, 他/她, glossary autosave and the export poster in the real app (2026-10-15).

Usage: python scripts/verify_review_click_fix_headed.py --output tmp/<fresh dir> [--exe path\\to\\2ByteASR.exe]
Runs on a private Windows desktop with isolated user data; see
twobyteasr/acceptance/review_click_fix_audit.py for the checks.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ffmpeg(*arguments):
    subprocess.run([str(ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'), '-y', '-v', 'error', *arguments],
                   check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    if args.exe and not args.exe.resolve().is_file():
        parser.error('--exe must identify an existing executable')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    import subtitle_core as legacy
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project

    # A glossary in the isolated user data: two names and one confirmed alias.
    library = legacy.create_learned_content('原神', create_new=True)
    for term in ('芙宁娜', '那维莱特'):
        legacy.add_learned_mapping(library, term, term, category='角色', origin='手动')
    legacy.add_learned_mapping(library, '芙宁那', '芙宁娜', category='角色', origin='手动')

    fixture = output / 'projects' / 'review-click-fix' / 'review-click-fix.2byteproj'
    fixture.parent.mkdir(parents=True)
    media = fixture.parent / 'review-click-fix.mp4'
    _ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=12',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=12',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '30', '-c:a', 'aac', '-shortest', str(media))
    poster = output / 'poster-source.mp4'
    _ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=30:duration=3',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '12', str(poster))
    evidence = {
        'e:0': {'moss_text': '然后他来到了那维来特的家', 'firered_text': '然后她来到了那维莱特的家',
                'qwen_asr_text': '然后她来到了那维莱特的家', 'primary_source': 'moss'},
        'e:1': {'moss_text': '芙宁那说他马上到', 'firered_text': '芙宁那说他马上到',
                'qwen_asr_text': '芙宁那说他马上到', 'primary_source': 'moss'},
    }
    save_project(SubtitleProject(
        media=StudioMedia(path=str(media), display_name='审核点字检查', duration_ms=12_000, width=1280, height=720),
        cues=[StudioCue('c0', 1000, 3500, '然后他来到了那维来特的家', evidence_refs=['e:0']),
              StudioCue('c1', 4500, 6500, '芙宁那说他马上到', evidence_refs=['e:1']),
              StudioCue('c2', 8000, 9500, '最后一句')],
        asr_evidence=evidence, glossary_ids=[library],
    ), fixture)
    (output / 'fixture.json').write_text(json.dumps(dict(library=library, poster_video=str(poster)),
                                                    ensure_ascii=False), 'utf8')

    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='review-click-fix',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               QT_QPA_PLATFORM='windows', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='127.0.0.1,localhost')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=600)
    receipt = output / 'result.json'
    deadline = time.monotonic() + 60
    result = {}
    while time.monotonic() < deadline:  # launchers may return before the GUI finishes
        try:
            result = json.loads(receipt.read_text('utf8'))
            if result.get('gui_shutdown'):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    result['launcher_exit'] = code
    result['passed'] = bool(result.get('passed') and code == 0 and result.get('gui_shutdown'))
    import psutil
    pid = result.get('pid')
    if pid and psutil.pid_exists(pid):
        try:
            result['child_exit'] = psutil.Process(pid).wait(timeout=25)
            result['passed'] = bool(result['passed'] and result['child_exit'] == 0)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            result['passed'] = False
            result['error'] = 'Owned review-click-fix GUI did not exit after normal close'
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    failed = [c['name'] for c in result.get('checks', []) if not c['passed']]
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), failed=failed,
                          launcher_exit=code, error=(result.get('error') or '')[-800:],
                          executable=result.get('executable'), output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
