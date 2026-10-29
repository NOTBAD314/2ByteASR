"""Speaker manager cards and the subtitle export dialog, in the real app (2026-10-18).

Usage: python scripts/verify_speaker_export_headed.py --output tmp/<fresh dir> [--exe path\\to\\2ByteASR.exe]
       [--theme grape|warm] [--language zh|zh-Hant|en|ja|ko]
Runs on a private Windows desktop with isolated user data, a synthetic 60 s
video with a tone and a three-speaker project; see
twobyteasr/acceptance/speaker_export_audit.py for the checks.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from isolated_windows_desktop import run_on_desktop

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--theme", default="grape")
    parser.add_argument("--language", default="zh")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("Use a fresh directory under tmp/")
    out.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.acceptance.speaker_export_audit import make_project
    from twobyteasr.storage.settings import load_runtime_settings, save_runtime_settings
    from twobyteasr.system.platform_media import ffmpeg_tool
    settings, _path, _warnings = load_runtime_settings()
    settings.setdefault("ui", {})["language"] = args.language
    save_runtime_settings(settings)
    media = out / "media" / "艾尔登法环 DLC 直播.mp4"
    media.parent.mkdir()
    subprocess.run([ffmpeg_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=330:beep_factor=4", "-t", "60",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                    "-shortest", str(media)], check=True)
    project = make_project(media, out / "speaker-check.2byteproj")
    env = dict(os.environ, QT_QPA_PLATFORM="windows", PYTHONUTF8="1",
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO="speaker-export",
               TWOBYTEASR_SPEAKER_AUDIT_THEME=args.theme, TWOBYTEASR_SPEAKER_AUDIT_PROJECT=str(project),
               TWOBYTEASR_SPEAKER_AUDIT_MEDIA=str(media), TWOBYTEASR_STARTUP_PROJECT=str(project),
               TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", NO_PROXY="127.0.0.1,localhost")
    for key in ("TWOBYTEASR_STARTUP_OPEN_STUDIO", "TWOBYTEASR_STARTUP_RAISE",
                "TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", "TWOBYTEASR_STARTUP_LEAVE_STUDIO"):
        env.pop(key, None)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / "process", timeout=300)
    path = out / "result.json"
    result = {}
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:  # launchers may return before the GUI finishes
        try:
            result = json.loads(path.read_text("utf-8"))
            if result.get("gui_shutdown"):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    passed = code == 0 and result.get("passed") and result.get("gui_shutdown")
    failed = [item["name"] for item in result.get("checks", []) if not item["passed"]]
    print(json.dumps(dict(passed=bool(passed), theme=args.theme, language=args.language,
                          checks=len(result.get("checks", [])), failed=failed, exit=code,
                          error=result.get("error")), ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
