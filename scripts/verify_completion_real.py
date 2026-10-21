"""Normal application UI audit using retained real task data; no new ASR."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def completion_dpi_environment(environment, scale):
    """Natural desktop DPI or explicit per-process Qt test controls."""
    result = environment.copy()
    overrides = ('QT_SCALE_FACTOR', 'QT_ENABLE_HIGHDPI_SCALING', 'QT_FONT_DPI',
                 'QT_SCALE_FACTOR_ROUNDING_POLICY')
    if scale == 'natural':
        for key in overrides:
            result.pop(key, None)
    else:
        result.update(QT_SCALE_FACTOR=scale, QT_ENABLE_HIGHDPI_SCALING='0',
            QT_FONT_DPI='96', QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--log', type=Path)
    parser.add_argument('--scale', default='1', help='Qt test multiplier, or natural for the inherited Windows desktop DPI without Qt overrides')
    parser.add_argument('--layout-baseline', type=Path)
    parser.add_argument('--summary-layout', action='store_true', help='Verify current summary/full/collapse layout using the retained real task')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    for source in (args.project, args.report):
        if not source.is_file():
            parser.error('Real project and report must exist')
    output.mkdir(parents=True)
    # PROCESS_START runs before app-level test isolation can redirect storage.
    os.environ['TWOBYTEASR_STARTUP_TRACE'] = str(output/'startup-trace.jsonl')
    fixture = output/'retained-real-task'
    fixture.mkdir()
    project = fixture/args.project.name
    report = fixture/args.report.name
    shutil.copy2(args.project, project)
    shutil.copy2(args.report, report)
    if args.log:
        shutil.copy2(args.log, fixture/'retained-run.log')
    layout_baseline = json.loads(args.layout_baseline.read_text('utf8')) if args.layout_baseline else None
    dpi_scope = ('Natural Windows desktop DPI; inherited Qt scale/font-DPI overrides removed; actual DPR measured by the app; OS DPI unchanged'
        if args.scale == 'natural' else 'Controlled per-process Qt test multiplier; actual DPR measured by the app; OS DPI unchanged')
    (output/'input.json').write_text(json.dumps(dict(project=str(project), report=str(report),
        source_project=str(args.project.resolve()), source_report=str(args.report.resolve()), requested_scale=args.scale,
        layout_baseline=layout_baseline, dpi_scope=dpi_scope, summary_layout=args.summary_layout,
        verification_scope='Retained real terminal replay through normal quick_start; structural state coverage separately labeled; no new ASR or provider call. ' + dpi_scope),
        ensure_ascii=False, indent=2), 'utf8')
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE',
                'TWOBYTEASR_STARTUP_LEAVE_STUDIO', 'TWOBYTEASR_STARTUP_PROJECT'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='completion-real',
        TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_INVOKER_CWD=str(ROOT), QT_QPA_PLATFORM='windows',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    env = completion_dpi_environment(env, args.scale)
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output/'process', timeout=240)
    result_path = output/'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else {'passed': False, 'error': 'No GUI receipt'}
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0 and result.get('provider_calls') == 0)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], error=result.get('error'), output=str(output)), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
