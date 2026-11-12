"""Normal-entry Windows benchmark; isolated data, source or the exact frozen EXE."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--first', choices=['workshop', 'history', 'terms', 'picker'], default='picker')
    p.add_argument('--cycles', type=int, default=8)
    p.add_argument('--scale', default='1')
    p.add_argument('--exe', type=Path)
    p.add_argument('--profile', action='store_true')
    p.add_argument('--collision-seconds', type=int, default=35)
    p.add_argument('--records', type=int, default=120)
    p.add_argument('--terms', type=int, default=0)
    p.add_argument('--slow-status-ms', type=int, default=0)
    args = p.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use a fresh directory under source/tmp')
    out.mkdir(parents=True)
    (out / 'placeholder.2byteproj').write_text('{}', 'utf8')
    reports = out / 'profile/local/2ByteASR/reports'
    reports.mkdir(parents=True)
    for i in range(args.records):
        (reports / f'case-{i}_字幕任务报告.json').write_text(json.dumps(dict(
            created_at=f'2026-11-12T12:{i % 60:02d}:00', media_path=f'test-{i}.mp4',
            media_name=f'性能样例 {i}', status='success', segments=[dict(start=0, end=1, text='测试字幕')],
            final_subtitles=[dict(start=0, end=1, text='测试字幕')],
            summary=dict(cue_count=1, duration_seconds=1)), ensure_ascii=False), 'utf8')
    if args.terms:
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(out/'profile')
        from twobyteasr.test_isolation import install
        install()
        import subtitle_core as legacy
        game = legacy.RUNTIME_GAME_NAME or '性能术语样例'
        identity = legacy.runtime_game_identity(game)
        payload = dict(schema=2, games={identity: dict(game=game, library_id=identity, content_type='game', mappings=[
            dict(**{'from':f'误听{i}', 'to':f'正确术语{i}'}, category=f'分类{i%8}', origin='手动',
                confirmed=True, provenance=legacy.TERM_PROVENANCE_USER_CONFIRMED) for i in range(args.terms)])})
        legacy._learned_payload_save(payload)
        os.environ['TWOBYTEASR_INTERACTION_GAME'] = game
    import ctypes
    user = ctypes.windll.user32
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    native = user.GetDpiForSystem() / 96
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
    env = dict(os.environ, QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=str(float(args.scale)/native),
        PYTHONUTF8='1', TWOBYTEASR_TEST_ROOT=str(out/'profile'),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='interaction-performance', TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'placeholder.2byteproj'), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'), TWOBYTEASR_NAVIGATION_TRACE='1',
        TWOBYTEASR_STARTUP_SIZE='1400x900', TWOBYTEASR_INTERACTION_FIRST=args.first,
        TWOBYTEASR_INTERACTION_CYCLES=str(args.cycles), TWOBYTEASR_INTERACTION_PROFILE=str(int(args.profile)),
        TWOBYTEASR_COLLISION_SECONDS=str(args.collision_seconds), TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_INTERACTION_TERMS=str(args.terms), TWOBYTEASR_SLOW_STATUS_MS=str(args.slow_status_ms))
    env.pop('TWOBYTEASR_STARTUP_OPEN_STUDIO', None)
    from audit_launch_bridge import run_audit_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_audit_on_desktop(command, cwd=ROOT, env=env, output=out, timeout=360, receipt=out/'result.json')
    result = json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    print(json.dumps(dict(exit=code, passed=result.get('passed'), error=result.get('error'),
        summary=result.get('summary'), output=str(out)), ensure_ascii=False))
    return 0 if code == 0 and result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
