"""批量替换 dialog, AI 清理 entry and toolbar moves (2026-10-21) in a real window, source or frozen."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True, help="video clip inside repository tmp")
    parser.add_argument("--theme", default="grape", choices=("grape", "warm"))
    parser.add_argument("--widths", default="1440,1600,1920")
    parser.add_argument("--zoom", type=int, default=100, choices=(100, 110, 120, 135, 150),
                        help="interface zoom saved on this (isolated) machine before the app starts")
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    out, media = args.output.resolve(), args.media.resolve()
    if not out.is_relative_to(root / "tmp") or not media.is_relative_to(root / "tmp") or out.exists():
        parser.error("fresh repository tmp output and a tmp media clip required")
    out.mkdir(parents=True)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out)
    from twobyteasr.test_isolation import install
    install()
    if args.zoom != 100:
        from PySide6.QtCore import QSettings
        settings = QSettings("2ByteASR", "2ByteASR")  # the isolated class after install()
        settings.setValue("ui/zoom_percent", args.zoom)
        settings.sync()
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    entry = save_project(SubtitleProject(media=StudioMedia(path="", duration_ms=0)), out / "entry.2byteproj")
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO="batch-replace",
               TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", TWOBYTEASR_INVOKER_CWD=str(root),
               TWOBYTEASR_BATCH_MEDIA=str(media), TWOBYTEASR_BATCH_THEME=args.theme,
               TWOBYTEASR_BATCH_WIDTHS=args.widths, QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    for key in ("NO_PLAYER", "NO_EDIT_PREVIEW", "HWDEC", "VO"):
        env.pop("TWOBYTEASR_DIAGNOSTIC_" + key, None)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(root / "quick_start.py")]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=root, env=env, output=out / "process", timeout=240)
    path = out / "result.json"
    result = json.loads(path.read_text("utf8")) if path.exists() else {}
    print(json.dumps(dict(exit_code=code, output=str(out), passed=result.get("passed"), error=result.get("error"),
                          failed=[c["name"] for c in result.get("checks", []) if not c["passed"]],
                          checks=len(result.get("checks", []))), ensure_ascii=False))
    return 0 if code == 0 and result.get("passed") and result.get("gui_shutdown") else 1


if __name__ == "__main__":
    raise SystemExit(main())
