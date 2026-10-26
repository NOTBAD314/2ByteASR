"""Real-window playback smoothness at caption starts + speaker manager open time (2026-10-22).

Copies a project into a fresh owned tmp directory, isolates all app data there
and runs the in-process `playback-hitch` scenario
(twobyteasr/acceptance/playback_hitch_audit.py) on a private Windows desktop. The
project's media is only read. Use --exe for a frozen candidate or the root
launcher. Writes result.json, ticks.json, posts.json and stacks.json.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=1500)
    parser.add_argument('--segments', default='200000:40,320000:40:2,600000:20:4',
                        help='start_ms:wall_seconds[:rate],...')
    parser.add_argument('--seeks', default='', help='start_ms:count:step_ms:interval_s,... jumps during 1x playback')
    parser.add_argument('--speaker-manager-opens', type=int, default=2)
    parser.add_argument('--profile-paints', type=int, default=0, help='cProfile every Nth full timeline repaint')
    parser.add_argument('--profile-speaker', action='store_true', help='cProfile the speaker manager opens')
    parser.add_argument('--settle', type=float, default=45.0, help='seconds to wait after opening (caches build)')
    parser.add_argument('--functional-only',action='store_true',help='Allow exit zero for functional checks only; display performance stays UNVERIFIED')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    project = out / 'project.2byteproj'
    shutil.copy2(args.project, project)
    media = json.loads(project.read_text('utf-8-sig')).get('media', {}).get('path', '')
    before = Path(media).stat() if media and Path(media).is_file() else None
    spec = dict(project=str(project), source=str(args.project), speaker_manager_opens=args.speaker_manager_opens, settle_s=args.settle, profile_paints=args.profile_paints, profile_speaker=args.profile_speaker,
                segments=[[float(x) for x in item.split(':')] for item in args.segments.split(',') if item],
                seeks=[[float(x) for x in item.split(':')] for item in args.seeks.split(',') if item])
    (out / 'input.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), 'utf-8')
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'),
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='playback-hitch',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'),
               TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    sys.path.insert(0, str(root / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    if args.exe and args.exe.resolve() == root / '2ByteASR.exe':
        command = [sys.executable, str(root / 'scripts/verify_desktop_entry_bridge.py'), str(out), json.dumps(command)]
    code = run_on_desktop(command, cwd=root, env=env, output=out / 'process', timeout=args.timeout)
    result = json.loads((out / 'result.json').read_text('utf-8')) if (out / 'result.json').exists() else dict(passed=False)
    after = Path(media).stat() if media and Path(media).is_file() else None
    result['process_exit'] = code
    result['media_unchanged'] = bool(before and after and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns))
    result['functional_pass']=bool(result.get('passed') and code==0 and result.get('gui_shutdown') and result['media_unchanged'])
    result['measurement_valid']=False
    result['performance_pass']='UNVERIFIED'
    result['performance_scope']='Qt callback gaps and backend counters; no calibrated visible/system display cadence'
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(output=str(out), checks=[(x['name'], x['passed']) for x in result.get('checks', [])],
                          playback=[{k: r[k] for k in ('segment', 'media_rate', 'boundaries', 'near', 'far')} for r in result.get('playback', [])],
                          posts=result.get('posts'), present=result.get('present'),
                          timeline={k: v for k, v in (result.get('timeline') or {}).items() if k != 'invalidated_by'},
                          speaker_manager_ms=result.get('speaker_manager_ms'), error=(result.get('error') or '')[-800:], exit=code,
                          media_unchanged=result['media_unchanged']), ensure_ascii=False, indent=1))
    return 0 if args.functional_only and result['functional_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
