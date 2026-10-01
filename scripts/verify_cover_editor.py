"""Normal source/frozen Studio entry, isolated before any application import."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--dpi', type=int, default=100)
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--sustain-seconds', type=int, default=0)
    parser.add_argument('--long', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():
        raise ValueError('Use a new directory under workspace/tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    sys.path.insert(0, str(root))
    from twobyteasr.studio_project import SubtitleProject
    p = SubtitleProject.from_dict(json.loads(args.project.read_text(encoding='utf-8-sig')))
    if not Path(p.media.path).is_file():
        raise FileNotFoundError(p.media.path)
    fixture = out/'fixture.2byteproj'
    fixture.write_text(json.dumps(p.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'),
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=str(args.dpi/175), PYTHONIOENCODING='utf-8',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='cover-editor',
        TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_COVER_QUICK='1' if args.quick else '0',
        TWOBYTEASR_COVER_SUSTAIN=str(args.sustain_seconds), TWOBYTEASR_COVER_LONG='1' if args.long else '0')
    cmd = [str(args.exe.resolve())] if args.exe else [sys.executable, '-X', 'utf8', '-B', str(root/'quick_start.py')]
    from twobyteasr.processes import run_hidden_subprocess
    with (out/'application.log').open('wb') as log:
        process = run_hidden_subprocess(cmd, cwd=root, env=env, stdout=log, stderr=log,
            timeout=600, purpose='isolated local cover editor acceptance')
    report = json.loads((out/'cover-runtime.json').read_text(encoding='utf-8'))
    print(json.dumps(dict(passed=report['passed'], checks=len(report['checks']), error=report.get('error'), exit_code=process.returncode), ensure_ascii=False))
    return 0 if report['passed'] and process.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
