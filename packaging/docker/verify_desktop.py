"""Run the existing Home GUI acceptance in a disposable container profile."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--timeline", default="off", choices=["off", "qwen_aligner", "paraformer", "whisper_turbo"])
    parser.add_argument("--cloud-loopback", action="store_true", help="Synthetic localhost protocol test; never calls a provider")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(Path("/media/tmp")) or output.exists():
        raise SystemExit("Choose a fresh directory below /media/tmp.")
    if not args.media.is_file():
        raise SystemExit("Explicit test media is missing.")
    output.mkdir(parents=True)
    for folder in ("local", "roaming", "profile", "temp", "config"):
        (output / folder).mkdir()
    (output / "guard.2byteproj").write_text("{}", encoding="utf8")
    (output / "home-flow.json").write_text(json.dumps({
        "media": str(args.media.resolve()), "accept_status": ["success", "degraded_success"],
        "timeout": 600, "asr": {"firered_asr_backend": args.timeline},
        "require_measured_words": args.timeline != "off",
    }), encoding="utf8")
    if args.cloud_loopback:
        duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                         "format=duration", "-of", "default=nw=1:nk=1", str(args.media)], text=True))
        reference = output / "synthetic-cloud-reference.json"
        reference.write_text(json.dumps({"utterances": [{"speaker": "M1",
            "text": "大家好欢迎来到兔白字幕今天我们测试本地语音识别",
            "start_s": 0, "end_s": duration}]}, ensure_ascii=False), encoding="utf8")
        config_path = output / "home-flow.json"
        config = json.loads(config_path.read_text("utf8"))
        config["loopback_mosi_reference"] = str(reference)
        config["asr"]["primary_asr_backend"] = "api"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf8")
    env = dict(os.environ)
    # The disposable Docker container is the outer isolation boundary. Keep the
    # real image runtime at /opt/venv so its production preflight is exercised.
    env.pop("TWOBYTEASR_TEST_ROOT", None)
    env.update({
        "DISPLAY": ":1", "QT_QPA_PLATFORM": "xcb",
        "LOCALAPPDATA": str(output / "local"), "APPDATA": str(output / "roaming"),
        "HOME": str(output / "profile"), "XDG_CONFIG_HOME": str(output / "config"),
        "TMPDIR": str(output / "temp"), "TEMP": str(output / "temp"), "TMP": str(output / "temp"),
        "2BYTEASR_USER_DATA_ROOT": str(output / "local"),
        "2BYTEASR_MODEL_ROOT": "/models", "2BYTEASR_RUNTIME_ROOT": str(output / "runtimes"),
        "TWOBYTEASR_MAIN_PYTHON": "/opt/venv/bin/python",
        "TWOBYTEASR_INVOKER_CWD": "/media", "TWOBYTEASR_ACCEPTANCE_DIR": str(output),
        "TWOBYTEASR_ACCEPTANCE_SCENARIO": "home-release-flow",
        "TWOBYTEASR_STARTUP_PROJECT": str(output / "guard.2byteproj"),
        "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
    })
    with (output / "application.log").open("wb") as log:
        run = subprocess.run([sys.executable, "-m", "twobyteasr.container.launch"],
                             cwd="/app", env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    receipt = output / "result.json"
    result = json.loads(receipt.read_text("utf8")) if receipt.is_file() else {}
    print(json.dumps({"passed": result.get("passed", False), "exit_code": run.returncode,
                      "checks": result.get("checks", {}), "error": result.get("error", ""),
                      "recognition": result.get("recognition") if not result.get("passed") else None},
                     ensure_ascii=False, indent=2))
    return 0 if result.get("passed") and run.returncode == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
