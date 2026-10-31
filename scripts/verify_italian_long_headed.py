"""Same complete real-project input for controlled baseline/current UI runs."""
import argparse
import os
from pathlib import Path
import sys
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--visible', action='store_true')
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--phases', default='italian-identity,select,drag-repeat,italian-navigation,italian-controls,italian-rates,italian-speakers,leak-cycles,idle-final')
    args = parser.parse_args()
    os.environ['PERF_ITALIAN'] = '1'
    if args.before:
        os.environ['ITALIAN_BEFORE'] = str(args.before.resolve())
    else:
        os.environ.pop('ITALIAN_BEFORE', None)
    os.environ['ITALIAN_PROFILE'] = '1' if args.profile else '0'
    os.environ['PERF_LEAK_CYCLES'] = str(max(1, min(12, args.cycles)))
    os.environ['ITALIAN_VISIBLE'] = '1' if args.visible else '0'
    os.environ['ITALIAN_PYTHON'] = sys.executable
    root = Path(__file__).resolve().parents[1]
    os.environ['ITALIAN_PROBE_SCRIPT'] = str(root/'scripts/italian_pixel_probe.py')
    empty = root / 'tmp' / 'empty-seek'
    empty.mkdir(parents=True, exist_ok=True)
    if args.exe and (args.before or args.profile):
        parser.error('Frozen audit does not replace or profile source modules')
    sys.argv = [sys.argv[0], '--project', str(args.project.resolve()), '--output', str(args.output),
                '--seek-cache', str(empty), '--phases', args.phases, '--drag-repeats', '3', '--timeout', '900']
    sys.argv += (['--exe', str(args.exe.resolve())] if args.exe else
                 ['--source-entry', str(root/'scripts/profile_italian_entry.py')])
    from verify_perf_regression_headed import main as run
    import isolated_windows_desktop
    original_run = isolated_windows_desktop.run_on_desktop
    def owned_run(command, *, cwd, env, output, timeout, **kwargs):
        # Make the pure-video control before the GUI starts. The normal full
        # project and all its contents remain available beside it.
        out = Path(output).parent
        payload = json.loads((out/'project.2byteproj').read_text(encoding='utf8'))
        payload.update(cues=[], speakers=[], asr_evidence={}, generation_metadata={},
                       project_id='italian-pure-video-control', report_path='', original_outputs={})
        payload['studio_state'] = {'playhead_ms': 2400000, 'zoom': 120000, 'bilingual_mode': False}
        (out/'pure-video.2byteproj').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf8')
        if args.visible:
            kwargs['desktop_name'] = 'Default'
        return original_run(command, cwd=cwd, env=env, output=output, timeout=timeout, **kwargs)
    isolated_windows_desktop.run_on_desktop = owned_run
    return run()


if __name__ == '__main__':
    raise SystemExit(main())
