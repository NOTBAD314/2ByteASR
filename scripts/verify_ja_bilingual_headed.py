"""Real-window Japanese word timing + bilingual workflow check (2026-10-12).

Copies a Japanese recognition project into a fresh owned tmp directory,
isolates all app data there, and runs the in-process `ja-bilingual` scenario
(twobyteasr/ja_bilingual_audit.py) on a private Windows desktop: razor cut at
measured Japanese boundaries, edit + re-alignment (real Qwen3-ForcedAligner
worker, read-only model folder), translation dialog against a MOCK provider
(offline), bilingual preview captures, split states, save/reopen, SRT/JSON
export and a burned-in clip. Use --exe for a frozen candidate or the root
launcher.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=1200)
    parser.add_argument('--model-root', type=Path, help='Existing read-only model folder (default: <repo>/models)')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    project = out / 'ja-project.2byteproj'
    shutil.copy2(args.project, project)
    (out / 'input.json').write_text(json.dumps(dict(project=str(project), source=str(args.project)),
                                               ensure_ascii=False, indent=2), 'utf-8')
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'),
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='ja-bilingual',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'),
               TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    sys.path.insert(0, str(root / 'scripts'))
    # Borrow the existing models and runtimes read only (junction + hashed
    # manifest); re-alignment writes only inside this output.
    from verify_perf_recognition_headed import sentinels, sha
    junction = out / 'models'
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str((args.model_root or root / 'models').resolve())],
                   check=True, capture_output=True)
    aligner_config = junction / 'Qwen3-ForcedAligner-0.6B' / 'config.json'
    roles = {role: dict(python=str(root / venv / 'Scripts/python.exe'), python_sha256=sha(root / venv / 'Scripts/python.exe'),
                        venv_config=str(root / venv / 'pyvenv.cfg'), venv_config_sha256=sha(root / venv / 'pyvenv.cfg'))
             for role, venv in (('main', '.venv-main'), ('moss', '.venv-moss'))}
    rows = sentinels(junction) + ([dict(path=str(aligner_config), sha256=sha(aligner_config))] if aligner_config.is_file() else [])
    manifest = out / 'borrowed-resources.json'
    manifest.write_text(json.dumps(dict(schema_version=1, roles=roles, model_root=dict(path=str(junction), sentinels=rows)),
                                   ensure_ascii=False, indent=2), 'utf-8')
    env['TWOBYTEASR_LIVE_BORROWED_RESOURCES'] = str(manifest)
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    if args.exe and args.exe.resolve() == root / '2ByteASR.exe':
        command = [sys.executable, str(root / 'scripts/verify_desktop_entry_bridge.py'), str(out), json.dumps(command)]
    code = run_on_desktop(command, cwd=root, env=env, output=out / 'process', timeout=args.timeout)
    result = json.loads((out / 'result.json').read_text('utf-8')) if (out / 'result.json').exists() else dict(passed=False)
    result['process_exit'] = code
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(output=str(out), checks=[(x['name'], x['passed']) for x in result.get('checks', [])],
                          error=result.get('error'), exit=code), ensure_ascii=False, indent=1))
    return 0 if result.get('passed') and code == 0 and result.get('gui_shutdown') else 1


if __name__ == '__main__':
    raise SystemExit(main())
