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
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/"tmp"):
        raise ValueError("Output must stay under repository tmp/")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output/"data"), QT_QPA_PLATFORM="windows",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    sys.path.insert(0, str(ROOT))
    if args.exe:
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
        fixture = output/'fixture.2byteproj'
        save_project(SubtitleProject(StudioMedia('',duration_ms=1000,width=320,height=180)), fixture)
        os.environ.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),
            TWOBYTEASR_ACCEPTANCE_SCENARIO='export-release', TWOBYTEASR_STARTUP_PROJECT=str(fixture),
            TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_MAIN_PYTHON=sys.executable)
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop([str(args.exe.resolve())],cwd=ROOT,env=dict(os.environ),
            output=output/'process',timeout=480)
        import json
        result=json.loads((output/'result.json').read_text('utf8'))
        result['exit_code']=code
        result['passed']=bool(result.get('passed') and result.get('frozen') and result.get('gui_shutdown') and code==0)
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['passed'] else 1
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
