"""Real-window check of link downloads A+B (2026-10-26): Studio Ctrl+V quick card,
toolbar capsule, import notice, and the YDL GUI style window.

Runs the real app (source, or ``--exe``) on a private desktop with an isolated
profile; downloads the 19-second public video jNQXAC9IVRw twice (video+subtitles,
then audio only). No cookies, no paid AI.

    python -X utf8 scripts/verify_link_ui_headed.py --output tmp/<new folder> [--theme sand] [--zoom 110]
"""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--theme", default="sand")
    parser.add_argument("--zoom", type=int, default=100)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp") or out.exists():
        parser.error("Use a fresh directory under repository tmp")
    out.mkdir(parents=True)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.app import ui_zoom
    from twobyteasr.design.theme_manager import save_theme_key
    ui_zoom.set_zoom_percent(args.zoom)   # isolated QSettings, shared with the app (same test root)
    save_theme_key(args.theme)
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    entry = save_project(SubtitleProject(media=StudioMedia(path="")), out / "entry.2byteproj")
    env = os.environ.copy()
    for key in ("TWOBYTEASR_STARTUP_OPEN_STUDIO", "TWOBYTEASR_STARTUP_RAISE", "TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE"):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO="link-ui", TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",
               TWOBYTEASR_LINK_UI_THEME=args.theme, TWOBYTEASR_LINK_UI_ZOOM=str(args.zoom),
               QT_QPA_PLATFORM="windows", PYTHONUTF8="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / "process", timeout=args.timeout)
    path = out / "link-ui.json"
    result = json.loads(path.read_text("utf-8")) if path.exists() else {}
    summary = dict(output=str(out), exit_code=code, passed=result.get("passed"), shutdown=result.get("gui_shutdown"),
                   checks=[(c["name"], c["passed"]) for c in result.get("checks", [])],
                   error=(result.get("error") or "")[-1500:], provider_calls=result.get("provider_calls"))
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if code == 0 and result.get("passed") and result.get("gui_shutdown") else 1


if __name__ == "__main__":
    raise SystemExit(main())
