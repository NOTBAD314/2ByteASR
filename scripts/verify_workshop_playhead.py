"""Create a six-second synthetic fixture and run the normal app entry audit."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp") or out.exists():
        raise ValueError("Use a new directory under repository tmp")
    out.mkdir(parents=True)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project
    ffmpeg = ROOT / "tools/ffmpeg/bin/ffmpeg.exe"
    media = out / "synthetic.mp4"
    run_hidden_subprocess([str(ffmpeg), "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=0x243442:s=1280x720:r=30:d=6", "-f", "lavfi", "-i",
        "anullsrc=r=48000:cl=stereo", "-t", "6", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest", str(media)], check=True, timeout=30, purpose="synthetic audit video")
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=6000, width=1280, height=720),
        speakers=[StudioSpeaker("S1", name="测试说话人")], cues=[
            StudioCue("old", 0, 1000, "之前选中的字幕", "S1"),
            StudioCue("now", 1000, 3500, "当前播放头字幕", "S1"),
        ])
    path = save_project(project, out / "fixture.2byteproj")
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO="workshop-playhead",
        TWOBYTEASR_STARTUP_PROJECT=str(path), TWOBYTEASR_STARTUP_OPEN_STUDIO="1",
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", QT_QPA_PLATFORM="windows", QT_SCALE_FACTOR=str(100/175),
        PYTHONIOENCODING="utf-8")
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    with (out / "application.log").open("wb") as log:
        result = run_hidden_subprocess(command, cwd=ROOT, env=env, stdout=log, stderr=log,
                                       timeout=200, purpose="workshop and playhead UI verification")
    report = json.loads((out / "runtime.json").read_text(encoding="utf-8"))
    if report.get("output"):
        decode = run_hidden_subprocess([str(ffmpeg), "-v", "error", "-i", report["output"], "-f", "null", "-"],
            capture_output=True, timeout=30, purpose="complete output decode")
        report["full_decode_passed"] = decode.returncode == 0
        (out / "runtime.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = report["passed"] and report.get("full_decode_passed", False) and result.returncode == 0
    print(json.dumps({"passed": passed, "checks": len(report["checks"]), "error": report.get("error"),
                      "exit_code": result.returncode, "output": str(out)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
