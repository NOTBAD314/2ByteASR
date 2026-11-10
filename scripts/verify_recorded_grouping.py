"""Fixed answer regression runner for source and ordinary frozen EXEs."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--reverse-completion", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/"tmp") or output.exists():
        raise ValueError("Choose a fresh output directory under source/tmp.")
    output.mkdir(parents=True)
    fixture = json.loads((ROOT/"tests/fixtures/grouping_contract/luoke_cfeea.json").read_text(encoding="utf-8"))
    fixture.update(audit_kind="recorded-grouping-task", workers=args.workers, reverse_completion=args.reverse_completion)
    if args.media:
        if not args.media.is_file():
            raise FileNotFoundError(args.media)
        fixture["media_path"] = str(args.media.resolve())
    (output/"fixture.json").write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(output/"profile")
    os.environ["TWOBYTEASR_INVOKER_CWD"] = str(ROOT)
    if args.exe:
        with (output/"process.log").open("wb") as log:
            process = subprocess.run([str(args.exe.resolve()), "--grouping-quality-audit", str(output)],
                cwd=ROOT, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT, timeout=240)
        code = process.returncode
    else:
        sys.path.insert(0, str(args.source_root.resolve()))
        spec = importlib.util.spec_from_file_location("recorded_audit", ROOT/"twobyteasr/acceptance/recorded_grouping_audit.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        code = module.main(output, fixture)
    result = json.loads((output/"comparison.json").read_text(encoding="utf-8"))
    print(json.dumps(dict(passed=result.get("passed"), checks=result.get("checks"),
                         error=result.get("error"), timeline_sha256=result.get("timeline_sha256")), ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
