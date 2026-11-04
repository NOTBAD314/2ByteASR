"""Fixed cleanup replay in the normal source/frozen entry on a private desktop."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import sys


def extended_completion_errors(result, expected_cases):
    """An older EXE must not silently ignore newly requested GUI scenarios."""
    if not expected_cases:
        return []
    rows = result.get('extended_cases')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return ['extended case receipts are missing or malformed']
    expected = [case['id'] for case in expected_cases]
    ids = [row.get('id') for row in rows]
    if len(ids) != len(expected) or set(ids) != set(expected) or len(ids) != len(set(ids)):
        return ['requested extended case IDs were not completed exactly once']
    errors = []
    by_id = {row['id']: row for row in rows}
    for case in expected_cases:
        row = by_id[case['id']]
        target = Path(case['project']).resolve()
        closed = row.get('before_generation')
        reopened = row.get('reopened_generation')
        if (row.get('passed') is not True or row.get('real_gui_reopened') is not True
                or row.get('mode') != case['mode'] or row.get('partial') != bool(case.get('partial'))
                or row.get('playing') != bool(case.get('playing'))
                or not isinstance(closed, int) or not isinstance(reopened, int) or reopened <= closed
                or row.get('old_project_object_id') == row.get('reopened_project_object_id')
                or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('saved_content_sha256', '')))
                or row.get('saved_content_sha256') != row.get('reopened_content_sha256')
                or Path(row.get('saved_project') or '').resolve() != target
                or row.get('open_project_entry_calls') != [str(target)]
                or not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest() != row.get('saved_sha256')
                or not (target.parent / case['id'] / 'actual-reopened-studio.png').is_file()):
            errors.append(case['id']+': successful real GUI save/close/reopen evidence is incomplete')
    return errors


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--expect-local", action="store_true")
    parser.add_argument("--extended-fixtures", type=Path,
                        help="Additional fixed cases after the unchanged repeat matrix and translation checks")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / "tmp"):
        parser.error("Use a fresh output directory under repository tmp")
    out.mkdir(parents=True)
    entry = out / "entry.2byteproj"
    shutil.copyfile(args.project.resolve(), entry)
    payload = json.loads(entry.read_text("utf-8"))
    config = dict(cue_count=len(payload["cues"]), repeat=args.repeat, expect_local=args.expect_local,
                  duration_ms=payload.get("media", {}).get("duration_ms", 0),
                  sha256=hashlib.sha256(entry.read_bytes()).hexdigest())
    if args.extended_fixtures:
        extra = json.loads(args.extended_fixtures.resolve().read_text("utf-8-sig"))["cases"]
        if not 3 <= len(extra) <= 5 or len({case['id'] for case in extra}) != len(extra):
            parser.error("Use 3 to 5 unique extended representative cases")
        for case in extra:
            if not re.fullmatch(r'[a-z0-9-]{1,64}', case['id']):
                parser.error("Extended case IDs must be safe file basenames")
            source = Path(case['project']).resolve()
            if hashlib.sha256(source.read_bytes()).hexdigest() != case['project_sha256']:
                parser.error("An extended fixture changed after it was prepared")
            copied = out / (case['id'] + '.2byteproj')
            shutil.copyfile(source, copied)
            case['project'] = str(copied)
        config['extended_cases'] = extra
    (out / "config.json").write_text(json.dumps(config, indent=2), "utf-8")
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out)
    from twobyteasr.test_isolation import install
    install()
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO="ai-cleanup-apply", TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"),
               TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",
               QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(root / "quick_start.py")]
    code = run_on_desktop(command, cwd=root, env=env, output=out / "process", timeout=420)
    path = out / "ai-cleanup.json"
    result = json.loads(path.read_text("utf-8")) if path.exists() else {}
    completion_errors = extended_completion_errors(result, config.get('extended_cases', []))
    passed = code == 0 and result.get("passed") and result.get("gui_shutdown") and not completion_errors
    (out / 'runner-completion.json').write_text(json.dumps(dict(passed=bool(passed),
        requested_extended=[case['id'] for case in config.get('extended_cases', [])],
        errors=completion_errors), ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(output=str(out), exit_code=code, passed=bool(passed),
                          checks=len(result.get("checks", [])), error=result.get("error"),
                          completion_errors=completion_errors)))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
