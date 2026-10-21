"""Run actual export-window clock acceptance on an isolated Windows desktop."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/"tmp"):
        raise ValueError("Output must stay under repository tmp/")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output/"data"), QT_QPA_PLATFORM="windows",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    sys.path.insert(0, str(ROOT))
    if args.child:
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.acceptance.export_clock_audit import run
        return run(output)
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop([sys.executable, "-X", "utf8", __file__, "--child", "--output", str(output)],
        cwd=ROOT, env=dict(os.environ), output=output/"process", timeout=300)
    print((output/"result.json").read_text("utf8") if (output/"result.json").exists() else
          (output/"process/stderr.log").read_text("utf8", errors="replace")[-4000:])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
